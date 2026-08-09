"""Session log -> World. Crude capability inference + decision counting (M4).

ADR-004: inference is an accelerator, never authority. This module is never imported
by replay.py. A capability only reaches state=confirmed when a human answers.

The three permitted questions, and no fourth (ADR-004):
  Q1 READ or WRITE?
  Q2 Which entity does it affect?
  Q3 Which field identifies that entity?
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from models import (Capability, CapabilityProposal, CompileReport, Entity,
                    EntityConstructionContract, Interaction, ValidationResult,
                    World)
from world import hash_tools_list, save_world

WRITE_VERBS = ("create", "update", "delete", "add", "remove", "set", "post", "put", "patch")
READ_VERBS = ("get", "list", "search", "find", "read", "query", "fetch", "show")
QUERY_HINTS = ("query", "jql", "sql", "filter_expr", "expression", "q")
PAGINATION_KEYS = ("limit", "offset", "cursor", "page", "per_page", "page_size")


# ===================================================================== ADR-006
# Entity Construction Contract derivation and structural validation (V1-V6).
# Authority is OBSERVED DATA. Human answers establish intent, never shape.

_TS = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")


def _is_entityish(value, template: set[str]) -> bool:
    return isinstance(value, dict) and bool(set(value) & template)


def _contains_entity_array(payload, template: set[str]) -> bool:
    """V3 signal: an array whose elements look like entities means batch cardinality."""
    if isinstance(payload, list):
        return any(_is_entityish(v, template) for v in payload)
    if isinstance(payload, dict):
        return any(_contains_entity_array(v, template) for v in payload.values())
    return False


def _observed_entities(interactions, tools, entity_type: str) -> list[dict]:
    """Every entity of this type we actually saw, from any tool."""
    out: list[dict] = []
    for i in interactions:
        cap = tools.get((i.server, i.tool))
        if not cap or cap.entity_type != entity_type or i.status != "success":
            continue
        if cap.collection_response_path:
            for row in (i.response.get(cap.collection_response_path[2:]) or []):
                if isinstance(row, dict):
                    out.append(row)
        elif isinstance(i.response, dict) and "id" in i.response:
            out.append(i.response)
    return out


def _create_pairs(interactions, server: str, tool: str) -> list[tuple[dict, dict]]:
    """(request, response-entity) pairs for one create tool. Ground truth for V5."""
    return [(i.request, i.response) for i in interactions
            if i.server == server and i.tool == tool and i.status == "success"
            and isinstance(i.response, dict)]


def build_ecc(entity_type: str, id_field: str, observed: list[dict],
              create_pairs: list[tuple[dict, dict]]) -> EntityConstructionContract:
    """Derive the contract from observation. No human input."""
    template: list[str] = []
    for e in observed:
        for k in e:
            if k not in template:
                template.append(k)
    required = tuple(sorted(k for k in template
                            if observed and all(k in e for e in observed)))

    # Bindings: an entity value that equals a request value, across ALL create pairs.
    bindings: dict[str, str] = {}
    if create_pairs:
        for key in template:
            candidates = None
            for req, ent in create_pairs:
                if key not in ent:
                    candidates = set()
                    break
                here = {rk for rk, rv in req.items() if rv == ent[key]}
                candidates = here if candidates is None else (candidates & here)
            if candidates:
                bindings[key] = sorted(candidates)[0]

    # Constants: identical across every create response, and not bound.
    constants: dict = {}
    for key in template:
        if key in bindings or not create_pairs:
            continue
        vals = [ent.get(key) for _, ent in create_pairs if key in ent]
        if vals and len(vals) == len(create_pairs) and all(v == vals[0] for v in vals):
            if not (isinstance(vals[0], str) and _TS.match(vals[0])):
                constants[key] = vals[0]

    generated: dict[str, str] = {}
    if id_field in template:
        generated[id_field] = "mint"
    for key in template:
        if key in bindings or key in constants or key in generated:
            continue
        vals = [e.get(key) for e in observed if key in e]
        if vals and all(isinstance(v, str) and _TS.match(v) for v in vals):
            generated[key] = "clock"

    cardinality = "one"
    tset = set(template)
    for req, ent in create_pairs:
        if _contains_entity_array(req, tset) or _contains_entity_array(ent, tset):
            cardinality = "many"
            break

    return EntityConstructionContract(
        entity_template=tuple(template), required_fields=required,
        field_bindings=bindings, generated_fields=generated,
        constant_defaults=constants, cardinality=cardinality)


def validate_ecc(ecc: EntityConstructionContract, id_field: str, observed: list[dict],
                 create_pairs: list[tuple[dict, dict]],
                 collection_rows: list[dict] | None) -> ValidationResult:
    """ADR-006 s3. V1-V6 against observed data. No answer may override a failure."""
    passed: list[str] = []
    failed: list[str] = []
    why: dict[str, str] = {}

    def judge(name: str, ok: bool, reason: str = "") -> None:
        (passed if ok else failed).append(name)
        if not ok:
            why[name] = reason

    judge("V1", bool(ecc.entity_template) and bool(observed),
          "no observed entity of this type; entity_template is empty")
    judge("V2", bool(observed) and all(
        isinstance(e.get(id_field), (str, int)) and e.get(id_field) is not None
        for e in observed),
        f"id field {id_field!r} does not resolve to a scalar on every observed entity")
    judge("V3", ecc.cardinality == "one",
          "batch cardinality: an entity-shaped array was observed in the create "
          "request or response. Batch writes are outside L2-Core (ADR-006 s2)")
    judge("V4", not ecc.unresolved(),
          f"unresolved required field(s) {list(ecc.unresolved())}")

    # V5 round-trip: construct from each recorded create request, compare to ground truth.
    v5_ok, v5_why = True, ""
    if not create_pairs:
        v5_ok, v5_why = False, "no recorded create interaction to round-trip against"
    for req, ent in create_pairs:
        built, fail = ecc.construct(req, mint=lambda: "<minted>", clock=lambda: "<clock>")
        if built is None:
            v5_ok, v5_why = False, f"construction failed: {fail}"
            break
        for key in ecc.required_fields:
            if key in ecc.generated_fields:
                if key not in built:                    # value cannot match; presence must
                    v5_ok, v5_why = False, f"generated field {key!r} absent from construction"
                    break
            elif built.get(key) != ent.get(key):
                v5_ok, v5_why = False, (
                    f"round-trip mismatch on {key!r}: constructed {built.get(key)!r} "
                    f"but observed {ent.get(key)!r}")
                break
        if not v5_ok:
            break
    judge("V5", v5_ok, v5_why)

    if collection_rows:
        row_keys = set()
        for r in collection_rows:
            row_keys |= set(r)
        extra = set(ecc.entity_template) - row_keys
        judge("V6", not extra,
              f"constructed key set adds {sorted(extra)} not present in collection rows")
    else:
        judge("V6", True)

    return ValidationResult(tuple(passed), tuple(failed), why)


# =============================================================================


def _verb(tool: str) -> str:
    return tool.split("_", 1)[0].lower()


def _noun(tool: str) -> str | None:
    parts = tool.split("_", 1)
    if len(parts) < 2:
        return None
    n = parts[1].lower()
    return n[:-1] if n.endswith("s") else n


def propose_capability(tool_schema: dict, observed: list[Interaction]) -> CapabilityProposal:
    """Crude inference. Emits a question wherever it is NOT confident."""
    tool = tool_schema.get("name", "")
    props = ((tool_schema.get("inputSchema") or {}).get("properties") or {})
    questions: list[str] = []
    auto: list[str] = []
    verb = _verb(tool)

    # ---- Q1: operation -------------------------------------------------
    if verb in WRITE_VERBS:
        operation = "write"
        auto.append("operation<-verb")
    elif verb in READ_VERBS:
        operation = "read"
        auto.append("operation<-verb")
    else:
        operation = "unknown"
        questions.append("Q1 operation: READ or WRITE?")

    # ---- query-language tools are pinned to L1 immediately --------------
    if any(h in props for h in QUERY_HINTS):
        return CapabilityProposal(
            Capability(operation=operation if operation != "unknown" else "read",
                       state="proposed", fidelity="l1"),
            questions=questions + ["Q2 entity: none (query language) -> pin to l1?"],
            auto_derived=auto + ["fidelity<-query-language-detected"])

    # ---- Q2: entity ----------------------------------------------------
    entity = _noun(tool)
    if entity:
        auto.append("entity<-tool-noun")
    else:
        questions.append("Q2 entity: which entity does this tool affect?")

    # ---- Q3: identifying field -----------------------------------------
    sample = next((i.response for i in observed if i.status == "success"), {}) or {}
    coll_path, coll_rows = None, []
    for k, v in sample.items():
        if isinstance(v, list):
            coll_path, coll_rows = f"$.{k}", v
            break
    row = coll_rows[0] if coll_rows and isinstance(coll_rows[0], dict) else sample

    if isinstance(row, dict) and "id" in row:
        id_field = "id"
        auto.append("id_field<-response.id")
    else:
        id_field = None
        questions.append("Q3 identity: which field identifies the entity?")

    # ---- everything below is DERIVED, never asked ----------------------
    pagination = tuple(f"$.{k}" for k in props if k in PAGINATION_KEYS)
    if pagination:
        auto.append("pagination<-schema")

    predicate, ignored, mutation = None, (), None
    id_request_path = f"$.{id_field}" if (id_field and id_field in props) else None
    id_response_path, body_request_path, collection_response_path = None, None, None

    if operation == "write":
        mutation = ("create" if verb in ("create", "add", "post") else
                    "delete" if verb in ("delete", "remove") else "update")
        if mutation == "create":
            id_response_path = f"$.{id_field}" if id_field else None
            body_request_path = "$."
            auto.append("body<-whole-request")
        else:
            id_request_path = id_request_path or "$.id"
            body_request_path = "$."
    else:
        if coll_path:
            collection_response_path = coll_path
            auto.append("collection<-response-list")
            clauses = []
            for pname in props:
                if pname in PAGINATION_KEYS:
                    continue
                if isinstance(row, dict) and pname in row:
                    clauses.append({"kind": "field_equals",
                                    "request_path": f"$.{pname}",
                                    "entity_path": f"$.{pname}"})
            if len(clauses) == 1:
                predicate = clauses[0]
            elif clauses:
                predicate = {"kind": "all_of", "clauses": clauses}
            if clauses:
                auto.append("predicate<-request/entity-field-overlap")
            ignored = tuple(f"$.{p}" for p in props
                            if p not in PAGINATION_KEYS
                            and not (isinstance(row, dict) and p in row))
        else:
            id_request_path = id_request_path or "$.id"
            auto.append("get-by-id<-scalar-response")

    fidelity = "l2_core" if (entity and id_field and operation in ("read", "write")) else "l1"
    cap = Capability(operation=operation, state="proposed", fidelity=fidelity,
                     entity_type=entity, id_request_path=id_request_path,
                     id_response_path=id_response_path,
                     body_request_path=body_request_path,
                     collection_response_path=collection_response_path,
                     predicate=predicate, ignored_request_paths=ignored,
                     pagination_paths=pagination, mutation=mutation)
    return CapabilityProposal(cap, questions=questions, auto_derived=auto)


# Answer keys map onto the three permitted questions (ADR-004). Anything not listed
# here is DERIVED and must never be counted as human burden.
_Q_OF_KEY = {
    "operation": "Q1", "fidelity": "Q1",
    "entity_type": "Q2",
    "id_request_path": "Q3", "id_response_path": "Q3",
}


def _confirm(prop: CapabilityProposal, answers: dict) -> tuple[Capability, int]:
    """Apply human answers. Returns (capability, manual_decision_count).

    Decisions are counted as distinct QUESTIONS (Q1/Q2/Q3), not as dict keys.
    """
    cap = prop.capability
    over = dict(answers or {})
    asked = {q.split()[0] for q in prop.questions}
    asked |= {_Q_OF_KEY[k] for k in over if k in _Q_OF_KEY}
    decisions = len(asked)
    if over:
        cap = Capability(
            operation=over.get("operation", cap.operation),
            state="confirmed", fidelity=over.get("fidelity", cap.fidelity),
            entity_type=over.get("entity_type", cap.entity_type),
            id_request_path=over.get("id_request_path", cap.id_request_path),
            id_response_path=over.get("id_response_path", cap.id_response_path),
            body_request_path=over.get("body_request_path", cap.body_request_path),
            collection_response_path=over.get("collection_response_path",
                                              cap.collection_response_path),
            predicate=over.get("predicate", cap.predicate),
            ignored_request_paths=tuple(over.get("ignored_request_paths",
                                                 cap.ignored_request_paths)),
            pagination_paths=tuple(over.get("pagination_paths", cap.pagination_paths)),
            mutation=over.get("mutation", cap.mutation),
            derived_paths=tuple(over.get("derived_paths", cap.derived_paths)))
    else:
        # Accepting a confident proposal is still an explicit human act.
        cap = Capability(**{**cap.__dict__, "state": "confirmed"})

    # Fidelity is DERIVED from the three answers, never asked for directly.
    # Identity may live on the request/response (get, create, update, delete) OR on the
    # rows of a returned collection (list). Both satisfy Q3.
    if "fidelity" not in over and prop.capability.fidelity != "l1":
        has_identity = bool(cap.id_request_path or cap.id_response_path
                            or cap.collection_response_path)
        derived = "l2_core" if (cap.entity_type and has_identity
                                and cap.operation in ("read", "write")) else "l1"
        cap = Capability(**{**cap.__dict__, "fidelity": derived})
    elif "fidelity" not in over and over:
        # Human answered Q3 for a tool inference had pinned to l1; re-derive.
        has_identity = bool(cap.id_request_path or cap.id_response_path
                            or cap.collection_response_path)
        if cap.entity_type and has_identity and cap.operation in ("read", "write"):
            cap = Capability(**{**cap.__dict__, "fidelity": "l2_core"})
    if cap.state != "confirmed":
        cap = Capability(**{**cap.__dict__, "fidelity": "l1"})   # INV-016
    return cap, decisions


def compile_world(session_log: Path, interactive: bool = False, *,
                  world_id: str = "m0", answers: dict | None = None,
                  seed_epoch: str = "2026-01-01T00:00:00Z",
                  out: Path | None = None) -> tuple[World, CompileReport]:
    doc = json.loads(Path(session_log).read_text(encoding="utf-8"))
    answers = answers or {}
    interactions = [Interaction(**i) for i in doc["interactions"]]
    tools_list = doc.get("tools_list") or {}

    tools: dict[tuple[str, str], Capability] = {}
    report = CompileReport()
    for server, schemas in tools_list.items():
        for schema in schemas:
            name = schema.get("name", "")
            observed = [i for i in interactions if i.server == server and i.tool == name]
            prop = propose_capability(schema, observed)
            cap, decisions = _confirm(prop, answers.get(f"{server}/{name}"))
            tools[(server, name)] = cap
            report.decisions_per_tool[f"{server}/{name}"] = decisions
            report.proposals[f"{server}/{name}"] = prop

    # ---- ADR-006 s3: structural validation gates fidelity -------------------
    # Every create tool provisionally at l2_core must earn it against observed data.
    for (server, name), cap in list(tools.items()):
        if cap.operation != "write" or cap.mutation != "create" or not cap.entity_type:
            continue
        id_field = (cap.id_response_path or cap.id_request_path or "$.id")[2:]
        observed = _observed_entities(interactions, tools, cap.entity_type)
        pairs = _create_pairs(interactions, server, name)
        coll_rows: list[dict] = []
        for (s2, t2), c2 in tools.items():
            if c2.entity_type == cap.entity_type and c2.collection_response_path:
                for i in interactions:
                    if i.server == s2 and i.tool == t2 and i.status == "success":
                        coll_rows += [r for r in
                                      (i.response.get(c2.collection_response_path[2:]) or [])
                                      if isinstance(r, dict)]
        ecc = build_ecc(cap.entity_type, id_field, observed, pairs)
        result = validate_ecc(ecc, id_field, observed, pairs, coll_rows or None)
        # A failed validation can never be overridden by a human answer.
        final_fidelity = cap.fidelity if result.ok else "l1"
        final_state = cap.state if result.ok else "proposed"
        tools[(server, name)] = Capability(**{**cap.__dict__, "ecc": ecc,
                                              "validation": result,
                                              "fidelity": final_fidelity,
                                              "state": final_state})

    # Initial entity set, extracted from recorded reads.
    entities: dict[str, list[Entity]] = {}
    for i in interactions:
        cap = tools.get((i.server, i.tool))
        if not cap or cap.fidelity != "l2_core" or not cap.entity_type:
            continue
        rows = []
        if cap.collection_response_path:
            rows = i.response.get(cap.collection_response_path[2:]) or []
        elif isinstance(i.response, dict) and "id" in i.response:
            rows = [i.response]
        for r in rows:
            if not isinstance(r, dict) or "id" not in r:
                continue
            bucket = entities.setdefault(cap.entity_type, [])
            if not any(e.entity_id == r["id"] for e in bucket):
                bucket.append(Entity(cap.entity_type, r["id"], dict(r)))

    minting = {et: f"{et[:2].upper()}-M{{counter:03d}}" for et in entities} or \
              {c.entity_type: f"{c.entity_type[:2].upper()}-M{{counter:03d}}"
               for c in tools.values() if c.entity_type}

    world = World(world_id=world_id, seed_epoch=seed_epoch,
                  volatile_paths=("$.requestId",), tools=tools,
                  interactions=interactions, entities=entities,
                  id_minting=minting, tools_list_hash=hash_tools_list(tools_list),
                  tools_list=tools_list)
    if out:
        save_world(world, out)
    return world, report
