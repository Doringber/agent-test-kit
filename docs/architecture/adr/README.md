# Architecture Decision Records

## Status

| ADR | Decision | Status | Date |
|---|---|---|---|
| [ADR-002](ADR-002-protocol-boundary-interception.md) | Protocol-boundary interception | **Accepted** | 2026-08-09 |
| [ADR-003](ADR-003-replay-matching-and-divergence.md) | Replay matching and divergence | **Accepted** | 2026-08-09 |
| [ADR-004](ADR-004-l2-core-state-model.md) | L2-Core state model | **Accepted** | 2026-08-09 |
| [ADR-005](ADR-005-evidence-semantics.md) | PASS / FAIL / UNKNOWN evidence semantics | **Accepted** (amended by ADR-006 §6) | 2026-08-09 |
| [ADR-006](ADR-006-entity-construction-and-structural-fidelity.md) | Entity construction and structural fidelity | **Accepted** | 2026-08-09 |

ADR-001 is intentionally unassigned. The world format decision it would have covered is specified directly in [ARCH-002 §R.1](../ARCH-002.md) and does not require a separate record.

---

## Governance

**Accepted ADRs are immutable. History is never rewritten.**

Changing an accepted decision requires all three of:

1. **New evidence** produced by implementation or measurement. Not a preference, not a theoretical alternative, not "I would have done it differently".
2. **A new ADR** with its own number, carrying `Supersedes: ADR-XXX` or `Amends: ADR-XXX` in its header.
3. **The affected ADR updated in place with exactly one line**: `Superseded by: ADR-YYY` or `Amended by: ADR-YYY`. Nothing else in it changes.

**Supersede versus amend.** Supersede when the original decision is replaced wholesale. Amend when a bounded part of it changes and the remainder stands. ADR-006 amends ADR-004 (entity construction, cardinality, capability states) and ADR-005 (one added degradation trigger); the rest of both decisions is untouched and still binding.

### Worked precedent: ADR-006

Milestone 0 measured a structural fabrication that ADR-004 permitted (finding F-1). The implementing engineer **stopped, recorded the evidence, and did not fix it in code** despite three plausible fixes being available. The amendment was then made as a decision, with the spike data as its basis. That is the workflow this section describes, and it is the standard for future changes.

The workflow is:

```
observation -> evidence -> new/superseding ADR -> implementation
```

**Never silently change architecture in code.** See [INV-015](../invariants.md#inv-015--architecture-governance).

### What counts as evidence

| Counts | Does not count |
|---|---|
| A Milestone measurement missing its target | "This would be cleaner" |
| A conformance test that cannot be made to pass | "Another library does it differently" |
| A reproducible correctness failure | "This is more flexible" |
| A profiled performance bottleneck | An anticipated future requirement |
| A user-observed adoption blocker with data | A theoretical edge case |

### If you are mid-implementation and believe an ADR is wrong

Stop. Do not work around it. Do not implement both paths. Write the observation and the evidence into [current-phase.md](../../development/current-phase.md) under "Open implementation questions" and escalate. The cost of a paused task is much lower than the cost of an architecture that drifts from its record.

---

## Format

Each ADR contains: Status, Date, Supersedes/Superseded-by, Context, Decision, Rationale, Consequences (accepted, gained, rejected-and-why).

ADRs state what was decided and why. They do not restate requirements (see [functional-requirements.md](../../requirements/functional-requirements.md)) and they do not restate invariants (see [invariants.md](../invariants.md)). They are the reason those exist.
