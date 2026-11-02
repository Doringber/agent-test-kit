"""Built-in deterministic evals."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from agent_test_kit.evals.base import Eval
from agent_test_kit.models.execution import AgentExecutionResult
from agent_test_kit.scoring import RequiredTermsScorer, Score

ToolSpec = str | tuple[str | None, str]


class RequiredTermsEval(Eval):
    """Fraction of required terms present in the response text."""

    def __init__(
        self,
        terms: Iterable[str],
        *,
        threshold: float = 1.0,
        name: str = "required_terms",
        case_sensitive: bool = False,
    ) -> None:
        super().__init__(name=name, threshold=threshold)
        self._scorer = RequiredTermsScorer(terms, case_sensitive=case_sensitive, name=name)

    def score(self, result: AgentExecutionResult) -> Score:
        return self._scorer.score(result)


class RequiredToolsEval(Eval):
    """Fraction of required tools that appear in the trace.

    Each tool is a name, or a ``(server, name)`` pair. Order does not matter.
    """

    def __init__(
        self,
        tools: Sequence[ToolSpec],
        *,
        threshold: float = 1.0,
        name: str = "required_tools",
    ) -> None:
        super().__init__(name=name, threshold=threshold)
        parsed = tuple(_parse_tool(tool) for tool in tools)
        if not parsed:
            raise ValueError("at least one tool is required")
        self.tools = parsed

    def score(self, result: AgentExecutionResult) -> Score:
        missing = [
            _qualified(server, tool_name)
            for server, tool_name in self.tools
            if not any(call.matches(tool_name, server) for call in result.tool_calls)
        ]
        found = len(self.tools) - len(missing)
        return Score(
            found / len(self.tools),
            reason=f"Missing tools: {missing}" if missing else None,
            details={"missing": missing},
        )


def _parse_tool(tool: ToolSpec) -> tuple[str | None, str]:
    if isinstance(tool, str):
        if not tool:
            raise ValueError("tool names must be non-empty strings")
        return None, tool
    if (
        isinstance(tool, tuple)
        and len(tool) == 2
        and (tool[0] is None or isinstance(tool[0], str))
        and isinstance(tool[1], str)
        and tool[1]
    ):
        return tool
    raise ValueError("tools must be names or (server, name) pairs")


def _qualified(server: str | None, tool_name: str) -> str:
    if server:
        return f"{server}/{tool_name}"
    return tool_name
