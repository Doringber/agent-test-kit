"""Incremental Markdown status report for test and release evidence."""

from __future__ import annotations

from pathlib import Path


def _safe(value: str) -> str:
    return value.replace("\n", " ").replace("\r", " ")


class MarkdownStatusReportWriter:
    """Collect operational evidence and write a concise Markdown handoff."""

    def __init__(self, output_path: Path, *, title: str = "Agent test status") -> None:
        self.output_path = output_path
        self.title = title
        self._provenance: list[tuple[str, str]] = []
        self._commands: list[tuple[str, int]] = []
        self._counts: dict[str, int] = {}
        self._artifacts: list[tuple[str, str]] = []
        self._evidence: list[tuple[str, str]] = []
        self._cleanup: list[tuple[str, str]] = []
        self._skips: list[str] = []
        self._blockers: list[str] = []

    def record_provenance(self, package: str, version: str) -> None:
        self._provenance.append((_safe(package), _safe(version)))

    def record_command(self, command: str, *, exit_code: int) -> None:
        self._commands.append((_safe(command), exit_code))

    def set_counts(
        self,
        *,
        passed: int,
        failed: int,
        skipped: int,
        errors: int,
    ) -> None:
        self._counts = {
            "Passed": passed,
            "Failed": failed,
            "Skipped": skipped,
            "Errors": errors,
        }

    def add_artifact(self, name: str, path: str) -> None:
        self._artifacts.append((_safe(name), _safe(path)))

    def add_evidence(self, name: str, url: str) -> None:
        self._evidence.append((_safe(name), _safe(url)))

    def add_cleanup(self, resource: str, result: str) -> None:
        self._cleanup.append((_safe(resource), _safe(result)))

    def add_skip(self, reason: str) -> None:
        self._skips.append(_safe(reason))

    def add_blocker(self, blocker: str) -> None:
        self._blockers.append(_safe(blocker))

    def write(self) -> Path:
        sections = [f"# {_safe(self.title)}"]
        self._append_pairs(
            sections,
            "Package provenance",
            [f"- {package} `{version}`" for package, version in self._provenance],
        )
        self._append_pairs(
            sections,
            "Commands",
            [f"- `{command}` — exit {exit_code}" for command, exit_code in self._commands],
        )
        if self._counts:
            self._append_pairs(
                sections,
                "Counts",
                [f"- {name}: {value}" for name, value in self._counts.items()],
            )
        self._append_pairs(
            sections,
            "Artifacts",
            [f"- {name}: `{path}`" for name, path in self._artifacts],
        )
        self._append_pairs(
            sections,
            "Live evidence",
            [f"- [{name}]({url})" for name, url in self._evidence],
        )
        self._append_pairs(
            sections,
            "Cleanup",
            [f"- {resource} — {result}" for resource, result in self._cleanup],
        )
        self._append_pairs(sections, "Skips", [f"- {reason}" for reason in self._skips])
        self._append_pairs(
            sections,
            "Blockers",
            [f"- {blocker}" for blocker in self._blockers],
        )
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text("\n\n".join(sections) + "\n", encoding="utf-8")
        return self.output_path

    @staticmethod
    def _append_pairs(sections: list[str], heading: str, lines: list[str]) -> None:
        if lines:
            sections.append(f"## {heading}\n" + "\n".join(lines))
