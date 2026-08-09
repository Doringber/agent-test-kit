# ADR-005: PASS / FAIL / UNKNOWN evidence semantics

**Status:** Accepted
**Date:** 2026-08-09
**Supersedes:** none
**Superseded by:** none
**Amended by:** [ADR-006](ADR-006-entity-construction-and-structural-fidelity.md) §6 (adds one response-content degradation trigger: non-empty `synthesized_entity_ids`)

---

## Context

The superseded implementation in this repository was empirically tested during architecture review. Against an `AgentExecutionResult` containing zero tool calls:

```
assert_read_only()                -> PASSED
assert_no_duplicate_tool_writes() -> PASSED
assert_no_failed_tool_calls()     -> PASSED
```

Separately, `refund_payment` classifies as UNKNOWN operation kind under the name heuristic, so two identical `refund_payment` calls pass `assert_no_duplicate_tool_writes()`.

Both are the same defect: **absence of evidence silently rendered as a positive verdict**, with the decision left to each individual assertion.

---

## Decision

**Adopt a three-state outcome model. Enforce evidence sufficiency once, in the assertion engine, before any individual assertion executes.**

### States

| State | Meaning |
|---|---|
| `PASS` | Positive evidence the expectation held |
| `FAIL` | Positive evidence it was violated |
| `UNKNOWN` | Insufficient evidence to decide |

### The `evidence_sufficient` precondition

Applied before any assertion runs. If the trajectory is empty, or a FATAL or ERROR divergence occurred, **no assertion is evaluated** and all yield UNKNOWN.

This is a single engine-level check, not a convention each assertion follows. The superseded implementation demonstrates that per-assertion discipline fails: three assertions written by a careful engineer all got it wrong.

### Propagation and exit codes

UNKNOWN propagates upward through execution, scenario, and run.

| Exit code | Meaning |
|---|---|
| 0 | PASS |
| 1 | FAIL |
| **2** | **UNKNOWN** |
| 3 | Usage or configuration error |
| 4 | Internal error |

UNKNOWN must be distinguishable from FAIL at the process boundary, or CI cannot treat them differently.

### Capability-driven degradation

Safety-sensitive assertions (`operation_profile`, `unique_writes`, and any assertion reading `operation`) yield UNKNOWN when the relevant capability state is PROPOSED or UNKNOWN. See [ADR-004](ADR-004-l2-core-state-model.md).

### Provenance-driven degradation, scoped correctly

Provenance does not degrade every assertion. The distinction preserves most of the suite's value:

| Class | Members | Degraded by provenance? |
|---|---|---|
| **Call-shape** | `called`, `sequence`, `ordered`, `attempts_within`, `workflow_size`, `operation_profile`, `unique_writes` | **No.** These evaluate what the agent *did*, unaffected by whether a response field was stale |
| **Response-content** | argument predicates reading results, `side_effect` verifiers consuming results | **Yes.** Consuming a SYNTHESIZED response or touching a STALE path yields UNKNOWN |

### Case table

| Condition | Result |
|---|---|
| Empty trajectory | UNKNOWN, all assertions, none evaluated |
| Partial trajectory (crash, cancellation) | UNKNOWN for assertions depending on the missing region; others evaluate |
| Malformed tool payload | UNKNOWN for the affected call and its dependents |
| Divergence FATAL or ERROR | UNKNOWN for the execution |
| Divergence WARN | UNKNOWN for dependent assertions only |
| Timeout | TIMEOUT, rendered as UNKNOWN in aggregation |
| Capability PROPOSED or UNKNOWN | Safety-sensitive assertions UNKNOWN |
| Verifier raised | FAIL for that verifier, isolated |
| Verifier timed out | **UNKNOWN** for that verifier (the superseded code marked it failed) |
| World hash mismatch | FATAL, run aborts |
| Engine internal error | Exit 4, run UNKNOWN, never attributed to the agent |

### The overriding invariant

**No code path may produce PASS in the absence of positive evidence. This supersedes every other requirement in conflict with it.**

---

## Rationale

- A verification tool reporting PASS without evidence converts uncertainty into false confidence at scale, which is worse than having no tool.
- Centralizing the check is essential and is justified by direct evidence: per-assertion handling was tried in this repository and failed three times out of three.
- Distinguishing UNKNOWN from FAIL lets CI treat "the agent misbehaved" differently from "we could not tell", which are different engineering responses.
- Scoping provenance degradation to response-content assertions prevents a defensible honesty rule from nullifying the entire assertion suite.

---

## Consequences

### Accepted

- More UNKNOWN outcomes than competing tools produce, and worse-looking results in a naive bake-off. This is the cost of honesty and it is accepted deliberately.
- Users must be taught that UNKNOWN is **actionable** (extend the world, confirm a capability) rather than a failure.
- Three-state logic complicates aggregation, CI integration, and reporting.

### Gained

- The verified defect class becomes structurally impossible rather than a matter of author discipline.
- A verdict means something, which is the only durable basis for a verification product.

### Enforcement

An adversarial evidence test **per assertion**, proving it yields UNKNOWN rather than PASS on empty and divergent evidence. This suite is release-blocking. Its absence blocks any release. See [testing-strategy.md](../../testing/testing-strategy.md#adversarial-evidence-tests).

---

## Related

- Requirements: FR-049, FR-064, FR-082, FR-101, FR-170 to FR-173
- Invariants: [INV-001](../invariants.md#inv-001--no-false-green), [INV-002](../invariants.md#inv-002--absence-of-evidence-is-unknown), [INV-016](../invariants.md#inv-016--capability-state-gates-authority)
- Components: C8 Assertion Engine
