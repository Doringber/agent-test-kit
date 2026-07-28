#!/usr/bin/env python3
"""Optional: sample rows from superagent-guard HF dataset into local golden YAML.

Requires Hugging Face login (gated dataset):
  https://huggingface.co/datasets/superagent-ai/superagent-guard

  pip install datasets huggingface_hub
  huggingface-cli login
  python scripts/sync_superagent_guard_sample.py --limit 20 --output tests/data/superagent_guard_import.yaml
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def _extract_user_prompt(messages: list[dict[str, Any]]) -> str:
    for message in messages:
        if message.get("role") != "user":
            continue
        content = str(message.get("content", ""))
        match = re.search(r"Analyze:\s*(.+)", content, flags=re.DOTALL)
        return match.group(1).strip() if match else content.strip()
    return ""


def _extract_assistant_label(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    return {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Import superagent-guard sample cases")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("tests/data/superagent_guard_import.yaml"),
    )
    args = parser.parse_args()

    try:
        from datasets import load_dataset
    except ImportError as exc:
        msg = "Install datasets: pip install datasets huggingface_hub"
        raise SystemExit(msg) from exc

    dataset = load_dataset("superagent-ai/superagent-guard", split="train")
    cases: list[dict[str, Any]] = []
    for index, row in enumerate(dataset):
        if index >= args.limit:
            break
        messages = row.get("messages", [])
        if not isinstance(messages, list):
            continue
        user_prompt = _extract_user_prompt(messages)
        if not user_prompt:
            continue
        assistant = ""
        for message in messages:
            if message.get("role") == "assistant":
                assistant = str(message.get("content", ""))
        label = _extract_assistant_label(assistant)
        classification = str(label.get("classification", "block"))
        violation_types = label.get("violation_types") or []
        case_id = f"superagent_import_{index:04d}"
        cases.append(
            {
                "id": case_id,
                "category": "adversarial" if classification == "block" else "control",
                "source": "superagent-guard-import",
                "violation_types": violation_types,
                "expected_classification": classification,
                "golden_outcome": f"superagent-guard labels this as {classification}",
                "prompt": user_prompt,
                "expect_review_mutates": True,
                "forbidden_in_suggestion": [],
            }
        )

    payload = {
        "schema_version": "2.0",
        "sources": [
            {
                "name": "superagent-guard-import",
                "url": "https://huggingface.co/datasets/superagent-ai/superagent-guard",
                "note": f"Imported {len(cases)} rows via sync_superagent_guard_sample.py",
            }
        ],
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    import yaml

    args.output.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(f"Wrote {len(cases)} cases to {args.output}")


if __name__ == "__main__":
    main()
