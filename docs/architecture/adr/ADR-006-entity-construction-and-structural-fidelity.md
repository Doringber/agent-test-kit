# ADR-006: Entity construction and structural fidelity

**Status:** Accepted
**Date:** 2026-08-09
**Supersedes:** none
**Amends:** [ADR-004](ADR-004-l2-core-state-model.md) (overlay construction, capability states, batch cardinality), [ADR-005](ADR-005-evidence-semantics.md) (one added degradation trigger)
**Superseded by:** none
**Evidence:** Milestone 0, finding F-1. [`spike/results/FINDINGS.md`](../../../spike/results/FINDINGS.md) §4, raw data in [`spike/results/f1_evidence.json`](../../../spike/results/f1_evidence.json)

---

## Context

Milestone 0 validated the L2-Core replay model and returned GO, but produced one finding the gate did not contemplate.

ADR-004 declares that an L2-Core create builds the new overlay entity using `body_request_path`. The engine therefore derives entity state **from the write request**. It has no model of what the server would actually have persisted.

Two failures were measured.

**Mild, Server C (our fixture).** `create_issue({project, title})` persists `{id, project, title, status, created_at}`. The overlay entity was `{id, project, title, created_at}`. The server-assigned default `status` was absent. The subsequent merged read served that entity with `provenance=overlay` and no marker distinguishing it from a recorded entity.

**Severe, Server A (`@modelcontextprotocol/server-memory`, real third-party).** `create_entities({entities:[...]})` persists nodes shaped `{name, entityType, observations}`. The overlay entity was:

```json
{"entities": [{"name": "beta", "entityType": "svc", "observations": ["two"]}],
 "id": "NO-M900", "created_at": "2026-01-01T00:00:01Z"}
```

The request envelope, not a node. The subsequent `read_graph` merged it into the entity collection and returned `served=True`, `divergence=None`, `provenance=overlay`.

### Why this is architectural, not a bug

- The engine did exactly what ADR-004 instructed. `body_request_path` was honoured.
- The capability was CONFIRMED, and under [INV-016](../invariants.md#inv-016--capability-state-gates-authority) CONFIRMED is absolute authority.
- Nothing in the architecture relates a *declaration* to *observed reality*, so a well-formed but semantically wrong declaration cannot be detected.
- [INV-004](../invariants.md#inv-004--never-fabricate) was not violated on its own terms: the response was synthesized from a *declared* mutation template. The gap is that the template itself was never validated.

**M2 (out-of-contract fabrication rate) measured 0% and was necessary but insufficient.** The call was in-contract. M2 cannot see a structurally wrong in-contract response.

---

## Decision

### 1. Entity Construction Contract

**Chosen: Option D, hybrid, with observed data as the authority and explicit mapping only as a fallback.**

`body_request_path` is retired as the sole basis for entity construction. It is replaced by an **Entity Construction Contract (ECC)**, which is the minimum information required to turn a write request into overlay state:

| Element | Meaning | Source |
|---|---|---|
| `entity_template` | The authoritative key set of the entity type | **Observed**: recorded create responses, then recorded collection rows |
| `required_fields` | Keys present on **every** observed entity of the type | Derived |
| `field_bindings` | `entity_path <- request_path` | Derived by value-matching across recorded (request, entity) pairs; declared explicitly only where derivation fails |
| `generated_fields` | Keys the server assigns: identity and timestamps | Declared kind (`mint` / `clock`), never invented |
| `constant_defaults` | Keys whose observed value is identical across **all** observed entities | Derived |
| `cardinality` | `one`. See §2 | Validated |

**Runtime precedence, strict:**

1. **Exact recorded create.** The recorded create response *is* the entity. Adopt it verbatim, including the recorded identity. Provenance `RECORDED_ENTITY`. No synthesis occurs.
2. **Unrecorded create.** Construct from `entity_template`, filling `field_bindings` from the request, `generated_fields` from the minting rule and virtual clock, and `constant_defaults` from observation. Provenance `SYNTHESIZED_ENTITY`.
3. **Any required field unresolved.** Construction fails. See §4.

Rationale for D over the alternatives: (A) alone cannot fill a template for an *unrecorded* create, which is the only case that matters in replay; (B) alone pushes schema authoring onto users and violates the three-question budget; (C) alone is unavailable for unrecorded creates by definition. D uses observation as truth and asks a human only where observation is genuinely ambiguous.

### 2. Batch writes

**Chosen: Option A. Batch writes are outside L2-Core in v0.1.**

A create whose declared body resolves to an **array** on any observed request is structurally rejected at compile time and the tool is pinned to `fidelity: l1`.

No seventh operation is added. [INV-014](../invariants.md#inv-014--l2-core-is-exactly-six-operations) stands unchanged. `cardinality: many` is **reserved** in the schema namespace for L2-Extended and is not implemented.

This is deliberately narrow. It also makes the severe F-1 case impossible by construction rather than by detection, and it matches what M0 already showed to be the honest configuration for Server A (all nine tools at L1, zero fabrication).

### 3. Structural validation, and what CONFIRMED now means

Before a tool may be assigned `fidelity: l2_core`, the compiler must run six validations against observed data:

| # | Validation |
|---|---|
| **V1** | An `entity_template` exists: at least one observed entity of the declared type |
| **V2** | Identity resolves: the declared id path yields a non-null scalar on **every** observed entity |
| **V3** | Cardinality is `one`: the declared body path resolves to an object, never an array, on every observed request |
| **V4** | Template coverage: every `required_field` is bound, generated, or a constant default. **No unresolved required field** |
| **V5** | **Round-trip:** for every recorded (create request, create response) pair, constructing the entity through the ECC reproduces the recorded entity exactly on all required fields |
| **V6** | Collection compatibility: the constructed key set is compatible with the row shape of the declared collection read (no extra keys, no missing required keys) |

V5 is the decisive check. It tests the contract directly against ground truth and would have caught both F-1 cases at compile time.

**CONFIRMED is redefined:**

> **CONFIRMED = a human answered the three questions AND structural validation passed against observed data.**

Human answers establish *intent*. Observed data establishes *shape*. Neither alone is sufficient, and a human confirming READ/WRITE is explicitly **not** proof of entity semantics.

**No fourth capability state is introduced.** A tool whose human answers are complete but whose validation failed remains **PROPOSED** and therefore `l1`, per INV-016. The capability additionally carries a `validation` record naming the failed check, so the distinction between "unanswered" and "answered but invalid" is diagnosable without expanding the state model.

### 4. Runtime behaviour when construction is uncertain

For an L2-Core write whose entity cannot be constructed faithfully:

1. **No overlay mutation occurs.** Nothing structurally unverified enters the overlay, ever.
2. If an **exact recorded response** exists, serve it and apply the mutation using that recorded response as the entity (server-returned truth). Provenance `recorded` / `RECORDED_ENTITY`.
3. Otherwise **refuse**: `served=False`, `response=None`, new divergence `ENTITY_CONSTRUCTION_FAILED` (severity **ERROR**), naming the unresolved field or failed binding.
4. **Fidelity is never downgraded at runtime.** Fidelity is a compile-time property of the world. Mutating it mid-session would make replay depend on execution history and break [INV-007](../invariants.md#inv-007--determinism-of-the-world).

### 5. Provenance propagation

Entity-level provenance is introduced, with exactly two values:

| Value | Meaning |
|---|---|
| `RECORDED_ENTITY` | Came from observed data: a recorded create response or a recorded collection row |
| `SYNTHESIZED_ENTITY` | Constructed through a **validated** ECC from an unrecorded request |

`VERIFIED_SYNTHESIZED_ENTITY` and `UNKNOWN_ENTITY` are deliberately **not** introduced. After §4, unverifiable state can never enter the overlay, so "unknown entity" has no referent; and after §3 every synthesized entity is by definition validated, so "verified synthesized" collapses into `SYNTHESIZED_ENTITY`. Field-level provenance is not introduced.

#### Amendment note, 2026-08-09 (closes O-1)

Milestone 0.1 found this section defined provenance for **create** but was ambiguous for an
unrecorded **update** of an existing `RECORDED_ENTITY`. Settled by the governing principle:

> Provenance describes whether an entity's **current state** is fully grounded in recorded
> external state, or contains replay-synthesized state.

| Case | Provenance |
|---|---|
| Newly created replay-only entity | `SYNTHESIZED_ENTITY` |
| Recorded entity never modified in replay | `RECORDED_ENTITY` |
| Recorded entity modified by an unrecorded replay write | **`SYNTHESIZED_ENTITY`** |
| Once `SYNTHESIZED_ENTITY` in a ReplaySession | **Never returns to `RECORDED_ENTITY` in that session** |

The entity's *identity* may be recorded while its *current state* is not. Both facts stay
visible: the id is unchanged, and the provenance is downgraded. Applies uniformly to update
and delete.

Monotonicity is **per session**. `reset()` rebuilds the overlay from world entities, so a new
execution starts from `RECORDED_ENTITY` again, preserving [INV-006](../invariants.md#inv-006--per-execution-state-isolation).

**Invariant check:** conservative in the only direction that matters. It increases visibility
and never reduces it, so it cannot violate [INV-017](../invariants.md#inv-017--no-structurally-unverified-overlay-state)
or [INV-004](../invariants.md#inv-004--never-fabricate). It is a deterministic function of the
call sequence, so [INV-007](../invariants.md#inv-007--determinism-of-the-world) holds; verified
by the M5 outcome hash being unchanged at `80c6e57f69a0d807`. No new state, no field-level
provenance, no seventh operation. Recorded as an amendment rather than a new ADR because it
resolves an ambiguity in this decision rather than replacing any part of it.

Regression test: `T7` in `spike/test_spike.py`.

**Propagation rule.** A response carries the identities of every synthesized entity it contains:

- Response provenance is unchanged (`recorded` / `overlay` / `synthesized`).
- A response additionally carries `synthesized_entity_ids`, non-empty whenever any entity in it has provenance `SYNTHESIZED_ENTITY`.
- **This field is never cleared by a downstream read.** A merged read that includes a synthesized entity reports it. This is the direct fix for the F-1 observation that a synthesized write became invisible once merged into a later read.

### 6. Assertion impact

ADR-005's call-shape versus response-content split stands. One trigger is added to the response-content degradation list:

> A response-content assertion consuming a response whose `synthesized_entity_ids` is non-empty yields **UNKNOWN**.

Unchanged and still safe to assert on a trajectory containing synthesized state: `called`, `sequence`, `ordered`, `unique_writes`, `attempts_within`, `workflow_size`, `operation_profile`, `no_failures`. The agent's actions are real regardless of how the world constructed the entities it was shown.

ADR-005 is **amended, not superseded**. Its three-state model, its `evidence_sufficient` precondition, and its exemption of call-shape assertions are all unchanged.

---

## Consequences

### Accepted

- Fewer tools reach `l2_core`. Validation V1 to V6 will reject real tools that ADR-004 alone would have admitted. This is the intended trade.
- Batch-create tools stay L1 for the whole of v0.1, including the real `server-memory` case.
- The compiler grows a validation stage and must retain observed (request, entity) pairs to run V5.
- A create whose server assigns a *varying* field that is neither bound nor observed-constant now fails V4 and the tool drops to L1, where previously it silently produced an incomplete entity.

### Gained

- The severe F-1 case is impossible by construction (V3), not merely detected.
- The mild F-1 case is caught by V4 and V5 at compile time.
- Synthesized state stays visible downstream, so ADR-005's degradation can actually fire.
- CONFIRMED now means something checkable, which closes the gap where a wrong human answer became absolute authority.

### Rejected, and why

| Option | Reason |
|---|---|
| Add a batch/multi-entity operation | Violates INV-014, and one observed server does not justify widening the contract |
| Field-level provenance | Overengineered for the observed failure; entity-level is sufficient and cheaper |
| A fourth capability state for "validated" | Expands a model INV-016 depends on; a `validation` record achieves diagnosability without it |
| Runtime fidelity downgrade | Would make replay depend on execution history, breaking INV-007 |
| Trusting `body_request_path` with a post-hoc shape warning | A warning that fires after the entity is already in the overlay still exposes unverified state, which INV-017 forbids |

---

## Related

- Invariants: **[INV-017](../invariants.md#inv-017--no-structurally-unverified-overlay-state)** (new), [INV-004](../invariants.md#inv-004--never-fabricate), [INV-014](../invariants.md#inv-014--l2-core-is-exactly-six-operations), [INV-016](../invariants.md#inv-016--capability-state-gates-authority)
- Requirements: FR-200 to FR-213
- Verification: [Milestone 0.1](../../development/milestone-0.1.md)
