"""Heuristics for MCP server and read/write classification from tool names."""

from __future__ import annotations

from agent_test_kit.models.enums import ToolOperationKind

_KNOWN_SERVER_PREFIXES = (
    "bitbucket",
    "jira",
    "confluence",
    "atlassian",
    "playwright",
    "qase",
    "browserstack",
    "coralogix",
    "pango",
    "sql",
    "bill",
)

_WRITE_VERBS = (
    "create",
    "update",
    "post",
    "add",
    "merge",
    "delete",
    "transition",
    "assign",
    "comment",
    "publish",
    "write",
    "put",
    "send",
)

_READ_VERBS = (
    "get",
    "list",
    "search",
    "fetch",
    "read",
    "describe",
    "review",
    "lookup",
    "find",
    "show",
    "open",
    "summarize",
    "echo",
)


def infer_server(
    tool_name: str,
    *,
    mappings: dict[str, str] | None = None,
) -> str | None:
    """Infer MCP server from a normalized tool name."""
    if mappings is not None and tool_name in mappings:
        return mappings[tool_name]
    if tool_name.startswith("mcp__"):
        parts = tool_name.split("__")
        if len(parts) >= 3:
            return parts[1]
    lower = tool_name.lower()
    for prefix in _KNOWN_SERVER_PREFIXES:
        if lower.startswith(f"{prefix}_"):
            return prefix
    return None


def infer_operation_kind(
    tool_name: str,
    *,
    mappings: dict[str, ToolOperationKind] | None = None,
) -> ToolOperationKind:
    """Classify tool name as read, write, or unknown."""
    if mappings is not None and tool_name in mappings:
        return mappings[tool_name]
    lower = tool_name.lower()
    padded = f"_{lower}_"
    for verb in _WRITE_VERBS:
        if lower.startswith(f"{verb}_") or f"_{verb}_" in padded:
            return ToolOperationKind.WRITE
    for verb in _READ_VERBS:
        if lower.startswith(f"{verb}_") or f"_{verb}_" in padded:
            return ToolOperationKind.READ
    return ToolOperationKind.UNKNOWN
