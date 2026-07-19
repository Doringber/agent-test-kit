"""Real-HTTP fakes for the deterministic PR-review acceptance scenario."""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.request import Request, urlopen

from agent_test_kit.verifiers import VerificationContext, VerificationResult

IDEMPOTENCY_KEY = "acceptance-pr-42-v1"
FAKE_SECRET = "fake-jira-token-never-report"
CRITICAL_SUMMARY = "Critical SQL injection in PR #42"
CRITICAL_DESCRIPTION = (
    "src/payments.py:18 interpolates account_id into an SQL statement before execution."
)
PR_REVIEW_REQUEST: dict[str, Any] = {
    "workspace": "pango_dev",
    "repository": "payments-api",
    "pull_request_id": 42,
    "request": "Review this pull request and report critical issues; do not merge.",
    "jira_project": "SEC",
}
_FIXED_TIMESTAMP = "2026-07-18T12:00:00+00:00"

JsonObject = dict[str, Any]
HttpApplication = Callable[
    [str, str, Mapping[str, str], JsonObject],
    tuple[int, JsonObject],
]


class _QuietThreadingHttpServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class MonotonicMcpLedger:
    """Thread-safe request ledger shared by every fake MCP server."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[JsonObject] = []

    def record(self, server: str, tool: Any, arguments: JsonObject) -> None:
        with self._lock:
            self._entries.append(
                {
                    "sequence": len(self._entries) + 1,
                    "server": server,
                    "tool": tool,
                    "arguments": json.loads(json.dumps(arguments)),
                }
            )

    def snapshot(self) -> list[JsonObject]:
        with self._lock:
            return json.loads(json.dumps(self._entries))


class LocalHttpServer:
    """Small localhost HTTP server with deterministic JSON handling."""

    def __init__(self, application: HttpApplication) -> None:
        self._application = application
        self._server: _QuietThreadingHttpServer | None = None
        self._thread: threading.Thread | None = None
        self.closed = False

    @property
    def url(self) -> str:
        if self._server is None:
            raise RuntimeError("Server has not been started")
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def start(self) -> None:
        application = self._application

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
                if self.path == "/__ready__":
                    self._write(HTTPStatus.OK, {"ready": True})
                    return
                content_length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(content_length)
                try:
                    payload = json.loads(raw_body or b"{}")
                except json.JSONDecodeError:
                    self._write(HTTPStatus.BAD_REQUEST, {"error": "invalid JSON"})
                    return
                status, response = application(
                    "POST",
                    self.path,
                    dict(self.headers.items()),
                    payload,
                )
                self._write(status, response)

            def log_message(self, format: str, *args: Any) -> None:
                return

            def _write(self, status: int, payload: JsonObject) -> None:
                body = json.dumps(payload, separators=(",", ":")).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._server = _QuietThreadingHttpServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="acceptance-fake-http",
            daemon=True,
        )
        self._thread.start()
        request = Request(
            f"{self.url}/__ready__",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=2):  # noqa: S310 - localhost readiness probe
            pass

    def close(self) -> None:
        if self._server is None or self.closed:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self.closed = True


def _json_rpc_result(request_id: Any, result: JsonObject) -> JsonObject:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "content": [{"type": "json", "json": result}],
            "structuredContent": result,
        },
    }


def _json_rpc_error(request_id: Any, code: int, message: str) -> JsonObject:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


class JsonRpcMcpClient:
    """Minimal MCP tools/call client crossing a real HTTP boundary."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._request_id = 0

    def call(self, tool: str, arguments: JsonObject) -> JsonObject:
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
        request = Request(
            f"{self._url}/mcp",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=2) as response:  # noqa: S310 - localhost test server
            body = json.loads(response.read())
        if "error" in body:
            raise RuntimeError(body["error"]["message"])
        return dict(body["result"]["structuredContent"])


@dataclass(slots=True)
class JiraIssue:
    key: str
    summary: str
    description: str
    severity: str
    idempotency_key: str
    run_marker: str
    url: str
    archived: bool = False


@dataclass(slots=True)
class PullRequestComment:
    comment_id: int
    content: str
    idempotency_key: str
    run_marker: str
    url: str
    closed: bool = False


@dataclass(slots=True)
class JiraState:
    issues: list[JiraIssue] = field(default_factory=list)
    call_log: list[JsonObject] = field(default_factory=list)


@dataclass(slots=True)
class BitbucketState:
    comments: list[PullRequestComment] = field(default_factory=list)
    call_log: list[JsonObject] = field(default_factory=list)
    merge_count: int = 0


@dataclass(slots=True)
class DashboardState:
    payload: JsonObject | None = None
    authorization: str | None = None
    call_log: list[JsonObject] = field(default_factory=list)


class FakeJiraMcp:
    """Stateful Jira MCP fake with idempotency and archive behavior."""

    def __init__(self, ledger: MonotonicMcpLedger) -> None:
        self._ledger = ledger
        self.state = JiraState()
        self.server = LocalHttpServer(self._handle)

    def _handle(
        self,
        method: str,
        path: str,
        headers: Mapping[str, str],
        payload: JsonObject,
    ) -> tuple[int, JsonObject]:
        del headers
        if method != "POST" or path != "/mcp":
            return HTTPStatus.NOT_FOUND, {"error": "not found"}
        request_id = payload.get("id")
        if payload.get("jsonrpc") != "2.0" or payload.get("method") != "tools/call":
            return HTTPStatus.OK, _json_rpc_error(request_id, -32600, "invalid request")
        params = payload.get("params", {})
        tool = params.get("name")
        arguments = dict(params.get("arguments", {}))
        self._ledger.record("jira", tool, arguments)
        self.state.call_log.append({"tool": tool, "arguments": arguments})
        match tool:
            case "jira_create_issue":
                return HTTPStatus.OK, _json_rpc_result(
                    request_id,
                    self._create_issue(arguments),
                )
            case "jira_search_issues":
                return HTTPStatus.OK, _json_rpc_result(
                    request_id,
                    self._search_issues(arguments),
                )
            case "jira_archive_issue":
                return HTTPStatus.OK, _json_rpc_result(
                    request_id,
                    self._archive_issue(arguments),
                )
            case _:
                return HTTPStatus.OK, _json_rpc_error(
                    request_id,
                    -32601,
                    f"unknown Jira tool: {tool}",
                )

    def _create_issue(self, arguments: JsonObject) -> JsonObject:
        marker = str(arguments["run_marker"])
        existing = next(
            (issue for issue in self.state.issues if issue.run_marker == marker),
            None,
        )
        if existing is not None:
            return self._issue_payload(existing, duplicate=True)
        issue = JiraIssue(
            key="SEC-1001",
            summary=str(arguments["summary"]),
            description=str(arguments["description"]),
            severity=str(arguments["severity"]),
            idempotency_key=str(arguments["idempotency_key"]),
            run_marker=marker,
            url=f"{self.server.url}/browse/SEC-1001",
        )
        self.state.issues.append(issue)
        return self._issue_payload(issue, duplicate=False)

    def _search_issues(self, arguments: JsonObject) -> JsonObject:
        marker = str(arguments["run_marker"])
        issues = [
            self._issue_payload(issue, duplicate=False)
            for issue in self.state.issues
            if issue.run_marker == marker and not issue.archived
        ]
        return {"issues": issues, "total": len(issues)}

    def _archive_issue(self, arguments: JsonObject) -> JsonObject:
        issue = next(
            (
                candidate
                for candidate in self.state.issues
                if candidate.key == arguments["issue_key"]
                and candidate.idempotency_key == arguments["idempotency_key"]
            ),
            None,
        )
        if issue is None:
            raise RuntimeError("issue not found for cleanup")
        issue.archived = True
        return {"key": issue.key, "archived": True}

    @staticmethod
    def _issue_payload(issue: JiraIssue, *, duplicate: bool) -> JsonObject:
        return {
            "key": issue.key,
            "summary": issue.summary,
            "description": issue.description,
            "severity": issue.severity,
            "idempotency_key": issue.idempotency_key,
            "run_marker": issue.run_marker,
            "url": issue.url,
            "archived": issue.archived,
            "duplicate": duplicate,
        }


class FakeBitbucketMcp:
    """Stateful Bitbucket MCP fake with comments and merge observability."""

    def __init__(self, ledger: MonotonicMcpLedger) -> None:
        self._ledger = ledger
        self.state = BitbucketState()
        self.server = LocalHttpServer(self._handle)

    def _handle(
        self,
        method: str,
        path: str,
        headers: Mapping[str, str],
        payload: JsonObject,
    ) -> tuple[int, JsonObject]:
        del headers
        if method != "POST" or path != "/mcp":
            return HTTPStatus.NOT_FOUND, {"error": "not found"}
        request_id = payload.get("id")
        if payload.get("jsonrpc") != "2.0" or payload.get("method") != "tools/call":
            return HTTPStatus.OK, _json_rpc_error(request_id, -32600, "invalid request")
        params = payload.get("params", {})
        tool = params.get("name")
        arguments = dict(params.get("arguments", {}))
        self._ledger.record("bitbucket", tool, arguments)
        self.state.call_log.append({"tool": tool, "arguments": arguments})
        match tool:
            case "bitbucket_get_pullrequest_by_id":
                result = self._get_pull_request(arguments)
            case "bitbucket_get_pr_diff":
                result = self._get_diff(arguments)
            case "bitbucket_post_pr_comment":
                result = self._post_comment(arguments)
            case "bitbucket_get_pr_review_state":
                result = self._review_state(arguments)
            case "bitbucket_close_pr_comment":
                result = self._close_comment(arguments)
            case "bitbucket_merge_pullrequest":
                self.state.merge_count += 1
                result = {"merged": True}
            case _:
                return HTTPStatus.OK, _json_rpc_error(
                    request_id,
                    -32601,
                    f"unknown Bitbucket tool: {tool}",
                )
        return HTTPStatus.OK, _json_rpc_result(request_id, result)

    @staticmethod
    def _get_pull_request(arguments: JsonObject) -> JsonObject:
        return {
            "id": arguments["pull_request_id"],
            "title": "Add account payment lookup",
            "state": "OPEN",
            "author": "acceptance-user",
            "source": {"branch": {"name": "feature/payment-lookup"}},
            "destination": {"branch": {"name": "main"}},
            "links": {"html": "https://bitbucket.test/payments-api/pull-requests/42"},
        }

    @staticmethod
    def _get_diff(arguments: JsonObject) -> JsonObject:
        return {
            "pull_request_id": arguments["pull_request_id"],
            "diff": (
                "diff --git a/src/payments.py b/src/payments.py\n"
                '+query = f"SELECT * FROM payments WHERE account_id = {account_id}"\n'
                "+cursor.execute(query)\n"
            ),
            "files": ["src/payments.py"],
        }

    def _post_comment(self, arguments: JsonObject) -> JsonObject:
        marker = str(arguments["run_marker"])
        existing = next(
            (comment for comment in self.state.comments if comment.run_marker == marker),
            None,
        )
        if existing is not None:
            return self._comment_payload(existing, duplicate=True)
        comment = PullRequestComment(
            comment_id=7001,
            content=str(arguments["content"]),
            idempotency_key=str(arguments["idempotency_key"]),
            run_marker=marker,
            url=f"{self.server.url}/comments/7001",
        )
        self.state.comments.append(comment)
        return self._comment_payload(comment, duplicate=False)

    def _review_state(self, arguments: JsonObject) -> JsonObject:
        marker = str(arguments["run_marker"])
        comments = [
            self._comment_payload(comment, duplicate=False)
            for comment in self.state.comments
            if comment.run_marker == marker and not comment.closed
        ]
        return {
            "comments": comments,
            "comment_total": len(comments),
            "merged": self.state.merge_count > 0,
            "merge_count": self.state.merge_count,
        }

    def _close_comment(self, arguments: JsonObject) -> JsonObject:
        comment = next(
            (
                candidate
                for candidate in self.state.comments
                if candidate.comment_id == arguments["comment_id"]
                and candidate.idempotency_key == arguments["idempotency_key"]
            ),
            None,
        )
        if comment is None:
            raise RuntimeError("comment not found for cleanup")
        comment.closed = True
        return {"comment_id": comment.comment_id, "closed": True}

    @staticmethod
    def _comment_payload(
        comment: PullRequestComment,
        *,
        duplicate: bool,
    ) -> JsonObject:
        return {
            "comment_id": comment.comment_id,
            "content": comment.content,
            "idempotency_key": comment.idempotency_key,
            "run_marker": comment.run_marker,
            "url": comment.url,
            "closed": comment.closed,
            "duplicate": duplicate,
        }


class FakeDashboard:
    """Captures redacted reports posted to the fake ingestion endpoint."""

    def __init__(self) -> None:
        self.state = DashboardState()
        self.server = LocalHttpServer(self._handle)

    def _handle(
        self,
        method: str,
        path: str,
        headers: Mapping[str, str],
        payload: JsonObject,
    ) -> tuple[int, JsonObject]:
        if method != "POST" or path != "/ingest":
            return HTTPStatus.NOT_FOUND, {"error": "not found"}
        self.state.payload = payload
        self.state.authorization = headers.get("Authorization")
        self.state.call_log.append({"path": path, "payload": payload})
        return HTTPStatus.ACCEPTED, {"accepted": True}


class DeterministicReviewAgent:
    """Rule-based agent fake that orchestrates two MCP servers over HTTP."""

    _READ_TOOLS = {
        "bitbucket_get_pullrequest_by_id",
        "bitbucket_get_pr_diff",
        "bitbucket_get_pr_review_state",
        "jira_search_issues",
    }

    def __init__(self, *, bitbucket_url: str, jira_url: str) -> None:
        self._bitbucket = JsonRpcMcpClient(bitbucket_url)
        self._jira = JsonRpcMcpClient(jira_url)
        self._completed: dict[str, JsonObject] = {}
        self.server = LocalHttpServer(self._handle)

    def _handle(
        self,
        method: str,
        path: str,
        headers: Mapping[str, str],
        payload: JsonObject,
    ) -> tuple[int, JsonObject]:
        del headers
        if method != "POST" or path != "/api/v1/execute":
            return HTTPStatus.NOT_FOUND, {"error": "not found"}
        metadata = dict(payload["metadata"])
        request_input = dict(payload["input"])
        marker = str(metadata["idempotency_key"])
        tool_calls: list[JsonObject] = []

        pr_arguments = {
            "workspace": request_input["workspace"],
            "repository": request_input["repository"],
            "pull_request_id": request_input["pull_request_id"],
            "run_marker": marker,
        }
        diff_arguments = {**pr_arguments, "context_lines": 3}
        self._call(
            self._bitbucket,
            "bitbucket",
            "bitbucket_get_pullrequest_by_id",
            pr_arguments,
            tool_calls,
        )
        diff = self._call(
            self._bitbucket,
            "bitbucket",
            "bitbucket_get_pr_diff",
            diff_arguments,
            tool_calls,
        )
        if "cursor.execute(query)" not in str(diff["diff"]):
            return HTTPStatus.OK, self._response(
                metadata,
                success=False,
                response={"critical_issue": None},
                tool_calls=tool_calls,
                error="Expected deterministic critical issue was absent",
            )

        if marker not in self._completed:
            issue_arguments = {
                "project": request_input["jira_project"],
                "summary": CRITICAL_SUMMARY,
                "description": CRITICAL_DESCRIPTION,
                "severity": "critical",
                "idempotency_key": marker,
                "run_marker": marker,
                "api_token": FAKE_SECRET,
            }
            issue = self._call(
                self._jira,
                "jira",
                "jira_create_issue",
                issue_arguments,
                tool_calls,
            )
            comment_arguments = {
                **pr_arguments,
                "content": (
                    "Blocked: critical SQL injection at src/payments.py:18. "
                    f"Tracking issue {issue['key']}."
                ),
                "idempotency_key": marker,
            }
            comment = self._call(
                self._bitbucket,
                "bitbucket",
                "bitbucket_post_pr_comment",
                comment_arguments,
                tool_calls,
            )
            self._completed[marker] = {
                "critical_issue": CRITICAL_SUMMARY,
                "severity": "critical",
                "jira_issue": issue["key"],
                "jira_issue_url": issue["url"],
                "bitbucket_comment_id": comment["comment_id"],
                "bitbucket_comment_url": comment["url"],
                "merged": False,
                "idempotency_key": marker,
            }
        else:
            self._call(
                self._jira,
                "jira",
                "jira_search_issues",
                {"project": request_input["jira_project"], "run_marker": marker},
                tool_calls,
            )
            self._call(
                self._bitbucket,
                "bitbucket",
                "bitbucket_get_pr_review_state",
                pr_arguments,
                tool_calls,
            )

        return HTTPStatus.OK, self._response(
            metadata,
            success=True,
            response=self._completed[marker],
            tool_calls=tool_calls,
        )

    def _call(
        self,
        client: JsonRpcMcpClient,
        server: str,
        tool: str,
        arguments: JsonObject,
        tool_calls: list[JsonObject],
    ) -> JsonObject:
        output = client.call(tool, arguments)
        tool_calls.append(
            {
                "id": f"call-{len(tool_calls) + 1}",
                "server": server,
                "name": tool,
                "arguments": arguments,
                "output": output,
                "status": "success",
                "started_at": _FIXED_TIMESTAMP,
                "completed_at": _FIXED_TIMESTAMP,
                "duration_ms": 1,
                "attempt": 1,
                "parent_step_id": "review-pr",
                "operation_kind": "read" if tool in self._READ_TOOLS else "write",
            }
        )
        return output

    @staticmethod
    def _response(
        metadata: JsonObject,
        *,
        success: bool,
        response: JsonObject,
        tool_calls: list[JsonObject],
        error: str | None = None,
    ) -> JsonObject:
        events = [
            {
                "timestamp": _FIXED_TIMESTAMP,
                "label": f"{call['server']}/{call['name']}",
                "event_type": "tool_result",
                "server": call["server"],
                "tool_name": call["name"],
                "status": call["status"],
                "metadata": {"attempt": call["attempt"]},
            }
            for call in tool_calls
        ]
        return {
            "success": success,
            "run_id": metadata["run_id"],
            "trace_id": metadata["trace_id"],
            "correlation_id": metadata["correlation_id"],
            "response": response,
            "error": error,
            "trace": {
                "tool_calls": tool_calls,
                "events": events,
                "token_usage": 128,
                "estimated_cost_usd": 0.0,
                "model": "deterministic-rules-v1",
            },
            "started_at": _FIXED_TIMESTAMP,
            "completed_at": _FIXED_TIMESTAMP,
            "duration_ms": len(tool_calls),
        }


class ReviewStateVerifier:
    """Independently verifies Jira, Bitbucket comment, and no-merge state."""

    name = "independent-jira-bitbucket-state"

    def __init__(
        self,
        *,
        jira_url: str,
        bitbucket_url: str,
        idempotency_key: str,
    ) -> None:
        self._jira_url = jira_url
        self._bitbucket_url = bitbucket_url
        self._idempotency_key = idempotency_key

    async def verify(self, context: VerificationContext) -> VerificationResult:
        del context
        return await asyncio.to_thread(self._verify_sync)

    def _verify_sync(self) -> VerificationResult:
        issues = JsonRpcMcpClient(self._jira_url).call(
            "jira_search_issues",
            {"project": "SEC", "run_marker": self._idempotency_key},
        )
        review = JsonRpcMcpClient(self._bitbucket_url).call(
            "bitbucket_get_pr_review_state",
            {
                "workspace": "pango_dev",
                "repository": "payments-api",
                "pull_request_id": 42,
                "run_marker": self._idempotency_key,
            },
        )
        issue_rows = issues["issues"]
        comments = review["comments"]
        passed = (
            issues["total"] == 1
            and review["comment_total"] == 1
            and review["merge_count"] == 0
            and issue_rows[0]["idempotency_key"] == self._idempotency_key
            and comments[0]["idempotency_key"] == self._idempotency_key
        )
        return VerificationResult(
            passed=passed,
            message=(
                "One Jira issue and one PR comment exist; pull request was not merged"
                if passed
                else "Unexpected Jira, Bitbucket comment, or merge state"
            ),
            evidence={
                "jira_issue": issue_rows[0]["url"] if issue_rows else None,
                "bitbucket_comment": comments[0]["url"] if comments else None,
                "merge_count": review["merge_count"],
                "issue_count": issues["total"],
                "comment_count": review["comment_total"],
            },
        )


class FakeReviewEnvironment:
    """Owns the complete disposable acceptance environment and state."""

    def __init__(self) -> None:
        self._mcp_ledger = MonotonicMcpLedger()
        self.jira = FakeJiraMcp(self._mcp_ledger)
        self.bitbucket = FakeBitbucketMcp(self._mcp_ledger)
        self.dashboard = FakeDashboard()
        self.agent: DeterministicReviewAgent | None = None
        self.cleanup_log: list[str] = []
        self.is_closed = False

    def start(self) -> None:
        self.jira.server.start()
        self.bitbucket.server.start()
        self.dashboard.server.start()
        self.agent = DeterministicReviewAgent(
            bitbucket_url=self.bitbucket_url,
            jira_url=self.jira_url,
        )
        self.agent.server.start()

    @property
    def agent_url(self) -> str:
        if self.agent is None:
            raise RuntimeError("Environment has not been started")
        return self.agent.server.url

    @property
    def jira_url(self) -> str:
        return self.jira.server.url

    @property
    def bitbucket_url(self) -> str:
        return self.bitbucket.server.url

    @property
    def dashboard_url(self) -> str:
        return self.dashboard.server.url

    @property
    def active_issue_count(self) -> int:
        return sum(not issue.archived for issue in self.jira.state.issues)

    @property
    def archived_issue_count(self) -> int:
        return sum(issue.archived for issue in self.jira.state.issues)

    @property
    def active_comment_count(self) -> int:
        return sum(not comment.closed for comment in self.bitbucket.state.comments)

    @property
    def closed_comment_count(self) -> int:
        return sum(comment.closed for comment in self.bitbucket.state.comments)

    @property
    def merge_count(self) -> int:
        return self.bitbucket.state.merge_count

    @property
    def write_call_log(self) -> list[JsonObject]:
        writes = {"jira_create_issue", "bitbucket_post_pr_comment"}
        return [
            entry
            for entry in [*self.jira.state.call_log, *self.bitbucket.state.call_log]
            if entry["tool"] in writes
        ]

    @property
    def dashboard_payload(self) -> JsonObject | None:
        return self.dashboard.state.payload

    @property
    def dashboard_authorization(self) -> str | None:
        return self.dashboard.state.authorization

    @property
    def mcp_request_ledger(self) -> list[JsonObject]:
        return self._mcp_ledger.snapshot()

    async def cleanup_resources(self, idempotency_key: str) -> None:
        await asyncio.to_thread(self._cleanup_resources_sync, idempotency_key)

    def _cleanup_resources_sync(self, idempotency_key: str) -> None:
        issue = next(
            (
                issue
                for issue in self.jira.state.issues
                if issue.idempotency_key == idempotency_key and not issue.archived
            ),
            None,
        )
        if issue is not None:
            JsonRpcMcpClient(self.jira_url).call(
                "jira_archive_issue",
                {"issue_key": issue.key, "idempotency_key": idempotency_key},
            )
            self.cleanup_log.append("jira_archive_issue")
        comment = next(
            (
                comment
                for comment in self.bitbucket.state.comments
                if comment.idempotency_key == idempotency_key and not comment.closed
            ),
            None,
        )
        if comment is not None:
            JsonRpcMcpClient(self.bitbucket_url).call(
                "bitbucket_close_pr_comment",
                {
                    "comment_id": comment.comment_id,
                    "idempotency_key": idempotency_key,
                },
            )
            self.cleanup_log.append("bitbucket_close_pr_comment")

    def close(self) -> None:
        if self.agent is not None:
            self.agent.server.close()
        self.dashboard.server.close()
        self.jira.server.close()
        self.bitbucket.server.close()
        self.is_closed = True
