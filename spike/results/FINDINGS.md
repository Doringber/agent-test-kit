# Milestone 0 Findings

**Date:** 2026-08-09
**Engineer:** Implementing Staff Engineer
**Status:** Complete. Recommendation at the end.

> Throwaway validation code. The measurements are the deliverable; the code is not.

---

## 1. What was actually exercised

Three target servers, two of which are **real third-party MCP servers I did not write** and
which contain no code of mine:

| | Server | Provenance |
|---|---|---|
| A | `@modelcontextprotocol/server-memory` 2026.7.4 | Real vendor package, entity/knowledge-graph shaped |
| B | `mcp-server-sqlite-npx` 0.8.0 | Real vendor package, SQL shaped |
| C | `spike/fixture_server/server.py` | Ours. Known ground truth |

No vendor-specific code exists anywhere in the engine. Only the scripted call sequences and
the capability answers differ per server, and both live in `prompts/targets.json`.

---

## 2. Nine-step results

| Step | Server C | Server A (real) | Server B (real) |
|---|---|---|---|
| 1 record | ok | ok | ok |
| 2 exact replay | ok | ok | ok |
| 3 unrecorded write | ok | n/a (L1) | n/a (L1) |
| 4 overlay mutation | ok | n/a (L1) | n/a (L1) |
| **5 read-after-write** | **ok** | n/a (L1) | n/a (L1) |
| 6 reset | ok | ok | ok |
| 7 determinism | ok | ok | ok |
| 8 unsupported issued | ok | ok | ok |
| **9 classified divergence, no fabrication** | **ok** | **ok** | **ok** |
| **Coverage** | **9/9** | 6/9 | 6/9 |

**Servers A and B scoring 6/9 is the correct outcome, not a failure.** Both were classified
`l1` for every tool, refused every uncovered call, and fabricated nothing. That is the
architecture recognising and declaring what it cannot simulate (OQ-4 answered affirmatively).

All six L2-Core operations were exercised on Server C in one session:

```
create_issue  -> synthesized, minted IS-M900
list_issues   -> overlay, ids [FX-001, IS-M900], $.total STALE
update_issue  -> synthesized (FX-001 status=closed)
get_issue     -> overlay, status=closed          (update observed)
delete_issue  -> synthesized
list_issues   -> overlay, ids [IS-M900]          (FX-001 gone)
```

---

## 3. Measurements M1-M9

| # | Measurement | Target | Result | Verdict |
|---|---|---|---|---|
| M1 | In-contract correctness | 100% | **100.0%** | met |
| M2 | Out-of-contract fabrication | 0% | **0.0%** | met |
| M3 | Divergence classification accuracy | >= 95% | **100.0%** | met |
| M4 | Manual decisions per tool | median <= 3 | **median 1.0, max 2** | met |
| M5 | Determinism | 10/10 + cross-OS | **10/10 on all 3 servers; cross-OS NOT run** | **partially met** |
| M6 | Replay latency p95 | < 10 ms | **1.9 / 2.3 / 2.0 ms** | met |
| M7 | Nine-step coverage | A,C 9/9; B honest L1 | **C 9/9, A 6/9, B 6/9** | met (see §2) |
| M8 | Extend-loop closure | qualitative | **does not close. See §6** | gap |
| M9 | Spike line count | < 2500 | **2012** | met |

**M5 caveat, stated plainly:** ten identical outcome hashes per server were verified on
Windows only. The cross-OS half of M5 was not executed because only one platform was
available. This is unverified, not passed.

Test suite: `python test_spike.py` — **38 checks, 0 failures**, covering canonicalization,
exact matching, no-fabrication, all overlay operations, reset isolation, determinism,
divergence classification, staleness, and capability-state gating.

---

## 4. F-1: Structural fabrication of overlay entities

**This is the most important finding of the spike and it was not anticipated by the gate.**

L2-Core builds a created entity from the **request**. It has no model of what the server
would actually have produced. The engine therefore emits entities that are incomplete or
structurally alien, **while reporting `divergence=None`**.

### Mild case, Server C (evidence: `results/f1_evidence.json`)

```
recorded entity keys : [created_at, id, project, status, title]
overlay entity keys  : [created_at, id, project, title]        <- 'status' missing
create divergence    : SYNTHESIZED_WRITE_RESPONSE
read   divergence    : STALE_DERIVED_FIELD   (for $.total only)
```

The row itself carries no marker that it was synthesized. `status` is a server-assigned
default the engine cannot know. An agent branching on `status` would misbehave.

### Severe case, Server A forced into L2-Core by human answers

```
real node shape    : [entityType, name, observations]
overlay row shape  : [created_at, entities, id]
served             : True
divergence         : None            <- silent
```

The merged `read_graph` response contained the **request envelope** rather than a node.
`create_entities({entities:[...]})` is a **batch** create: N entities per call. ADR-004
defines create as one entity per call and INV-014 forbids a seventh operation. Nothing in
the architecture detects the arity mismatch, because a CONFIRMED capability is treated as
absolute authority (INV-016).

### What this challenges

- **ADR-004** has no validation that a declared `body_request_path` actually yields a single
  entity of the declared shape. A wrong human answer produces silent structural fabrication.
- **INV-004** is not violated on its own terms: the engine did synthesize from a *declared*
  mutation template. The gap is that the declaration itself is unvalidated.
- **M2 has a blind spot.** It measures only whether *out-of-contract* calls were served. A
  structurally wrong but *in-contract* response is invisible to it. M2 = 0% is true and
  insufficient.

### What I did NOT do

I did not add a batch operation (INV-014). I did not add compile-time shape validation. I did
not add a new divergence class. I did not weaken the six operations. Three plausible fixes
exist and choosing among them is an architecture decision, which is not mine to make.

**Escalated. Requires an amending or superseding ADR before M1 builds on L2-Core.**

I made the experiment detect it instead: `f1_structural_fidelity` compares overlay entity
shape against recorded entity shape and is reported separately from step 5, because folding
it into step 5 would change the criterion the specification defines.

---

## 5. Interpretations I had to make (ADR ambiguities)

Recorded rather than resolved silently.

**I-1. Ordering of "exact recorded match" versus "L2-Core read merge."**
ADR-003 lists exact match (3) before L2-Core read merge (5). Taken literally, a recorded
`list_issues` would always be served from the recording, which makes read-after-write
impossible and defeats ADR-004 entirely. I implemented: exact match wins **while the overlay
is clean for that entity type**; once dirty, the merge path runs. This is the only reading
consistent with both ADRs, but the ADR text does not say it.

**I-2. Which divergence class an L1 tool produces on a miss.**
ADR-003 step 2 is `OUT_OF_CONTRACT`, step 6 is `NO_RECORDED_INTERACTION`. For an L1 tool
whose arguments were never recorded, both readings are defensible. I implemented
`OUT_OF_CONTRACT`, because the L1 contract *is* "exactly the recorded interactions", and
because milestone-0.md explicitly requires `OUT_OF_CONTRACT` for the `search` case.
`NO_RECORDED_INTERACTION` is reserved for L2-Core tools that pass the contract check but have
neither a recorded base nor overlay coverage.

**I-3. Id minting inputs.**
ADR-004 specifies minting from `(seed, entity_type, canonical_args, mutation_seq)`. I used a
per-type sequential counter offset into a disjoint range (`IS-M900`+). Determinism holds and
ids stay readable. `seed` and `canonical_args` were not required for the single-threaded
case; they would matter for parallel or branching execution.

---

## 6. M8: the extend loop does not close

`Divergence` carries `(cls, severity, seq, server, tool, detail)`. It does **not** carry the
request arguments. A world patch cannot be generated from a divergence record without
re-recording, because the thing that must be added to the world is precisely the
request/response pair the divergence describes.

`detail` contains the arguments only as free-form English text.

This is a concrete input for sizing M2.5: **the divergence record needs the canonical request
attached, or World Extend cannot be automated.** Not fixed here; it would be a domain-model
change.

---

## 7. Capability inference: what was hard

M4 came in at median 1.0, max 2, comfortably inside the target. The failures were instructive:

| Tool | Inference outcome | Why |
|---|---|---|
| `fixture/delete_issue` | Q3 asked | Response is `{"deleted": "FX-002"}`. **Delete responses commonly do not echo the entity**, so identity cannot be inferred from the response |
| `fixture/search_issues` | pinned L1, 1 question | `query` property detected as a query language. Correct and automatic |
| `memory/*` (all 9) | all L1 | Batch/array argument shapes; rows carry `name`, not `id`. Identity inference found no `id` field |
| `sqlite/*` (all 5) | all L1 | Every tool takes `query`. Correct and automatic |

**OQ-2 answered: yes, read/write was inferred correctly from the verb on every tool across
all three servers.** No fourth question was needed and none was added.

**OQ-3 answered, and the answer is negative.** A real third-party entity-oriented server
(Server A) did **not** map onto L2-Core. Its create is a batch operation and its entities have
no `id` field. The honest configuration leaves all nine tools at L1. Forcing it to L2-Core is
what produced F-1's severe case.

**A second-order effect worth noting:** because entity extraction only runs over `l2_core`
tools, a wrong fidelity assignment silently empties the initial entity set, which then makes
every subsequent get/update/delete return `NO_RECORDED_INTERACTION`. Fidelity errors cascade.

---

## 8. Where the implementation resisted the architecture

1. **Fidelity is derived, not declared, and I derived it wrongly twice.** First attempt
   required an id *path*, which broke collection reads whose identity lives on the rows.
   The derivation rule needs to be written down somewhere normative; it currently is not.
2. **Answer keys are not questions.** Counting raw answer dict keys inflated M4 from 1 to 4
   for one tool. Decisions must be counted as Q1/Q2/Q3 buckets, or the burden metric lies.
3. **`PAGINATION_OVERLAY_SKIPPED` requires a recorded page to exist.** With no recorded page,
   the more severe `NO_RECORDED_INTERACTION` fires instead. Both are non-fabricating, so the
   behaviour is correct, but the declared-limitations table in ADR-004 implies the WARN case
   is the only one.
4. **Synthesized-ness does not propagate.** A `SYNTHESIZED_WRITE_RESPONSE` on a create does
   not mark the resulting entity, so a later read that merges it reports `provenance=overlay`
   with no trace of synthesis. This is the mechanism behind F-1.

---

## 9. Deviations from the specification

**D-1. The agent is a scripted MCP client, not an LLM.** M5 requires identical outcome hashes
for a fixed tool-call sequence. A live model would vary the sequence and make world
determinism unmeasurable. The scripted client crosses the identical protocol boundary
(ADR-002 interception point), so nothing about the engine is tested differently. This is the
correct instrument, not a shortcut.

**D-2. Servers A and B are `@modelcontextprotocol/server-memory` and `mcp-server-sqlite-npx`
rather than Jira/GitHub and Postgres.** Both are real third-party MCP servers requiring no
credentials. This is stronger evidence than a self-written stand-in would have been.

**D-3. Cross-OS determinism not executed.** Single platform available. M5 is partially
verified.

**D-4. `models.py` has three fields not in the milestone-0 dataclasses** (`Capability.mutation`,
`Capability.derived_paths`, `World.tools_list`). `mutation` is required to distinguish the
declared create/update/delete operations of ADR-004; the spec's dataclass omitted it.
`tools_list` is needed to serve `tools/list` in replay without an upstream.

---

## 10. Files that should survive

| Path | Keep? | Why |
|---|---|---|
| `spike/fixture_server/` | **Yes** | Server C, as planned. Known-ground-truth conformance fixture |
| `spike/results/measurements.json` | **Yes** | The deliverable |
| `spike/results/f1_evidence.json` | **Yes** | Hard evidence for the F-1 escalation |
| `spike/results/FINDINGS.md` | **Yes** | This document |
| `spike/test_spike.py` | **Consider** | The 38 checks map almost 1:1 onto the planned conformance and property suites. Cheaper to port than to rewrite |
| everything else | No | Throwaway, as planned |

---

## 11. Recommendation

Applying only the gate defined in milestone-0.md:

| Gate condition | Fires? |
|---|---|
| M2 > 0% -> NO-GO | No. M2 = 0.0% |
| M1 < 100% in-contract -> NO-GO | No. M1 = 100.0% |
| M5 fails -> NO-GO | No. 10/10 on all three servers (cross-OS unverified) |
| Steps 1-7 pass but step 9 fabricates -> NO-GO | No. All three servers refused correctly |
| M4 median > 5 -> REDESIGN | No. Median 1.0 |
| M1 = 100, M2 = 0, M4 <= 3, M5 passes -> GO | Yes |

# GO

The core architectural claims held. Read-after-write works over a declared narrow contract.
Out-of-contract calls are refused and classified with zero fabrication across three servers,
two of them real third-party software. Determinism is exact. Capability burden is well under
budget.

**Two hard preconditions before Milestone 1 starts.** Neither softens the verdict; both
follow from the escalation duty:

1. **F-1 requires an ADR amending or superseding ADR-004** covering validation of declared
   capabilities against observed entity shape, and how synthesized-ness propagates from a
   write into subsequent reads. M1 must not build L2-Core on an unvalidated declaration.
2. **M5's cross-OS half must be executed** on Linux or macOS before determinism is claimed as
   verified.

I also recommend recording I-1, I-2, and I-3 as clarifications to ADR-003 and ADR-004, since
the next implementer will hit the same three ambiguities.

---
---

# Milestone 0.1 Findings: Structural Fidelity Verification

**Date:** 2026-08-09
**Authority:** ADR-006. No architecture decisions were made during implementation.
**Appended.** The Milestone 0 sections above are unchanged.

---

## 12. ADR-006 implementation observations

The amendment was implementable as written. Six spike modules changed; no ADR needed
reinterpretation, and no decision was improvised.

| Module | Change |
|---|---|
| `models.py` | `EntityConstructionContract` (+ `.construct()`), `ValidationResult`, `Entity.provenance`, `CallOutcome.synthesized_entity_ids`, `ENTITY_CONSTRUCTION_FAILED` |
| `compile.py` | ECC derivation from observed data; validations V1-V6; fidelity granted only on pass |
| `replay.py` | Construction through the validated contract; refusal without mutation; entity provenance; propagation through merge |
| `world.py` | ECC and validation record persisted in the world artifact (see F-2) |
| `test_spike.py` | T1, T1b, T2-T6 |
| `experiment.py` | M10 as a first-class measurement |

**Placement note.** `ECC.construct()` lives on the contract in `models.py`, not in
`compile.py`, so `replay/` can construct without importing inference (FR-165). Deriving a
contract is inference; applying one is mechanical. The boundary held.

---

## 13. V1-V6 results

| Server | Tool | Result | Check | Reason |
|---|---|---|---|---|
| C | `create_issue` | **accepted, l2_core** | V1-V6 all pass | `status` resolved as a `constant_default` observed across every create response |
| A | `create_entities` (honest config) | rejected, l1 | **V1, V2** | no observed entity of the inferred type; template empty |
| A | `create_entities` (entity type supplied) | rejected, l1 | **V3, V4, V5** | batch cardinality: an entity-shaped array observed in the create request/response |
| A | `create_relations`, `add_observations` | rejected, l1 | V1 | same |
| B | all five tools | l1, never evaluated as creates | n/a | query-language detection pins them before the ECC applies |

**What V1-V6 rejected that ADR-004 alone would have admitted:** `create_entities` under a
human answer set. Under ADR-004 that answer set produced the F-1 envelope. Under ADR-006 it
is refused at compile time and no human answer can override it.

**T1's open question resolved.** milestone-0.1 allowed either outcome for `status`
(constant default, or drop to l1). Observation settled it: `status` is `"open"` on every
create response, so it became a `constant_default`. Deriving constants from **create
responses only**, rather than from all observed entities, is what makes this correct.
`update_issue` later sets `status: "closed"`, and including update responses would have made
`status` non-constant and dropped the tool to l1 for the wrong reason.

---

## 14. Server A batch rejection evidence

```
V3 reason: batch cardinality: an entity-shaped array was observed in the create
           request or response. Batch writes are outside L2-Core (ADR-006 s2)
```

The detector is not vendor-specific: it looks for an array whose elements share at least one
key with the entity template. A test asserts that no vendor identifier
(`create_entities`, `read_graph`, `sqlite`, `read_query`, `npx`, and others) appears in any
engine module outside comments. It passes.

---

## 15. T3 regression evidence: the F-1 envelope is impossible

Reproducing the exact M0 configuration that produced the fabrication:

| M0 (ADR-004 only) | M0.1 (ADR-006) |
|---|---|
| `create_entities` forced to `l2_core` by answers | **pinned to `l1`**; validation failed V3, V4, V5 |
| overlay entity `{entities:[...], id, created_at}` | **no overlay mutation at all** |
| `read_graph` served it, `divergence=None` | request envelope absent from every read |
| `served=True` | `served=False`, `response=None`, classified refusal |

Asserted directly: the node overlay is empty, and no row containing an `entities` key
appears in any read. **A human answer can no longer override failed validation.**

---

## 16. Provenance findings

Propagation works and survives repeated reads. Trace from `crossos.py`:

```
create_issue      synthesized   synth=['IS-M900']
list_issues       overlay       synth=['IS-M900']   <- survives the merge
update_issue      synthesized   synth=['FX-001']
get_issue         overlay       synth=['FX-001']    <- survives get-by-id
delete_issue      synthesized   synth=[]
list_issues       overlay       synth=['IS-M900']   <- still reported on a later read
```

A purely recorded read reports `synthesized_entity_ids == ()`, so the signal is not noise.

**Observation O-1, recorded not resolved.** ADR-006 s5 defines entity provenance for
**create**. It does not say what an unrecorded **update** to a RECORDED_ENTITY produces. The
resulting state is part observed, part request-derived. The spike marks it
`SYNTHESIZED_ENTITY`, the conservative direction, which cannot violate INV-017 because it
increases visibility rather than reducing it. This is an implementation choice inside a gap
in the ADR, not a decision. **It should be settled explicitly before M1** so the production
engine does not inherit an undocumented rule.

---

## 17. F-2 (new): the ECC was not persisted in the world artifact

`crossos.py` loads the world **from disk** rather than from memory, and immediately failed:
`create_issue` returned `ENTITY_CONSTRUCTION_FAILED`. Cause: `models.Capability` gained
`ecc` and `validation`, but the `world.py` serializer was never updated, so a round-tripped
world silently lost its contract.

Two things are worth recording.

1. **The failure was fail-closed.** A world with no contract refused to create rather than
   falling back to request-derived construction. INV-017 held under a defect it was not
   written for. That is the invariant doing its job.
2. **In-memory tests did not catch it.** Every other M0.1 test used the compiled in-memory
   world. Only the disk path exposed it. `T1b` now guards the round-trip permanently, and
   the production `spec/` work should treat "the contract is world data" as a schema
   requirement rather than an implementation detail.

Fixed in `world.py`. Not an architecture change.

---

## 18. Measurements

| # | Target | M0 | M0.1 | Verdict |
|---|---|---|---|---|
| M1 in-contract correctness | 100% | 100.0% | **100.0%** | met, no regression |
| M2 out-of-contract fabrication | 0% | 0.0% | **0.0%** | met, no regression |
| M3 divergence classification | >= 95% | 100.0% | **100.0%** | met |
| M4 manual decisions | median <= 3 | 1.0 / max 2 | **1.0 / max 2** | met |
| M5 same-OS determinism | 10/10 | 10/10 | **10/10 all servers** | met |
| M5 cross-OS | equal hashes | not run | **NOT RUN** | **open, see 19** |
| M6 latency p95 | < 10 ms | 1.9-2.3 ms | **2.8-3.5 ms** | met |
| M7 nine-step | C 9/9, B honest l1 | C 9/9, A 6/9, B 6/9 | **unchanged** | met |
| **M10 structural fidelity** | 100% | n/a | **100.0%** | met |
| M9 spike lines | < 2500 | 2012 | **2670** | **EXCEEDED, see 20** |

**M10 detail:** 4 contract candidates evaluated, 1 accepted, 3 rejected. Rejection
distribution `{V1: 3}` in the honest configuration. By INV-017 a rejected contract admits no
entities, so every entity in overlay state came from an accepted contract: 100%.

Test suite: **72 checks, 0 failures**, comprising the original 38 M0 claim checks plus T1,
T1b, and T2 through T6.

---

## 19. Cross-OS determinism: NOT CLOSED

Same-OS is 10/10 on all three servers and on the dedicated `crossos.py` sequence. Cross-OS
was **not executed**, and the requirement was not weakened to compensate.

| Route | Outcome |
|---|---|
| Docker | Engine installed (29.4.0) but the daemon would not start headlessly; Docker Desktop appears to require interactive sign-in |
| WSL | Only the `docker-desktop` utility distro exists: busybox, no Python |
| GitHub Actions | Available in principle (`origin` is a public GitHub repo) but requires **pushing a branch**, an outward-facing action that was not authorized |

Prepared and ready, requiring one approval to execute:

- `spike/crossos.py` — fixed world, seed, and 10-step sequence; no Node dependency
- `spike/results/m5_windows.json` — Windows run, 10/10 identical
- `spike/results/m5_reference.json` — the reference hash **`80c6e57f69a0d807`**
- `spike/results/m5_crossos_workflow.yml` — a `workflow_dispatch` matrix over
  ubuntu/macos/windows that fails the job if the hash differs. Deliberately **not** placed in
  `.github/workflows/`, because activating it means pushing.

If the hashes differ, `milestone-0.1.md` already specifies the response: capture
`m5_divergence_evidence.json`, diff to the first differing step, escalate. **Do not
normalize until green.**

---

## 20. M9 exceeded: 2670 against a 2500 limit

Reported rather than trimmed. Trimming code to slip under a number would be gaming the
measurement.

| | Lines |
|---|---|
| Engine (`models`, `world`, `replay`, `coordinator`, `proxy`, `compile`) | 1563 |
| Harness, tests, fixture (`experiment`, `test_spike`, `crossos`, `fixture_server`) | 1107 |
| **Total** | **2670** |

Growth since M0 is +658, against milestone-0.1's estimate of 150-250. Attribution:
`compile.py` +213 (ECC derivation and six validations), `test_spike.py` +188 (T1, T1b,
T2-T6), `experiment.py` +106 (M10), `models.py` +83 (contract, validation, provenance),
`replay.py` +44, `world.py` +30 (F-2 fix), `crossos.py` +85 (new).

**Assessment against M9's stated purpose** ("a hidden architectural problem is being solved
by volume"): every added line is attributable to a construct ADR-006 names explicitly or a
test milestone-0.1 mandates. No new abstraction was introduced. 41% of the total is tests
and harness rather than engine.

That is an argument, not a ruling. **The threshold was breached, and whether to re-scope the
budget or trim is not the implementer's call.** Escalated. M9 is not part of Gate A, B, or C,
so it does not by itself block M1.

---

## 21. Architecture integrity

| Invariant | Status | Evidence |
|---|---|---|
| **INV-017** no structurally unverified overlay state | **holds** | T3; F-2 showed it holding even under a defect it was not written for |
| INV-004 never fabricate | holds | 0% fabrication; every refusal carries `response=None` |
| INV-007 determinism | holds same-OS; cross-OS unverified | 10/10 on every server and on `crossos.py` |
| INV-014 six operations | holds | no seventh operation added; batch excluded, not accommodated |
| INV-016 capability state gates authority | holds, strengthened | a human answer cannot override failed validation (T3) |

**No accepted ADR is challenged by M0.1.** One documented gap (O-1, update provenance) and
one implementation defect (F-2, now fixed and guarded) were found. Neither contradicts a
decision; O-1 is an unaddressed case that should be settled before M1.

---

# Milestone 0.1 Addendum: O-1 closure, M9 disposition, Gate B status

**Date:** 2026-08-09
**Appended.** Sections 1 through 21 above are unchanged.

---

## 22. O-1 closed by ADR-006 amendment

The ambiguity recorded in section 16 is resolved. The governing principle adopted:

> Provenance describes whether an entity's **current state** is fully grounded in recorded
> external state, or contains replay-synthesized state.

| Case | Provenance |
|---|---|
| Newly created replay-only entity | `SYNTHESIZED_ENTITY` |
| Recorded entity never modified in replay | `RECORDED_ENTITY` |
| Recorded entity modified by an unrecorded replay write | **`SYNTHESIZED_ENTITY`** |
| Once synthesized in a ReplaySession | **never returns to `RECORDED_ENTITY` in that session** |

Recorded as a short **amendment note inside ADR-006 s5**, not a new ADR, because it resolves
an ambiguity in that decision rather than replacing any part of it.

### Invariant check performed before adopting

| Invariant | Result |
|---|---|
| INV-017 no structurally unverified overlay state | **No conflict.** The rule only ever increases visibility |
| INV-004 never fabricate | **No conflict.** Nothing about what is served changes |
| INV-007 determinism | **No conflict.** A deterministic function of the call sequence. Verified: the M5 outcome hash is **unchanged at `80c6e57f69a0d807`** after the change |
| INV-006 per-execution isolation | **Preserved.** Monotonicity is per session; `reset()` rebuilds from world entities and restores `RECORDED_ENTITY` |
| INV-014 six operations | **No conflict.** No operation added |

### Implementation

Monotonicity is enforced in one place, `ReplayEngine._mark_synthesized`, applied uniformly to
update and delete. The exact-recorded-create path now carries an explicit guard so a recorded
create can never downgrade an entity that already holds synthesized state.

**No field-level provenance was added**, as instructed.

### Regression test T7

```
unmodified recorded entity          -> synthesized_entity_ids == ()
unrecorded update of FX-001
  get FX-001                        -> synthesized_entity_ids == ('FX-001',)
  list                              -> contains FX-001
  list again                        -> STILL contains FX-001   (monotonic)
  overlay entity provenance         -> SYNTHESIZED_ENTITY
  id                                -> still 'FX-001', the RECORDED id
reset()
  get FX-001                        -> synthesized_entity_ids == ()   (per-session)
  status                            -> back to 'open'
```

Identity remains recorded while current state is not, and both facts stay visible. That is
the point of the rule.

Test suite after T7: **82 checks, 0 failures**.

---

## 23. M9: accepted measurement deviation

**Final: 2,728 lines against a 2,500 target.** Recorded as an accepted deviation. No code was
trimmed to satisfy the number, and the target is **not** amended retroactively.

| | Lines |
|---|---|
| Engine (`models`, `world`, `replay`, `coordinator`, `proxy`, `compile`) | ~1,570 |
| Harness, tests, fixture (`experiment`, `test_spike`, `crossos`, `fixture_server`) | ~1,158 |
| **Total** | **2,728** |

Grounds for acceptance:

1. **The target was heuristic, not a release gate.** M9 is absent from Gate A, B, and C.
2. **The increase is attributable to ADR-006 validation and required regression coverage:**
   ECC derivation and validations V1-V6, tests T1, T1b, T2-T7, the M10 measurement, and the
   F-2 serialization fix.
3. **No new product abstraction was introduced solely to support the spike.** Every construct
   added is one ADR-006 names explicitly.
4. This is throwaway validation code. Optimizing it would spend effort on an artifact that is
   scheduled for deletion.

M9's stated purpose was to detect "a hidden architectural problem being solved by volume."
On the evidence, that is not what happened.

---

## 24. Gate B: executed as far as authorization permits

**No divergence was found, because the cross-platform run could not be executed.** This is an
execution gap, not a determinism failure. `spike/results/m5_divergence_evidence.json` is
deliberately **absent**: creating it would imply a difference was observed.

| Route | Attempted | Outcome |
|---|---|---|
| Local Docker | Yes | Engine present (29.4.0); daemon will not start headlessly. Docker Desktop appears to require interactive sign-in |
| Local WSL | Yes | Only the `docker-desktop` utility distro exists: busybox, no Python |
| GitHub Actions | Prepared, not run | Requires pushing a branch to a public repository. Not authorized in this task |

### What is ready

| Artifact | Status |
|---|---|
| `.github/workflows/m5-crossos.yml` | **Installed.** `workflow_dispatch` only, so it fires on nothing until run manually. Matrix over ubuntu / macos / windows. Fails the job if a hash differs |
| `spike/crossos.py` | Fixed world, seed, and 10-step sequence. Server C only, no Node dependency |
| `spike/results/m5_reference.json` | Reference hash **`80c6e57f69a0d807`**, Windows 11, CPython 3.14.4, 10/10 identical |
| `spike/results/m5_windows.json` | Current-OS run, re-verified after the O-1 change |

The deterministic sequence was **not altered** to make any platform pass, and canonicalization
and serialization are untouched.

### Same-OS determinism, re-verified after O-1

| Scope | Result |
|---|---|
| `crossos.py`, 10 runs | 1 distinct hash, `80c6e57f69a0d807` |
| Server C, experiment | 1 distinct hash |
| Server A (real), experiment | 1 distinct hash |
| Server B (real), experiment | 1 distinct hash |

### If the cross-OS run reports DIFFER

The response is already specified and must be followed: do not modify canonicalization or
serialization; build `spike/results/m5_divergence_evidence.json` from the uploaded
`m5_<os>.json` artifacts recording OS, Python version, locale, both hashes, the serialized
payload for every step, the first differing byte, and the semantic, provenance, `stale_paths`,
and divergence diffs; then escalate.
