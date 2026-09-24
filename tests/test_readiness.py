"""Release readiness: persona segments, baseline comparison, and Go / No-Go."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_test_kit import AgentTestConfig, ReadinessPolicy, evaluate_readiness, load_report
from agent_test_kit.models.report import AgentTestRunReport, ScenarioReport, ScenarioStatus
from agent_test_kit.plugin import pytest_plugin
from agent_test_kit.regression import RegressionEvaluation, RegressionRunEvaluation
from agent_test_kit.reporting.html_report import HtmlReportWriter
from agent_test_kit.reporting.json_report import JsonReportWriter

pytestmark = pytest.mark.agent_unit

_NOW = datetime(2026, 9, 24, tzinfo=UTC)


def _scenario(
    nodeid: str,
    status: ScenarioStatus = "passed",
    **fields: Any,
) -> ScenarioReport:
    return ScenarioReport(
        name=nodeid.rsplit("::", 1)[-1],
        nodeid=nodeid,
        passed=status == "passed",
        status=status,
        duration_ms=1,
        **fields,
    )


def _report(
    *scenarios: ScenarioReport, run_id: str = "run_now", **fields: Any
) -> AgentTestRunReport:
    report = AgentTestRunReport(
        run_id=run_id,
        agent_id="support-agent",
        environment="ci",
        started_at=_NOW,
        completed_at=_NOW,
        scenarios=list(scenarios),
        **fields,
    )
    report.finalize_metrics()
    return report


def _evaluation(
    persona: str | None = "frustrated_customer",
    *,
    pass_rate: float = 1.0,
    runs: int = 1,
) -> RegressionRunEvaluation:
    return RegressionRunEvaluation(
        case_id="refund_status",
        goal="Customer learns refund status",
        persona=persona,
        passed=pass_rate >= 0.6,
        pass_rate=pass_rate,
        min_pass_rate=0.6,
        runs=tuple(RegressionEvaluation(case_id="refund_status", passed=True) for _ in range(runs)),
    )


class TestReadinessPolicy:
    @pytest.mark.parametrize("field", ["min_persona_pass_rate", "max_pass_rate_drop"])
    @pytest.mark.parametrize("value", [-0.1, 1.5, float("nan")])
    def test_rejects_values_outside_unit_interval(self, field: str, value: float) -> None:
        with pytest.raises(ValueError, match=field):
            ReadinessPolicy(**{field: value})

    def test_defaults_add_no_thresholds(self) -> None:
        policy = ReadinessPolicy()

        assert policy.min_persona_pass_rate is None
        assert policy.max_pass_rate_drop is None


class TestVerdict:
    def test_all_passed_is_go(self) -> None:
        readiness = evaluate_readiness(_report(_scenario("t::a"), _scenario("t::b")))

        assert readiness.verdict == "go"
        assert readiness.blocking == []
        assert readiness.baseline is None

    @pytest.mark.parametrize(
        ("scenarios", "reason"),
        [
            ((), "No scenarios executed"),
            ((_scenario("t::a", "skipped"),), "No scenarios executed"),
            ((_scenario("t::a", "failed"),), "1 scenario(s) failed or errored"),
            (
                (_scenario("t::a", "error"), _scenario("t::b", "failed")),
                "2 scenario(s) failed or errored",
            ),
            ((_scenario("t::a", security_failure=True),), "1 security failure(s)"),
            ((_scenario("t::a", duplicate_write_count=2),), "2 duplicate write(s)"),
        ],
    )
    def test_blocking_reasons(self, scenarios: tuple[ScenarioReport, ...], reason: str) -> None:
        readiness = evaluate_readiness(_report(*scenarios))

        assert readiness.verdict == "no_go"
        assert reason in readiness.blocking

    def test_extra_notes_never_block(self) -> None:
        readiness = evaluate_readiness(_report(_scenario("t::a")), notes=["heads up"])

        assert readiness.verdict == "go"
        assert readiness.notes == ["heads up"]


class TestPersonaSegments:
    def test_segments_are_weakest_first_and_skip_unexecuted(self) -> None:
        report = _report(
            _scenario("t::a", persona="novice", pass_rate=0.6),
            _scenario("t::b", persona="novice"),
            _scenario("t::c", persona="expert"),
            _scenario("t::d", "skipped", persona="expert"),
            _scenario("t::e", "failed", persona="frustrated"),
            _scenario("t::f"),
        )

        segments = evaluate_readiness(report).persona_segments

        assert [(s.persona, s.scenarios, s.passed) for s in segments] == [
            ("frustrated", 1, 0),
            ("novice", 2, 2),
            ("expert", 1, 1),
        ]
        assert segments[1].pass_rate == pytest.approx(0.8)

    @pytest.mark.parametrize(("threshold", "verdict"), [(0.9, "no_go"), (0.8, "go")])
    def test_min_persona_pass_rate(self, threshold: float, verdict: str) -> None:
        report = _report(
            _scenario("t::a", persona="novice", pass_rate=0.8),
            _scenario("t::b", persona="expert", pass_rate=1.0),
        )

        readiness = evaluate_readiness(
            report,
            policy=ReadinessPolicy(min_persona_pass_rate=threshold),
        )

        assert readiness.verdict == verdict
        if verdict == "no_go":
            assert readiness.blocking == ["Persona 'novice' pass rate 80% is below 90%"]


class TestBaseline:
    def test_regression_blocks_and_is_listed(self) -> None:
        baseline = _report(_scenario("t::a"), _scenario("t::b"), run_id="run_before")
        current = _report(_scenario("t::a", "failed"), _scenario("t::b"))

        readiness = evaluate_readiness(current, baseline=baseline)

        assert readiness.verdict == "no_go"
        assert readiness.baseline is not None
        assert readiness.baseline.baseline_run_id == "run_before"
        assert readiness.baseline.regressions == ["t::a"]
        assert "1 scenario(s) regressed since baseline run_before" in readiness.blocking

    def test_already_failing_scenario_is_not_a_regression(self) -> None:
        baseline = _report(_scenario("t::a", "failed"))
        current = _report(_scenario("t::a", "failed"))

        readiness = evaluate_readiness(current, baseline=baseline)

        assert readiness.baseline is not None
        assert readiness.baseline.regressions == []

    def test_pass_rate_drop_is_a_note_by_default(self) -> None:
        baseline = _report(_scenario("t::a", pass_rate=1.0), run_id="before")
        current = _report(_scenario("t::a", pass_rate=0.8))

        readiness = evaluate_readiness(current, baseline=baseline)

        assert readiness.verdict == "go"
        assert readiness.notes == ["Pass rate dropped: t::a: 100% -> 80%"]

    @pytest.mark.parametrize(("max_drop", "verdict"), [(0.1, "no_go"), (0.3, "go")])
    def test_max_pass_rate_drop_blocks(self, max_drop: float, verdict: str) -> None:
        baseline = _report(_scenario("t::a", pass_rate=1.0))
        current = _report(_scenario("t::a", pass_rate=0.8))

        readiness = evaluate_readiness(
            current,
            baseline=baseline,
            policy=ReadinessPolicy(max_pass_rate_drop=max_drop),
        )

        assert readiness.verdict == verdict

    def test_fingerprint_changes_and_missing_scenarios_are_notes(self) -> None:
        baseline = _report(
            _scenario("t::a"),
            _scenario("t::gone"),
            _scenario("t::skipped", "skipped"),
            model="model-a",
            knowledge_version="kb-1",
        )
        current = _report(_scenario("t::a"), model="model-b", knowledge_version="kb-2")

        readiness = evaluate_readiness(current, baseline=baseline)

        assert readiness.verdict == "go"
        assert readiness.baseline is not None
        assert readiness.baseline.missing_scenarios == ["t::gone"]
        assert readiness.notes == [
            "model changed: model-a -> model-b",
            "knowledge_version changed: kb-1 -> kb-2",
            "1 baseline scenario(s) were not run",
        ]

    @pytest.mark.parametrize(
        ("before", "after", "note"),
        [
            (100, 150, "Token usage increased 50% (100 -> 150)"),
            (100, 110, None),
            (None, 150, None),
        ],
    )
    def test_token_usage_note(self, before: int | None, after: int, note: str | None) -> None:
        baseline = _report(_scenario("t::a", token_usage=before))
        current = _report(_scenario("t::a", token_usage=after))

        readiness = evaluate_readiness(current, baseline=baseline)

        assert readiness.notes == ([note] if note else [])


class TestReportRoundTrip:
    def test_json_writer_records_regression_fields_and_knowledge_version(
        self,
        tmp_path: Path,
    ) -> None:
        output = tmp_path / "report.json"
        writer = JsonReportWriter(
            config=AgentTestConfig(agent_id="demo", knowledge_version="kb-7"),
            output_path=output,
        )
        writer.record_scenario(
            name="test_refund",
            nodeid="t::refund",
            passed=True,
            duration_ms=5,
            markers=[],
            regression_evaluation=_evaluation(pass_rate=0.8, runs=5),
        )
        writer.write()

        loaded = load_report(output)
        scenario = loaded.scenarios[0]

        assert loaded.knowledge_version == "kb-7"
        assert (scenario.case_id, scenario.goal, scenario.persona) == (
            "refund_status",
            "Customer learns refund status",
            "frustrated_customer",
        )
        assert (scenario.pass_rate, scenario.min_pass_rate, scenario.run_count) == (0.8, 0.6, 5)

    def test_html_shows_readiness_and_behavior_rows(self, tmp_path: Path) -> None:
        baseline = _report(_scenario("t::a"), run_id="run_before", model="m1")
        report = _report(
            _scenario(
                "t::a",
                "failed",
                goal="Refund <status>",
                persona="novice",
                pass_rate=0.4,
                min_pass_rate=0.8,
                run_count=5,
            ),
            model="m2",
            knowledge_version="kb-9",
        )
        report.readiness = evaluate_readiness(report, baseline=baseline)

        html = HtmlReportWriter(tmp_path / "report.html").write(report).read_text("utf-8")

        assert 'class="card readiness readiness-no-go"' in html
        assert "NO-GO" in html
        assert "1 scenario(s) regressed since baseline run_before" in html
        assert "model changed: m1 -&gt; m2" in html
        assert "Knowledge version" in html
        assert "kb-9" in html
        assert "Refund &lt;status&gt;" in html
        assert "40% (required 80%)" in html

    @pytest.mark.parametrize(
        ("readiness", "expected", "absent"),
        [
            ("go", 'class="card readiness readiness-go"', "NO-GO"),
            (None, "Agent test report", "Release readiness"),
        ],
    )
    def test_html_readiness_optional(
        self,
        tmp_path: Path,
        readiness: str | None,
        expected: str,
        absent: str,
    ) -> None:
        report = _report(_scenario("t::a"))
        if readiness:
            report.readiness = evaluate_readiness(report)

        html = HtmlReportWriter(tmp_path / "r.html").write(report).read_text("utf-8")

        assert expected in html
        assert absent not in html


def _session_state(tmp_path: Path, **fields: Any) -> tuple[MagicMock, pytest_plugin.PluginState]:
    writer = JsonReportWriter(config=AgentTestConfig(), output_path=tmp_path / "report.json")
    writer.record_scenario(name="a", nodeid="t::a", passed=True, duration_ms=1, markers=[])
    state = pytest_plugin.PluginState(agent_config=AgentTestConfig(), json_writer=writer, **fields)
    session = MagicMock()
    session.config.stash = pytest.Stash()
    session.config.stash[pytest_plugin._STASH_KEY] = state
    session.exitstatus = pytest.ExitCode.OK
    return session, state


class TestPluginSession:
    @pytest.mark.parametrize(
        ("baseline_content", "note_prefix"),
        [(None, "Baseline report not found"), ("{not json", "Baseline report unreadable")],
    )
    def test_bad_baseline_becomes_a_note(
        self,
        tmp_path: Path,
        baseline_content: str | None,
        note_prefix: str,
    ) -> None:
        baseline = tmp_path / "baseline.json"
        if baseline_content is not None:
            baseline.write_text(baseline_content, encoding="utf-8")
        session, _ = _session_state(tmp_path, baseline_path=baseline)

        pytest_plugin.pytest_sessionfinish(session, pytest.ExitCode.OK)

        payload = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
        assert payload["readiness"]["verdict"] == "go"
        assert payload["readiness"]["notes"][0].startswith(note_prefix)
        assert session.exitstatus == pytest.ExitCode.OK

    def test_valid_baseline_is_compared(self, tmp_path: Path) -> None:
        baseline = tmp_path / "baseline.json"
        baseline.write_text(_report(_scenario("t::a"), run_id="run_b").model_dump_json())
        session, _ = _session_state(tmp_path, baseline_path=baseline)

        pytest_plugin.pytest_sessionfinish(session, pytest.ExitCode.OK)

        payload = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
        assert payload["readiness"]["baseline"]["baseline_run_id"] == "run_b"

    @pytest.mark.parametrize(
        ("enforce", "exitstatus", "expected"),
        [
            (True, pytest.ExitCode.OK, pytest.ExitCode.TESTS_FAILED),
            (False, pytest.ExitCode.OK, pytest.ExitCode.OK),
            (True, pytest.ExitCode.INTERRUPTED, pytest.ExitCode.INTERRUPTED),
        ],
    )
    def test_enforcement_is_opt_in(
        self,
        tmp_path: Path,
        enforce: bool,
        exitstatus: pytest.ExitCode,
        expected: pytest.ExitCode,
    ) -> None:
        session, _ = _session_state(
            tmp_path,
            readiness_policy=ReadinessPolicy(min_persona_pass_rate=1.0),
            enforce_readiness=enforce,
        )
        session.exitstatus = exitstatus
        state = session.config.stash[pytest_plugin._STASH_KEY]
        assert state.json_writer is not None
        state.json_writer.scenarios[0].persona = "novice"
        state.json_writer.scenarios[0].pass_rate = 0.5

        pytest_plugin.pytest_sessionfinish(session, exitstatus)

        assert session.exitstatus == expected

    def test_attach_regression_evaluation_ignores_missing_state(self) -> None:
        config = MagicMock()
        config.stash = pytest.Stash()

        pytest_plugin.ScenarioResultRecorder(config, "t::a").attach_regression_evaluation(
            _evaluation()
        )

        assert pytest_plugin._STASH_KEY not in config.stash


def test_cli_enforces_persona_readiness_end_to_end(
    pytester: pytest.Pytester,
    tmp_path: Path,
) -> None:
    json_path = tmp_path / "readiness.json"
    pytester.makepyfile(
        """
from agent_test_kit.regression import RegressionEvaluation, RegressionRunEvaluation


def test_refund(agent_scenario):
    agent_scenario.attach_regression_evaluation(
        RegressionRunEvaluation(
            case_id="refund",
            goal="Refund status",
            persona="novice",
            passed=True,
            pass_rate=0.6,
            min_pass_rate=0.6,
            runs=(RegressionEvaluation(case_id="refund", passed=True),),
        )
    )
"""
    )

    result = pytester.runpytest(
        f"--agent-report-json={json_path}",
        "--agent-min-persona-pass-rate=0.8",
        "--agent-enforce-readiness",
        "-q",
        "-p",
        "no:cacheprovider",
    )

    result.assert_outcomes(passed=1)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["readiness"]["verdict"] == "no_go"
    assert payload["readiness"]["persona_segments"][0]["persona"] == "novice"
    assert payload["scenarios"][0]["pass_rate"] == 0.6
