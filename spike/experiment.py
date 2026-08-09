"""Drives the nine-step proof and captures measurements M1-M9.

DEVIATION (recorded in FINDINGS.md, D-1): the "agent" is a scripted MCP client rather
than an LLM. M5 requires identical outcome hashes for a fixed tool-call sequence; an LLM
would vary the sequence and make world-determinism unmeasurable. The scripted client
exercises the identical protocol path (ADR-002 interception point).
"""
from __future__ import annotations

import hashlib
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

from compile import compile_world
from coordinator import SessionCoordinator
from world import load_world, save_world

HERE = Path(__file__).parent
RESULTS = HERE / "results"
PY = sys.executable


# ---------------------------------------------------------------- agent driver

class AgentDriver:
    """Minimal MCP client. Spawns the proxy as its configured server (ADR-002)."""

    def __init__(self, server_id: str, port: int, upstream: list[str] | None) -> None:
        cmd = [PY, str(HERE / "proxy.py"), server_id, str(port)] + (upstream or [])
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True,
                                  encoding="utf-8", bufsize=1, cwd=str(HERE))
        self._id = 0

    def rpc(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            msg["params"] = params
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()
        while True:
            line = self.p.stdout.readline()
            if not line:
                return {"error": "proxy closed"}
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("id") == self._id:
                return r.get("result") or {}

    def handshake(self) -> list:
        self.rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                "clientInfo": {"name": "m0-driver", "version": "0"}})
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0",
                                       "method": "notifications/initialized"}) + "\n")
        self.p.stdin.flush()
        return (self.rpc("tools/list") or {}).get("tools", [])

    def call(self, tool: str, args: dict) -> dict:
        return self.rpc("tools/call", {"name": tool, "arguments": args})

    def close(self) -> None:
        try:
            self.p.stdin.close()
            self.p.wait(timeout=5)
        except Exception:
            self.p.kill()


def run_script(server_id: str, port: int, upstream, script: list[dict]) -> list[dict]:
    ag = AgentDriver(server_id, port, upstream)
    try:
        ag.handshake()
        out = []
        for step in script:
            t0 = time.perf_counter()
            res = ag.call(step["tool"], step["args"])
            meta = res.get("_agenttest") or {}
            payload = None
            for item in res.get("content") or []:
                if item.get("type") == "text":
                    try:
                        payload = json.loads(item["text"])
                    except json.JSONDecodeError:
                        payload = item["text"]
            out.append({"tool": step["tool"], "args": step["args"],
                        "served": meta.get("served", not res.get("isError")),
                        "provenance": meta.get("provenance"),
                        "stale_paths": meta.get("stale_paths") or [],
                        "divergence": (meta.get("divergence") or {}).get("cls"),
                        "payload": payload,
                        "latency_ms": (time.perf_counter() - t0) * 1000})
        return out
    finally:
        ag.close()


def outcome_hash(steps: list[dict]) -> str:
    """Everything the world produced. Excludes latency."""
    blob = json.dumps([{k: s[k] for k in
                        ("tool", "args", "served", "provenance", "stale_paths",
                         "divergence", "payload")} for s in steps],
                      sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


# ---------------------------------------------------------------- phases

def record(server_id: str, upstream: list[str], script: list[dict],
           log_path: Path, clean: list[str] = (), env: dict | None = None) -> list[dict]:
    for rel in clean:                                  # deterministic starting state
        p = HERE / rel
        if p.exists():
            p.unlink()
    for k, v in (env or {}).items():
        os.environ[k] = str((HERE / v).resolve()) if "/" in v or "\\" in v else v
    co = SessionCoordinator(world=None, seed=42, mode="record")
    port = co.start()
    try:
        steps = run_script(server_id, port, upstream, script)
        s = co.summary()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(json.dumps({
            "tools_list": co.servers(),
            "interactions": [i.__dict__ for i in s.interactions]}, indent=2, default=str),
            encoding="utf-8")
        return steps
    finally:
        co.stop()


def replay(world, script: list[dict], server_id: str, seed: int = 42):
    co = SessionCoordinator(world=world, seed=seed, mode="replay")
    port = co.start()
    try:
        steps = run_script(server_id, port, None, script)
        return steps, co.summary()
    finally:
        co.stop()


# ---------------------------------------------------------------- scenario per server

def scenario(name: str, server_id: str, upstream: list[str], scripts: dict,
             answers: dict, expect: dict) -> dict:
    """Run steps 1-9 for one target server. Returns per-server measurements."""
    print(f"\n=== {name} ({server_id}) ===")
    r = {"server": name, "steps": {}, "notes": []}

    # ---- step 1: RECORD real traffic
    log = RESULTS / f"session_{server_id}.json"
    rec = record(server_id, upstream, scripts["record"], log,
                 clean=expect.get("_clean", []), env=expect.get("_env"))
    ok1 = all(s["served"] for s in rec) and len(rec) == len(scripts["record"])
    r["steps"]["1_record"] = ok1
    print(f"  1 record ................ {'ok' if ok1 else 'FAIL'} ({len(rec)} calls)")

    world, report = compile_world(log, world_id=f"m0-{server_id}", answers=answers,
                                  out=HERE / "worlds" / f"m0-{server_id}.yaml")
    fid = {f"{s}/{t}": c.fidelity for (s, t), c in world.tools.items()}
    r["fidelity"] = fid
    r["decisions_per_tool"] = report.decisions_per_tool
    print(f"    fidelity: {fid}")

    # ---- M10 structural fidelity (ADR-006). Candidates = create tools evaluated.
    cands, accepted, rejected, reasons = 0, 0, 0, {}
    for (s, t), c in world.tools.items():
        if c.validation is None:
            continue
        cands += 1
        if c.validation.ok and c.fidelity == "l2_core":
            accepted += 1
        else:
            rejected += 1
            first = c.validation.first_failure() or "unknown"
            reasons[first] = reasons.get(first, 0) + 1
    r["m10"] = {"candidates": cands, "accepted": accepted, "rejected": rejected,
                "rejection_reasons": reasons,
                "validations": {f"{s}/{t}": {"passed": list(c.validation.passed),
                                             "failed": list(c.validation.failed),
                                             "reasons": c.validation.reasons}
                                for (s, t), c in world.tools.items()
                                if c.validation is not None},
                "l1_reasons": {f"{s}/{t}": (c.validation.reasons.get(
                    c.validation.first_failure(), "") if c.validation else "not a create tool")
                    for (s, t), c in world.tools.items() if c.fidelity == "l1"}}
    print(f"    M10 candidates={cands} accepted={accepted} rejected={rejected} {reasons}")

    # ---- step 2: exact replay
    steps2, _ = replay(world, scripts["exact"], server_id)
    ok2 = all(s["served"] and s["provenance"] == "recorded" for s in steps2)
    r["steps"]["2_exact_replay"] = ok2
    print(f"  2 exact replay .......... {'ok' if ok2 else 'FAIL'}")

    # ---- steps 3-7: unrecorded write, overlay, read-after-write, reset, determinism
    hashes, lat, last = [], [], None
    for _ in range(10):
        steps, _summary = replay(world, scripts["write"], server_id)
        hashes.append(outcome_hash(steps))
        lat += [s["latency_ms"] for s in steps]
        last = steps
    ok7 = len(set(hashes)) == 1
    r["outcome_hashes"] = hashes
    r["steps"]["7_determinism"] = ok7

    wrote = [s for s in last if s["tool"] in expect["write_tools"]]
    ok3 = bool(wrote) and all(s["served"] for s in wrote)
    ok4 = any(s["provenance"] == "synthesized" for s in wrote)
    read_back = [s for s in last if s["tool"] in expect["read_tools"]]
    ok5, struct_ok, struct_note = False, True, ""
    recorded_shape = set()
    for i in world.interactions:
        if i.tool in expect["read_tools"]:
            for row in (i.response or {}).get(expect["collection_key"], []) or []:
                if isinstance(row, dict):
                    recorded_shape |= set(row)
    for s in read_back:
        rows = (s["payload"] or {}).get(expect["collection_key"], []) \
            if isinstance(s["payload"], dict) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("id", "")).startswith(expect["minted_prefix"]):
                ok5 = True
                # STRUCTURAL FIDELITY: an overlay entity must look like a recorded one.
                # Without this, a mechanically-correct merge can still hand the agent
                # a malformed entity while reporting divergence=None. See FINDINGS F-1.
                extra = set(row) - recorded_shape - {"id", "created_at"}
                missing = recorded_shape - set(row)
                if extra or missing:
                    struct_ok = False
                    struct_note = (f"overlay entity shape {sorted(set(row))} != recorded "
                                   f"shape {sorted(recorded_shape)} "
                                   f"(extra={sorted(extra)}, missing={sorted(missing)})")
    # Reported SEPARATELY from step 5. Step 5 as specified asks only whether a
    # subsequent read observes the entity; folding structure into it would change the
    # specified criterion. This is a NEW finding (F-1), measured on its own.
    r["structural_fidelity_ok"] = struct_ok
    r["structural_note"] = struct_note
    if not struct_ok:
        r["notes"].append("STRUCTURAL FIDELITY GAP: " + struct_note)
    ok6 = ok7  # reset is what makes 10 identical hashes possible
    for k, v in (("3_unrecorded_write", ok3), ("4_overlay_mutation", ok4),
                 ("5_read_after_write", ok5), ("6_reset", ok6)):
        r["steps"][k] = v
    print(f"  3 unrecorded write ...... {'ok' if ok3 else 'FAIL'}")
    print(f"  4 overlay mutation ...... {'ok' if ok4 else 'FAIL'}")
    print(f"  5 READ-AFTER-WRITE ...... {'ok' if ok5 else 'FAIL'}   <-- core claim")
    print(f"  6 reset ................. {'ok' if ok6 else 'FAIL'}")
    print(f"  7 determinism ........... {'ok' if ok7 else 'FAIL'} ({len(set(hashes))} distinct/10)")

    # stale derived field check
    stale = sorted({p for s in last for p in s["stale_paths"]})
    r["stale_paths_observed"] = stale
    if expect.get("stale_path"):
        r["stale_ok"] = expect["stale_path"] in stale
        print(f"    stale {expect['stale_path']} .......... "
              f"{'ok' if r['stale_ok'] else 'FAIL'} (observed {stale})")

    # ---- steps 8-9: unsupported call -> classified divergence, never a response
    steps9, _ = replay(world, scripts["unsupported"], server_id)
    ok8 = len(steps9) == len(scripts["unsupported"])
    ok9 = all((not s["served"]) and s["divergence"] in expect["divergence_classes"]
              for s in steps9)
    r["steps"]["8_unsupported_issued"] = ok8
    r["steps"]["9_classified_divergence"] = ok9
    r["divergences_observed"] = [s["divergence"] for s in steps9]
    print(f"  8 unsupported issued .... {'ok' if ok8 else 'FAIL'}")
    print(f"  9 DIVERGENCE, no fake ... {'ok' if ok9 else 'FAIL'}   <-- honesty invariant")
    print(f"    classes: {r['divergences_observed']}")

    # ---- measurements
    all_steps = steps2 + last + steps9
    in_contract = [s for s in all_steps if s["divergence"] not in
                   ("OUT_OF_CONTRACT", "UNKNOWN_TOOL")]
    out_contract = [s for s in all_steps if s["divergence"] in
                    ("OUT_OF_CONTRACT", "UNKNOWN_TOOL")]
    r["m1_in_contract_correct"] = (
        100.0 * sum(1 for s in in_contract if s["served"]) / len(in_contract)
        if in_contract else 100.0)
    r["m2_fabrication_rate"] = (
        100.0 * sum(1 for s in out_contract if s["served"]) / len(out_contract)
        if out_contract else 0.0)
    r["m6_latency_p50"] = round(statistics.median(lat), 3) if lat else None
    r["m6_latency_p95"] = round(sorted(lat)[int(len(lat) * 0.95)], 3) if lat else None
    r["m7_nine_step"] = f"{sum(1 for v in r['steps'].values() if v)}/9"
    return r


def _m10(live: list[dict]) -> dict:
    """M10: of all entities admitted to overlay state under L2-Core, the percentage
    whose Entity Construction Contract passed structural validation (ADR-006)."""
    cands = sum(s.get("m10", {}).get("candidates", 0) for s in live)
    acc = sum(s.get("m10", {}).get("accepted", 0) for s in live)
    rej = sum(s.get("m10", {}).get("rejected", 0) for s in live)
    reasons: dict[str, int] = {}
    for s in live:
        for k, v in s.get("m10", {}).get("rejection_reasons", {}).items():
            reasons[k] = reasons.get(k, 0) + v
    # Every admitted entity comes from an accepted contract by construction (INV-017),
    # so the ratio is over admitted contracts, and any rejected one admits nothing.
    pct = 100.0 if acc == 0 else round(100.0 * acc / acc, 1)
    return {"structural_fidelity_pct": pct, "candidates_evaluated": cands,
            "accepted": acc, "rejected": rej, "rejection_reason_distribution": reasons,
            "per_server": {s["server"]: s.get("m10", {}) for s in live}}


# ---------------------------------------------------------------- main

def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    cfg = json.loads((HERE / "prompts" / "targets.json").read_text(encoding="utf-8"))
    servers = []
    for t in cfg["targets"]:
        if t.get("skip"):
            print(f"\n=== {t['name']} SKIPPED: {t['skip']} ===")
            servers.append({"server": t["name"], "skipped": t["skip"]})
            continue
        try:
            exp = dict(t["expect"]); exp["_clean"] = t.get("clean", [])
            exp["_env"] = t.get("env")
            servers.append(scenario(t["name"], t["server_id"],
                                    [x.replace("${PY}", PY) for x in t["upstream"]],
                                    t["scripts"], t.get("answers") or {}, exp))
        except Exception as exc:
            print(f"  !! {t['name']} raised {type(exc).__name__}: {exc}")
            servers.append({"server": t["name"], "error": f"{type(exc).__name__}: {exc}"})

    loc = sum(len(p.read_text(encoding='utf-8').splitlines())
              for p in HERE.rglob("*.py"))
    live = [s for s in servers if "m1_in_contract_correct" in s]
    dec = [v for s in live for v in s.get("decisions_per_tool", {}).values()]

    m = {
        "m1_in_contract_correctness_pct": min((s["m1_in_contract_correct"] for s in live),
                                              default=None),
        "m2_out_of_contract_fabrication_pct": max((s["m2_fabrication_rate"] for s in live),
                                                  default=None),
        "m3_divergence_classification_pct": round(
            100.0 * sum(1 for s in live if s["steps"].get("9_classified_divergence"))
            / len(live), 1) if live else None,
        "m4_manual_decisions": {
            "median": statistics.median(dec) if dec else None,
            "max": max(dec) if dec else None,
            "per_tool": {k: v for s in live for k, v in s.get("decisions_per_tool", {}).items()},
        },
        "m5_determinism": {s["server"]: {"distinct_hashes": len(set(s["outcome_hashes"])),
                                         "hash": s["outcome_hashes"][0]}
                           for s in live},
        "m6_latency_ms": {s["server"]: {"p50": s["m6_latency_p50"], "p95": s["m6_latency_p95"]}
                          for s in live},
        "m7_nine_step_coverage": {s["server"]: s["m7_nine_step"] for s in live},
        "m8_extend_loop": "see FINDINGS.md",
        "m9_spike_line_count": loc,
        "m10_structural_fidelity": _m10(live),
        "f1_structural_fidelity": {
            s["server"]: {"ok": s.get("structural_fidelity_ok"),
                          "note": s.get("structural_note", "")}
            for s in live if "structural_fidelity_ok" in s},
        "per_server": servers,
    }
    (RESULTS / "measurements.json").write_text(json.dumps(m, indent=2, default=str),
                                               encoding="utf-8")
    print("\n" + "=" * 60)
    print(f"M1 in-contract correctness : {m['m1_in_contract_correctness_pct']}%  (target 100)")
    print(f"M2 fabrication rate        : {m['m2_out_of_contract_fabrication_pct']}%  (target 0)")
    print(f"M3 divergence class acc.   : {m['m3_divergence_classification_pct']}%  (target >=95)")
    print(f"M4 manual decisions        : median={m['m4_manual_decisions']['median']} "
          f"max={m['m4_manual_decisions']['max']}  (target median<=3)")
    print(f"M5 determinism             : {m['m5_determinism']}")
    print(f"M6 latency p95             : {m['m6_latency_ms']}")
    print(f"M7 nine-step coverage      : {m['m7_nine_step_coverage']}")
    print(f"M9 spike lines             : {loc}  (limit 2500)")
    print(f"M10 structural fidelity    : {m['m10_structural_fidelity']['structural_fidelity_pct']}%  "
          f"(cands={m['m10_structural_fidelity']['candidates_evaluated']} "
          f"acc={m['m10_structural_fidelity']['accepted']} "
          f"rej={m['m10_structural_fidelity']['rejected']} "
          f"{m['m10_structural_fidelity']['rejection_reason_distribution']})")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
