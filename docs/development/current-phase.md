# Current Development Phase

> **Living document.** This is the first thing to read before any implementation task, and the last thing to update after one. It overrides stale assumptions anywhere else.

**Last updated:** 2026-08-09
**Updated by:** Implementing Staff Engineer (Milestone 0.1 executed)

---

## Current milestone

**Milestone 0.1: Structural Fidelity Verification.**

Full specification: [milestone-0.1.md](milestone-0.1.md). Milestone 0 is complete ([milestone-0.md](milestone-0.md)).

## Goal

Verify that [ADR-006](../architecture/adr/ADR-006-entity-construction-and-structural-fidelity.md) closes Milestone 0 finding **F-1** (structural fabrication of overlay entities), and close the **M5 cross-OS** verification gap.

**Nothing else.** M0.1 reuses the existing spike and does not start production code.

## Status

**M0 complete. Outcome: GO, with two hard preconditions before M1 starts.**

Full write-up: [`spike/results/FINDINGS.md`](../../spike/results/FINDINGS.md).
Measurements: [`spike/results/measurements.json`](../../spike/results/measurements.json).

| Item | State |
|---|---|
| ARCH-002 | Approved |
| ADR-002, 003, 004, 005 | Accepted |
| Engineering context system | Complete |
| M0 spike code | **Complete.** 2,012 lines, `spike/` only |
| M0 gate | **GO** (M1 100%, M2 0%, M3 100%, M4 median 1.0, M5 10/10 per server) |
| Production code (`src/agenttest/`) | **Not started. Blocked on the two preconditions below** |
| Superseded package (`src/agent_test_kit/`) | Present, untouched |

### Preconditions before Milestone 1 may begin

| # | Precondition | State |
|---|---|---|
| 1 | ADR amending ADR-004 for **F-1** | **Done.** [ADR-006](../architecture/adr/ADR-006-entity-construction-and-structural-fidelity.md) accepted, [INV-017](../architecture/invariants.md#inv-017--no-structurally-unverified-overlay-state) added |
| 2 | **M0.1 passes** (T1-T7, M10 = 100%, no regression) | **Done.** 82 checks, 0 failures. M10 = 100%. M1/M2/M3/M4 unregressed |
| 3 | **Cross-OS determinism passes** | **OPEN. BLOCKING.** Same-OS 10/10; cross-OS requires one authorized push |
| 4 | No accepted invariant remains challenged | **Done.** INV-017 holds under T3; INV-004/006/007/014/016 unchallenged |

### M0.1 result: Gate A pass, Gate C pass, **Gate B open**

| Gate | Verdict |
|---|---|
| **A — Structural fidelity** | **PASS.** T1, T1b, T2-T7 green; M10 = 100%; the F-1 envelope is impossible (T3) |
| **B — Determinism** | **NOT CLOSED.** Same-OS 10/10 on all servers and on `crossos.py`; cross-OS **not executed** |
| **C — Architecture integrity** | **PASS.** INV-017 holds; ADR-002 through ADR-006 unchallenged |

**Why Gate B is open.** Docker is installed but its daemon will not start headlessly; WSL has
only the busybox `docker-desktop` distro; GitHub Actions requires **pushing a branch to a
public repo**. The requirement was not weakened and the deterministic sequence was not
altered. **No divergence was observed**, so `spike/results/m5_divergence_evidence.json` is
deliberately absent.

Ready to run, needing exactly one authorized push:

- `.github/workflows/m5-crossos.yml` — **installed**, `workflow_dispatch` only, fires on nothing until run manually
- `spike/crossos.py` — fixed world, seed, 10-step sequence, Server C only, no Node dependency
- `spike/results/m5_reference.json` — reference hash **`80c6e57f69a0d807`**

### Closed items

| # | Item | Disposition |
|---|---|---|
| **O-1** | Provenance of a recorded entity modified in replay | **CLOSED.** ADR-006 s5 amendment note. Current state, not identity, determines provenance; monotonic per session. Regression test **T7**. Outcome hash unchanged, so INV-007 verified |
| **F-2** | ECC not persisted in the world artifact; disk round-trip lost it | **CLOSED.** Fixed in `world.py`, guarded by **T1b**. Failure had been fail-closed. Carry "the contract is world data" into `spec/` at M1 |
| **M9** | 2,728 lines against a 2,500 target | **CLOSED as an accepted measurement deviation.** Target was heuristic, not a release gate; growth attributable to ADR-006 validation and mandated regression coverage; no new product abstraction added. **The target is not amended retroactively** and no code was trimmed to satisfy it |

Still recommended: record interpretations **I-1, I-2, I-3** as clarifications to ADR-003 and
ADR-004 (see FINDINGS §5). Not blocking; the next implementer will hit the same ambiguities.

---

## Scope: what M0.1 may build

Changes to the **existing spike only**: `compile.py` (ECC + validations V1-V6), `replay.py`
(construction, refusal, entity provenance), `models.py` (new types), `test_spike.py` (T1-T6),
`experiment.py` (M10). Roughly 150-250 net lines. See [milestone-0.1.md](milestone-0.1.md).

**M0.1 does not modify `src/`.** Batch cardinality, field-level provenance, world patches,
the assertions engine, and HTTP transport all remain out of scope.

---

## Scope: what M0 built (complete)

Throwaway code under `spike/` only. Six modules plus a fixture server:

- `coordinator.py` — session state over loopback TCP
- `proxy.py` — stdio relay
- `world.py` — minimal world load/save, canonicalization
- `compile.py` — session log to world, capability proposal, decision counting
- `replay.py` — matcher, contract check, overlay, merge, divergence
- `experiment.py` — drives the nine-step loop, captures measurements
- `fixture_server/` — Server C. **The only artifact intended to survive**

Target: under 2,500 lines total. Exceeding it signals a hidden architectural problem; escalate rather than continuing.

## Explicit non-goals

Building any of these during M0 is a spike failure:

Assertions, scenarios, verdicts, PASS/FAIL/UNKNOWN machinery, trajectory model or persistence, pytest integration, CLI polish, packaging, `init`, parallel execution, HTTP or SSE transport, full redaction (a stub is required and sufficient), world patches or merge or migration, `WorldRef`, HYBRID safety machinery, error injection beyond Server C, cloud anything, performance optimization, error-message quality work.

**M0 does not modify `src/`.**

---

## Accepted architecture decisions

Closed. Do not reopen without new evidence and a superseding ADR ([INV-015](../architecture/invariants.md#inv-015--architecture-governance)).

| ADR | Decision |
|---|---|
| [ADR-002](../architecture/adr/ADR-002-protocol-boundary-interception.md) | Protocol-boundary interception. stdio only in v0.1 |
| [ADR-003](../architecture/adr/ADR-003-replay-matching-and-divergence.md) | Exact canonical matching, never fuzzy. Divergence taxonomy |
| [ADR-004](../architecture/adr/ADR-004-l2-core-state-model.md) | L2-Core six operations, restricted predicate grammar, three capability states |
| [ADR-005](../architecture/adr/ADR-005-evidence-semantics.md) | PASS / FAIL / UNKNOWN, centralized `evidence_sufficient` |
| [ADR-006](../architecture/adr/ADR-006-entity-construction-and-structural-fidelity.md) | Entity Construction Contract; batch excluded; CONFIRMED requires validation; entity provenance. **Amends ADR-004 and ADR-005** |

---

## Open implementation questions

Escalate rather than resolving locally. Record findings here as they arise.

| # | Question | Escalation trigger |
|---|---|---|
| OQ-1 | Does the heuristic sibling rule for staleness produce excessive false positives on real responses? | **Do not invent a replacement heuristic.** Record the observation and escalate |
| OQ-2 | Can capability proposal distinguish read from write on a real server's schema? | **Do not add a fourth question.** Record and escalate; it means the three-question target needs redesign |
| OQ-3 | Does read-after-write hold for Server A's real list semantics? | Report as measurement M1 |
| OQ-4 | Is Server B (SQL) correctly and honestly classified L1-only? | If it is forced into L2-Core, the spike has failed |

### M0 findings

| # | Outcome |
|---|---|
| **OQ-1** | **No false positives.** The sibling rule fired exactly once, correctly, on `$.total`. No replacement heuristic was invented |
| **OQ-2** | **Answered yes.** Read/write was inferred correctly from the verb on all 20 tools across three servers. No fourth question was needed or added |
| **OQ-3** | **Answered NO, and this is significant.** A real third-party entity-oriented server (`server-memory`) does **not** map onto L2-Core: its create is a *batch* operation and its entities carry `name`, not `id`. Honest configuration leaves all nine tools at L1. Forcing it to L2-Core produced finding F-1 |
| **OQ-4** | **Answered yes.** All five `sqlite` tools classified L1 automatically via query-language detection. Zero fabrication. The boundary is honest |
| **F-1 (new)** | **Structural fabrication of overlay entities.** Escalated; see precondition 1 above and FINDINGS §4 |
| **I-1, I-2, I-3 (new)** | Three ADR ambiguities required interpretation during implementation. Recorded, not silently resolved. FINDINGS §5 |
| **M8 (new)** | The extend loop **does not close**: `Divergence` omits the canonical request, so a world patch cannot be generated without re-recording. Sizing input for M2.5. FINDINGS §6 |

---

## Gate criteria

M0 produces a **GO**, **NO-GO**, or **REDESIGN** recommendation based on measurements M1 to M9 ([milestone-0.md](milestone-0.md#measurements)).

| Outcome | Action |
|---|---|
| M1 = 100%, M2 = 0%, M4 median ≤ 3, M5 passes | **GO.** Proceed to Milestone 1 |
| M2 > 0% (any fabrication) | **NO-GO.** Halt, redesign ADR-003 |
| M1 < 100% in-contract | **NO-GO.** Halt, redesign ADR-004 |
| M4 median > 5 | **REDESIGN.** Rework the capability model before M1 |
| M5 fails (non-determinism) | **NO-GO.** Halt and find it. Severity-one |
| Steps 1 to 7 pass but step 9 fabricates | **NO-GO.** The worst outcome and the most important to detect |

---

## Next milestone after GO

**M1: L1 replay end to end with the Session Coordinator.** 3 weeks. First production code in `src/agenttest/`. Does not begin until this document records a GO.

---

## Update protocol

After any implementation session, update:

1. **Status** table
2. **Open implementation questions** with new findings
3. **Last updated** date and author

Do not update Scope or Gate criteria without a decision. Those change by approval, not by drift.
