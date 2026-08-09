# Architecture Invariants

Hard rules. Enforceable, testable, and non-negotiable within the current architecture.

An invariant is not a guideline. If code violates one, the code is wrong, regardless of how convenient it is. If an invariant is genuinely wrong, it changes through a superseding ADR, never through a code change.

---

## INV-001 — No false green

**Rule:** No code path may produce a PASS verdict in the absence of positive evidence. This requirement supersedes every other requirement in conflict with it.

**Reason:** A verification tool that reports PASS without evidence is worse than no tool, because it converts uncertainty into false confidence at scale.

**Violation example:** `assert_read_only()` returns PASS against a trajectory containing zero tool calls. This was empirically verified in the superseded `src/agent_test_kit/` implementation for three separate assertions.

**Related decision:** [ADR-005](adr/ADR-005-evidence-semantics.md)

---

## INV-002 — Absence of evidence is UNKNOWN

**Rule:** Empty trajectory, FATAL or ERROR divergence, timeout, crash, unparseable world, or a missing capability produces **UNKNOWN**, never PASS and never FAIL. UNKNOWN propagates upward through execution, scenario, and run, and is distinguishable at the process boundary (exit code 2).

**Reason:** "The agent misbehaved" and "we could not tell" require different engineering responses. Collapsing them destroys the signal.

**Violation example:** mapping a replay timeout to FAIL because it is "safer". It is not safer; it is a different wrong answer, and it trains users to ignore failures.

**Enforcement:** the `evidence_sufficient` precondition runs once in the assertion engine before any individual assertion executes. Individual assertions are not trusted to handle empty input.

**Related decision:** [ADR-005](adr/ADR-005-evidence-semantics.md)

---

## INV-003 — Fidelity contract

**Rule:** Only behavior **inside** a tool's declared fidelity contract receives a correctness guarantee. Every tool carries a computed fidelity level (`l1` or `l2_core`). A call outside that contract receives a classified divergence, never a response.

**Reason:** We do not simulate third-party services. We replay a declared subset. Bounding the claim is what makes the product predictable, and predictability is what makes it trustworthy.

**Violation example:** serving a plausible response for a `list` call containing a request parameter the predicate does not cover, on the grounds that the parameter "probably does not matter".

**Related decision:** [ADR-004](adr/ADR-004-l2-core-state-model.md)

---

## INV-004 — Never fabricate

**Rule:** The replay engine never synthesizes a response it cannot justify from a recording, the overlay, or a declared mutation template. No fuzzy matching. No nearest-neighbor. No "close enough".

**Reason:** A near-match served as an exact match is fabrication with extra steps, and it is precisely the failure this product exists to prevent.

**Violation example:** an incoming call differs from a recorded call by one argument, and the engine serves the recorded response anyway.

**Note:** synthesizing a write response from a *declared* mutation template is permitted and is tagged `SYNTHESIZED` provenance, which degrades dependent response-content assertions to UNKNOWN. That is justified construction, not fabrication.

**Related decision:** [ADR-003](adr/ADR-003-replay-matching-and-divergence.md)

---

## INV-005 — Divergence is first-class and always visible

**Rule:** Divergence is a domain object, not an error path. Every divergence is classified, recorded in the trajectory, surfaced in the human summary, and included in machine-readable output. No divergence at any severity may result in PASS for an assertion that depended on the diverged interaction.

**Reason:** Telling the user when we cannot answer *is* the product. A silently swallowed divergence converts the system from honest to dangerous in one line of code.

**Violation example:** catching a `NO_RECORDED_INTERACTION` divergence, logging it at debug level, and continuing.

**Related decision:** [ADR-003](adr/ADR-003-replay-matching-and-divergence.md)

---

## INV-006 — Per-execution state isolation

**Rule:** Overlay, virtual clock, id-minting counters, sequence counter, and divergence log are owned by exactly one Session Coordinator per **execution**, and are fully reset between executions. No state crosses an execution boundary.

**Reason:** N-run statistical execution requires independent samples. Shared state between executions silently correlates them and invalidates every distribution the product reports.

**Violation example:** sharing one coordinator across parallel executions to save process overhead. Sequence numbers interleave non-deterministically and INV-007 breaks.

**Related decision:** [ARCH-002 R.3.1](ARCH-002.md#r31-new-component-c10-session-coordinator)

---

## INV-007 — Determinism of the world

**Rule:** Given an identical world, an identical seed, and an identical sequence of agent tool calls, the replay engine returns byte-identical responses in an identical order, on any machine and any supported OS.

**Scope, stated precisely:** the **world** is deterministic. The **agent** is not. World replay drives a live model and therefore produces varying agent decisions; that is intended and is what makes it a test.

**Reason:** Without world determinism there is no baseline, no regression detection, and no reproducible debugging.

**Violation example:** iterating a hash map to build a merged collection, reading the wall clock, or using unseeded randomness anywhere in engine code. Any residual non-determinism inside the engine is a severity-one defect.

**Related decision:** [ARCH-002 §NFR-010 to NFR-016](../requirements/non-functional-requirements.md#determinism)

---

## INV-008 — Protocol neutrality

**Rule:** The `domain/` layer contains no MCP-specific identifier, type, or assumption. MCP is the first protocol adapter, not the product. The normalized `ToolInteraction` is the sole boundary type between protocol adapters and everything above them.

**Reason:** The superseded implementation coupled to one vendor's stdout format across 437 lines and to one organization's server inventory in its classification heuristics. That coupling is the specific failure this invariant prevents.

**Corollary:** if MCP later standardizes operation type, idempotency, or capability metadata, we consume it and reduce our declaration burden. This is a desirable outcome. **No design decision may be made whose purpose is to preserve the value of our declaration burden.**

**Violation example:** a field named `mcp_tool_name` in a domain dataclass. A JSON-RPC error code in a domain enum.

**Related decision:** [ADR-002](adr/ADR-002-protocol-boundary-interception.md)

---

## INV-009 — Worlds are immutable historical artifacts

**Rule:** A World records a specific version of an external world and remains replayable indefinitely. Service drift never invalidates a World. `world check` reports drift; it does not mutate or expire anything. Drift produces a **new** World version with `parent_hash` set.

**Reason:** Historical reproducibility is the basis of regression detection. A world that expires makes every prior trajectory unverifiable.

**Violation example:** `world check` marking a world "stale" and refusing to replay it.

---

## INV-010 — Extension produces patches, never silent mutation

**Rule:** World extension (HYBRID mode) emits a **patch proposal** to a separate path. A committed World is never mutated in place. Every extension produces a reviewable diff before anything is written.

**Reason:** A world is reviewed like code. Silent mutation makes review meaningless and makes divergence history unauditable.

**Violation example:** HYBRID mode appending newly observed interactions directly to `worlds/foo.yaml`.

**Related decision:** [ARCH-002 R.3.2](ARCH-002.md#r32-new-component-c11-world-maintenance)

---

## INV-011 — REPLAY carries no credentials

**Rule:** REPLAY mode requires zero MCP server credentials, and this is enforced rather than merely permitted.

**Reason:** This is a safety interlock, not a convenience. A misconfigured "replay" run that actually reaches a real server fails to authenticate rather than succeeding destructively. It is also what makes fork-PR CI viable.

**Violation example:** passing through the developer's environment to the replay proxy "so it works either way".

**Related threat:** [T5, T6](../security/threat-model.md)

---

## INV-012 — Mode separation, and HYBRID is forbidden in CI

**Rule:** RECORD, REPLAY, and HYBRID are mutually exclusive, explicit, and recorded in every trajectory. HYBRID requires two independent flags and **refuses to start when any CI environment marker is present. There is no override flag.**

**Reason:** HYBRID performs real writes against real systems. Accidental activation in an automated context is the single most damaging operational failure available to this product.

**Violation example:** adding `--force` to let HYBRID run in CI because a pipeline needed it. The correct response is that the pipeline must not need it.

**Related decision:** [ARCH-002 R.2](ARCH-002.md#r2-execution-modes)

---

## INV-013 — World Replay is the test mode

**Rule:** World Replay drives live agent decisions and is the mode used for behavioral testing. **Trajectory Replay is a diagnostic tool only** and must never be presented, defaulted to, or documented as a cheaper substitute for agent testing.

**Reason:** Replaying recorded agent decisions tests the replay engine, not the agent. Using it as a test mode would mean a prompt change is never actually exercised, which silently defeats the entire product.

**Violation example:** defaulting CI to trajectory replay to reduce model cost.

---

## INV-014 — L2-Core is exactly six operations

**Rule:** L2-Core supports create, update, delete, get-by-id, list-with-simple-predicate, and read-after-write within one session. There is no seventh operation. The predicate grammar is `field_equals`, `field_in`, `all_of`, `always`, and nothing else.

**Reason:** A bounded, declared capability is confirmable in three human answers and enforceable by the engine. An unbounded one is neither.

**Violation example:** adding range predicates because a customer's list endpoint filters on dates. The correct response is that such a call is out of contract and diverges.

**Related decision:** [ADR-004](adr/ADR-004-l2-core-state-model.md)

---

## INV-015 — Architecture governance

**Rule:** Accepted ADRs may only change through a new ADR carrying `Supersedes: ADR-XXX`. Architecture is never changed silently in code. The workflow is: observation, then evidence, then ADR amendment or superseding ADR, then implementation.

**Reason:** Decisions that can be reopened by any coding session are not decisions. Re-litigation consumes more engineering time than any implementation task.

**Violation example:** an implementation session concluding that fuzzy matching would be more convenient and adding it, with a comment explaining why.

**Related:** [adr/README.md](adr/README.md#governance)

---

## INV-016 — Capability state gates authority

**Rule:** Capability metadata has three states: CONFIRMED, PROPOSED, UNKNOWN. **PROPOSED and UNKNOWN never enable safety-sensitive assertions and never enable L2-Core.** Safety-sensitive assertions are exactly those reading `operation`: `operation_profile`, `unique_writes`, and any successor.

**Reason:** Inference is an accelerator, never authority. The superseded implementation inferred operation kind from tool names and was verified to classify `open_pull_request` as READ and `refund_payment` as UNKNOWN, allowing a double refund to pass a duplicate-write assertion.

**Violation example:** allowing a PROPOSED capability to satisfy `operation_profile` because inference "is usually right".

**Amended by ADR-006:** CONFIRMED now requires **both** a human answer **and** passing structural validation against observed data. A human answering the three questions is not, by itself, proof of entity semantics. A capability whose answers are complete but whose validation failed remains PROPOSED and therefore `l1`. The three states are unchanged.

**Related decision:** [ADR-004](adr/ADR-004-l2-core-state-model.md), [ADR-005](adr/ADR-005-evidence-semantics.md), [ADR-006](adr/ADR-006-entity-construction-and-structural-fidelity.md)

---

## INV-017 — No structurally unverified overlay state

**Rule:** A replay engine may expose overlay-derived entities as faithful external state **only** when their Entity Construction Contract has been validated against observed entity structure. Where that evidence does not exist, the engine must diverge or degrade. **No request-derived object may become authoritative entity state merely because a capability was CONFIRMED.**

Concretely:

1. Nothing structurally unverified ever enters the overlay.
2. A write whose entity cannot be faithfully constructed performs **no** overlay mutation. It serves an exact recorded response if one exists, otherwise refuses with `ENTITY_CONSTRUCTION_FAILED`.
3. Every entity carries provenance (`RECORDED_ENTITY` or `SYNTHESIZED_ENTITY`), and a response containing a synthesized entity reports it via `synthesized_entity_ids`, which **no downstream read may clear**.

**Reason:** Milestone 0 measured the failure this prevents. Against a real third-party MCP server, an L2-Core create built the overlay entity from the request envelope. A later read served that malformed entity with `served=True`, `divergence=None`, and ordinary `overlay` provenance. Every mechanical rule was followed and the result was still fabricated state presented as faithful.

**Why INV-004 was not enough:** the engine synthesized from a *declared* mutation template, which INV-004 permits. The declaration itself was never checked against reality. INV-017 closes that gap.

**Violation example:** constructing an overlay entity from `body_request_path` without a validated template, then merging it into a collection read and reporting `provenance=overlay` with no indication that the entity was synthesized.

**Second violation example:** downgrading a tool from `l2_core` to `l1` at runtime after a construction failure. Fidelity is a compile-time property; changing it mid-session makes replay depend on execution history and breaks [INV-007](#inv-007--determinism-of-the-world).

**Related decision:** [ADR-006](adr/ADR-006-entity-construction-and-structural-fidelity.md)

---

## Enforcement summary

| Invariant | Enforced by |
|---|---|
| INV-001, INV-002, INV-016 | Adversarial evidence test suite. Release-blocking |
| INV-003, INV-004, INV-014 | Conformance test suite. Release-blocking |
| **INV-017** | **Structural fidelity suite (compiler validations V1-V6 + runtime refusal). Release-blocking** |
| INV-005 | Conformance suite plus divergence classification tests |
| INV-006, INV-007 | Determinism test suite, multi-OS. Release-blocking |
| INV-008 | CI import lint over `domain/` |
| INV-009, INV-010 | World Maintenance unit tests |
| INV-011, INV-012 | Mode integration tests plus CI-marker refusal test |
| INV-013 | Documentation and code review |
| INV-015 | Code review and this document |

See [testing-strategy.md](../testing/testing-strategy.md) for the test classes referenced above.
