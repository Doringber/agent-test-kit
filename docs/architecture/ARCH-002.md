# ARCH-002: System Architecture Specification

**Status:** Approved for implementation
**Date:** 2026-08-09
**Supersedes:** ARCH-001 (not retained; superseded in full)
**Remaining gate:** [Milestone 0.1](../development/milestone-0.1.md)

> **Amendment, 2026-08-09.** Milestone 0 returned GO and produced finding **F-1**.
> [ADR-006](adr/ADR-006-entity-construction-and-structural-fidelity.md) amends §3 (the
> fidelity contract) and §7 (provenance) of this document: entity construction now runs
> through a validated **Entity Construction Contract** rather than `body_request_path`,
> batch writes are excluded from L2-Core in v0.1, CONFIRMED requires structural validation,
> and entity-level provenance propagates through reads. ADR-006 governs where it and this
> document differ. The rest of ARCH-002 is unchanged.

> **Layer 3 document.** Deep reference. You should not need to read this on a routine implementation task. For daily work use [CLAUDE.md](../../CLAUDE.md), [current-phase.md](../development/current-phase.md), [invariants.md](invariants.md), and [architecture-map.md](architecture-map.md).

**One source of truth.** This document does not restate the four architecture decisions (see [adr/](adr/)), the requirement catalogs (see [requirements/](../requirements/)), the invariants (see [invariants.md](invariants.md)), the component map (see [architecture-map.md](architecture-map.md)), or the M0 spec (see [milestone-0.md](../development/milestone-0.md)). It specifies what those documents assume.

---

## 1. System context

**Enters the system:** a running agent process (any framework, any language) configured to reach its tools through us; MCP tool traffic over stdio; a scenario definition; configuration.

**Exits the system:** a World artifact; a Trajectory; a Verdict (PASS / FAIL / UNKNOWN); machine-readable JSON; a human summary; a process exit code.

**Ours:** recorder proxy, world compiler, replay engine, session coordinator, world maintenance, scenario runner, assertion engine, CLI, local artifact store.

**The user's:** the agent, prompts, model credentials, MCP server configuration, CI, repository, side-effect verifiers.

**Third-party, untrusted:** model providers, MCP servers.

Topology, trust boundaries B1 to B6, and mode lifecycles: [architecture-map.md](architecture-map.md).

### 1.1 The structural property everything depends on

The recorder and the replay engine occupy the **same position** in the topology. In RECORD the other side is a real server; in REPLAY it is a world file. One interception mechanism, one adapter, both modes.

**Any design that breaks this symmetry must be rejected.** See [ADR-002](adr/ADR-002-protocol-boundary-interception.md).

---

## 2. Product promise, stated normatively

> We construct a deterministic test world around **the subset of external behavior your agent depends on**, and we tell you explicitly, and always, when that world can no longer faithfully answer the agent.

Two binding consequences:

1. **We never claim to simulate a third-party service.** We claim to replay a declared subset. Every documentation, error-message, and marketing surface must be consistent with this.
2. **Divergence is a first-class domain object**, not an error path. It is the mechanism by which the promise is kept. A run producing divergences is a run working correctly.

---

## 3. The fidelity contract

Fidelity ladder, the six L2-Core operations, the complete predicate grammar, request parameter classification, and declared limitations: **[ADR-004](adr/ADR-004-l2-core-state-model.md)**.

The contract invariant, stated here because it governs the whole system:

> For any call falling inside a tool's declared fidelity contract, replay is correct.
> For any call falling outside it, replay emits a classified divergence and never fabricates a response.

Both halves are testable, and both are [Milestone 0](../development/milestone-0.md) exit criteria.

---

## 4. Execution modes

| | RECORD | REPLAY | HYBRID (Extend) |
|---|---|---|---|
| Tool traffic source | Real servers via recorder | Worlds only | Worlds, with allowlisted passthrough |
| MCP credentials | Required | **None** | Required |
| Real side effects | Yes | **None** | **Yes** |
| Produces | Session log to World | Trajectory to Verdict | Trajectory plus World patch proposal |
| Permitted in CI | No | **Yes, default** | **No, hard-blocked** |
| Assertions evaluated | No | Yes | Yes, trajectory marked non-baseline |

**REPLAY is the default and the safe mode.** Absence of credentials is the safety interlock: a misconfigured "replay" run that actually reaches a real server fails to authenticate rather than succeeding destructively.

**HYBRID safety** is specified by FR-140 to FR-146. The critical rule: HYBRID refuses to start when any CI environment marker is present, and **there is no override flag**. See [INV-012](invariants.md#inv-012--mode-separation-and-hybrid-is-forbidden-in-ci).

Mode lifecycles: [architecture-map.md](architecture-map.md#lifecycle-record).

---

## 5. Components

Full inventory, ownership, dependency rules, and state locations: **[architecture-map.md](architecture-map.md)**.

Eleven components in v0.1. Two require justification here because they were added in this revision.

### 5.1 C10 Session Coordinator

**Why it exists.** In stdio MCP the agent's client spawns one process per server. Those processes must share a monotonic sequence counter, a session identity, and in replay a single overlay and clock. ARCH-001 proposed an advisory file lock: non-deterministic under contention, awkward on Windows, untestable.

**Cardinality: one coordinator per execution.** N parallel executions means N coordinators. Sharing across executions interleaves sequence numbers non-deterministically and breaks [INV-007](invariants.md#inv-007--determinism-of-the-world).

**Transport:** loopback TCP with the port published in a session file. Chosen over Unix domain sockets for Windows portability without a second code path.

**The Replay Engine executes inside the coordinator process.** Per-server proxy endpoints are thin relays. This eliminates any possibility of overlay state diverging between servers.

**Note on IPC.** The prior requirement to use serialized IPC in order to preserve a future Go extraction is **removed**. The IPC here exists for a concrete, present reason: multiple OS processes must share session state.

### 5.2 C11 World Maintenance

Promoted from a v0.5 feature set to a v0.1 module, because [ADR-003](adr/ADR-003-replay-matching-and-divergence.md)'s strictness makes world evolution load-bearing rather than optional. A domain and application module inside the modular monolith, **not** a service and **not** a separate process.

| Operation | Contract |
|---|---|
| `validate` | Schema, hash, referential integrity, capability completeness, predicate well-formedness |
| `diff` | **Semantic**, not textual: tools, capabilities, interactions, entities, fidelity changes |
| `extend` | Patch from HYBRID observations. **Never mutates the input** |
| `merge` | Applies a reviewed patch; reports conflicts rather than resolving them |
| `inspect` | Tools by fidelity, capability states, coverage, data inventory |
| `fingerprint` | `tools_list_hash`, per-tool input schema hashes, server metadata hash |
| `check` | Drift against a live surface: unchanged / compatible / breaking / tool added / tool removed |
| `migrate` | Deterministic schema version upgrades |

Invariants: [INV-009](invariants.md#inv-009--worlds-are-immutable-historical-artifacts), [INV-010](invariants.md#inv-010--extension-produces-patches-never-silent-mutation).

---

## 6. Capability model

Three states and the confirmation workflow: **[ADR-004](adr/ADR-004-l2-core-state-model.md)**.

The burden target governs the design: **median at most 3 manual decisions per tool; a median above 5 is a redesign trigger for the capability model, not a user problem** (FR-160 to FR-162). The generated World may contain many more fields internally; those are derived, not authored.

Inference lives in `compile/` and is never imported by `replay/`, so it can improve over time without changing engine behavior (FR-165).

---

## 7. Provenance

Every replayed response carries provenance: `RECORDED`, `OVERLAY`, `SYNTHESIZED`, plus `stale_paths` for path-level staleness.

**Staleness detection, two mechanisms:**

1. **Declared.** A tool may declare `derived_paths`. If the overlay is dirty for that entity type, those paths are STALE.
2. **Heuristic sibling rule.** After a collection merge, any numeric or boolean scalar that is a sibling of the merged collection (`total`, `count`, `hasMore`, `nextCursor`) is STALE. Cheap, catches the dominant case, suppressible by declaration.

Undeclared derived fields elsewhere are a documented limitation and produce no divergence, because no claim is made about them.

Assertion degradation is scoped to **response-content** assertions only. Call-shape assertions are exempt. See [ADR-005](adr/ADR-005-evidence-semantics.md).

---

## 8. WorldRef

```
WorldRef := <scheme>://<locator>[@<version>]

v0.1 implemented:  file://worlds/pr-review-jira
                   file:///abs/path/world.yaml
v0.1 parsed, rejected with a specific message naming the scheme:
                   git://<repo>@<ref>:<path>
                   cloud://<project>/<world>/<version>
```

Scenarios reference a `WorldRef`, never a filesystem path (FR-150 to FR-154). The resolver is an **internal** interface, not a public extension point. Large worlds use a manifest plus sharded interaction files under a single reference; sharding is invisible to the reference.

---

## 9. Assertion set

Nine composable primitives replace the superseded 16-method API, plus the engine-level `evidence_sufficient` precondition, which is not an assertion.

**Canonical list, signatures, and the call-shape / response-content / safety-sensitive classification: [domain-model.md § Assertion](../domain/domain-model.md#assertion).** Semantics: [ADR-005](adr/ADR-005-evidence-semantics.md).

Declarative (YAML) assertion authoring is deferred until a second language binding is actually being written. The Python API will then become a thin builder over the declarative model, never a parallel implementation.

---

## 10. Technology

**Python 3.11+ for all components.** The prior requirement to design the engine boundary around a hypothetical Go extraction is removed. What remains is ordinary practice: clean module interfaces, pure domain models, no unnecessary coupling, benchmarks. Go is reconsidered only if profiling demonstrates an actual bottleneck, which model latency makes unlikely in World replay.

| Concern | Choice | Trade-off accepted |
|---|---|---|
| World serialization | YAML, safe loader, no custom tags | Slower parse, offset by a content-addressed binary index cache. Bought: reviewability |
| Trajectory serialization | JSON Lines | No comments. Bought: streaming writes, cheap appends, trivial multi-language parsing |
| Schema validation | pydantic v2, `extra="forbid"` on inputs, reserved namespaces preserved | Runtime cost |
| CLI | argparse or a thin typed wrapper | Fewer conveniences. Bought: near-zero startup, one fewer dependency on the untrusted-input path |
| Async | asyncio for proxy and runner; synchronous for compiler and assertions | Mixed model requires discipline |
| Local proxy | One process per MCP server, asyncio subprocess stdio relay | More processes. Bought: crash isolation and exact transparency |

---

## 11. Repository structure

```
src/agenttest/
  domain/      # + worldref.py provenance.py capability.py mode.py. Imports nothing.
  session/     # coordinator.py registry.py sequence.py ipc.py
  world/       # validate diff extend merge inspect fingerprint check migrate
  protocol/mcp/  # stdio.py only in v0.1
  recording/  compile/  replay/  assertions/  execution/
  verifiers/  artifacts/  redaction/  integrations/  cli/

spec/          # language-neutral format specifications, versioned
conformance/   # shared by every implementation and every OS
tests/         # unit/ property/ conformance/ integration/ determinism/ security/
```

Enforced dependency rule and migration mapping from the superseded package: [architecture-map.md](architecture-map.md) and [important-files.md](../development/important-files.md).

---

## 12. Milestone plan

| Milestone | Objective | Duration |
|---|---|---|
| **M0** | Prove the nine-step architectural loop. **Only remaining gate** | 2 weeks |
| M1 | L1 replay end to end with the Session Coordinator | 3 weeks |
| M2 | L2-Core with contract enforcement and provenance | 4 weeks |
| M2.5 | World Maintenance and the HYBRID extend loop | 2 weeks |
| M3 | Scenario runner, nine assertions, evidence semantics | 3 weeks |
| M4 | CI-ready developer experience including `init` | 3 weeks |

Approximately 17 weeks to v0.1. M0 is specified in [milestone-0.md](../development/milestone-0.md).

---

## 13. Accepted residual risk

The highest-risk code in the system is the collection merge function and the contract check preceding it. A narrow capability that fails **opaquely** outside its range is experienced by users as arbitrary, which damages adoption faster than an honest limitation does.

Mitigations, all already in the design: the contract check precedes the match; every out-of-contract call is classified; fidelity is assigned per tool so one unsupported tool does not disable a world; merge is the most heavily property-tested module.

**Measured in M0 as M1 (in-contract correctness) and M2 (out-of-contract fabrication rate).**
