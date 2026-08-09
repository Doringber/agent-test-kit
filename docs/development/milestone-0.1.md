# Milestone 0.1: Structural Fidelity Verification

> **This is not Milestone 1.** It is a bounded verification that [ADR-006](../architecture/adr/ADR-006-entity-construction-and-structural-fidelity.md) closes finding F-1, plus closure of the M5 cross-OS gap.
>
> **Reuse the existing spike.** Do not start `src/agenttest/`. Do not generalize the spike.

**Estimated size:** 2 to 3 days. Expect roughly 150 to 250 net lines added to `spike/`.
**Authority:** ADR-006. No architecture decisions are open.

---

## Scope

Modify only these spike modules:

| File | Change |
|---|---|
| `compile.py` | Build the Entity Construction Contract; run validations V1-V6; set `l2_core` only on pass; record `validation` on failure |
| `replay.py` | Construct entities via the ECC; refuse with `ENTITY_CONSTRUCTION_FAILED`; tag entity provenance; propagate `synthesized_entity_ids` |
| `models.py` | Add `EntityConstructionContract`, `Entity.provenance`, `CallOutcome.synthesized_entity_ids`, the new divergence class |
| `test_spike.py` | Add the six checks below |
| `experiment.py` | Report structural fidelity as a first-class measurement, not a side note |

**Out of scope:** batch cardinality (excluded by ADR-006 §2), field-level provenance, world patches, assertions engine, HTTP transport, anything in `src/`.

---

## Required tests

All six must pass. They map one-to-one onto the ADR-006 decisions.

| # | Test | Expected | Verifies |
|---|---|---|---|
| **T1** | Server C `create_issue` under the new contract | Succeeds. Constructed entity includes `status` via `constant_defaults` (or the tool drops to `l1` if `status` is observed to vary) | ADR-006 §1, mild F-1 closed |
| **T2** | Server A `create_entities` (real, batch) | Classified **outside L2-Core** (`l1`) by validation **V3**, with the reason recorded | ADR-006 §2, §3 |
| **T3** | The F-1 envelope is **impossible** | Forcing `create_entities` to `l2_core` via answers must now fail compilation (V3 and V5) rather than produce `{entities:[...], id, created_at}` in the overlay | ADR-006 §3, INV-017 |
| **T4** | Provenance survives a read | Create an unrecorded entity, then list. The response carries non-empty `synthesized_entity_ids` containing the minted id | ADR-006 §5, FR-213 |
| **T5** | Degradation trigger fires | A response with non-empty `synthesized_entity_ids` marks response-content assertions UNKNOWN under production semantics. Spike asserts the **flag**, not an assertion engine | ADR-006 §6, FR-214 |
| **T6** | No regression | M1 = 100%, M2 = 0%, M5 = 10/10 per server, M4 median <= 3 | Gate preserved |

**T3 is the decisive test.** It converts the F-1 evidence into a permanent regression guard.

---

## Measurement changes

`results/measurements.json` gains one first-class measurement, since M0 proved M2 alone is insufficient:

```
M10  structural_fidelity
     definition : of all overlay entities exposed in a read, the percentage whose key
                  set matches the observed entity template for their type
     target     : 100%
     rationale  : M2 measures only out-of-contract calls and cannot see a structurally
                  wrong in-contract response. F-1 scored M2 = 0% while fabricating.
```

Also record, per tool: which of V1-V6 passed, and the reason for every `l1` assignment.

---

## Definition of done

1. T1 through T6 pass.
2. M10 = 100%.
3. M1 = 100%, M2 = 0% (no regression).
4. Cross-OS determinism closed (below).
5. `FINDINGS.md` gains an M0.1 section: what changed, what V1-V6 rejected that ADR-004 would have admitted, and any new observation.
6. No accepted invariant left in a challenged state.

---

## Cross-OS determinism (closes M5)

M5's ten-identical-hashes half passed on Windows. The cross-platform half was never executed.

**Do not redesign serialization unless the hashes actually differ.**

### Workflow

Fixed world, fixed seed, fixed tool-call sequence. Run on the current OS and on at least one Unix-like OS, then compare.

```bash
cd spike && python experiment.py
python -c "import json;m=json.load(open('results/measurements.json'));print(json.dumps(m['m5_determinism'],indent=2))"
```

Record the per-server `hash` values. On a second OS (Linux or macOS, Python 3.11+, `pip install pyyaml`, Node for Servers A and B):

```bash
cd spike && python experiment.py
python - <<'PY'
import json
cur = json.load(open("results/measurements.json"))["m5_determinism"]
ref = json.load(open("results/m5_reference.json"))     # hashes from the first OS
for srv, v in cur.items():
    same = ref.get(srv, {}).get("hash") == v["hash"]
    print(f"{srv}: {'MATCH' if same else 'DIFFER'}  {ref.get(srv,{}).get('hash')} vs {v['hash']}")
PY
```

Server C alone is sufficient to close M5 if Node is unavailable on the second OS; it is the deterministic fixture and has no external dependency. Record that Servers A and B were not cross-checked if so.

### If hashes differ

**Stop. Do not adjust serialization to make them match.** Capture the difference and escalate:

```bash
python - <<'PY'
import json
a = json.load(open("results/measurements.json"))["per_server"]
json.dump(a, open("results/m5_divergence_evidence.json","w"), indent=2, default=str)
PY
```

Then diff the per-step `payload`, `provenance`, `stale_paths`, and `divergence` fields between platforms and record the first differing step at byte level. Likely causes, in order of probability: dict ordering leaking into a serialized structure, float repr, path separator entering a payload, locale-dependent string normalization. Each is a defect against [NFR-013](../requirements/non-functional-requirements.md#determinism), not a reason to weaken the hash.

---

## Readiness rule for Milestone 1

**M1 may start only when all four hold:**

1. **The structural fabrication case is closed.** ADR-006 accepted, T3 demonstrates the F-1 envelope is impossible.
2. **M0.1 passes.** T1 to T6 green, M10 = 100%, no regression on M1/M2/M4/M5.
3. **Cross-OS determinism passes.** Outcome hashes identical on two operating systems, or a recorded and escalated divergence.
4. **No accepted invariant remains challenged.** INV-017 holds under test; INV-004, INV-007, INV-014, INV-016 remain unchallenged.

Record the outcome in [current-phase.md](current-phase.md). Until then, `src/agenttest/` stays empty.
