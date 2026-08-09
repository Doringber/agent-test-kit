"""M0 architectural claim tests. Single file, no framework ceremony.

Verifies the claims the spike exists to prove. Run: python test_spike.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from models import (Capability, Entity, EntityConstructionContract,
                    Interaction, World)
from replay import ReplayEngine
from world import canonicalize, key_of

FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------- fixture world

ISSUE_ECC = EntityConstructionContract(
    entity_template=("id", "project", "title", "status", "created_at"),
    required_fields=("created_at", "id", "project", "status", "title"),
    field_bindings={"project": "project", "title": "title"},
    generated_fields={"id": "mint", "created_at": "clock"},
    constant_defaults={"status": "open"},
    cardinality="one")


def build_world() -> World:
    caps = {
        ("s", "create_issue"): Capability(
            "write", "confirmed", "l2_core", entity_type="issue",
            id_response_path="$.id", body_request_path="$.", mutation="create",
            ecc=ISSUE_ECC),
        ("s", "get_issue"): Capability(
            "read", "confirmed", "l2_core", entity_type="issue", id_request_path="$.id"),
        ("s", "update_issue"): Capability(
            "write", "confirmed", "l2_core", entity_type="issue",
            id_request_path="$.id", body_request_path="$.", mutation="update"),
        ("s", "delete_issue"): Capability(
            "write", "confirmed", "l2_core", entity_type="issue",
            id_request_path="$.id", mutation="delete"),
        ("s", "list_issues"): Capability(
            "read", "confirmed", "l2_core", entity_type="issue",
            collection_response_path="$.issues",
            predicate={"kind": "field_equals", "request_path": "$.project",
                       "entity_path": "$.project"},
            pagination_paths=("$.limit", "$.offset")),
        ("s", "search_issues"): Capability("read", "confirmed", "l1"),
    }
    base = {"id": "FX-001", "project": "QA", "title": "Existing",
        "status": "open", "created_at": "2026-01-01T00:00:00Z"}
    return World(
        world_id="t", seed_epoch="2026-01-01T00:00:00Z", volatile_paths=("$.requestId",),
        tools=caps,
        interactions=[
            Interaction(1, "s", "list_issues", {"project": "QA"},
                        {"issues": [dict(base)], "total": 1}, "success"),
            Interaction(2, "s", "search_issues", {"query": "project=QA"},
                        {"issues": [dict(base)]}, "success"),
            # A recorded PAGE, so PAGINATION_OVERLAY_SKIPPED has something to serve.
            Interaction(3, "s", "list_issues", {"limit": 1, "project": "QA"},
                        {"issues": [dict(base)], "total": 1}, "success"),
        ],
        entities={"issue": [Entity("issue", "FX-001", dict(base))]},
        id_minting={"issue": "IS-M{counter:03d}"}, tools_list_hash="sha256:test")


def eng() -> ReplayEngine:
    return ReplayEngine(build_world(), seed=42)


# ---------------------------------------------------------------- tests

def test_canonicalization() -> None:
    print("\n[canonicalization]")
    a = canonicalize({"b": 1, "a": {"y": 2.0, "x": 1}}, ())
    b = canonicalize({"a": {"x": 1, "y": 2}, "b": 1.0}, ())
    check("key order and numeric form produce one canonical value", key_of(a) == key_of(b))
    nfc = canonicalize({"t": "é"}, ())          # e + combining acute
    pre = canonicalize({"t": "é"}, ())           # precomposed
    check("unicode normalized to NFC", key_of(nfc) == key_of(pre))
    check("volatile paths dropped",
          key_of(canonicalize({"a": 1, "requestId": "x"}, ("$.requestId",)))
          == key_of(canonicalize({"a": 1}, ())))
    check("canonicalization is idempotent", key_of(canonicalize(a, ())) == key_of(a))
    check("different arguments stay different",
          key_of(canonicalize({"a": 1}, ())) != key_of(canonicalize({"a": 2}, ())))


def test_exact_matching() -> None:
    print("\n[exact matching]")
    e = eng()
    ok = e.handle("s", "list_issues", {"project": "QA"})
    check("recorded call is served from the recording",
          ok.served and ok.provenance == "recorded")
    e2 = eng()
    miss = e2.handle("s", "search_issues", {"query": "project=ZZ"})
    check("near-miss on an l1 tool is NOT served", not miss.served)
    check("near-miss is classified, not silently dropped", miss.divergence is not None)


def test_no_fabrication() -> None:
    print("\n[no fabrication - INV-004]")
    e = eng()
    r1 = e.handle("s", "nope_tool", {})
    check("unknown tool -> UNKNOWN_TOOL, no response",
          (not r1.served) and r1.response is None and r1.divergence.cls == "UNKNOWN_TOOL")
    check("unknown tool severity is fatal", r1.divergence.severity == "fatal")
    r2 = e.handle("s", "list_issues", {"project": "QA", "assignee": "bob"})
    check("unrecognized parameter -> OUT_OF_CONTRACT, no response",
          (not r2.served) and r2.response is None and r2.divergence.cls == "OUT_OF_CONTRACT")
    r3 = e.handle("s", "search_issues", {"query": "never recorded"})
    check("l1 tool outside its recordings -> refused, no response",
          (not r3.served) and r3.response is None)
    refused = [x for x in (r1, r2, r3)]
    check("every refusal carries response=None",
          all(x.response is None for x in refused))


def test_overlay() -> None:
    print("\n[overlay - L2-Core]")
    e = eng()
    c = e.handle("s", "create_issue", {"project": "QA", "title": "New"})
    check("create is served", c.served and c.provenance == "synthesized")
    minted = c.response["id"]
    check("minted id is in a range disjoint from recorded ids",
          minted.startswith("IS-M") and minted != "FX-001", minted)

    lst = e.handle("s", "list_issues", {"project": "QA"})
    ids = [r["id"] for r in lst.response["issues"]]
    check("create -> list observes the created entity", minted in ids, str(ids))
    check("list also retains the recorded entity", "FX-001" in ids)

    u = e.handle("s", "update_issue", {"id": "FX-001", "status": "closed"})
    check("update is served", u.served)
    g = e.handle("s", "get_issue", {"id": "FX-001"})
    check("update -> get observes the update", g.response.get("status") == "closed")

    e.handle("s", "delete_issue", {"id": "FX-001"})
    g2 = e.handle("s", "get_issue", {"id": "FX-001"})
    check("delete -> get no longer serves the entity", not g2.served)
    lst2 = e.handle("s", "list_issues", {"project": "QA"})
    ids2 = [r["id"] for r in lst2.response["issues"]]
    check("delete -> list no longer exposes the entity", "FX-001" not in ids2, str(ids2))

    e3 = eng()
    e3.handle("s", "create_issue", {"project": "OTHER", "title": "X"})
    l3 = e3.handle("s", "list_issues", {"project": "QA"})
    check("predicate filters out non-matching created entities",
          all(r["id"] != "IS-M900" for r in l3.response["issues"]))


def test_reset_isolation() -> None:
    print("\n[reset isolation - INV-006]")
    e = eng()
    e.handle("s", "create_issue", {"project": "QA", "title": "A"})
    before = [r["id"] for r in e.handle("s", "list_issues", {"project": "QA"}).response["issues"]]
    e.reset()
    after = [r["id"] for r in e.handle("s", "list_issues", {"project": "QA"}).response["issues"]]
    check("execution A state is absent from execution B",
          "IS-M900" in before and "IS-M900" not in after, f"{before} -> {after}")
    check("minting counter resets", e.handle(
        "s", "create_issue", {"project": "QA", "title": "B"}).response["id"] == "IS-M900")


def test_determinism() -> None:
    print("\n[determinism - INV-007]")
    seq = [("create_issue", {"project": "QA", "title": "D"}),
           ("list_issues", {"project": "QA"}),
           ("update_issue", {"id": "FX-001", "status": "x"}),
           ("get_issue", {"id": "FX-001"})]
    runs = []
    for _ in range(10):
        e = eng()
        runs.append(key_of([e.handle("s", t, a).__dict__ for t, a in seq]))
    check("10 executions produce one identical outcome", len(set(runs)) == 1,
          f"{len(set(runs))} distinct")
    e1, e2 = eng(), eng()
    r1 = key_of([e1.handle("s", t, a).__dict__ for t, a in seq])
    e2.reset()
    r2 = key_of([e2.handle("s", t, a).__dict__ for t, a in seq])
    check("a reset engine reproduces a fresh engine", r1 == r2)


def test_divergence_classes() -> None:
    print("\n[divergence classification - INV-005]")
    cases = [
        ("unknown tool", ("s", "ghost", {}), "UNKNOWN_TOOL"),
        ("unrecognized param", ("s", "list_issues", {"project": "QA", "zz": 1}),
         "OUT_OF_CONTRACT"),
        ("l1 outside recordings", ("s", "search_issues", {"query": "zz"}),
         "OUT_OF_CONTRACT"),
        ("get missing entity", ("s", "get_issue", {"id": "NOPE"}),
         "NO_RECORDED_INTERACTION"),
    ]
    for label, (srv, tool, args), expected in cases:
        out = eng().handle(srv, tool, args)
        got = out.divergence.cls if out.divergence else None
        check(f"{label} -> {expected}", got == expected, str(got))

    e = eng()
    e.handle("s", "create_issue", {"project": "QA", "title": "P"})
    pg = e.handle("s", "list_issues", {"project": "QA", "limit": 1})
    check("paginated read with dirty overlay -> PAGINATION_OVERLAY_SKIPPED",
          pg.divergence is not None
          and pg.divergence.cls == "PAGINATION_OVERLAY_SKIPPED",
          str(pg.divergence.cls if pg.divergence else None))
    check("skipped page serves the RECORDED page, overlay entity absent",
          pg.served and [r["id"] for r in pg.response["issues"]] == ["FX-001"])
    e2 = eng()
    e2.handle("s", "create_issue", {"project": "QA", "title": "P"})
    pg2 = e2.handle("s", "list_issues", {"project": "QA", "limit": 5})
    check("paginated read with NO recorded page -> refused, still no fabrication",
          (not pg2.served) and pg2.response is None
          and pg2.divergence.cls == "NO_RECORDED_INTERACTION",
          str(pg2.divergence.cls if pg2.divergence else None))


def test_stale_derived_fields() -> None:
    print("\n[stale derived fields]")
    e = eng()
    clean = e.handle("s", "list_issues", {"project": "QA"})
    check("clean overlay produces no stale paths", clean.stale_paths == ())
    e.handle("s", "create_issue", {"project": "QA", "title": "S"})
    dirty = e.handle("s", "list_issues", {"project": "QA"})
    check("$.total is STALE after an overlay create",
          "$.total" in dirty.stale_paths, str(dirty.stale_paths))
    check("stale response still carries the merged collection",
          len(dirty.response["issues"]) == 2)
    check("stale total retains the RECORDED value, not a recomputed one",
          dirty.response["total"] == 1, str(dirty.response.get("total")))
    check("staleness raises STALE_DERIVED_FIELD",
          dirty.divergence is not None and dirty.divergence.cls == "STALE_DERIVED_FIELD")


def test_capability_state_gating() -> None:
    print("\n[capability state gating - INV-016]")
    w = build_world()
    w.tools[("s", "create_issue")] = Capability(
        "write", "proposed", "l1", entity_type="issue")     # PROPOSED -> l1 only
    e = ReplayEngine(w, seed=42)
    out = e.handle("s", "create_issue", {"project": "QA", "title": "N"})
    check("a PROPOSED capability does not get L2-Core treatment", not out.served)


# ================================================================ M0.1 (ADR-006)

def _compile(session: str, world_id: str, answers=None):
    from compile import compile_world
    return compile_world(Path("results") / session, world_id=world_id,
                         answers=answers or {})


def _would_be_unknown(outcome, assertion_class: str) -> bool:
    """Smallest possible simulation of ADR-005 + ADR-006 s6.

    NOT an assertion engine. Encodes only the degradation rule under test.
    """
    if assertion_class == "call_shape":
        return False
    return bool(outcome.synthesized_entity_ids) or bool(outcome.stale_paths) \
        or outcome.provenance == "synthesized"


def t1_server_c_still_valid() -> None:
    print("\n[T1] Server C remains valid under ADR-006")
    w, _ = _compile("session_fixture.json", "t1", {"fixture/delete_issue":
                                                   {"id_request_path": "$.id"}})
    cap = w.tools[("fixture", "create_issue")]
    check("T1 create_issue passes structural validation",
          cap.validation is not None and cap.validation.ok,
          str(cap.validation.failed if cap.validation else None))
    check("T1 create_issue remains l2_core", cap.fidelity == "l2_core", cap.fidelity)
    check("T1 contract is cardinality=one", cap.ecc.cardinality == "one")
    check("T1 server-assigned 'status' resolved via constant_defaults",
          "status" in cap.ecc.constant_defaults, str(cap.ecc.constant_defaults))
    e = ReplayEngine(w, seed=42)
    c = e.handle("fixture", "create_issue", {"project": "QA", "title": "T1"})
    check("T1 create is served", c.served)
    tmpl = set(cap.ecc.entity_template)
    check("T1 constructed entity matches the observed template exactly",
          set(c.response) == tmpl, f"{sorted(set(c.response))} vs {sorted(tmpl)}")
    lst = e.handle("fixture", "list_issues", {"project": "QA"})
    ids = [r["id"] for r in lst.response["issues"]]
    check("T1 read-after-write still works", c.response["id"] in ids, str(ids))
    check("T1 no structural fabrication in the merged read",
          all(set(r) == tmpl for r in lst.response["issues"]),
          str([sorted(set(r)) for r in lst.response["issues"]]))


def t2_server_a_batch_rejected() -> None:
    print("\n[T2] Server A batch create rejected by V3")
    w, _ = _compile("session_memory.json", "t2")
    cap = w.tools[("memory", "create_entities")]
    check("T2 create_entities is NOT l2_core", cap.fidelity == "l1", cap.fidelity)
    check("T2 capability is not CONFIRMED-with-L2", cap.state != "confirmed"
          or cap.fidelity == "l1", cap.state)
    check("T2 a rejection reason is recorded",
          cap.validation is not None and bool(cap.validation.failed),
          f"failed={list(cap.validation.failed) if cap.validation else None}")
    print(f"       honest-config rejection: {list(cap.validation.failed)} "
          f"-> {cap.validation.reasons.get(cap.validation.first_failure(), '')[:90]}")

    # In the honest configuration the tool is rejected earlier, for lack of any observed
    # entity of the inferred type. To prove V3 itself detects batch cardinality, give it
    # the correct entity type and check which validation then fires.
    typed = {"memory/create_entities": {"entity_type": "node", "id_response_path": "$.name"},
             "memory/read_graph": {"entity_type": "node",
                                   "collection_response_path": "$.entities",
                                   "predicate": {"kind": "always"}}}
    w2, _ = _compile("session_memory.json", "t2-typed", typed)
    cap2 = w2.tools[("memory", "create_entities")]
    check("T2 with the entity type identified, V3 fires on batch cardinality",
          cap2.validation is not None and "V3" in cap2.validation.failed,
          f"failed={list(cap2.validation.failed) if cap2.validation else None}")
    check("T2 it still does not reach l2_core", cap2.fidelity == "l1", cap2.fidelity)
    print(f"       V3 reason: {cap2.validation.reasons.get('V3','')[:110]}")
    # No vendor identifier may appear in the engine. Comments/docstrings are excluded;
    # the generic English word "entities" is not a vendor identifier.
    vendor = ("create_entities", "read_graph", "search_nodes", "open_nodes",
              "server-memory", "sqlite", "read_query", "write_query", "npx")
    leaks = []
    for mod in ("replay.py", "world.py", "coordinator.py", "proxy.py", "models.py"):
        src = Path(mod).read_text(encoding="utf-8")
        code = "\n".join(ln.split("#")[0] for ln in src.splitlines())
        leaks += [f"{mod}:{v}" for v in vendor if v in code]
    check("T2 no vendor identifier appears anywhere in the engine", not leaks, str(leaks))


def t3_f1_fabrication_impossible() -> None:
    print("\n[T3] Original F-1 fabrication is impossible  <-- decisive")
    forced = {"memory/create_entities": {"operation": "write", "entity_type": "node",
                                         "mutation": "create", "id_response_path": "$.name",
                                         "body_request_path": "$."},
              "memory/read_graph": {"operation": "read", "entity_type": "node",
                                    "collection_response_path": "$.entities",
                                    "predicate": {"kind": "always"}}}
    w, _ = _compile("session_memory.json", "t3-forced", forced)
    cap = w.tools[("memory", "create_entities")]
    pinned = cap.fidelity == "l1"
    check("T3 a human answer cannot override failed validation", pinned,
          f"fidelity={cap.fidelity} failed={list(cap.validation.failed) if cap.validation else None}")

    e = ReplayEngine(w, seed=42)
    c = e.handle("memory", "create_entities",
                 {"entities": [{"name": "beta", "entityType": "svc",
                                "observations": ["two"]}]})
    check("T3 the create is refused, not fabricated",
          (not c.served) and c.response is None,
          f"served={c.served} div={c.divergence.cls if c.divergence else None}")
    check("T3 refusal is classified",
          c.divergence is not None
          and c.divergence.cls in ("OUT_OF_CONTRACT", "ENTITY_CONSTRUCTION_FAILED"),
          str(c.divergence.cls if c.divergence else None))

    g = e.handle("memory", "read_graph", {})
    rows = (g.response or {}).get("entities", []) if g.served else []
    envelope = [r for r in rows if isinstance(r, dict) and "entities" in r]
    check("T3 the request envelope NEVER appears in overlay state",
          envelope == [], str(envelope)[:120])
    check("T3 no overlay mutation occurred", not e.overlay.get("node"),
          str(list(e.overlay.get("node", {}))))


def t4_provenance_propagation() -> None:
    print("\n[T4] Provenance survives downstream reads")
    e = eng()
    c = e.handle("s", "create_issue", {"project": "QA", "title": "T4"})
    minted = c.response["id"]
    check("T4 create reports its synthesized entity",
          c.synthesized_entity_ids == (minted,), str(c.synthesized_entity_ids))
    lst = e.handle("s", "list_issues", {"project": "QA"})
    check("T4 merged read carries the synthesized id",
          minted in lst.synthesized_entity_ids, str(lst.synthesized_entity_ids))
    lst2 = e.handle("s", "list_issues", {"project": "QA"})
    check("T4 a SECOND downstream read still exposes it",
          minted in lst2.synthesized_entity_ids, str(lst2.synthesized_entity_ids))
    g = e.handle("s", "get_issue", {"id": minted})
    check("T4 get-by-id also reports synthesized provenance",
          g.synthesized_entity_ids == (minted,), str(g.synthesized_entity_ids))
    clean = eng().handle("s", "list_issues", {"project": "QA"})
    check("T4 a purely recorded read reports NO synthesized ids",
          clean.synthesized_entity_ids == (), str(clean.synthesized_entity_ids))


def t5_response_content_degradation() -> None:
    print("\n[T5] Response-content degradation (ADR-005 + ADR-006 s6)")
    e = eng()
    e.handle("s", "create_issue", {"project": "QA", "title": "T5"})
    dirty = e.handle("s", "list_issues", {"project": "QA"})
    check("T5 response-content assertion would be UNKNOWN",
          _would_be_unknown(dirty, "response_content"))
    check("T5 call-shape assertion is unaffected",
          not _would_be_unknown(dirty, "call_shape"))
    clean = eng().handle("s", "list_issues", {"project": "QA"})
    check("T5 a clean recorded response degrades nothing",
          not _would_be_unknown(clean, "response_content")
          and not _would_be_unknown(clean, "call_shape"))


def t1b_world_roundtrip() -> None:
    """The contract IS world data. A world loaded from disk must still be able to
    construct entities, or replay silently degrades wherever worlds are persisted.
    Found by crossos.py, which loads from disk rather than from memory."""
    print("\n[T1b] Entity Construction Contract survives world serialization")
    from world import load_world, save_world
    w, _ = _compile("session_fixture.json", "rt",
                    {"fixture/delete_issue": {"id_request_path": "$.id"}})
    mem = w.tools[("fixture", "create_issue")]
    save_world(w, Path("results") / "_rt.yaml")
    disk_world = load_world(Path("results") / "_rt.yaml")
    disk = disk_world.tools[("fixture", "create_issue")]
    check("T1b ecc survives the YAML round-trip", mem.ecc == disk.ecc)
    check("T1b validation record survives", disk.validation is not None and disk.validation.ok)
    e = ReplayEngine(disk_world, seed=42)
    c = e.handle("fixture", "create_issue", {"project": "QA", "title": "RT"})
    check("T1b a disk-loaded world can still construct entities", c.served,
          str(c.divergence.cls if c.divergence else None))


def t7_o1_update_provenance() -> None:
    """O-1, settled by the ADR-006 amendment. Provenance describes whether CURRENT STATE
    is fully grounded in recorded external state, and is MONOTONIC within a session."""
    print("\n[T7] O-1: provenance of a recorded entity modified in replay")
    e = eng()

    clean = e.handle("s", "get_issue", {"id": "FX-001"})
    check("T7 an unmodified recorded entity is NOT synthesized",
          clean.synthesized_entity_ids == (), str(clean.synthesized_entity_ids))
    lst0 = e.handle("s", "list_issues", {"project": "QA"})
    check("T7 a list of unmodified recorded entities is clean",
          lst0.synthesized_entity_ids == (), str(lst0.synthesized_entity_ids))

    e.handle("s", "update_issue", {"id": "FX-001", "status": "closed"})

    g = e.handle("s", "get_issue", {"id": "FX-001"})
    check("T7 after an unrecorded update, get reports it synthesized",
          g.synthesized_entity_ids == ("FX-001",), str(g.synthesized_entity_ids))
    check("T7 the update is actually visible", g.response.get("status") == "closed")
    lst = e.handle("s", "list_issues", {"project": "QA"})
    check("T7 a subsequent list reports it synthesized",
          "FX-001" in lst.synthesized_entity_ids, str(lst.synthesized_entity_ids))
    lst2 = e.handle("s", "list_issues", {"project": "QA"})
    check("T7 provenance is MONOTONIC: a later read does not clear it",
          "FX-001" in lst2.synthesized_entity_ids, str(lst2.synthesized_entity_ids))
    check("T7 the overlay entity itself carries SYNTHESIZED_ENTITY",
          e.overlay["issue"]["FX-001"].provenance == "SYNTHESIZED_ENTITY")

    # Identity is recorded; current state is not. Both facts must remain visible.
    check("T7 the entity id is still the RECORDED id, not a minted one",
          g.response["id"] == "FX-001", g.response["id"])

    e.reset()
    after = e.handle("s", "get_issue", {"id": "FX-001"})
    check("T7 reset restores RECORDED_ENTITY (monotonicity is per-session)",
          after.synthesized_entity_ids == (), str(after.synthesized_entity_ids))
    check("T7 reset also reverts the state itself",
          after.response.get("status") == "open", str(after.response.get("status")))


def t6_m0_regression() -> None:
    print("\n[T6] M0 regression (engine-level; full suite in experiment.py)")
    e = eng()
    ok = e.handle("s", "list_issues", {"project": "QA"})
    check("T6 exact replay still served from recording", ok.provenance == "recorded")
    bad = e.handle("s", "nope", {})
    check("T6 unknown tool still refused", (not bad.served) and bad.response is None)
    seq = [("create_issue", {"project": "QA", "title": "R"}),
           ("list_issues", {"project": "QA"})]
    runs = {key_of([eng().handle("s", t, a).__dict__ for t, a in seq]) for _ in range(10)}
    check("T6 determinism still 10/10", len(runs) == 1, f"{len(runs)} distinct")


def main() -> int:
    for fn in (test_canonicalization, test_exact_matching, test_no_fabrication,
               test_overlay, test_reset_isolation, test_determinism,
               test_divergence_classes, test_stale_derived_fields,
               test_capability_state_gating,
               t1_server_c_still_valid, t1b_world_roundtrip, t2_server_a_batch_rejected,
               t3_f1_fabrication_impossible, t4_provenance_propagation,
               t5_response_content_degradation, t7_o1_update_provenance,
               t6_m0_regression):
        fn()
    print("\n" + "=" * 56)
    print(f"FAILURES: {len(FAILS)}" + (f" -> {FAILS}" if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
