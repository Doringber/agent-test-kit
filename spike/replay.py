"""Replay engine: contract check, matcher, overlay, merge, divergence.

Implements ADR-003 (matching order, divergence taxonomy) and ADR-004 (L2-Core).
The highest-risk module in the system. Deliberately explicit over clever.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta

from models import (SEVERITY_OF, CallOutcome, Divergence, Entity, ReplayStats,
                    World)
from world import canonicalize, key_of, path_get

TICK = timedelta(seconds=1)


class ReplayEngine:
    def __init__(self, world: World, seed: int) -> None:
        self.world = world
        self.seed = seed
        self._index: dict[tuple[str, str, str], dict] = {}
        for i in world.interactions:
            self._index[(i.server, i.tool, key_of(i.request))] = i.response
        self.reset()

    # ------------------------------------------------------------ lifecycle

    def reset(self) -> None:
        """INV-006: full per-execution isolation."""
        self.overlay: dict[str, dict[str, Entity]] = {
            et: {e.entity_id: Entity(et, e.entity_id, copy.deepcopy(e.body))
                 for e in rows}
            for et, rows in self.world.entities.items()
        }
        self._created: dict[str, list[str]] = {}   # entity_type -> insertion order
        self._dirty: set[str] = set()              # entity types mutated this session
        self._mint_counts: dict[str, int] = {}
        self._clock_ticks = 0
        self._seq = 0
        self._stats = ReplayStats()

    def stats(self) -> ReplayStats:
        return self._stats

    # ------------------------------------------------------------ helpers

    def _now(self) -> str:
        self._clock_ticks += 1
        base = datetime.fromisoformat(self.world.seed_epoch.replace("Z", "+00:00"))
        return (base + TICK * self._clock_ticks).isoformat().replace("+00:00", "Z")

    def _mint(self, entity_type: str) -> str:
        """Deterministic id minting in a range disjoint from recorded ids (ADR-004)."""
        n = self._mint_counts.get(entity_type, 0)
        self._mint_counts[entity_type] = n + 1
        template = self.world.id_minting.get(entity_type, entity_type.upper() + "-{counter:03d}")
        return template.format(counter=900 + n)

    def _diverge(self, cls: str, server: str, tool: str, detail: str) -> Divergence:
        d = Divergence(cls=cls, severity=SEVERITY_OF[cls], seq=self._seq,
                       server=server, tool=tool, detail=detail)
        self._stats.divergences.append(d)
        return d

    @staticmethod
    def _mark_synthesized(ent: Entity) -> None:
        """ADR-006 s5 amendment (O-1). Provenance is MONOTONIC within a session.

        Once an entity's current state contains data the external service never produced,
        it can never go back to RECORDED_ENTITY for the rest of this ReplaySession.
        Session boundaries reset it, because reset() rebuilds from world entities.
        """
        ent.provenance = "SYNTHESIZED_ENTITY"

    def _refuse(self, cls: str, server: str, tool: str, detail: str) -> CallOutcome:
        """INV-004: no response is ever produced alongside an error-class divergence."""
        self._stats.refused += 1
        return CallOutcome(served=False, response=None, provenance=None,
                           stale_paths=(), divergence=self._diverge(cls, server, tool, detail))

    # ------------------------------------------------------------ predicate (ADR-004 grammar)

    def _predicate_ok(self, pred: dict | None, args: dict, body: dict) -> bool:
        if pred is None:
            return True
        kind = pred.get("kind", "always")
        if kind == "always":
            return True
        if kind == "field_equals":
            return path_get(args, pred["request_path"]) == path_get(body, pred["entity_path"])
        if kind == "field_in":
            want = path_get(args, pred["request_path"])
            return isinstance(want, list) and path_get(body, pred["entity_path"]) in want
        if kind == "all_of":
            return all(self._predicate_ok(p, args, body) for p in pred["clauses"])
        raise ValueError(f"predicate kind outside the ADR-004 grammar: {kind}")

    # ------------------------------------------------------------ contract check (INV-003)

    def _contract_violation(self, cap, args: dict) -> str | None:
        """Classify every request parameter. Unrecognized => out of contract."""
        if cap.fidelity != "l2_core":
            return None                              # L1 contract handled by exact match
        recognized: set[str] = set()
        for p in cap.ignored_request_paths + cap.pagination_paths:
            if p.startswith("$."):
                recognized.add(p[2:].split(".")[0])
        for p in (cap.id_request_path, cap.body_request_path):
            if p and p.startswith("$."):
                recognized.add(p[2:].split(".")[0])
        pred = cap.predicate

        def collect(p):
            if not p:
                return
            if p.get("kind") == "all_of":
                for c in p["clauses"]:
                    collect(c)
            elif "request_path" in p:
                recognized.add(p["request_path"][2:].split(".")[0])
        collect(pred)
        # A create's body fields arrive inline when body_request_path is "$." (whole request).
        if cap.body_request_path == "$.":
            return None
        unknown = sorted(set(args) - recognized)
        if unknown:
            return f"unrecognized request parameter(s): {unknown}"
        return None

    # ------------------------------------------------------------ staleness

    def _stale_paths(self, cap, response: dict) -> tuple[str, ...]:
        """Declared derived_paths + the heuristic sibling rule (ARCH-002 R.7)."""
        stale: list[str] = []
        for p in cap.derived_paths:
            if path_get(response, p) is not None:
                stale.append(p)
        coll = cap.collection_response_path
        if coll and coll.startswith("$.") and "." not in coll[2:]:
            for k, v in response.items():
                if k == coll[2:]:
                    continue
                if isinstance(v, bool) or isinstance(v, (int, float)):
                    path = f"$.{k}"
                    if path not in stale:
                        stale.append(path)
        return tuple(stale)

    # ------------------------------------------------------------ main entry (ADR-003 order)

    def handle(self, server_id: str, tool: str, args: dict) -> CallOutcome:
        self._seq += 1
        self._stats.calls += 1
        cap = self.world.tools.get((server_id, tool))

        # 1. unknown tool -> FATAL
        if cap is None:
            return self._refuse("UNKNOWN_TOOL", server_id, tool,
                                f"tool {server_id}/{tool} is not present in world "
                                f"{self.world.world_id}")

        canon = canonicalize(args, self.world.volatile_paths)

        # 2. outside declared fidelity contract -> ERROR
        violation = self._contract_violation(cap, canon)
        if violation:
            return self._refuse("OUT_OF_CONTRACT", server_id, tool, violation)

        # 3. exact recorded match
        recorded = self._index.get((server_id, tool, key_of(canon)))

        if cap.fidelity == "l1":
            if recorded is not None:
                self._stats.served_recorded += 1
                if self._dirty:
                    self._diverge("UNMERGEABLE_OVERLAY", server_id, tool,
                                  "L1 tool served from recording while overlay is dirty")
                return CallOutcome(True, copy.deepcopy(recorded), "recorded", (), None)
            # An L1 tool's declared contract is "exactly the recorded interactions".
            return self._refuse(
                "OUT_OF_CONTRACT", server_id, tool,
                f"tool is fidelity=l1 (no declared entity semantics); "
                f"arguments {sorted(canon)} were never recorded")

        # ---- L2-Core ----
        # ADR-003 puts "exact recorded match" (3) BEFORE "L2-Core read merge" (5).
        # That ordering can only hold while the overlay is clean for this entity type;
        # once it is dirty, serving the recorded response would defeat read-after-write,
        # which is ADR-004's entire purpose. Interpretation recorded in FINDINGS (I-1).
        if (recorded is not None and cap.operation == "read"
                and cap.entity_type not in self._dirty):
            self._stats.served_recorded += 1
            return CallOutcome(True, copy.deepcopy(recorded), "recorded", (), None)

        if cap.operation == "write":
            return self._l2_write(cap, server_id, tool, canon, recorded)
        return self._l2_read(cap, server_id, tool, canon, recorded)

    # ------------------------------------------------------------ L2-Core write

    def _l2_write(self, cap, server_id, tool, canon, recorded) -> CallOutcome:
        et = cap.entity_type
        self._dirty.add(et)
        store = self.overlay.setdefault(et, {})
        mutation = cap.mutation or "create"

        id_field = (cap.id_response_path or cap.id_request_path or "$.id")[2:]

        if mutation == "create":
            # ADR-006 s1 precedence 1: an exact recorded create IS the entity.
            if recorded is not None:
                rid = path_get(recorded, cap.id_response_path or "$.id")
                eid = str(rid) if rid is not None else self._mint(et)
                body = dict(recorded) if isinstance(recorded, dict) else {}
                body.setdefault(id_field, eid)
                # Monotonicity (O-1): a recorded create never downgrades an entity that
                # already carries synthesized state in this session.
                prior = store.get(eid)
                prov = "SYNTHESIZED_ENTITY" if (
                    prior is not None and prior.provenance == "SYNTHESIZED_ENTITY"
                ) else "RECORDED_ENTITY"
                store[eid] = Entity(et, eid, body, provenance=prov)
                self._created.setdefault(et, []).append(eid)
                self._stats.served_recorded += 1
                return CallOutcome(True, copy.deepcopy(recorded), "recorded", (), None)

            # ADR-006 s1 precedence 2/3 + s4: construct through the VALIDATED contract.
            # No contract, or a failed construction, means NO overlay mutation at all.
            if cap.ecc is None:
                return self._refuse(
                    "ENTITY_CONSTRUCTION_FAILED", server_id, tool,
                    "no entity construction contract; nothing may enter the overlay")
            body, failure = cap.ecc.construct(canon, mint=lambda: self._mint(et),
                                              clock=self._now)
            if body is None:
                return self._refuse("ENTITY_CONSTRUCTION_FAILED", server_id, tool,
                                    f"entity construction failed: {failure}")
            eid = str(body.get(id_field))
            store[eid] = Entity(et, eid, body, provenance="SYNTHESIZED_ENTITY")
            self._created.setdefault(et, []).append(eid)
            self._stats.served_synthesized += 1
            d = self._diverge("SYNTHESIZED_WRITE_RESPONSE", server_id, tool,
                              f"no recorded response; constructed {et} {eid} through the "
                              f"validated entity construction contract")
            return CallOutcome(True, copy.deepcopy(body), "synthesized", (), d,
                               synthesized_entity_ids=(eid,))

        eid = path_get(canon, cap.id_request_path) if cap.id_request_path else None
        ent = store.get(eid)
        if ent is None or ent.deleted:
            return self._refuse("NO_RECORDED_INTERACTION", server_id, tool,
                                f"{mutation} target {et} id={eid!r} is absent from the overlay")

        if mutation == "update":
            patch = path_get(canon, cap.body_request_path) if cap.body_request_path else None
            if not isinstance(patch, dict):
                patch = {k: v for k, v in canon.items()
                         if k != (cap.id_request_path or "$.id")[2:]}
            ent.body.update({k: v for k, v in patch.items() if v is not None})
            # O-1, now settled by the ADR-006 amendment: an unrecorded update makes a
            # recorded entity's CURRENT STATE partly request-derived, so it becomes
            # SYNTHESIZED_ENTITY and stays that way for the rest of the session.
            self._mark_synthesized(ent)
            self._stats.served_synthesized += 1
            d = self._diverge("SYNTHESIZED_WRITE_RESPONSE", server_id, tool,
                              f"update response synthesized for {et} {eid}")
            return CallOutcome(True, copy.deepcopy(ent.body), "synthesized", (), d,
                               synthesized_entity_ids=(eid,))

        if mutation == "delete":
            ent.deleted = True
            self._mark_synthesized(ent)          # O-1 monotonicity, applied uniformly
            self._stats.served_synthesized += 1
            d = self._diverge("SYNTHESIZED_WRITE_RESPONSE", server_id, tool,
                              f"delete response synthesized for {et} {eid}")
            return CallOutcome(True, {"deleted": eid}, "synthesized", (), d)

        return self._refuse("OUT_OF_CONTRACT", server_id, tool,
                            f"mutation {mutation!r} is outside the six L2-Core operations")

    # ------------------------------------------------------------ L2-Core read

    def _l2_read(self, cap, server_id, tool, canon, recorded) -> CallOutcome:
        et = cap.entity_type
        store = self.overlay.get(et, {})

        # get-by-id
        if cap.collection_response_path is None:
            eid = path_get(canon, cap.id_request_path) if cap.id_request_path else None
            ent = store.get(eid)
            if ent is not None and not ent.deleted:
                self._stats.served_overlay += 1
                synth = (eid,) if ent.provenance == "SYNTHESIZED_ENTITY" else ()
                return CallOutcome(True, copy.deepcopy(ent.body), "overlay", (), None,
                                   synthesized_entity_ids=synth)
            if ent is not None and ent.deleted:
                return self._refuse("NO_RECORDED_INTERACTION", server_id, tool,
                                    f"{et} {eid} was deleted in this session; "
                                    f"no recorded not-found response is available")
            if recorded is not None:
                self._stats.served_recorded += 1
                return CallOutcome(True, copy.deepcopy(recorded), "recorded", (), None)
            return self._refuse("NO_RECORDED_INTERACTION", server_id, tool,
                                f"no recorded interaction and no overlay entity for "
                                f"{et} id={eid!r}")

        # list / filter
        paginating = any(path_get(canon, p) is not None for p in cap.pagination_paths)
        if paginating and self._dirty:
            if recorded is None:
                return self._refuse("NO_RECORDED_INTERACTION", server_id, tool,
                                    "paginated read with a dirty overlay and no recorded page")
            self._stats.served_recorded += 1
            d = self._diverge("PAGINATION_OVERLAY_SKIPPED", server_id, tool,
                              "overlay entities were NOT injected into a paginated read")
            return CallOutcome(True, copy.deepcopy(recorded), "recorded", (), d)

        base_rows, base_resp = [], None
        if recorded is not None:
            base_resp = copy.deepcopy(recorded)
            base_rows = list(path_get(base_resp, cap.collection_response_path) or [])

        overlay_rows, synth_ids = self._merge(cap, canon, base_rows)

        if recorded is None and not overlay_rows:
            return self._refuse("NO_RECORDED_INTERACTION", server_id, tool,
                                f"no recorded interaction for {sorted(canon)} and no "
                                f"overlay entity satisfies the declared predicate")

        resp = base_resp if base_resp is not None else {}
        key = cap.collection_response_path[2:]
        resp[key] = overlay_rows
        stale = self._stale_paths(cap, resp) if self._dirty else ()
        div = None
        if stale:
            div = self._diverge("STALE_DERIVED_FIELD", server_id, tool,
                                f"derived field(s) {list(stale)} cannot be recomputed "
                                f"after overlay mutation")
        self._stats.served_overlay += 1
        return CallOutcome(True, resp, "overlay", stale, div,
                           synthesized_entity_ids=synth_ids)

    def _merge(self, cap, canon, base_rows: list) -> tuple[list, tuple[str, ...]]:
        """ADR-004 merge: recorded -> drop deleted -> replace updated -> append created.

        ADR-006 s5: also reports the ids of every SYNTHESIZED_ENTITY that ends up in
        the result, so provenance survives the merge instead of being erased by it.
        """
        et = cap.entity_type
        store = self.overlay.get(et, {})
        out, seen, synth = [], set(), []
        id_key = (cap.id_request_path or "$.id")[2:]
        for row in base_rows:
            rid = row.get(id_key, row.get("id")) if isinstance(row, dict) else None
            ent = store.get(rid)
            if ent is not None and ent.deleted:
                continue
            if ent is not None:
                out.append(copy.deepcopy(ent.body))
                if ent.provenance == "SYNTHESIZED_ENTITY":
                    synth.append(ent.entity_id)
            else:
                out.append(row)
            if rid:
                seen.add(rid)
        for eid in self._created.get(et, []):
            ent = store.get(eid)
            if ent is None or ent.deleted or eid in seen:
                continue
            if self._predicate_ok(cap.predicate, canon, ent.body):
                out.append(copy.deepcopy(ent.body))
                seen.add(eid)
                if ent.provenance == "SYNTHESIZED_ENTITY":
                    synth.append(eid)
        return out, tuple(synth)
