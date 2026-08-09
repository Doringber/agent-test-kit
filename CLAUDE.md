# CLAUDE.md

Always-needed context. Keep this file under 200 lines. Everything else is linked, not copied.

---

## What we are building

**Infrastructure for testing stateful AI agents against deterministic, replayable external worlds.**

We record an agent's real interaction with its tools once, freeze it into a portable **World** artifact, and serve that world back to the agent so the interaction can be re-executed indefinitely without touching anything real.

### What we are NOT building

Do not add these. Do not accept requests that drift toward them without an approved requirement.

- LLM evaluation or output scoring
- Prompt scoring, prompt management, prompt versioning
- Hallucination or factuality detection
- General observability or production tracing
- A production agent runtime
- Runtime authorization or policy enforcement
- A model gateway or proxy (we never proxy model traffic)
- Generic simulation of arbitrary SaaS systems

The last one is the most important. See [INV-003](docs/architecture/invariants.md#inv-003--fidelity-contract).

### The promise, stated precisely

> We construct a deterministic test world around the subset of external behavior your agent depends on, and we tell you explicitly, and always, when that world can no longer faithfully answer the agent.

---

## Current phase

**Architecture is approved. ARCH-002 is the governing specification.**

**Current implementation phase: Milestone 0 architectural spike.**

Production architecture must not be implemented until M0 reaches **GO**.

Read [docs/development/current-phase.md](docs/development/current-phase.md) before any implementation task. It is a living document and it overrides stale assumptions in this file.

---

## Architectural invariants

Non-negotiable. Full statements, reasons, and violation examples in [docs/architecture/invariants.md](docs/architecture/invariants.md).

| ID | Invariant |
|---|---|
| INV-001 | **No false green.** No code path produces PASS without positive evidence |
| INV-002 | **No evidence means UNKNOWN**, never PASS and never FAIL |
| INV-003 | Only **in-contract** behavior receives a correctness guarantee |
| INV-004 | **The replay engine never fabricates a response** |
| INV-005 | **Divergence is first-class** and always visible |
| INV-006 | Replay state is **isolated per execution** |
| INV-007 | Same world + seed + tool-call sequence produces **identical world behavior** |
| INV-008 | **The domain layer contains no MCP-specific concepts.** MCP is an adapter, not the product |
| INV-009 | **Worlds are immutable, versioned historical artifacts** |
| INV-010 | World extension produces **patches, never silent mutation** |
| INV-011 | **REPLAY requires no real MCP credentials** |
| INV-012 | **RECORD / REPLAY / HYBRID semantics remain distinct**; HYBRID is forbidden in CI |
| INV-013 | **World Replay tests live agent decisions.** Trajectory Replay is diagnostic only |
| INV-014 | **L2-Core supports only its defined six-operation set** |
| INV-015 | Accepted ADRs change only through a **new superseding ADR**, never silently in code |
| INV-016 | Capability state gates authority: **PROPOSED never enables safety-sensitive assertions** |
| INV-017 | **No structurally unverified overlay state.** Entity construction must be validated against observed structure, or the engine diverges |

---

## Dependency boundaries

Enforced by CI lint. Violations fail the build.

```
domain/        depends on nothing
    ^
    |  (may be imported by all below; imports none of them)
    |
session/  world/  protocol/  compile/  replay/  assertions/  execution/
    ^
    |
integrations/  cli/     (may import everything)
```

Hard rules:

- `domain/` imports nothing from any other package in this repository.
- No MCP-specific identifier, type, or assumption appears outside `protocol/`. See [INV-008](docs/architecture/invariants.md#inv-008--protocol-neutrality).
- No vendor name appears in any identifier outside `protocol/` and `integrations/`.
- `replay/` never imports from `compile/`. Capability inference is a compile-time concern and must never influence the engine at runtime.

---

## Current scope: Milestone 0 only

Full specification: [docs/development/milestone-0.md](docs/development/milestone-0.md).

**M0 may build**, as throwaway code under `spike/`:

- Session Coordinator (loopback TCP, session state)
- stdio proxy
- Minimal world load/save and canonicalization
- World compiler with capability proposal
- Replay engine: matcher, contract check, overlay, merge, divergence
- Experiment driver
- `fixture_server/` (Server C), the only artifact intended to survive

**M0 must NOT build:**

Assertions, scenarios, verdicts, trajectories, pytest integration, CLI polish, packaging, `init`, parallel execution, HTTP or SSE transport, world patches or merge or migration, `WorldRef`, HYBRID safety machinery, cloud anything, performance optimization, error-message polish.

M0 does not modify `src/`. The existing `src/agent_test_kit/` package is the superseded implementation and remains untouched during M0.

---

## Navigation

Start at [docs/README.md](docs/README.md). It maps every recurring question to its canonical document.

Most frequently needed:

| Need | Document |
|---|---|
| What am I allowed to build right now | [current-phase.md](docs/development/current-phase.md) |
| How a session should proceed | [implementation-workflow.md](docs/development/implementation-workflow.md) |
| Hard rules I must not break | [invariants.md](docs/architecture/invariants.md) |
| Which component owns what | [architecture-map.md](docs/architecture/architecture-map.md) |
| What a term means | [glossary.md](docs/domain/glossary.md) |
| Requirement detail by ID | [functional-requirements.md](docs/requirements/functional-requirements.md) |

---

## Working rules

1. **Read [current-phase.md](docs/development/current-phase.md) before writing code.** It is the authority on scope.
2. **Do not redesign architecture during a coding task.** If implementation produces evidence contradicting an accepted ADR, stop and write up the evidence. See [implementation-workflow.md](docs/development/implementation-workflow.md).
3. **Do not add abstractions for later.** Only two public extension points exist: `AgentLauncher` and `SideEffectVerifier`. Everything else is internal and changeable.
4. **Do not implement future-phase requirements.** A requirement marked `v0.5` or `v1+` is out of scope until its phase is current.
5. **Never convert absence of evidence into a passing result.** This is INV-001 and it supersedes every other consideration.
6. Cite requirement IDs (`FR-xxx`, `NFR-xxx`) and invariant IDs (`INV-xxx`) in commit messages and pull requests.

---

## Repository status note

`src/agent_test_kit/` is the **superseded** implementation from the prior architecture. It is retained for code harvest, not extension. Approximately 900 lines will migrate (assertion engine core, verifier protocol, cleanup manager, redaction). See [important-files.md](docs/development/important-files.md).

`docs/AGENT_E2E_FULL_FLOW.md` documents the superseded client-based architecture and is **obsolete**. Do not follow it.
