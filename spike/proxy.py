"""stdio MCP proxy. ADR-002: interception at the tool-protocol boundary.

RECORD  : spawn the real server as a child, relay both ways, log every tools/call.
REPLAY  : no upstream, no credentials, no network. Serve from the coordinator.

Newline-delimited JSON-RPC 2.0, which is the MCP stdio framing.
Spawned BY the agent's MCP client as its configured server command.
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading


class Link:
    """Line-delimited JSON over loopback TCP to the Session Coordinator."""

    def __init__(self, port: int) -> None:
        self.sock = socket.create_connection(("127.0.0.1", port))
        self.buf = b""
        self.lock = threading.Lock()

    def rpc(self, msg: dict) -> dict:
        with self.lock:
            self.sock.sendall((json.dumps(msg, default=str) + "\n").encode())
            while b"\n" not in self.buf:
                chunk = self.sock.recv(65536)
                if not chunk:
                    return {"error": "coordinator closed"}
                self.buf += chunk
            raw, self.buf = self.buf.split(b"\n", 1)
            return json.loads(raw)


class StdioProxy:
    def __init__(self, server_id: str, coordinator_port: int,
                 upstream_cmd: list[str] | None) -> None:
        self.server_id = server_id
        self.link = Link(coordinator_port)
        self.upstream_cmd = upstream_cmd
        self.proc: subprocess.Popen | None = None
        self._pending: dict = {}

    # ------------------------------------------------------------ upstream (RECORD)

    def _start_upstream(self) -> None:
        self.proc = subprocess.Popen(
            self.upstream_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=sys.stderr, text=True, encoding="utf-8", bufsize=1)

    def _upstream_rpc(self, msg: dict) -> dict:
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        while True:
            line = self.proc.stdout.readline()
            if not line:
                return {"jsonrpc": "2.0", "id": msg.get("id"),
                        "error": {"code": -32000, "message": "upstream closed"}}
            line = line.strip()
            if not line:
                continue
            try:
                reply = json.loads(line)
            except json.JSONDecodeError:
                continue
            if reply.get("id") == msg.get("id"):
                return reply

    # ------------------------------------------------------------ run loop

    def run(self) -> int:
        self.link.rpc({"op": "register", "server_id": self.server_id})
        if self.upstream_cmd:
            self._start_upstream()

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

            if method == "notifications/initialized":
                if self.upstream_cmd:
                    self.proc.stdin.write(line + "\n")
                    self.proc.stdin.flush()
                continue

            result = self._handle(method, msg)
            if mid is not None and result is not None:
                out.write(json.dumps({"jsonrpc": "2.0", "id": mid, "result": result},
                                     default=str) + "\n")
                out.flush()

        if self.proc:
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()
        return 0

    def _handle(self, method: str, msg: dict):
        if method == "initialize":
            if self.upstream_cmd:
                return self._upstream_rpc(msg).get("result")
            return {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                    "serverInfo": {"name": f"replay:{self.server_id}", "version": "0.1.0"}}

        if method == "tools/list":
            if self.upstream_cmd:
                res = self._upstream_rpc(msg).get("result") or {}
                self.link.rpc({"op": "tools_list", "server_id": self.server_id,
                               "tools": res.get("tools", [])})
                return res
            return {"tools": self.link.rpc({"op": "tools_of",
                                            "server_id": self.server_id}).get("tools", [])}

        if method == "tools/call":
            params = msg.get("params") or {}
            tool = params.get("name", "")
            args = params.get("arguments") or {}
            self.link.rpc({"op": "seq"})              # preserve global ordering

            if self.upstream_cmd:                      # RECORD
                reply = self._upstream_rpc(msg)
                res = reply.get("result") or {}
                payload, status = _unwrap(res)
                self.link.rpc({"op": "log", "server_id": self.server_id, "tool": tool,
                               "request": args, "response": payload, "status": status})
                return res

            # REPLAY
            r = self.link.rpc({"op": "call", "server_id": self.server_id,
                               "tool": tool, "args": args})
            if not r.get("served"):
                d = r.get("divergence") or {}
                return {"content": [{"type": "text", "text": json.dumps(
                    {"divergence": d.get("cls"), "severity": d.get("severity"),
                     "detail": d.get("detail")})}], "isError": True,
                    "_agenttest": {"served": False, "divergence": d}}
            return {"content": [{"type": "text",
                                 "text": json.dumps(r.get("response"), default=str)}],
                    "isError": False,
                    "_agenttest": {"served": True, "provenance": r.get("provenance"),
                                   "stale_paths": r.get("stale_paths"),
                                   "divergence": r.get("divergence")}}
        return None


def _unwrap(res: dict) -> tuple[dict, str]:
    """MCP tool results are content arrays; recover the JSON payload for the world."""
    status = "error" if res.get("isError") else "success"
    for item in res.get("content") or []:
        if item.get("type") == "text":
            try:
                val = json.loads(item.get("text") or "")
                return (val if isinstance(val, dict) else {"value": val}), status
            except json.JSONDecodeError:
                return {"text": item.get("text")}, status
    return {}, status


if __name__ == "__main__":
    _sid, _port, *_cmd = sys.argv[1:]
    raise SystemExit(StdioProxy(_sid, int(_port), _cmd or None).run())
