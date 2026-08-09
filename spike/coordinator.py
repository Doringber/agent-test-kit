"""Session Coordinator: owns ALL per-execution state. One coordinator per execution.

ARCH-002 R.3.1. Loopback TCP so multiple stdio proxy processes share one session
(sequence counter, overlay, clock, minting, divergence log). INV-006, INV-007.
"""
from __future__ import annotations

import json
import socket
import threading
import uuid

from models import Interaction, ReplayStats, SessionSummary, World
from replay import ReplayEngine
from world import canonicalize

_REDACT_KEYS = {"token", "secret", "password", "authorization", "api_key", "apikey"}


def redact(obj):
    """Stub redactor. NFR-041 requires this before persistence; full impl is out of M0."""
    if isinstance(obj, dict):
        return {k: ("[REDACTED]" if k.lower() in _REDACT_KEYS else redact(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


class SessionCoordinator:
    def __init__(self, world: World | None, seed: int, mode: str) -> None:
        self.world = world
        self.seed = seed
        self.mode = mode
        self.session_id = f"m0_{uuid.uuid4().hex[:8]}"
        self._seq = 0
        self._lock = threading.Lock()
        self._servers: dict[str, list] = {}
        self._interactions: list[Interaction] = []
        self._engine = ReplayEngine(world, seed) if (world and mode == "replay") else None
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = False

    # ------------------------------------------------------------ lifecycle

    def start(self) -> int:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        return self._sock.getsockname()[1]

    def stop(self) -> None:
        self._running = False
        try:
            if self._sock:
                self._sock.close()
        except OSError:
            pass

    def reset(self) -> None:
        """Step 6. Full isolation between executions (INV-006)."""
        with self._lock:
            self._seq = 0
            self._interactions.clear()
            if self._engine:
                self._engine.reset()

    def summary(self) -> SessionSummary:
        stats = self._engine.stats() if self._engine else ReplayStats()
        return SessionSummary(self.session_id, self._seq, stats, list(self._interactions))

    # ------------------------------------------------------------ session state

    def next_seq(self) -> int:
        with self._lock:
            self._seq += 1
            return self._seq

    def register_server(self, server_id: str) -> None:
        with self._lock:
            self._servers.setdefault(server_id, [])

    def handle_call(self, server_id: str, tool: str, args: dict):
        """REPLAY only. Never raises for protocol reasons."""
        if self._engine is None:
            raise RuntimeError("handle_call requires replay mode")
        with self._lock:
            return self._engine.handle(server_id, tool, args)

    def log_interaction(self, server_id: str, tool: str, request: dict,
                        response: dict, status: str) -> None:
        """RECORD only. Redaction happens here, before anything is persisted."""
        vol = self.world.volatile_paths if self.world else ()
        with self._lock:
            self._interactions.append(Interaction(
                seq=self._seq, server=server_id, tool=tool,
                request=canonicalize(redact(request), vol),
                response=redact(response), status=status))

    def log_tools(self, server_id: str, tools: list) -> None:
        with self._lock:
            self._servers[server_id] = tools

    def tools_of(self, server_id: str) -> list:
        if self.world and self.world.tools_list.get(server_id):
            return self.world.tools_list[server_id]
        return self._servers.get(server_id, [])

    def servers(self) -> dict[str, list]:
        return dict(self._servers)

    # ------------------------------------------------------------ IPC

    def _serve(self) -> None:
        while self._running:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()

    def _client(self, conn: socket.socket) -> None:
        buf = b""
        with conn:
            while self._running:
                try:
                    chunk = conn.recv(65536)
                except OSError:
                    return
                if not chunk:
                    return
                buf += chunk
                while b"\n" in buf:
                    raw, buf = buf.split(b"\n", 1)
                    if not raw.strip():
                        continue
                    try:
                        reply = self._dispatch(json.loads(raw))
                    except Exception as exc:                      # spike: surface, never hide
                        reply = {"error": f"{type(exc).__name__}: {exc}"}
                    try:
                        conn.sendall((json.dumps(reply, default=str) + "\n").encode())
                    except OSError:
                        return

    def _dispatch(self, msg: dict) -> dict:
        op = msg.get("op")
        if op == "register":
            self.register_server(msg["server_id"])
            return {"ok": True, "mode": self.mode}
        if op == "seq":
            return {"seq": self.next_seq()}
        if op == "tools_list":
            self.log_tools(msg["server_id"], msg.get("tools") or [])
            return {"ok": True}
        if op == "tools_of":
            return {"tools": self.tools_of(msg["server_id"])}
        if op == "log":
            self.log_interaction(msg["server_id"], msg["tool"], msg.get("request") or {},
                                 msg.get("response") or {}, msg.get("status", "success"))
            return {"ok": True}
        if op == "call":
            out = self.handle_call(msg["server_id"], msg["tool"], msg.get("args") or {})
            return {"served": out.served, "response": out.response,
                    "provenance": out.provenance, "stale_paths": list(out.stale_paths),
                    "divergence": (None if out.divergence is None else {
                        "cls": out.divergence.cls, "severity": out.divergence.severity,
                        "seq": out.divergence.seq, "detail": out.divergence.detail})}
        return {"error": f"unknown op {op!r}"}
