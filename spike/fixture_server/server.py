#!/usr/bin/env python3
"""Server C: deterministic MCP fixture server. Known ground truth for the spike.

Entity-oriented issue tracker over MCP stdio (newline-delimited JSON-RPC 2.0).
Deliberately small. Not a framework.

Tools:
  create_issue(project, title)          -> {id, project, title, status, created_at}
  get_issue(id)                         -> issue | error
  update_issue(id, title?, status?)     -> issue
  delete_issue(id)                      -> {deleted: id}
  list_issues(project, limit?, offset?) -> {issues: [...], total: N}
  search_issues(query)                  -> {issues: [...]}   # query language, L1 only

Determinism: timestamps come from a virtual clock (fixed epoch + fixed tick).
Errors: FIXTURE_FAIL_ON="tool_name" env var forces one controlled error.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
TICK = timedelta(seconds=1)

TOOLS = [
    {"name": "create_issue", "description": "Create an issue",
     "inputSchema": {"type": "object", "properties": {
         "project": {"type": "string"}, "title": {"type": "string"}},
         "required": ["project", "title"]}},
    {"name": "get_issue", "description": "Get one issue by id",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}},
                     "required": ["id"]}},
    {"name": "update_issue", "description": "Update an issue",
     "inputSchema": {"type": "object", "properties": {
         "id": {"type": "string"}, "title": {"type": "string"},
         "status": {"type": "string"}}, "required": ["id"]}},
    {"name": "delete_issue", "description": "Delete an issue",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}},
                     "required": ["id"]}},
    {"name": "list_issues", "description": "List issues in a project",
     "inputSchema": {"type": "object", "properties": {
         "project": {"type": "string"}, "limit": {"type": "integer"},
         "offset": {"type": "integer"}}, "required": ["project"]}},
    {"name": "search_issues", "description": "Search issues with a query expression",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}},
                     "required": ["query"]}},
]


class Store:
    def __init__(self) -> None:
        self.ticks = 0
        self.counter = 0
        self.issues: dict[str, dict] = {}
        # Seed state, so a recording has something to read.
        self._seed("QA", "Existing issue")

    def now(self) -> str:
        self.ticks += 1
        return (EPOCH + TICK * self.ticks).isoformat().replace("+00:00", "Z")

    def _seed(self, project: str, title: str) -> dict:
        self.counter += 1
        iid = f"FX-{self.counter:03d}"
        issue = {"id": iid, "project": project, "title": title,
                 "status": "open", "created_at": self.now()}
        self.issues[iid] = issue
        return issue

    def create(self, project: str, title: str) -> dict:
        return self._seed(project, title)

    def get(self, iid: str) -> dict | None:
        return self.issues.get(iid)

    def update(self, iid: str, **fields) -> dict | None:
        issue = self.issues.get(iid)
        if issue is None:
            return None
        for k, v in fields.items():
            if v is not None and k in ("title", "status"):
                issue[k] = v
        return issue

    def delete(self, iid: str) -> bool:
        return self.issues.pop(iid, None) is not None

    def list(self, project: str, limit: int | None, offset: int | None) -> dict:
        rows = [i for i in self.issues.values() if i["project"] == project]
        rows.sort(key=lambda i: i["id"])
        total = len(rows)
        off = offset or 0
        page = rows[off: off + limit] if limit is not None else rows[off:]
        return {"issues": page, "total": total}

    def search(self, query: str) -> dict:
        # Deliberately a query language: "field=value AND field=value".
        rows = list(self.issues.values())
        for clause in [c.strip() for c in query.split("AND")]:
            if "=" not in clause:
                continue
            k, v = (p.strip() for p in clause.split("=", 1))
            rows = [r for r in rows if str(r.get(k)) == v]
        rows.sort(key=lambda i: i["id"])
        return {"issues": rows}


def dispatch(store: Store, tool: str, args: dict) -> tuple[dict | None, str | None]:
    """Return (result, error_message)."""
    if os.environ.get("FIXTURE_FAIL_ON") == tool:
        return None, f"controlled failure for {tool}"
    if tool == "create_issue":
        return store.create(args["project"], args["title"]), None
    if tool == "get_issue":
        issue = store.get(args["id"])
        return (issue, None) if issue else (None, f"no such issue {args['id']}")
    if tool == "update_issue":
        issue = store.update(args["id"], title=args.get("title"), status=args.get("status"))
        return (issue, None) if issue else (None, f"no such issue {args['id']}")
    if tool == "delete_issue":
        ok = store.delete(args["id"])
        return ({"deleted": args["id"]}, None) if ok else (None, f"no such issue {args['id']}")
    if tool == "list_issues":
        return store.list(args["project"], args.get("limit"), args.get("offset")), None
    if tool == "search_issues":
        return store.search(args["query"]), None
    return None, f"unknown tool {tool}"


def main() -> int:
    store = Store()
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method, mid = msg.get("method"), msg.get("id")
        if method == "initialize":
            reply = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                     "serverInfo": {"name": "fixture-issues", "version": "0.1.0"}}
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            reply = {"tools": TOOLS}
        elif method == "tools/call":
            params = msg.get("params") or {}
            result, err = dispatch(store, params.get("name", ""),
                                   params.get("arguments") or {})
            if err is not None:
                reply = {"content": [{"type": "text", "text": err}], "isError": True}
            else:
                reply = {"content": [{"type": "text", "text": json.dumps(result)}],
                         "isError": False}
        else:
            if mid is None:
                continue
            out.write(json.dumps({"jsonrpc": "2.0", "id": mid,
                                  "error": {"code": -32601, "message": "method not found"}}) + "\n")
            out.flush()
            continue
        if mid is not None:
            out.write(json.dumps({"jsonrpc": "2.0", "id": mid, "result": reply}) + "\n")
            out.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
