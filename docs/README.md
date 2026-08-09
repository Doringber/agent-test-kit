# Documentation Index

Entry point for humans and agents. **"I need to understand X, which document do I read?"**

Each concept has exactly one canonical home. Documents cross-link; they do not copy.

---

## Canonical documents

| Question | Canonical document |
|---|---|
| What product are we building? | [PRD-001](product/PRD-001.md) |
| What architecture are we implementing? | [ARCH-002](architecture/ARCH-002.md) |
| Why a protocol proxy and not an SDK shim? | [ADR-002](architecture/adr/ADR-002-protocol-boundary-interception.md) |
| How does replay matching work? What is divergence? | [ADR-003](architecture/adr/ADR-003-replay-matching-and-divergence.md) |
| What does L2-Core support? | [ADR-004](architecture/adr/ADR-004-l2-core-state-model.md) |
| When is something UNKNOWN? | [ADR-005](architecture/adr/ADR-005-evidence-semantics.md) |
| How is an overlay entity constructed, and when is it refused? | [ADR-006](architecture/adr/ADR-006-entity-construction-and-structural-fidelity.md) |
| What is Milestone 0.1? | [milestone-0.1.md](development/milestone-0.1.md) |
| What are the architecture invariants? | [invariants.md](architecture/invariants.md) |
| Which component owns what, and what may depend on what? | [architecture-map.md](architecture/architecture-map.md) |
| What are the domain concepts? | [domain-model.md](domain/domain-model.md) |
| What does this word mean? | [glossary.md](domain/glossary.md) |
| What are the functional requirements? | [functional-requirements.md](requirements/functional-requirements.md) |
| What are the non-functional requirements? | [non-functional-requirements.md](requirements/non-functional-requirements.md) |
| What are we building right now? | [current-phase.md](development/current-phase.md) |
| What exactly is Milestone 0? | [milestone-0.md](development/milestone-0.md) |
| How should an implementation session proceed? | [implementation-workflow.md](development/implementation-workflow.md) |
| Which files matter and why? | [important-files.md](development/important-files.md) |
| How should this system be tested? | [testing-strategy.md](testing/testing-strategy.md) |
| What are the security boundaries and threats? | [threat-model.md](security/threat-model.md) |
| What is the status of architecture decisions? | [adr/README.md](architecture/adr/README.md) |

---

## Three layers

**Layer 1, read every time.** [`/CLAUDE.md`](../CLAUDE.md) and [current-phase.md](development/current-phase.md). Under 300 lines combined.

**Layer 2, read for the task at hand.** [invariants.md](architecture/invariants.md), [architecture-map.md](architecture/architecture-map.md), [domain-model.md](domain/domain-model.md), [glossary.md](domain/glossary.md), the requirements catalogs, [testing-strategy.md](testing/testing-strategy.md), [threat-model.md](security/threat-model.md), the current milestone document.

**Layer 3, deep reference, rarely read in full.** [PRD-001](product/PRD-001.md), [ARCH-002](architecture/ARCH-002.md), the ADRs.

Loading strategy per task type is in [implementation-workflow.md](development/implementation-workflow.md#context-loading-by-task-type).

---

## Governance

- Accepted ADRs are immutable. Changing a decision requires a new superseding ADR with new evidence. See [adr/README.md](architecture/adr/README.md#governance).
- Requirement IDs are stable and never reused.
- [current-phase.md](development/current-phase.md) is the only living document that changes routinely. Everything else changes by decision, not by drift.

---

## Obsolete

`AGENT_E2E_FULL_FLOW.md` documents the superseded client-based architecture (HTTP agent clients, vendor stdout parsing, prompt-review pipeline). It is retained only as a historical record of the prior approach. **Do not follow it.** It contradicts ADR-002.
