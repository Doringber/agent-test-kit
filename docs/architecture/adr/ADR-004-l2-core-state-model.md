# ADR-004: L2-Core state model

**Status:** Accepted
**Date:** 2026-08-09
**Supersedes:** none
**Superseded by:** none
**Amended by:** [ADR-006](ADR-006-entity-construction-and-structural-fidelity.md) (entity construction contract replaces `body_request_path`; batch cardinality excluded; CONFIRMED requires structural validation)

---

## Context

Read-after-write is the dominant real pattern in agent workflows: create an issue then list issues; update a record then read it back. Serving it requires modelling external state. Modelling arbitrary third-party service semantics is not achievable at any cost.

The superseded implementation inferred tool operation kind from tool names. This was empirically tested and found to classify `open_pull_request` as READ (so a mutation passed a read-only assertion) and `refund_payment` as UNKNOWN (so two identical refunds passed a duplicate-write assertion).

---

## Decision

**Implement a per-session entity overlay supporting exactly six operations, with an explicitly declared and enforced contract per tool. Everything outside the contract produces a divergence.**

### The fidelity ladder

| Level | Definition | v0.1 |
|---|---|---|
| **L1** | Replay of exactly recorded request/response pairs | Supported. Default for every tool |
| **L2-Core** | The six declared operations below | Supported for CONFIRMED capabilities |
| **L2-Extended** | Service-specific semantics (derived-field calculators, overlay-aware pagination, query languages) | **Not implemented.** Reserved schema namespace only |
| **L3** | General semantic simulation of arbitrary services | **Permanently out of scope** |

### The six operations. There is no seventh.

| # | Operation | Declaration required |
|---|---|---|
| 1 | create entity | `entity_type`, `id_response_path`, `body_request_path` |
| 2 | update entity | `entity_type`, `id_request_path`, `body_request_path` |
| 3 | delete entity | `entity_type`, `id_request_path` |
| 4 | get entity by id | `entity_type`, `id_request_path` |
| 5 | list/filter entities | `entity_type`, `collection_response_path`, `predicate`, `ignored_request_paths` |
| 6 | read-after-write within one ReplaySession | Emergent from 1 to 5 |

### The predicate grammar. Complete.

```
predicate := field_equals | field_in | all_of | always
field_equals : { request_path, entity_path }
field_in     : { request_path (array-valued), entity_path }
all_of       : [ predicate, ... ]
always       : {}
```

No disjunction, no ranges, no regular expressions, no negation, no query languages.

### Request parameter classification

Every request parameter of an L2-Core tool is classified at compile time as exactly one of **predicate-bound**, **ignored**, **pagination**, or **unrecognized**. A call containing an unrecognized parameter is out of contract and produces `OUT_OF_CONTRACT`.

### Overlay semantics

- Initialized from the world's entity set at session open, reset between executions.
- Writes mint ids deterministically from `(seed, entity_type, canonical_args, mutation_seq)`, in a numeric range disjoint from recorded ids so minted entities are visually distinguishable in a trajectory.
- Reads merge: start from the recorded collection, remove overlay-deleted entities, replace overlay-updated entities by id, append overlay-created entities satisfying the predicate, sort by declared key falling back to (recorded order, insertion order).
- Virtual clock advances a fixed tick per interaction.

### Capability states

| State | Enables L2-Core | Enables safety-sensitive assertions | Serves L1 replay |
|---|---|---|---|
| **CONFIRMED** | Yes | Yes | Yes |
| **PROPOSED** | **No** | **No** | Yes |
| **UNKNOWN** | No | **No** | Yes |

**Inference is an accelerator, never authority.** Inference lives in `compile/` and must never be imported by `replay/`, so it can improve without changing engine behavior.

### Human confirmation burden

At most **three questions per tool**: is this READ or WRITE, which entity does it affect, which field identifies that entity. Everything else is derived by the compiler. Median must be at most 3; a median above 5 is a redesign trigger for the capability model, not a user problem.

### Declared limitations

| Limitation | Divergence |
|---|---|
| Pagination with a dirty overlay | `PAGINATION_OVERLAY_SKIPPED` (WARN) |
| Derived or computed fields after mutation | `STALE_DERIVED_FIELD` (WARN) |
| Query languages (JQL, SQL, GraphQL) | `OUT_OF_CONTRACT` (ERROR); tool stays L1 |
| Cross-entity invariants, permissions, quotas | None; no claim made |
| Server-side asynchronous effects | None; no claim made |
| Optimistic concurrency conflicts | None; no claim made |

---

## Rationale

- The six operations cover the dominant real pattern while remaining specifiable in a schema a human can confirm in three answers.
- A tiny predicate grammar is honest. The moment a real API's query capability exceeds it, the call is out of contract and the user is told, rather than served a wrong result set.
- Deterministic id minting is what makes N-run statistical execution reproducible.
- Assigning fidelity **per tool** localizes the blast radius: one unsupported tool does not disable a world.
- Three capability states are what prevent the verified `refund_payment` class of false negative.

---

## Consequences

### Accepted

- Tools with query languages remain L1 permanently in v0.1. Server B in [Milestone 0](../../development/milestone-0.md) exists specifically to confirm this and make the boundary honest rather than surprising.
- Users will hit the predicate grammar's limits. The mitigation is a clear message naming the unrecognized parameter, **not a richer grammar**.
- Merge semantics remain the highest-risk code in the system and therefore the most heavily property-tested module.

### Gained

- The correctness claim is bounded, stated, and testable, which makes the product predictable. Predictability is the property the architecture review identified as missing.
- L2-Extended has a reserved namespace and can be added per service without a schema break.

---

## Related

- Requirements: FR-022 to FR-026, FR-041 to FR-046, FR-055, FR-160 to FR-165, FR-188 to FR-190
- Invariants: [INV-003](../invariants.md#inv-003--fidelity-contract), [INV-014](../invariants.md#inv-014--l2-core-is-exactly-six-operations), [INV-016](../invariants.md#inv-016--capability-state-gates-authority)
- Components: C5 World Compiler, C6 Replay Engine
