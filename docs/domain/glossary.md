# Glossary

Canonical meanings. **This document exists to prevent terminology drift.** If a term is used in code, docs, or a commit message with a meaning different from the one here, either the usage is wrong or this document needs a deliberate update. Not both silently.

---

## Overloaded terms, disambiguated first

Three distinct things are called **UNKNOWN**. Never use the bare word in code or documentation; always qualify.

| Qualified term | Type | Meaning |
|---|---|---|
| **Verdict UNKNOWN** | `AssertionOutcome.state`, `Execution.verdict` | Insufficient evidence to decide. Exit code 2. See [ADR-005](../architecture/adr/ADR-005-evidence-semantics.md) |
| **CapabilityState UNKNOWN** | `ToolCapability.state` | The capability could not be inferred and was not confirmed. Tool serves L1 only, safety-sensitive assertions become **Verdict UNKNOWN** |
| **Operation UNKNOWN** | `ToolCapability.operation` | The tool's read/write nature is undeclared. **Treated as write-equivalent for all safety semantics** (FR-023) |

Two distinct things are called **Replay**:

| Qualified term | Meaning |
|---|---|
| **World Replay** | Live agent decisions against a replayed world. **The test mode** |
| **Trajectory Replay** | Recorded agent decisions and recorded world. **Diagnostic only** |

Two distinct things are called **Provenance** (ADR-006):

| Qualified term | Applies to | Values |
|---|---|---|
| **Response provenance** | A whole tool response | `RECORDED`, `OVERLAY`, `SYNTHESIZED` |
| **Entity provenance** | One entity in the overlay | `RECORDED_ENTITY`, `SYNTHESIZED_ENTITY` |

A response may be `OVERLAY` while containing entities of mixed entity provenance. That is exactly why `synthesized_entity_ids` exists.

Two distinct things are called **Overlay**:

| Qualified term | Meaning |
|---|---|
| **The Overlay** (component) | The per-session entity store owned by a `ReplaySession` |
| **OVERLAY** (provenance tag) | A response constructed from overlay state |

---

## A to Z

**Agent.** The system under test. A process that makes decisions using a model and acts on the world through tools. We do not run it in production; we launch it during an execution.

**Assertion.** A declarative behavioral expectation evaluated against a trajectory. Nine primitives exist. Produces an `AssertionOutcome` with a three-valued state.

**Call-shape assertion.** An assertion evaluating *what the agent did*: `called`, `sequence`, `ordered`, `attempts_within`, `workflow_size`, `operation_profile`, `unique_writes`. **Exempt from provenance degradation** (FR-172).

**Canonicalization.** The deterministic transformation applied to request arguments before matching: sort keys, normalize numerics, drop volatile paths, substitute minted ids, NFC-normalize Unicode. Specified in [ADR-003](../architecture/adr/ADR-003-replay-matching-and-divergence.md).

**Capability.** See `ToolCapability` in [domain-model.md](domain-model.md#toolcapability). The declared semantics of a tool.

**CONFIRMED.** A capability state. **A human answered the capability questions AND structural validation passed against observed data** (ADR-006). Human answers establish intent; observed data establishes shape. Neither alone suffices. The only state that enables L2-Core and safety-sensitive assertions.

**Contract.** The declared fidelity guarantee for a tool: which calls the engine promises to answer correctly. Not a legal term and not an interface in the OOP sense.

**Divergence.** A classified point at which the replayed world could not faithfully answer the agent. **A first-class domain object, never an error path.**

**Entity.** A stateful object in the simulated world, identified by `(entity_type, entity_id)`. Carries entity provenance.

**Entity Construction Contract (ECC).** The minimum information required to turn a write request into faithful overlay state: template, required fields, bindings, generated fields, constant defaults, cardinality. Its authority is **observed data**, not human declaration. Replaces `body_request_path`. See [ADR-006](../architecture/adr/ADR-006-entity-construction-and-structural-fidelity.md).

**ENTITY_CONSTRUCTION_FAILED.** Divergence class, severity ERROR. Raised when an L2-Core write cannot construct its entity faithfully and no exact recorded response exists. **No overlay mutation occurs.**

**Entity template.** The authoritative key set of an entity type, derived from observed entities. The thing a synthesized entity must match.

**Execution.** One run of one scenario. The unit of isolation. One `ReplaySession` and one `Session Coordinator` per execution.

**FAIL.** A verdict state. **Positive evidence that an expectation was violated.** Not the same as UNKNOWN.

**Fidelity.** The replay guarantee level assigned to a tool: `l1` or `l2_core`. Computed at compile time, enforced by the engine, assigned **per tool**.

**HYBRID.** An execution mode. Worlds plus allowlisted passthrough to real servers. Performs **real side effects**. Requires two flags, is hard-blocked in CI with no override, and produces a World patch proposal rather than mutating a world.

**In-contract.** A call falling inside a tool's declared fidelity contract. **Receives a correctness guarantee.**

**Interaction.** One recorded request/response pair inside a world. Distinct from `ToolInteraction`, which is the runtime observation.

**L1.** Fidelity level. Replay of exactly recorded request/response pairs, matched on canonical arguments. The default for every tool.

**L2-Core.** Fidelity level. Declared entity state transitions over **exactly six operations**: create, update, delete, get-by-id, list-with-simple-predicate, and read-after-write within a session. There is no seventh. See [ADR-004](../architecture/adr/ADR-004-l2-core-state-model.md).

**L2-Extended.** Reserved fidelity level for future service-specific semantics. **Not implemented.** Schema namespace only.

**L3.** General semantic simulation of arbitrary services. **Permanently out of scope.** Do not use this term except to say we do not do it.

**Out-of-contract.** A call falling outside a tool's declared fidelity contract. **Receives a classified divergence and no response.** Never fabricated.

**OVERLAY** (provenance). A response constructed from overlay state, typically a merge of a recorded collection with overlay entities.

**PASS.** A verdict state. **Positive evidence that an expectation held.** Never produced in the absence of evidence ([INV-001](../architecture/invariants.md#inv-001--no-false-green)).

**PROPOSED.** A capability state covering two cases: the compiler inferred it and no human confirmed it, **or** a human answered but structural validation failed (a `validation` record names the failed check). Serves L1 replay. **Never enables L2-Core and never enables safety-sensitive assertions.**

**Provenance.** The origin of a replayed response: RECORDED, OVERLAY, or SYNTHESIZED, plus `stale_paths`.

**RECORD.** An execution mode. All configured servers are live through the recorder. Requires credentials. Produces a session log, then a World.

**RECORDED** (response provenance). A response served verbatim from a recorded interaction.

**RECORDED_ENTITY** (entity provenance). An entity that came from observed data.

**SYNTHESIZED_ENTITY** (entity provenance). An entity whose **current state** contains replay-synthesized data: either constructed through a validated ECC from an unrecorded request, or a recorded entity modified by an unrecorded replay write. Always validated; there is no unvalidated variant, because [INV-017](../architecture/invariants.md#inv-017--no-structurally-unverified-overlay-state) forbids one existing. **Monotonic within a session:** once synthesized, an entity never returns to `RECORDED_ENTITY` until `reset()`.

**`synthesized_entity_ids`.** The ids of synthesized entities present in a response. **Never cleared by a downstream read.** Its presence degrades response-content assertions to Verdict UNKNOWN.

**Structural validation (V1-V6).** The six compiler checks a tool must pass before it may be assigned `l2_core`. V5, the round-trip check, is decisive.

**Recording.** The act of capturing real tool traffic, and the session log it produces. A recording is compiled into a World; it is not itself a World.

**REPLAY.** An execution mode. **The default and the safe mode.** Worlds only, no credentials, no network to MCP servers, no side effects. The default mode in CI.

**Replay match rate.** The fraction of tool calls served from the world without an ERROR or FATAL divergence. **The primary product health metric** (NFR-092), visible to users on every run.

**ReplaySession.** The lifetime of the replay engine for one execution. Owns overlay, clock, id counters, sequence, divergence log.

**Response-content assertion.** An assertion evaluating *what a tool returned*. **Degraded to Verdict UNKNOWN** by SYNTHESIZED provenance or a touched STALE path.

**Safety-sensitive assertion.** An assertion reading `operation`: `operation_profile`, `unique_writes`, and any successor. Requires a CONFIRMED capability, otherwise yields Verdict UNKNOWN.

**Scenario.** A named test unit: input, `WorldRef`, assertions, verifiers, run count, timeout, strictness.

**Session Coordinator.** The process owning all per-execution state. **One per execution.** Hosts the replay engine. Not a domain object; a component.

**STALE.** A path-level provenance marker. A recorded value that a mutation may have invalidated and that we cannot recompute. Degrades response-content assertions touching that path.

**SYNTHESIZED.** A provenance tag. A response constructed from a **declared** mutation template because no recording covered the call. Justified construction, not fabrication. Degrades response-content assertions.

**Tool.** A named capability an agent can invoke against an external system. In v0.1 always an MCP tool, but the domain layer must not assume it.

**ToolInteraction.** The normalized, protocol-neutral runtime record of one tool invocation and its result. **The sole boundary type between protocol adapters and everything above.** Contains no MCP-specific fields.

**Trajectory.** The complete evidence of one execution. Immutable. **The primary evidence object of the system.**

**Trajectory Replay.** Replaying both recorded world responses and recorded agent decisions, with zero model calls. **Diagnostic only.** Never a substitute for agent testing ([INV-013](../architecture/invariants.md#inv-013--world-replay-is-the-test-mode)).

**Verdict.** The three-valued result of an assertion, execution, scenario, or run: PASS, FAIL, or **Verdict UNKNOWN**.

**World.** A portable, versioned, **immutable** record of a subset of an external environment. The central artifact of the system.

**World Extend Mode.** Synonym for HYBRID when discussed from the World Maintenance perspective. Prefer **HYBRID** when discussing execution and **extend** when discussing the world operation.

**World Replay.** Replaying the world while the agent makes **live decisions** via a model. **The test mode.** The only mode that detects behavioral regressions.

**WorldRef.** A location-independent reference to a world. Scenarios reference this, never a filesystem path.

---

## Terms we do not use

| Avoid | Use instead | Why |
|---|---|---|
| "Mock" / "stub" | World, replay | Implies static fixtures, which is the thing we are not |
| "Simulate Jira" | Replay a declared subset | We do not simulate services. See [INV-003](../architecture/invariants.md#inv-003--fidelity-contract) |
| "Cassette" | World | Cassettes are stateless; worlds are not |
| "Eval" / "score" | Assertion, verdict | Different category. See [CLAUDE.md](../../CLAUDE.md#what-we-are-not-building) |
| "Sandbox" (for worlds) | Deterministic world | "Sandbox" implies isolation of the agent, which is the user's responsibility (NFR-050) |
| "Fail" (for missing evidence) | UNKNOWN | The distinction is the product |
