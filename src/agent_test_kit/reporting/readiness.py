"""Go / No-Go release readiness derived from a run report and an optional baseline."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from agent_test_kit.models.report import (
    AgentTestRunReport,
    BaselineComparison,
    PersonaSegment,
    ReleaseReadiness,
    ScenarioReport,
)
from agent_test_kit.scoring import validate_unit_interval

_FINGERPRINT_FIELDS = ("model", "prompt_version", "agent_version", "knowledge_version")
_TOKEN_INCREASE_NOTE_THRESHOLD = 0.2


@dataclass(frozen=True, slots=True)
class ReadinessPolicy:
    """Optional thresholds that turn readiness observations into blocking reasons.

    Failed, errored, security-failing, and duplicate-write scenarios always block.
    """

    min_persona_pass_rate: float | None = None
    max_pass_rate_drop: float | None = None

    def __post_init__(self) -> None:
        if self.min_persona_pass_rate is not None:
            validate_unit_interval("min_persona_pass_rate", self.min_persona_pass_rate)
        if self.max_pass_rate_drop is not None:
            validate_unit_interval("max_pass_rate_drop", self.max_pass_rate_drop)


def load_report(path: Path) -> AgentTestRunReport:
    """Load a JSON report written by ``--agent-report-json``."""
    return AgentTestRunReport.model_validate_json(path.read_text(encoding="utf-8"))


def evaluate_readiness(
    report: AgentTestRunReport,
    *,
    baseline: AgentTestRunReport | None = None,
    policy: ReadinessPolicy | None = None,
    notes: Iterable[str] = (),
) -> ReleaseReadiness:
    """Summarize whether the run's evidence supports releasing the agent.

    The verdict is ``no_go`` when any blocking reason exists. ``notes`` are informational
    and never change the verdict.
    """
    policy = policy or ReadinessPolicy()
    executed = [scenario for scenario in report.scenarios if scenario.status != "skipped"]
    blocking: list[str] = []
    all_notes = list(notes)

    if not executed:
        blocking.append("No scenarios executed")
    failed = [scenario for scenario in executed if scenario.status in {"failed", "error"}]
    if failed:
        blocking.append(f"{len(failed)} scenario(s) failed or errored")
    security_failures = sum(1 for scenario in executed if scenario.security_failure)
    if security_failures:
        blocking.append(f"{security_failures} security failure(s)")
    duplicate_writes = sum(scenario.duplicate_write_count for scenario in executed)
    if duplicate_writes:
        blocking.append(f"{duplicate_writes} duplicate write(s)")

    segments = persona_segments(executed)
    if policy.min_persona_pass_rate is not None:
        blocking.extend(
            f"Persona {segment.persona!r} pass rate {segment.pass_rate:.0%} "
            f"is below {policy.min_persona_pass_rate:.0%}"
            for segment in segments
            if segment.pass_rate < policy.min_persona_pass_rate
        )

    comparison = None
    if baseline is not None:
        comparison = compare_to_baseline(report, baseline)
        if comparison.regressions:
            blocking.append(
                f"{len(comparison.regressions)} scenario(s) regressed since baseline "
                f"{comparison.baseline_run_id}"
            )
        if policy.max_pass_rate_drop is not None:
            blocking.extend(_excessive_drops(report, baseline, policy.max_pass_rate_drop))
        all_notes.extend(comparison.fingerprint_changes)
        all_notes.extend(f"Pass rate dropped: {drop}" for drop in comparison.pass_rate_drops)
        if comparison.missing_scenarios:
            all_notes.append(
                f"{len(comparison.missing_scenarios)} baseline scenario(s) were not run"
            )
        token_note = _token_usage_note(report, baseline)
        if token_note:
            all_notes.append(token_note)

    return ReleaseReadiness(
        verdict="no_go" if blocking else "go",
        blocking=blocking,
        notes=all_notes,
        persona_segments=segments,
        baseline=comparison,
    )


def persona_segments(scenarios: Iterable[ScenarioReport]) -> list[PersonaSegment]:
    """Group executed scenarios by persona, weakest segment first."""
    grouped: dict[str, list[ScenarioReport]] = {}
    for scenario in scenarios:
        if scenario.persona and scenario.status != "skipped":
            grouped.setdefault(scenario.persona, []).append(scenario)
    segments = [
        PersonaSegment(
            persona=persona,
            scenarios=len(members),
            passed=sum(1 for member in members if member.status == "passed"),
            pass_rate=sum(_scenario_rate(member) for member in members) / len(members),
        )
        for persona, members in grouped.items()
    ]
    return sorted(segments, key=lambda segment: (segment.pass_rate, segment.persona))


def compare_to_baseline(
    report: AgentTestRunReport,
    baseline: AgentTestRunReport,
) -> BaselineComparison:
    """List scenario regressions, pass-rate drops, and fingerprint changes."""
    current = {scenario.nodeid: scenario for scenario in report.scenarios}
    previous = {scenario.nodeid: scenario for scenario in baseline.scenarios}
    regressions = [
        nodeid
        for nodeid, before in previous.items()
        if before.status == "passed"
        and nodeid in current
        and current[nodeid].status in {"failed", "error"}
    ]
    drops = [
        f"{nodeid}: {before:.0%} -> {after:.0%}"
        for nodeid, before, after in _pass_rate_pairs(current, previous)
        if after < before
    ]
    missing = [
        nodeid
        for nodeid, before in previous.items()
        if before.status != "skipped" and nodeid not in current
    ]
    fingerprint_changes = [
        f"{field} changed: {getattr(baseline, field)} -> {getattr(report, field)}"
        for field in _FINGERPRINT_FIELDS
        if getattr(baseline, field) != getattr(report, field)
    ]
    return BaselineComparison(
        baseline_run_id=baseline.run_id,
        regressions=regressions,
        pass_rate_drops=drops,
        missing_scenarios=missing,
        fingerprint_changes=fingerprint_changes,
    )


def _scenario_rate(scenario: ScenarioReport) -> float:
    if scenario.pass_rate is not None:
        return scenario.pass_rate
    return 1.0 if scenario.status == "passed" else 0.0


def _pass_rate_pairs(
    current: dict[str, ScenarioReport],
    previous: dict[str, ScenarioReport],
) -> list[tuple[str, float, float]]:
    return [
        (nodeid, _scenario_rate(before), _scenario_rate(current[nodeid]))
        for nodeid, before in previous.items()
        if nodeid in current
        and before.pass_rate is not None
        and current[nodeid].pass_rate is not None
    ]


def _excessive_drops(
    report: AgentTestRunReport,
    baseline: AgentTestRunReport,
    max_drop: float,
) -> list[str]:
    current = {scenario.nodeid: scenario for scenario in report.scenarios}
    previous = {scenario.nodeid: scenario for scenario in baseline.scenarios}
    return [
        f"{nodeid} pass rate dropped {before - after:.0%} (limit {max_drop:.0%})"
        for nodeid, before, after in _pass_rate_pairs(current, previous)
        if before - after > max_drop
    ]


def _token_usage_note(report: AgentTestRunReport, baseline: AgentTestRunReport) -> str | None:
    before = baseline.metrics.total_token_usage
    after = report.metrics.total_token_usage
    if not before or after is None:
        return None
    increase = (after - before) / before
    if increase <= _TOKEN_INCREASE_NOTE_THRESHOLD:
        return None
    return f"Token usage increased {increase:.0%} ({before} -> {after})"
