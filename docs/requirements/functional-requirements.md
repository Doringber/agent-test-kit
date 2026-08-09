# Functional Requirements

Canonical catalog. IDs are stable and **never reused**. Extracted from ARCH-002; no requirement here is new.

**Status values:** `Not implemented` | `M0 spike only` | `In progress` | `Implemented` | `Deferred`

As of 2026-08-09 every requirement is `Not implemented`. Milestone 0 builds throwaway spike code only and does not change any status; requirements exercised by the spike are marked `M0 spike only` in the Status column, which explicitly does **not** mean implemented.

**Priority:** MUST / SHOULD / COULD. **Phase:** v0.1 / v0.5 / v1+.

---

## Recording (FR-001 to FR-014)

Owner: **C3 Recorder Proxy**, **C4 Protocol Adapter**. Decision: [ADR-002](../architecture/adr/ADR-002-protocol-boundary-interception.md).

| ID | Requirement | Pri | Phase | Verification | Status |
|---|---|---|---|---|---|
| FR-001 | Intercept MCP JSON-RPC over stdio by spawning the real server as a child process | MUST | v0.1 | Integration | M0 spike only |
| FR-002 | Intercept MCP over HTTP and SSE via reverse proxy | MUST | **v0.5** | Integration | Deferred |
| FR-003 | Capture request, response, tool name, server id, monotonic sequence for every `tools/call` | MUST | v0.1 | Integration | M0 spike only |
| FR-004 | Capture `tools/list` responses as tool metadata including declared schemas | MUST | v0.1 | Integration | M0 spike only |
| FR-005 | Preserve total order via a single monotonic counter owned by the Session Coordinator | MUST | v0.1 | Determinism | M0 spike only |
| FR-006 | Record errors as first-class interactions with a typed failure class | MUST | v0.1 | Unit + integration | Not implemented |
| FR-007 | Record timing without making replay depend on it | MUST | v0.1 | Determinism | Not implemented |
| FR-008 | Redact secrets **before** any bytes are persisted, never after | MUST | v0.1 | Security | Not implemented |
| FR-009 | Fail the recording session if redaction cannot be applied | MUST | v0.1 | Security | Not implemented |
| FR-010 | Emit a World artifact from a completed recording session | MUST | v0.1 | Integration | M0 spike only |
| FR-011 | Detect and annotate retries (identical canonical arguments within a session) | SHOULD | v0.1 | Unit | Not implemented |
| FR-012 | Record streaming responses by materializing whole, retaining chunk boundaries | SHOULD | v0.1 | Integration | Not implemented |
| FR-013 | **Support appending to an existing world (incremental re-record)** | **MUST** | **v0.1** | Integration | Not implemented |
| FR-014 | Record MCP resources and prompts primitives, not only tools | COULD | v1+ | Integration | Deferred |

> FR-013 was promoted from SHOULD/v0.5. World rot is the primary retention risk; see [ADR-003](../architecture/adr/ADR-003-replay-matching-and-divergence.md) consequences.

---

## World Model (FR-020 to FR-034)

Owner: **C5 World Compiler**, **domain/**. Decision: [ADR-004](../architecture/adr/ADR-004-l2-core-state-model.md).

| ID | Requirement | Pri | Phase | Verification | Status |
|---|---|---|---|---|---|
| FR-020 | World is a single text artifact with an explicit `world_version` schema field | MUST | v0.1 | Unit | M0 spike only |
| FR-021 | Refuse to load a world whose schema version is newer than the engine | MUST | v0.1 | Unit | Not implemented |
| FR-022 | World declares per tool: server, name, operation kind, idempotency | MUST | v0.1 | Unit | M0 spike only |
| FR-023 | Unknown operation kind is legal and is **write-equivalent for all safety semantics** | MUST | v0.1 | Adversarial evidence | Not implemented |
| FR-024 | World declares an entity type per tool where state semantics apply | MUST | v0.1 | Unit | M0 spike only |
| FR-025 | Write tools declare mutation kind, id response path, body request path | MUST | v0.1 | Unit | M0 spike only |
| FR-026 | Read tools declare collection-returning, collection path, request selector | MUST | v0.1 | Unit | M0 spike only |
| FR-027 | Recorded interactions carry canonical, sorted arguments | MUST | v0.1 | Property | M0 spike only |
| FR-028 | World carries an initial entity set extracted from recorded reads | MUST | v0.1 | Unit | M0 spike only |
| FR-029 | World declares a virtual clock epoch and tick policy | MUST | v0.1 | Determinism | M0 spike only |
| FR-030 | World declares deterministic id-minting rules per entity type | MUST | v0.1 | Determinism | M0 spike only |
| FR-031 | Compiler proposes state semantics but **never applies them silently**; unconfirmed pins the tool to L1 | MUST | v0.1 | Unit | M0 spike only |
| FR-032 | World produces a legible line-oriented diff under standard git tooling | MUST | v0.1 | Manual review | Not implemented |
| FR-033 | World declares volatile fields excluded from canonicalization | MUST | v0.1 | Property | M0 spike only |
| FR-034 | Declared relationships between entity types | COULD | v1+ | Unit | Deferred |

---

## Replay (FR-040 to FR-056)

Owner: **C6 Replay Engine** (inside C10). Decisions: [ADR-003](../architecture/adr/ADR-003-replay-matching-and-divergence.md), [ADR-004](../architecture/adr/ADR-004-l2-core-state-model.md).

| ID | Requirement | Pri | Phase | Verification | Status |
|---|---|---|---|---|---|
| FR-040 | Serve a recorded response on exact match of (server, tool, canonical arguments) | MUST | v0.1 | Conformance | M0 spike only |
| FR-041 | Maintain a per-session overlay initialized from the world's entity set | MUST | v0.1 | Property | M0 spike only |
| FR-042 | Apply declared mutations to the overlay on every write tool call | MUST | v0.1 | Property | M0 spike only |
| FR-043 | Merge overlay entities into recorded reads, **collection reads with declared selectors only** | MUST | v0.1 | Property + conformance | M0 spike only |
| FR-044 | Non-collection read with dirty overlay and undeclared merge: return recorded, raise WARN | MUST | v0.1 | Conformance | Not implemented |
| FR-045 | Reset the overlay to the world's initial entity set between executions | MUST | v0.1 | Property (isolation) | M0 spike only |
| FR-046 | Mint entity ids deterministically from (seed, entity type, canonical args, mutation seq) | MUST | v0.1 | Determinism | M0 spike only |
| FR-047 | Serve time-derived values from a virtual clock advanced by a fixed tick | MUST | v0.1 | Determinism | M0 spike only |
| FR-048 | Detect divergence and classify by severity | MUST | v0.1 | Conformance | M0 spike only |
| FR-049 | **Never fabricate a response**; raise divergence and return UNKNOWN for the execution | MUST | v0.1 | Conformance (release-blocking) | M0 spike only |
| FR-050 | Strictness policy `strict` / `standard` / `lenient`; **none may convert divergence to PASS** | MUST | v0.1 | Adversarial evidence | Not implemented |
| FR-051 | Repeated identical writes observable as distinct mutations, not collapsed | MUST | v0.1 | Property | Not implemented |
| FR-052 | Declared idempotency keys: same key returns the original result without a second mutation | SHOULD | v0.5 | Property | Deferred |
| FR-053 | Failure injection: force a declared tool to return a specified error on the Nth call | SHOULD | v0.5 | Conformance | Deferred |
| FR-054 | **Trajectory replay mode** (zero model calls). **Diagnostic only, never a CI strategy** | SHOULD | v0.5 | Determinism | Deferred |
| FR-055 | Paginated reads served from recording only; WARN if the overlay would have changed the set | MUST | v0.1 | Conformance | Not implemented |
| FR-056 | Concurrent tool calls serialized at the engine; serialization order recorded | MUST | v0.1 | Determinism | Not implemented |

---

## Test Execution (FR-060 to FR-072)

Owner: **C7 Scenario Runner**.

| ID | Requirement | Pri | Phase | Verification | Status |
|---|---|---|---|---|---|
| FR-060 | A scenario binds input, world reference, assertions, optional verifiers | MUST | v0.1 | Unit | Not implemented |
| FR-061 | Execute N times with per-execution isolation of overlay, clock, id sequence | MUST | v0.1 | Property (isolation) | Not implemented |
| FR-062 | Aggregate N executions into a **distribution** verdict, not a boolean | MUST | v0.1 | Unit | Not implemented |
| FR-063 | Accept a run seed determining world behavior, never model behavior | MUST | v0.1 | Determinism | Not implemented |
| FR-064 | Per-execution timeout with a distinct TIMEOUT outcome, **never mapped to FAIL** | MUST | v0.1 | Adversarial evidence | Not implemented |
| FR-065 | Cancellation terminates the agent, drains the session, still emits a partial trajectory | MUST | v0.1 | Integration | Not implemented |
| FR-066 | Run cleanup after every execution regardless of outcome, including cancellation | MUST | v0.1 | Unit | Not implemented |
| FR-067 | Parallel local execution across executions of one scenario | MUST | v0.1 | Integration | Not implemented |
| FR-068 | Parallel execution across scenarios | SHOULD | v0.5 | Integration | Deferred |
| FR-069 | Run side-effect verifiers concurrently, failure-isolated, individually timed out | MUST | v0.1 | Unit | Not implemented |
| FR-070 | Retry only on infrastructural failure, **never on behavioral failure** | MUST | v0.1 | Unit | Not implemented |
| FR-071 | Scenario tags and selection expressions | SHOULD | v0.5 | Unit | Deferred |
| FR-072 | Declarative scenario format equivalent in power to the programmatic API | SHOULD | v0.5 | Conformance | Deferred |

---

## Results (FR-080 to FR-090)

Owner: **C8 Assertion Engine**, **C9 Artifact Store**. Decision: [ADR-005](../architecture/adr/ADR-005-evidence-semantics.md).

| ID | Requirement | Pri | Phase | Verification | Status |
|---|---|---|---|---|---|
| FR-080 | Capture full trajectory: tool calls, mutations, divergences, ordering | MUST | v0.1 | Integration | Not implemented |
| FR-081 | Capture every assertion outcome, on pass **and** on fail | MUST | v0.1 | Unit | Not implemented |
| FR-082 | Assertion outcomes are three-state: PASS / FAIL / **UNKNOWN** | MUST | v0.1 | Adversarial evidence (release-blocking) | Not implemented |
| FR-083 | Capture state mutations as a list distinct from tool calls | MUST | v0.1 | Unit | Not implemented |
| FR-084 | Capture verifier outcomes with evidence and evidence links | MUST | v0.1 | Unit | Not implemented |
| FR-085 | Capture token usage and cost when reported; **mark unavailable when not.** Never impute | SHOULD | v0.1 | Unit | Not implemented |
| FR-086 | Capture latency per tool call and per execution | SHOULD | v0.1 | Unit | Not implemented |
| FR-087 | Emit an execution verdict and a scenario verdict under a declared policy | MUST | v0.1 | Unit | Not implemented |
| FR-088 | All persisted results pass through redaction | MUST | v0.1 | Security | Not implemented |
| FR-089 | Trajectory schema versioned independently of the world schema | MUST | v0.1 | Unit | Not implemented |
| FR-090 | Trajectories content-addressable by hash | SHOULD | v0.5 | Unit | Deferred |

---

## CI Integration (FR-100 to FR-109)

Owner: **C1 CLI**, **integrations/**.

| ID | Requirement | Pri | Phase | Verification | Status |
|---|---|---|---|---|---|
| FR-100 | Single CLI entry point: `record`, `run`, `replay`, `world`, `init` | MUST | v0.1 | Integration | Not implemented |
| FR-101 | Exit codes 0 PASS, 1 FAIL, **2 UNKNOWN**, 3 usage, 4 internal | MUST | v0.1 | Integration | Not implemented |
| FR-102 | Machine-readable JSON output, schema-versioned | MUST | v0.1 | Unit | Not implemented |
| FR-103 | Human summary with a divergence section that is impossible to miss | MUST | v0.1 | Manual review | Not implemented |
| FR-104 | **Zero network access in replay mode** except to the model provider | MUST | v0.1 | Security | Not implemented |
| FR-105 | Content-addressed cache of parsed worlds keyed by file hash | SHOULD | v0.1 | Unit | Not implemented |
| FR-106 | pytest integration preserving the two-stage plugin registration pattern | SHOULD | v0.1 | Integration | Not implemented |
| FR-107 | Generic CI support; a GitHub Action as a thin convenience only | SHOULD | v0.5 | Integration | Deferred |
| FR-108 | PR comment rendering of a behavioral diff | SHOULD | v0.5 | Manual review | Deferred |
| FR-109 | Parallel-safe local execution with per-worker artifact isolation and a merge step | MUST | v0.1 | Integration | Not implemented |

---

## HYBRID mode safety (FR-140 to FR-146)

Owner: **C1 CLI**, **C7 Scenario Runner**. Invariant: [INV-012](../architecture/invariants.md#inv-012--mode-separation-and-hybrid-is-forbidden-in-ci).

| ID | Requirement | Pri | Phase | Verification | Status |
|---|---|---|---|---|---|
| FR-140 | HYBRID requires `--mode hybrid` **and** `--allow-real-side-effects`. Neither alone suffices | MUST | v0.1 | Integration | Not implemented |
| FR-141 | HYBRID refuses to start when any CI marker is set. **There is no override flag** | MUST | v0.1 | Integration (release-blocking) | Not implemented |
| FR-142 | HYBRID prints a persistent banner naming every passthrough-eligible server and tool | MUST | v0.1 | Manual review | Not implemented |
| FR-143 | Passthrough is allowlisted per (server, tool); non-allowlisted diverges | MUST | v0.1 | Integration | Not implemented |
| FR-144 | Write-tool passthrough requires a separate `--allow-write-passthrough` allowlist | MUST | v0.1 | Integration | Not implemented |
| FR-145 | HYBRID trajectories carry `mode: hybrid` and are rejected as regression baselines | MUST | v0.1 | Unit | Not implemented |
| FR-146 | HYBRID **never mutates a World**; it emits a patch proposal to a separate path | MUST | v0.1 | Unit | Not implemented |

---

## WorldRef (FR-150 to FR-154)

Owner: **domain/**, **C9 Artifact Store**.

| ID | Requirement | Pri | Phase | Verification | Status |
|---|---|---|---|---|---|
| FR-150 | `WorldRef` is a domain value object with parse, validate, render | MUST | v0.1 | Unit | Not implemented |
| FR-151 | A resolver interface maps `WorldRef` to a loaded World; one implementation (`file`) in v0.1 | MUST | v0.1 | Unit | Not implemented |
| FR-152 | Unimplemented schemes produce a specific error naming the scheme | MUST | v0.1 | Unit | Not implemented |
| FR-153 | The resolver is an **internal** interface, not a public extension point | MUST | v0.1 | Code review | Not implemented |
| FR-154 | Trajectories record the resolved `WorldRef` **and** the world `content_hash` | MUST | v0.1 | Unit | Not implemented |

---

## Capability confirmation (FR-160 to FR-165)

Owner: **C5 World Compiler**. Decision: [ADR-004](../architecture/adr/ADR-004-l2-core-state-model.md).

| ID | Requirement | Pri | Phase | Verification | Status |
|---|---|---|---|---|---|
| FR-160 | Median manual decisions per tool **at most 3**, measured and reported | MUST | v0.1 | M0 measurement M4 | M0 spike only |
| FR-161 | Compiler emits `manual_decision_count` per tool and a session median | MUST | v0.1 | Unit | M0 spike only |
| FR-162 | More than 5 manual decisions emits a design warning. **A median above 5 is a redesign trigger** | MUST | v0.1 | M0 measurement M4 | M0 spike only |
| FR-163 | A tool may be pinned to L1 with a single answer; always the cheapest path | MUST | v0.1 | Unit | M0 spike only |
| FR-164 | Confirmation interactive by default, scriptable via an answers file | SHOULD | v0.1 | Integration | Not implemented |
| FR-165 | Inference lives in `compile/`, **never imported by `replay/`** | MUST | v0.1 | CI import lint | Not implemented |

---

## Provenance (FR-170 to FR-173)

Owner: **C6 Replay Engine**, **C8 Assertion Engine**. Decision: [ADR-005](../architecture/adr/ADR-005-evidence-semantics.md).

| ID | Requirement | Pri | Phase | Verification | Status |
|---|---|---|---|---|---|
| FR-170 | Every ToolCall records `provenance` and `stale_paths` | MUST | v0.1 | Unit | M0 spike only |
| FR-171 | An assertion consuming SYNTHESIZED provenance or a STALE path yields UNKNOWN | MUST | v0.1 | Adversarial evidence | Not implemented |
| FR-172 | **Call-shape assertions are exempt** from provenance degradation | MUST | v0.1 | Adversarial evidence | Not implemented |
| FR-173 | Human summary reports provenance distribution across the run | SHOULD | v0.1 | Manual review | Not implemented |

---

## Session, config, world maintenance, privacy (FR-180 to FR-194)

| ID | Requirement | Owner | Pri | Phase | Verification | Status |
|---|---|---|---|---|---|---|
| FR-180 | Session Coordinator owns sequence, clock, minting, overlay; **one per execution** | C10 | MUST | v0.1 | Determinism | M0 spike only |
| FR-181 | Proxies register with the coordinator and **fail closed** on loss of connection | C3, C10 | MUST | v0.1 | Integration | M0 spike only |
| FR-182 | `agent-test init` discovers configured MCP servers and generates the test config | C1 | MUST | v0.1 | Integration | Not implemented |
| FR-183 | A documented manual wrapper exists where discovery is impossible | C1 | MUST | v0.1 | Manual review | Not implemented |
| FR-184 | `world validate` / `diff` / `inspect` / `check` / `extend` / `merge` | C11 | MUST | v0.1 | Unit | Not implemented |
| FR-185 | Extension produces a patch and a reviewable diff; **committed worlds never silently mutated** | C11 | MUST | v0.1 | Unit | Not implemented |
| FR-186 | Worlds record `tools_list_hash`, per-tool schema hashes, server fingerprint | C5, C11 | MUST | v0.1 | Unit | M0 spike only |
| FR-187 | `world check` classifies drift and **never invalidates a world** | C11 | MUST | v0.1 | Unit | Not implemented |
| FR-188 | Each tool carries a computed `fidelity`; the engine enforces it | C5, C6 | MUST | v0.1 | Conformance | M0 spike only |
| FR-189 | Out-of-contract calls produce divergence and **no fabricated response** | C6 | MUST | v0.1 | Conformance (release-blocking) | M0 spike only |
| FR-190 | Request params classified predicate-bound / ignored / pagination / **unrecognized** | C5, C6 | MUST | v0.1 | Conformance | M0 spike only |
| FR-191 | After compilation, state that the world contains production-shaped data and require an explicit user decision before offering commit guidance | C1 | MUST | v0.1 | Manual review | Not implemented |
| FR-192 | **No component emits telemetry. None** | all | MUST | v0.1 | Security + code review | Not implemented |
| FR-193 | Optional encrypted local world storage | C9 | SHOULD | v0.1 | Security | Not implemented |
| FR-194 | `init` proposes a `.gitignore` entry for worlds by default; committing is opt-in | C1 | MUST | v0.1 | Integration | Not implemented |

---

## Entity construction and structural fidelity (FR-200 to FR-213)

Owner: **C5 World Compiler**, **C6 Replay Engine**, **C8 Assertion Engine**.
Decision: [ADR-006](../architecture/adr/ADR-006-entity-construction-and-structural-fidelity.md).
Invariant: [INV-017](../architecture/invariants.md#inv-017--no-structurally-unverified-overlay-state).
Evidence: Milestone 0 finding F-1.

| ID | Requirement | Pri | Phase | Verification | Status |
|---|---|---|---|---|---|
| FR-200 | An L2-Core write tool declares an **Entity Construction Contract**: `entity_template`, `required_fields`, `field_bindings`, `generated_fields`, `constant_defaults`, `cardinality` | MUST | v0.1 | Unit | Not implemented |
| FR-201 | `body_request_path` is **retired** as the sole basis for entity construction | MUST | v0.1 | Code review | Not implemented |
| FR-202 | The entity template is derived from **observed** data: recorded create responses first, recorded collection rows second | MUST | v0.1 | Unit | Not implemented |
| FR-203 | Field bindings are derived by value-matching across recorded (request, entity) pairs; explicit declaration is a fallback only | MUST | v0.1 | Unit + M4 burden | Not implemented |
| FR-204 | An **exact recorded create** adopts the recorded response as the entity verbatim, including recorded identity. No synthesis occurs | MUST | v0.1 | Conformance | Not implemented |
| FR-205 | An **unrecorded create** constructs from template + bindings + generated + constant defaults | MUST | v0.1 | Conformance | Not implemented |
| FR-206 | Compiler runs validations **V1-V6** before assigning `fidelity: l2_core` | MUST | v0.1 | Structural fidelity suite (release-blocking) | Not implemented |
| FR-207 | **V5 round-trip:** constructing from each recorded create request must reproduce the recorded entity exactly on all required fields | MUST | v0.1 | Structural fidelity suite (release-blocking) | Not implemented |
| FR-208 | **V3 cardinality:** a body path resolving to an **array** on any observed request pins the tool to `l1`. Batch writes are outside L2-Core in v0.1 | MUST | v0.1 | Structural fidelity suite | Not implemented |
| FR-209 | CONFIRMED requires human answers **and** passing structural validation. Answered-but-invalid remains PROPOSED and `l1`, carrying a `validation` record naming the failed check | MUST | v0.1 | Adversarial evidence | Not implemented |
| FR-210 | A write whose entity cannot be constructed faithfully performs **no overlay mutation**; serves an exact recorded response if one exists, otherwise refuses with `ENTITY_CONSTRUCTION_FAILED` (ERROR) | MUST | v0.1 | Conformance (release-blocking) | Not implemented |
| FR-211 | Fidelity is **never** downgraded at runtime. It is a compile-time property | MUST | v0.1 | Determinism | Not implemented |
| FR-212 | Every overlay entity carries provenance: `RECORDED_ENTITY` or `SYNTHESIZED_ENTITY`. No other values in v0.1 | MUST | v0.1 | Unit | Not implemented |
| FR-213 | A response carries `synthesized_entity_ids`, non-empty when it contains any synthesized entity. **No downstream read may clear it** | MUST | v0.1 | Conformance (release-blocking) | Not implemented |
| FR-214 | A response-content assertion consuming a response with non-empty `synthesized_entity_ids` yields **UNKNOWN**. Call-shape assertions remain exempt | MUST | v0.1 | Adversarial evidence (release-blocking) | Not implemented |

---

## Cloud (FR-120 to FR-129)

All `Deferred`, phase v0.5+. Not designed for in v0.1 and must not influence v0.1 design. Listed for ID continuity only: job submission, scheduling, local/cloud behavioral equivalence enforced by a shared conformance suite, storage with retention, trajectory history query, behavioral diffing, baseline approval, world governance, self-hosted worker, flake detection.

---

## Traceability

Every requirement maps to an owning component ([architecture-map.md](../architecture/architecture-map.md)) and a verification strategy ([testing-strategy.md](../testing/testing-strategy.md)).

**Release-blocking verification** covers: FR-049, FR-082, FR-141, FR-189, **FR-206, FR-207, FR-210, FR-213, FR-214**. These are the requirements whose failure would make the product actively harmful rather than merely incomplete.

The FR-2xx additions come from a measured defect, not from anticipation: Milestone 0 finding F-1 produced structurally fabricated overlay state that passed every then-existing check, including M2 = 0%.
