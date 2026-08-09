"""Cross-OS determinism check (closes M5). Server C only: no Node dependency.

Fixed World + fixed seed + fixed tool-call sequence -> outcome hash.
Runs the replay engine in-process, so it measures WORLD determinism (NFR-010) without
requiring subprocess or npx on the second platform.

Usage: python crossos.py            -> writes results/m5_<platform>.json
"""
from __future__ import annotations

import hashlib
import json
import platform
import sys
from pathlib import Path

from replay import ReplayEngine
from world import load_world

HERE = Path(__file__).parent

# The fixed sequence. Must not change between platforms.
SEQUENCE = [
    ("fixture", "list_issues", {"project": "QA"}),
    ("fixture", "create_issue", {"project": "QA", "title": "Fresh unrecorded"}),
    ("fixture", "list_issues", {"project": "QA"}),
    ("fixture", "update_issue", {"id": "FX-001", "status": "closed"}),
    ("fixture", "get_issue", {"id": "FX-001"}),
    ("fixture", "delete_issue", {"id": "FX-001"}),
    ("fixture", "list_issues", {"project": "QA"}),
    ("fixture", "search_issues", {"query": "project=QA AND status=open"}),
    ("fixture", "list_issues", {"project": "QA", "assignee": "bob"}),
    ("fixture", "nonexistent_tool", {}),
]


def run_once(seed: int = 42) -> tuple[str, list[dict]]:
    world = load_world(HERE / "worlds" / "m0-fixture.yaml")
    engine = ReplayEngine(world, seed=seed)
    steps = []
    for server, tool, args in SEQUENCE:
        out = engine.handle(server, tool, args)
        steps.append({
            "tool": tool, "args": args, "served": out.served,
            "provenance": out.provenance, "response": out.response,
            "stale_paths": list(out.stale_paths),
            "synthesized_entity_ids": list(out.synthesized_entity_ids),
            "divergence": out.divergence.cls if out.divergence else None,
            "severity": out.divergence.severity if out.divergence else None,
        })
    blob = json.dumps(steps, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16], steps


def main() -> int:
    hashes = []
    steps = None
    for _ in range(10):                       # same-OS 10/10 as well
        h, steps = run_once()
        hashes.append(h)
    tag = platform.system().lower()
    out = {
        "platform": {
            "system": platform.system(), "release": platform.release(),
            "machine": platform.machine(), "python": sys.version.split()[0],
        },
        "world": "worlds/m0-fixture.yaml",
        "seed": 42,
        "sequence_len": len(SEQUENCE),
        "distinct_hashes": len(set(hashes)),
        "hash": hashes[0],
        "steps": steps,
    }
    path = HERE / "results" / f"m5_{tag}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"{platform.system()} {platform.release()} python {sys.version.split()[0]}")
    print(f"  distinct hashes over 10 runs : {len(set(hashes))}")
    print(f"  outcome hash                 : {hashes[0]}")
    print(f"  written                      : {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
