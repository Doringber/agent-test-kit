# agent-test

**Infrastructure for testing stateful AI agents against deterministic, replayable external worlds.**

> **Status: pre-implementation.** The architecture is approved and the project is entering Milestone 0, an architectural spike. There is no working release. See [Current status](#current-status).

---

## Why this exists

AI agents increasingly do their work by calling tools against external systems: issue trackers, databases, billing systems, source control. Testing them is hard for reasons that ordinary test infrastructure does not address.

- **The agent decides what to call.** You cannot write a fixture in advance for a call graph nobody declared.
- **Static mocks break on state.** An agent creates a record, then reads it back. A fixed response cannot answer a read that depends on a write the agent chose to make.
- **Tests cause real side effects.** Running a write-capable agent against real systems creates real tickets, real records, real charges. Cleaning up is not hygiene; it is a correctness problem.
- **Runs are not repeatable.** The same input produces a different execution each time, so a failure is hard to distinguish from ordinary variance.

The practical result is that agents that write to systems of record often ship with little or no automated behavioral testing.

This project records the slice of external behavior an agent actually depends on, then serves that recording back during tests, so the agent can be exercised repeatedly without contacting real systems.

---

## How it works

1. **Record.** Run the agent once against real tools. A proxy sitting on the tool protocol observes every request and response and writes them to a **World**.
2. **Confirm.** A compiler proposes what each tool does (read or write, which entity it affects, which field identifies it). A human confirms or corrects a small number of these.
3. **Replay.** Run the agent again with tools served from the World. No credentials, no network to those systems, no side effects.
4. **Observe.** When the agent does something the World cannot faithfully answer, the system reports a **divergence** rather than inventing a response.

---

## Core concepts

### World

A versioned artifact representing the subset of external behavior a set of agent tests requires: which tools exist, what they do, what they returned, and what entities existed. Worlds are immutable and are extended by producing a new version, never by silent mutation.

### Recording

Observing real tool interactions in order to construct a World. Redaction runs before anything is written to disk. A World should be assumed to contain production-shaped data.

### Replay

Serving tool interactions from a World instead of contacting real systems. Replay requires no credentials for those systems, which is a deliberate safety property: a run misconfigured as replay fails to authenticate rather than succeeding destructively.

### Stateful replay

Within a narrow, declared contract, writes apply to an isolated in-memory overlay so that subsequent reads within the same execution can observe them. The overlay is reset between executions, so runs do not contaminate one another.

### Divergence

A classified, visible report that the replayed world cannot faithfully answer the agent: an unknown tool, an unrecorded interaction, a call outside the declared contract.

Divergence is a designed feature, not merely an error condition. Telling you when the world can no longer answer is the point. The system does not guess, and a divergence never produces a passing verdict for anything that depended on it.

### Fidelity

Each tool is assigned a replay guarantee, enforced by the engine:

- **L1** — exact replay of recorded interactions, matched on canonical arguments.
- **L2-Core** — a narrow, declared set of entity-state operations (create, update, delete, get by id, list with a simple filter) that makes read-after-write work.

Calls outside a tool's assigned contract produce a divergence. Fidelity is per tool, so one unsupported tool does not disable a World.

---

## What this is not

Category clarity, not criticism of any of these.

- Not an LLM evaluation platform
- Not an LLM-as-judge framework
- Not a prompt scoring system
- Not a hallucination detector
- Not a general observability or tracing platform
- Not a production agent runtime
- Not a runtime authorization or policy enforcement product
- **Not a general-purpose simulator** for Jira, Stripe, GitHub, databases, or arbitrary SaaS systems

That last one matters most. We do not simulate services. We replay a declared subset of recorded behavior and state plainly when a request falls outside it.

### What is and is not controlled

The system controls **the replayed external world**: tool responses, entity identifiers, timestamps, and ordering are deterministic functions of the World and a seed.

The system does **not** control model or provider non-determinism. The agent still makes live decisions when tested, and those decisions vary. That is intentional, because it is what makes the run a test of the agent rather than a test of the replay engine.

---

## Architecture overview

```text
Agent
  |
  v
MCP client
  |
  v
Agent Test Proxy
  |
  +---- RECORD ----> Real MCP server
  |
  +---- REPLAY ----> World + State Overlay
```

Interception happens at the **tool-protocol boundary**, not through framework-specific integrations. The agent's tool configuration points at the proxy; the agent's source code is unchanged.

This is what keeps the system independent of any particular agent framework or language, and it is why the recorder and the replayer are the same component in the same position, differing only in what sits on the other side.

MCP is the first protocol adapter, not the product. The core domain contains no MCP-specific concepts.

Rationale: [ADR-002](docs/architecture/adr/ADR-002-protocol-boundary-interception.md). Component detail: [architecture-map.md](docs/architecture/architecture-map.md).

---

## Current status

**Architecture is complete. The project is currently entering Milestone 0, an architectural spike that validates the core replay model before production implementation begins.**

Milestone 0 is throwaway code, developed outside the production source tree, that must demonstrate:

- protocol-level recording of real tool traffic
- exact replay of a recorded interaction
- stateful read-after-write for a write the recording never contained
- deterministic world behavior across repeated executions and operating systems
- an explicit, correctly classified divergence instead of a fabricated response

M0 exists to end or redirect the project cheaply if these do not hold. It has a defined GO / NO-GO / REDESIGN gate.

Nothing in v0.1 is implemented. There is no package to install, no CLI to run, and no cloud service.

Details: [current-phase.md](docs/development/current-phase.md) and [milestone-0.md](docs/development/milestone-0.md).

---

## Repository guidance

### For contributors

1. Read [`CLAUDE.md`](CLAUDE.md) — project identity, invariants, and current scope.
2. Read [`docs/README.md`](docs/README.md) — the documentation index.
3. Check [`docs/development/current-phase.md`](docs/development/current-phase.md) — what may be built right now.
4. For current work, follow [`docs/development/milestone-0.md`](docs/development/milestone-0.md).

Implementation sessions should follow [implementation-workflow.md](docs/development/implementation-workflow.md), which defines how to load context and which changes require an architecture decision rather than a code change.

### About the existing `src/` tree

The existing `src/` implementation represents an earlier agent-testing approach and is **not** the target architecture defined by [ARCH-002](docs/architecture/ARCH-002.md). Milestone 0 is intentionally developed outside the production source tree so the new architecture can be validated before migration begins.

That earlier work is retained deliberately. Several components are sound and are planned for harvest, including the workflow assertion matcher, the side-effect verifier protocol, the async cleanup manager, and the redaction module. Others informed the current design by showing what did not work. Both are catalogued in [important-files.md](docs/development/important-files.md).

---

## Documentation

| Need | Read |
|---|---|
| Product vision | [PRD-001](docs/product/PRD-001.md) |
| Architecture | [ARCH-002](docs/architecture/ARCH-002.md) |
| Architecture decisions | [ADR index](docs/architecture/adr/README.md) |
| Architecture invariants | [invariants.md](docs/architecture/invariants.md) |
| Current implementation phase | [current-phase.md](docs/development/current-phase.md) |
| Milestone 0 | [milestone-0.md](docs/development/milestone-0.md) |
| Domain terminology | [glossary.md](docs/domain/glossary.md) |
| Testing strategy | [testing-strategy.md](docs/testing/testing-strategy.md) |
| Security model | [threat-model.md](docs/security/threat-model.md) |

Full index: [docs/README.md](docs/README.md).

---

## Project principles

- **No false green.** No result is reported as passing without positive evidence.
- **No evidence means UNKNOWN**, never a pass and never a failure.
- **Never fabricate replay responses.** If the world cannot answer, it says so.
- **Divergence is first-class**, always classified and always visible.
- **Replay worlds are isolated per execution**, so runs cannot contaminate each other.
- **MCP is an adapter, not the product.** The domain layer stays protocol-neutral.
- **Accepted architecture changes require an ADR**, supported by evidence. Architecture is not changed silently in code.

Each is stated as an enforceable rule, with its reason and a violation example, in [invariants.md](docs/architecture/invariants.md).

---

## License

See `pyproject.toml`. A `LICENSE` file has not yet been added.
