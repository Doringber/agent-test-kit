# Implementation Workflow

How an implementation session proceeds. Applies to human engineers and to Claude Code sessions equally.

---

## The workflow

1. **Read [CLAUDE.md](../../CLAUDE.md).** Always. It is short by design.
2. **Read [current-phase.md](current-phase.md).** It is the authority on what may be built right now and it overrides stale assumptions anywhere else.
3. **Read the current milestone document.** Currently [milestone-0.md](milestone-0.md).
4. **Read the relevant ADR(s).** Determined by the task. See [context loading by task type](#context-loading-by-task-type).
5. **Inspect the affected code.** Do not assume; read it.
6. **Produce a short implementation plan** naming the requirement IDs (`FR-xxx`) and invariants (`INV-xxx`) in scope. If the plan cannot cite at least one requirement ID, the task is probably out of scope.
7. **Implement only milestone scope.** Nothing else.
8. **Run the required tests** for the affected class. See [testing-strategy.md](../testing/testing-strategy.md).
9. **Check architectural invariants.** Walk [invariants.md](../architecture/invariants.md) against the diff. Anything touching evidence, replay, or divergence must be checked explicitly.
10. **Update [current-phase.md](current-phase.md):** status, open questions, last-updated date.
11. **Propose documentation or ADR changes only when implementation produced new evidence.** Not because an alternative occurred to you.

---

## Prohibited during a coding task

These are not discouraged. They are prohibited.

| Prohibited | Instead |
|---|---|
| **Architecture redesign** | Stop, record the evidence in [current-phase.md](current-phase.md) under Open implementation questions, escalate |
| **Adding future-phase features** | Check the Phase column in [functional-requirements.md](../requirements/functional-requirements.md). `v0.5` and `v1+` are out of scope |
| **Silently changing requirements** | Requirements change by decision. Propose it; do not enact it |
| **Introducing abstractions "for later"** | Two concrete implementations exist before an abstraction is declared. One implementation is a guess, not an abstraction |
| **Creating public extension points** | Only `AgentLauncher` and `SideEffectVerifier` are public. A new one requires an approved requirement |
| **Changing an accepted ADR** | Requires new evidence plus a superseding ADR. See [adr/README.md](../architecture/adr/README.md#governance) |
| **Working around an invariant** | An invariant that is inconvenient is still an invariant. If it is genuinely wrong, it changes through an ADR |
| **Making a decision listed as "escalate"** | [milestone-0.md](milestone-0.md#explicit-non-goals) names two. Escalate them |

### The escalation rule, stated plainly

> If you find yourself writing a comment explaining why you deviated from an ADR, stop. That comment is evidence that the deviation belongs in a document, not in the code.

The cost of a paused task is far lower than the cost of an architecture that drifts from its record.

---

## Context loading by task type

Do not load ARCH-002 or PRD-001 for routine work. They are Layer 3.

| Task | Load |
|---|---|
| **Any task** | CLAUDE.md, current-phase.md |
| Matching, canonicalization, divergence | + [ADR-003](../architecture/adr/ADR-003-replay-matching-and-divergence.md), [invariants.md](../architecture/invariants.md) INV-003/004/005/007, [glossary.md](../domain/glossary.md) |
| Overlay, merge, entity state, capabilities | + [ADR-004](../architecture/adr/ADR-004-l2-core-state-model.md), [domain-model.md](../domain/domain-model.md), INV-003/006/014/016 |
| Assertions, verdicts, outcomes | + [ADR-005](../architecture/adr/ADR-005-evidence-semantics.md), INV-001/002/016, [testing-strategy.md](../testing/testing-strategy.md#adversarial-evidence-tests) |
| Recorder, proxy, transport | + [ADR-002](../architecture/adr/ADR-002-protocol-boundary-interception.md), [architecture-map.md](../architecture/architecture-map.md), INV-008/011 |
| Session coordinator, ordering, isolation | + [architecture-map.md](../architecture/architecture-map.md), INV-006/007 |
| World format, maintenance, extend | + [ADR-004](../architecture/adr/ADR-004-l2-core-state-model.md), INV-009/010, [domain-model.md](../domain/domain-model.md) |
| Modes, CLI, CI integration | + INV-011/012, FR-100 to FR-109, FR-140 to FR-146 |
| Anything touching persistence or recording | + [threat-model.md](../security/threat-model.md) |
| Adding a test | + [testing-strategy.md](../testing/testing-strategy.md) |
| Naming anything | + [glossary.md](../domain/glossary.md) |

---

## Worked examples

### Task A: "Implement canonical argument matching"

**Load:** CLAUDE.md, current-phase.md, milestone-0.md, ADR-003, invariants INV-003/004/007, glossary (canonicalization, in-contract, out-of-contract).

**Constraints discoverable without ARCH-002 or PRD-001:**

- The five canonicalization steps, specified in ADR-003.
- Exact equality only; fuzzy matching is prohibited (INV-004).
- Contract check precedes matching (INV-003).
- Deterministic ordering; no hash-map iteration, no wall clock (INV-007, NFR-013).
- Requirements: FR-027, FR-033, FR-040, FR-190.
- Test class: property tests for round-trip, conformance for match behavior.

### Task B: "Add a new assertion"

**Load:** CLAUDE.md, current-phase.md, ADR-005, invariants INV-001/002/016, testing-strategy (adversarial evidence tests), glossary (call-shape vs response-content, the three UNKNOWNs).

**Constraints discoverable:**

- Outcome is three-valued (FR-082).
- Classify it: call-shape (exempt from provenance degradation) or response-content (degraded) (FR-171, FR-172).
- If it reads `operation`, it is safety-sensitive and requires CONFIRMED capability (INV-016).
- `evidence_sufficient` is engine-level; do not re-implement emptiness handling in the assertion (ADR-005).
- **An adversarial evidence test is mandatory and release-blocking.**
- The nine primitives and their classification are in [domain-model.md § Assertion](../domain/domain-model.md#assertion). Adding a tenth requires an approved requirement.

### Task C: "Add HTTP MCP support"

**Load:** CLAUDE.md, current-phase.md, ADR-002, architecture-map (C4 boundaries), functional-requirements (FR-002).

**Constraints discoverable:**

- **FR-002 is phase v0.5. Out of scope today.** The task stops here unless current-phase says otherwise.
- If in phase: it goes behind the existing protocol adapter interface, touching neither the replay engine nor the domain (INV-008, NFR-083).
- Session Coordinator registration is unchanged (FR-180, FR-181).
- SSE responses materialize whole with chunk boundaries retained (FR-012).
- Protocol adapters are **internal**, not a public extension point.

All three tasks resolve without reading ARCH-002 or PRD-001.

---

## Commit and PR conventions

- Reference requirement IDs and invariant IDs: `FR-049`, `INV-004`.
- A change touching evidence semantics, replay matching, or divergence classification states in the PR description which invariants were checked.
- A change contradicting an ADR is not reviewable as code. It needs an ADR first.

---

## When the milestone changes

On a milestone transition, exactly three things update:

1. [current-phase.md](current-phase.md): milestone, goal, scope, non-goals, gate, status.
2. [functional-requirements.md](../requirements/functional-requirements.md): Status column for requirements now in scope.
3. [important-files.md](important-files.md): new architecturally significant files.

Everything else changes by decision, not by milestone.
