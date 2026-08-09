"""World load/save and canonicalization (ADR-003 canonicalization rules)."""
from __future__ import annotations

import hashlib
import json
import unicodedata
from pathlib import Path

import yaml

from models import (Capability, Entity, EntityConstructionContract, Interaction,
                    ValidationResult, World)

# ---------------------------------------------------------------- paths

def path_get(obj, path: str):
    """Minimal JSONPath-lite: '$.a.b'. Returns None if absent."""
    if not path.startswith("$."):
        return None
    cur = obj
    for part in path[2:].split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def path_drop(obj, path: str):
    if not path.startswith("$."):
        return obj
    parts = path[2:].split(".")
    if not isinstance(obj, dict):
        return obj
    out = dict(obj)
    cur = out
    for part in parts[:-1]:
        if not isinstance(cur.get(part), dict):
            return out
        cur[part] = dict(cur[part])
        cur = cur[part]
    cur.pop(parts[-1], None)
    return out


# ---------------------------------------------------------------- canonicalization

def _norm_scalar(v):
    # ADR-003 step 2: normalize numeric representation.
    if isinstance(v, bool):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    # ADR-003 step 5: NFC.
    if isinstance(v, str):
        return unicodedata.normalize("NFC", v)
    return v


def _sort_norm(obj):
    # ADR-003 step 1: sort object keys (recursively), and normalize scalars.
    if isinstance(obj, dict):
        return {k: _sort_norm(obj[k]) for k in sorted(obj)}
    if isinstance(obj, list):
        return [_sort_norm(v) for v in obj]
    return _norm_scalar(obj)


def canonicalize(args: dict, volatile_paths: tuple[str, ...] = (),
                 id_map: dict[str, str] | None = None) -> dict:
    """ADR-003 canonicalization. Deterministic and total.

    1 sort keys | 2 normalize numerics | 3 drop volatile | 4 unmap minted ids | 5 NFC
    """
    out = dict(args)
    for p in volatile_paths:                       # 3
        out = path_drop(out, p)
    out = _sort_norm(out)                          # 1, 2, 5

    if id_map:                                     # 4
        def unmap(o):
            if isinstance(o, dict):
                return {k: unmap(v) for k, v in o.items()}
            if isinstance(o, list):
                return [unmap(v) for v in o]
            return id_map.get(o, o) if isinstance(o, str) else o
        out = unmap(out)
    return out


def key_of(args: dict) -> str:
    return json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)


# ---------------------------------------------------------------- (de)serialization

def _cap_to_dict(c: Capability) -> dict:
    d = {"operation": c.operation, "state": c.state, "fidelity": c.fidelity}
    for name in ("entity_type", "id_request_path", "id_response_path",
                 "body_request_path", "collection_response_path", "predicate", "mutation"):
        v = getattr(c, name)
        if v is not None:
            d[name] = v
    for name in ("ignored_request_paths", "pagination_paths", "derived_paths"):
        v = getattr(c, name)
        if v:
            d[name] = list(v)
    if c.ecc is not None:                       # ADR-006: the contract IS world data
        d["ecc"] = {
            "entity_template": list(c.ecc.entity_template),
            "required_fields": list(c.ecc.required_fields),
            "field_bindings": dict(c.ecc.field_bindings),
            "generated_fields": dict(c.ecc.generated_fields),
            "constant_defaults": dict(c.ecc.constant_defaults),
            "cardinality": c.ecc.cardinality,
        }
    if c.validation is not None:
        d["validation"] = {"passed": list(c.validation.passed),
                           "failed": list(c.validation.failed),
                           "reasons": dict(c.validation.reasons)}
    return d


def _cap_from_dict(d: dict) -> Capability:
    ecc = None
    if d.get("ecc"):
        e = d["ecc"]
        ecc = EntityConstructionContract(
            entity_template=tuple(e.get("entity_template", ())),
            required_fields=tuple(e.get("required_fields", ())),
            field_bindings=dict(e.get("field_bindings") or {}),
            generated_fields=dict(e.get("generated_fields") or {}),
            constant_defaults=dict(e.get("constant_defaults") or {}),
            cardinality=e.get("cardinality", "one"))
    validation = None
    if d.get("validation"):
        v = d["validation"]
        validation = ValidationResult(tuple(v.get("passed", ())), tuple(v.get("failed", ())),
                                      dict(v.get("reasons") or {}))
    return Capability(
        ecc=ecc, validation=validation,
        operation=d["operation"], state=d["state"], fidelity=d["fidelity"],
        entity_type=d.get("entity_type"),
        id_request_path=d.get("id_request_path"),
        id_response_path=d.get("id_response_path"),
        body_request_path=d.get("body_request_path"),
        collection_response_path=d.get("collection_response_path"),
        predicate=d.get("predicate"),
        ignored_request_paths=tuple(d.get("ignored_request_paths", ())),
        pagination_paths=tuple(d.get("pagination_paths", ())),
        mutation=d.get("mutation"),
        derived_paths=tuple(d.get("derived_paths", ())),
    )


def save_world(w: World, path: Path) -> Path:
    doc = {
        "world_id": w.world_id,
        "seed_epoch": w.seed_epoch,
        "volatile_paths": list(w.volatile_paths),
        "tools_list_hash": w.tools_list_hash,
        "tools": {f"{s}/{t}": _cap_to_dict(c) for (s, t), c in sorted(w.tools.items())},
        "id_minting": dict(w.id_minting),
        "entities": {et: [{"entity_id": e.entity_id, "body": e.body} for e in rows]
                     for et, rows in sorted(w.entities.items())},
        "interactions": [
            {"seq": i.seq, "server": i.server, "tool": i.tool,
             "request": i.request, "response": i.response, "status": i.status}
            for i in w.interactions],
        "tools_list": w.tools_list,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def load_world(path: Path) -> World:
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    tools = {}
    for k, v in (doc.get("tools") or {}).items():
        server, tool = k.split("/", 1)
        tools[(server, tool)] = _cap_from_dict(v)
    entities = {et: [Entity(et, r["entity_id"], r["body"]) for r in rows]
                for et, rows in (doc.get("entities") or {}).items()}
    interactions = [Interaction(i["seq"], i["server"], i["tool"], i["request"],
                                i["response"], i["status"])
                    for i in (doc.get("interactions") or [])]
    return World(
        world_id=doc["world_id"], seed_epoch=doc["seed_epoch"],
        volatile_paths=tuple(doc.get("volatile_paths", ())),
        tools=tools, interactions=interactions, entities=entities,
        id_minting=dict(doc.get("id_minting") or {}),
        tools_list_hash=doc.get("tools_list_hash", ""),
        tools_list=doc.get("tools_list") or {},
    )


def hash_tools_list(tools_list: dict) -> str:
    blob = json.dumps(tools_list, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(blob.encode()).hexdigest()[:16]
