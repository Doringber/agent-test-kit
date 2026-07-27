"""Parse Cursor CLI stream-json output into agent-test-kit traces."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from agent_test_kit.client.tool_inference import infer_operation_kind, infer_server
from agent_test_kit.models.enums import ToolCallStatus, ToolOperationKind
from agent_test_kit.models.tool_call import ToolCall
from agent_test_kit.models.trace import AgentTrace
from agent_test_kit.reporting.redaction import redact_value


def _extract_tool_name(event: dict[str, Any]) -> str:
    tool_call, mcp = _tool_payload(event)
    raw_mcp_args = mcp.get("args")
    mcp_args = raw_mcp_args if isinstance(raw_mcp_args, dict) else {}
    if "getMcpToolsToolCall" in (tool_call or {}):
        discovered = mcp_args.get("toolName")
        if discovered:
            return f"get_mcp_tools:{discovered}"
        return "get_mcp_tools"
    raw_tool_use = event.get("tool_use")
    tool_use = raw_tool_use if isinstance(raw_tool_use, dict) else {}
    raw_function = event.get("function")
    function = raw_function if isinstance(raw_function, dict) else {}
    nested_args = mcp_args.get("args")
    nested = nested_args if isinstance(nested_args, dict) else {}
    return str(
        mcp_args.get("toolName")
        or mcp_args.get("name")
        or nested.get("name")
        or event.get("name")
        or event.get("tool_name")
        or tool_use.get("name")
        or function.get("name")
        or "unknown"
    )


def _first_value(source: dict[str, Any], *keys: str) -> Any | None:
    for key in keys:
        if key in source and source[key] is not None:
            return source[key]
    return None


def _tool_payload(event: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    tool_call = event.get("tool_call")
    if tool_call is not None and not isinstance(tool_call, dict):
        msg = "tool_call must be an object"
        raise ValueError(msg)
    normalized_tool_call = tool_call or {}
    mcp: dict[str, Any] = {}
    if "mcpToolCall" in normalized_tool_call:
        raw = normalized_tool_call.get("mcpToolCall")
        mcp = raw if isinstance(raw, dict) else {}
    elif "getMcpToolsToolCall" in normalized_tool_call:
        raw = normalized_tool_call.get("getMcpToolsToolCall")
        mcp = raw if isinstance(raw, dict) else {}
    else:
        for key, value in normalized_tool_call.items():
            if key.endswith("ToolCall") and isinstance(value, dict):
                mcp = value
                break
    return normalized_tool_call, mcp


def _extract_call_id(event: dict[str, Any]) -> str | None:
    tool_call, mcp = _tool_payload(event)
    raw_id = (
        _first_value(event, "id", "call_id", "tool_call_id", "toolCallId")
        or _first_value(tool_call, "id", "call_id", "toolCallId")
        or _first_value(mcp, "id", "call_id", "toolCallId")
    )
    return str(raw_id) if raw_id is not None else None


def _extract_server(event: dict[str, Any]) -> str | None:
    tool_call, mcp = _tool_payload(event)
    mcp_args = mcp.get("args")
    normalized_args = mcp_args if isinstance(mcp_args, dict) else {}
    raw_server = (
        _first_value(event, "server", "server_name", "serverName")
        or _first_value(tool_call, "server", "server_name", "serverName")
        or _first_value(mcp, "server", "server_name", "serverName")
        or _first_value(
            normalized_args,
            "server",
            "server_name",
            "serverName",
            "serverIdentifier",
            "providerIdentifier",
        )
    )
    return str(raw_server) if raw_server is not None else None


def _extract_arguments(event: dict[str, Any]) -> dict[str, Any]:
    tool_call, mcp = _tool_payload(event)
    mcp_args = mcp.get("args")
    normalized_mcp_args = mcp_args if isinstance(mcp_args, dict) else {}
    raw_arguments = (
        normalized_mcp_args.get("arguments")
        or normalized_mcp_args.get("input")
        or normalized_mcp_args.get("args")
        or tool_call.get("arguments")
        or event.get("arguments")
        or event.get("input")
    )
    if not isinstance(raw_arguments, dict):
        return {}
    redacted_arguments = redact_value(dict(raw_arguments))
    return redacted_arguments if isinstance(redacted_arguments, dict) else {}


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _event_timestamp(event: dict[str, Any]) -> datetime | None:
    return _parse_datetime(
        _first_value(event, "timestamp", "started_at", "startedAt", "completed_at", "completedAt")
    )


def _completion_status(event: dict[str, Any]) -> ToolCallStatus:
    tool_call, mcp = _tool_payload(event)
    result = mcp.get("result")
    normalized_result = result if isinstance(result, dict) else {}
    raw_status = str(
        event.get("status")
        or tool_call.get("status")
        or mcp.get("status")
        or normalized_result.get("status")
        or event.get("subtype")
        or ""
    ).lower()
    if raw_status in {"timeout", "timed_out"}:
        return ToolCallStatus.TIMEOUT
    has_error = (
        event.get("error") is not None
        or tool_call.get("error") is not None
        or mcp.get("error") is not None
        or normalized_result.get("error") is not None
        or normalized_result.get("isError") is True
        or normalized_result.get("success") is False
    )
    if raw_status in {"error", "failed", "failure"} or has_error:
        return ToolCallStatus.ERROR
    if raw_status in {"completed", "success", "succeeded", "ok"}:
        return ToolCallStatus.SUCCESS
    return ToolCallStatus.ERROR


def _completion_output(event: dict[str, Any]) -> Any | None:
    output = _first_value(event, "output", "result", "response", "error")
    if output is None:
        tool_call, mcp = _tool_payload(event)
        output = _first_value(tool_call, "output", "result", "response", "error")
        if output is None:
            output = _first_value(mcp, "output", "result", "response", "error")
    return redact_value(output)


def _extract_tokens(source: dict[str, Any], dest: dict[str, int]) -> None:
    mappings = (
        ("total_tokens", ("total_tokens", "totalTokens")),
        ("input_tokens", ("input_tokens", "inputTokens", "totalInputTokens")),
        ("output_tokens", ("output_tokens", "outputTokens", "totalOutputTokens")),
        ("cache_read_input_tokens", ("cache_read_input_tokens", "cacheReadInputTokens")),
        (
            "cache_creation_input_tokens",
            ("cache_creation_input_tokens", "cacheCreationInputTokens"),
        ),
    )
    for canonical, keys in mappings:
        if canonical in dest:
            continue
        for raw_key in keys:
            value = source.get(raw_key)
            if isinstance(value, (int, float)) and value > 0:
                dest[canonical] = int(value)
                break


def _total_tokens(token_usage: dict[str, int]) -> int | None:
    if "total_tokens" in token_usage:
        return token_usage["total_tokens"]
    total = token_usage.get("input_tokens", 0) + token_usage.get("output_tokens", 0)
    return total or None


def _connected_servers_from_stdout(
    stdout: str,
    tool_calls: list[ToolCall],
) -> list[str]:
    """Collect MCP server identifiers declared in stream-json and tool calls."""
    servers: set[str] = set()
    for call in tool_calls:
        if call.server and call.server.strip().lower() != "unknown":
            servers.add(call.server.strip())
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        for match in re.finditer(
            r'"(?:server|serverIdentifier|providerIdentifier)"\s*:\s*"([^"]+)"',
            stripped,
        ):
            value = match.group(1).strip()
            if value and not value.startswith("http"):
                servers.add(value)
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "user":
            continue
        message = event.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "text":
                continue
            text = str(part.get("text") or "")
            banner = re.search(
                r"following servers:\s*([^\n.]+)",
                text,
                flags=re.IGNORECASE,
            )
            if banner:
                for item in banner.group(1).split(","):
                    candidate = item.strip()
                    if candidate:
                        servers.add(candidate)
    return sorted(servers)


def parse_stream_json_stdout(
    stdout: str,
    *,
    server_mappings: dict[str, str] | None = None,
    operation_mappings: dict[str, ToolOperationKind] | None = None,
) -> AgentTrace:
    """Parse line-delimited stream-json stdout into a normalized trace."""
    token_usage: dict[str, int] = {}
    tool_calls: list[ToolCall] = []
    calls_by_id: dict[str, ToolCall] = {}
    model: str | None = None
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("type", ""))
        if event_type in {"result", "usage", "token_usage"}:
            usage = event.get("usage")
            _extract_tokens(usage if isinstance(usage, dict) else event, token_usage)
            raw_model = event.get("model") or event.get("model_name")
            if raw_model is not None:
                model = str(raw_model)
        if event_type not in {"tool_use", "tool_call"}:
            continue

        subtype = str(event.get("subtype", "called")).lower()
        call_id = _extract_call_id(event)
        is_completion = subtype in {
            "completed",
            "success",
            "succeeded",
            "error",
            "failed",
            "failure",
            "timeout",
            "timed_out",
        }
        if is_completion:
            call = calls_by_id.get(call_id) if call_id is not None else None
            if call is None:
                name = _extract_tool_name(event)
                call = next(
                    (
                        candidate
                        for candidate in reversed(tool_calls)
                        if candidate.name == name and candidate.status != ToolCallStatus.SUCCESS
                    ),
                    None,
                )
            if call is None:
                call = _tool_call_from_event(
                    event,
                    index=len(tool_calls),
                    server_mappings=server_mappings,
                    operation_mappings=operation_mappings,
                )
                tool_calls.append(call)
                if call.id is not None:
                    calls_by_id[call.id] = call
            call.status = _completion_status(event)
            call.output = _completion_output(event)
            call.completed_at = _event_timestamp(event)
            explicit_duration = _first_value(event, "duration_ms", "durationMs")
            if isinstance(explicit_duration, (int, float)):
                call.duration_ms = int(explicit_duration)
            elif call.started_at is not None and call.completed_at is not None:
                call.duration_ms = int((call.completed_at - call.started_at).total_seconds() * 1000)
            continue

        call = _tool_call_from_event(
            event,
            index=len(tool_calls),
            server_mappings=server_mappings,
            operation_mappings=operation_mappings,
        )
        tool_calls.append(call)
        if call.id is not None:
            calls_by_id[call.id] = call

    connected = _connected_servers_from_stdout(stdout, tool_calls)
    return AgentTrace(
        tool_calls=tool_calls,
        token_usage=_total_tokens(token_usage),
        model=model,
        connected_mcp_servers=connected,
    )


def _tool_call_from_event(
    event: dict[str, Any],
    *,
    index: int,
    server_mappings: dict[str, str] | None,
    operation_mappings: dict[str, ToolOperationKind] | None,
) -> ToolCall:
    name = _extract_tool_name(event)
    explicit_server = _extract_server(event)
    raw_attempt = event.get("attempt", 1)
    attempt = int(raw_attempt) if isinstance(raw_attempt, (int, float, str)) else 1
    parent_step = _first_value(event, "parent_step_id", "parentStepId")
    return ToolCall(
        id=_extract_call_id(event) or str(index + 1),
        server=explicit_server or infer_server(name, mappings=server_mappings),
        name=name,
        arguments=_extract_arguments(event),
        status=ToolCallStatus.RUNNING,
        started_at=_event_timestamp(event),
        attempt=attempt,
        parent_step_id=str(parent_step) if parent_step is not None else None,
        operation_kind=infer_operation_kind(name, mappings=operation_mappings),
    )


def _tool_call_from_name(
    name: str,
    *,
    index: int,
    server_mappings: dict[str, str] | None = None,
    operation_mappings: dict[str, ToolOperationKind] | None = None,
) -> ToolCall:
    return ToolCall(
        id=str(index + 1),
        server=infer_server(name, mappings=server_mappings),
        name=name,
        status=ToolCallStatus.PENDING,
        operation_kind=infer_operation_kind(name, mappings=operation_mappings),
    )


def trace_from_cursor_response(
    body: dict[str, Any],
    *,
    server_mappings: dict[str, str] | None = None,
    operation_mappings: dict[str, ToolOperationKind] | None = None,
) -> AgentTrace:
    """Build trace from a Pango /agent JSON response."""
    nested_trace = body.get("trace")
    if isinstance(nested_trace, dict):
        redacted_trace = redact_value(nested_trace)
        if not isinstance(redacted_trace, dict):
            msg = "nested trace must normalize to an object"
            raise ValueError(msg)
        trace = AgentTrace.from_payload(redacted_trace)
        for call in trace.tool_calls:
            if call.server is None or call.server.strip().lower() == "unknown":
                call.server = infer_server(call.name, mappings=server_mappings)
            if call.operation_kind == ToolOperationKind.UNKNOWN:
                call.operation_kind = infer_operation_kind(
                    call.name,
                    mappings=operation_mappings,
                )
        return trace

    stdout = body.get("stdout")
    if isinstance(stdout, str) and stdout.strip():
        parsed = parse_stream_json_stdout(
            stdout,
            server_mappings=server_mappings,
            operation_mappings=operation_mappings,
        )
        if parsed.tool_calls or parsed.token_usage or parsed.connected_mcp_servers:
            return parsed

    tools_called = body.get("tools_called")
    if isinstance(tools_called, list):
        names = [str(item) for item in tools_called]
        return AgentTrace(
            tool_calls=[
                _tool_call_from_name(
                    name,
                    index=i,
                    server_mappings=server_mappings,
                    operation_mappings=operation_mappings,
                )
                for i, name in enumerate(names)
            ]
        )

    return AgentTrace()
