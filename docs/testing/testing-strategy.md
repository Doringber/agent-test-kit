# Testing Strategy

Derived from the architecture, not from generic practice. Every test class below exists because a specific invariant or decision requires it.

**We are building a verification product.** Our own test suite is the primary evidence that our verdicts mean anything. A gap here is not a coverage gap; it is a credibility gap.

---

## Test classes

| Class | Location | Enforces | Release-blocking |
|---|---|---|---|
| Unit | `tests/unit/` | Correctness of pure functions | No |
| Property | `tests/property/` | INV-006, INV-007, INV-014 | Yes, for the listed properties |
| **Conformance** | `conformance/` + `tests/conformance/` | **INV-003, INV-004, INV-005** | **Yes** |
| **Adversarial evidence** | `tests/adversarial/` | **INV-001, INV-002, INV-016** | **Yes** |
| Determinism | `tests/determinism/` | INV-007, NFR-015 | **Yes** |
| Security | `tests/security/` | NFR-044, NFR-045, NFR-046, T1 to T10 | **Yes**, for NFR-045 |
| Integration | `tests/integration/` | End-to-end record → compile → replay | No |
| Fault injection | `tests/integration/` | NFR-002, NFR-004, NFR-005 | No |

---

## Unit tests

Pure domain objects and transformations. No I/O, no processes, no fixtures beyond data.

Covers: domain value objects, `WorldRef` parsing, divergence construction, verdict aggregation, world schema validation, capability state transitions, exit-code mapping.

---

## Property tests

The system's correctness claims are universally quantified, so the tests must be too.

| Property | Statement | Related |
|---|---|---|
| **Canonicalization round-trip** | `canonicalize(canonicalize(x)) == canonicalize(x)`, and semantically equal arguments canonicalize identically regardless of key order, numeric representation, or Unicode form | FR-027, FR-033 |
| **Canonicalization stability** | Volatile-path removal never changes the canonical form of paths outside the volatile set | FR-033 |
| **Overlay mutation** | For arbitrary interleavings of create / update / delete / get / list, the overlay's final state equals the sequential application of those mutations | FR-041, FR-042, INV-014 |
| **Collection merge determinism** | `merge(recorded, overlay)` produces identical ordering across runs, processes, and platforms. **Never depends on map iteration order** | NFR-016, INV-007 |
| **Merge soundness** | Every entity in a merged result either appears in the recording or satisfies the declared predicate. **No entity appears that satisfies neither** | FR-043, INV-004 |
| **Deterministic id minting** | Same `(seed, entity_type, canonical_args, mutation_seq)` yields the same id. Different inputs yield different ids. Minted ids never collide with recorded ids | FR-046 |
| **Reset isolation** | After `reset()`, the overlay is byte-identical to the world's initial entity set. **No mutation from execution N is observable in execution N+1** | FR-045, INV-006 |
| **Sequence monotonicity** | Sequence numbers issued by one coordinator are strictly increasing with no gaps and no duplicates under concurrent proxy registration | FR-005, FR-180 |

---

## Conformance tests

**The most important suite in the repository.**

### Contract

```
Given:   World + Seed + ordered Tool Calls
Expect:  byte-equivalent Responses
       + exact Divergence set (class, severity, sequence)
       + identical trajectory hash
```

Stored as data in `conformance/`, not as code. Same corpus runs:

- Locally on Linux, macOS, Windows
- In CI on every commit
- In a cloud worker (from v0.5), enforcing FR-122 local/cloud equivalence
- Against any future non-Python implementation

**Any divergence between environments is a release blocker.**

### Required cases

| Case | Asserts |
|---|---|
| Exact recorded match | Response byte-identical, provenance RECORDED |
| Argument drift within volatile paths | Match succeeds, INFO divergence |
| Argument drift outside volatile paths | **No match. ERROR divergence. No response** |
| L2-Core create then list | Overlay entity appears, provenance OVERLAY |
| L2-Core create then get-by-id | Overlay entity returned |
| Update then read | Merged body reflects the update |
| Delete then list | Entity absent |
| **Unrecognized request parameter** | **`OUT_OF_CONTRACT`. No response** |
| **Unknown tool** | **`UNKNOWN_TOOL` FATAL. No response** |
| **L1 tool with dirty overlay** | Recorded response, `UNMERGEABLE_OVERLAY` WARN |
| Paginated read with dirty overlay | Recorded page unmodified, `PAGINATION_OVERLAY_SKIPPED` WARN |
| **Derived field after mutation** | Recorded value served, path marked STALE, `STALE_DERIVED_FIELD` WARN |
| Repeated identical write | Two distinct mutations, not collapsed |
| Query-language tool (SQL, JQL) | Classified L1; non-recorded call produces `OUT_OF_CONTRACT` |

**Server C (the M0 fixture server) is the permanent generator of this corpus**, because it is the only environment where correct semantics are known with certainty.

---

## Adversarial evidence tests

**Enforces [ADR-005](../architecture/adr/ADR-005-evidence-semantics.md). Release-blocking. Absence blocks any release.**

Existence justified by direct evidence: the superseded implementation had three assertions that returned PASS on empty trajectories, written by a careful engineer. Per-assertion discipline demonstrably fails.

### Required per assertion, no exceptions

| # | Test | Expected |
|---|---|---|
| 1 | Empty trajectory | **UNKNOWN**, and the assertion is not evaluated at all |
| 2 | FATAL divergence present | **UNKNOWN** |
| 3 | ERROR divergence present | **UNKNOWN** |
| 4 | Trajectory truncated by timeout | **UNKNOWN**, never FAIL |
| 5 | Trajectory truncated by crash | **UNKNOWN** for dependent assertions |
| 6 | Capability PROPOSED, assertion is safety-sensitive | **UNKNOWN** |
| 7 | Capability UNKNOWN, assertion is safety-sensitive | **UNKNOWN** |
| 8 | Response provenance SYNTHESIZED, assertion is response-content | **UNKNOWN** |
| 9 | Response provenance SYNTHESIZED, assertion is **call-shape** | **Evaluates normally.** Exemption verified (FR-172) |
| 10 | STALE path touched by a response-content assertion | **UNKNOWN** |
| 11 | Operation kind `unknown`, duplicate writes present | **Detected.** Write-equivalent treatment verified (FR-023) |

### Regression tests against known historical defects

Ported from verified failures in the superseded implementation. These must never pass silently again.

| Historical defect | Test |
|---|---|
| `assert_read_only()` PASSed on zero tool calls | `operation_profile` yields UNKNOWN on empty trajectory |
| `assert_no_duplicate_tool_writes()` PASSed on zero calls | `unique_writes` yields UNKNOWN on empty trajectory |
| `assert_no_failed_tool_calls()` PASSed on zero calls | `no_failures` yields UNKNOWN on empty trajectory |
| Two identical `refund_payment` calls passed duplicate-write | UNKNOWN-operation duplicates are detected |
| `open_pull_request` classified READ | Undeclared capability cannot satisfy `operation_profile` |
| Verifier timeout marked failed | Verifier timeout yields UNKNOWN, not FAIL |

---

## Determinism tests

Enforces [INV-007](../architecture/invariants.md#inv-007--determinism-of-the-world), NFR-010 to NFR-016. **Release-blocking.**

| Test | Assertion |
|---|---|
| Repeated execution | 10 executions of the same (world, seed, call sequence) produce identical trajectory hashes |
| **Cross-OS** | The conformance corpus produces identical trajectory hashes on Linux, macOS, and Windows |
| Cross-process | Two coordinator processes with the same seed produce identical minted ids |
| No wall clock | Static analysis: no `datetime.now`, `time.time`, or equivalent in `replay/` or `session/` |
| No unseeded randomness | Static analysis: no `random` without an explicit seed in engine paths |
| Ordering independence | Merged collection ordering is unchanged under `PYTHONHASHSEED` variation |
| Trajectory replay isolation | Zero outbound network calls (v0.5, NFR-014) |

---

## Security tests

Threats and IDs: [threat-model.md](../security/threat-model.md).

| Test | Enforces |
|---|---|
| **Malicious world files** (deep nesting, billion-laughs expansion, oversized payloads, hostile selectors, path traversal in every path field) | **NFR-045, T3. Release-blocking** |
| Safe parsing only: no arbitrary object construction, no code evaluation | NFR-045 |
| Bounded depth, size, and expansion enforced with clear errors | NFR-045 |
| Selector grammar rejects function calls and back-references | NFR-046 |
| **Redaction before persistence**: a secret in a tool argument never reaches disk | NFR-041, T1 |
| Redaction failure terminates the recording session | NFR-042, FR-009 |
| Tool output is never interpreted as path, template, instruction, or code | NFR-044, T2 |
| **REPLAY mode makes zero network calls to MCP servers and requires no credentials** | NFR-048, INV-011, T5 |
| **HYBRID refuses to start with any CI marker set, with no override** | FR-141, INV-012, T6 |
| No telemetry from any component | NFR-064, FR-192 |

---

## Integration tests

Full loop: record → compile → replay, against the Server C fixture. Multi-server sessions verifying cross-server sequence ordering through one coordinator. Mode transitions. CLI exit codes including the distinct code 2 for UNKNOWN.

## Fault injection

Coordinator killed mid-execution (partial trajectory, UNKNOWN). Proxy loses coordinator connection (fails closed, never fabricates). Disk full during recording (terminates, does not drop records). Agent crash mid-turn. Cleanup runs after each.

---

## Release-blocking summary

A release is blocked if any of the following fails:

1. **Conformance suite**, on all supported platforms
2. **Adversarial evidence suite**, all 11 cases for every assertion
3. **Determinism suite**, including cross-OS trajectory hash equality
4. **Malicious world file suite** (NFR-045)
5. **HYBRID CI-refusal test** (FR-141)
6. Property tests for reset isolation and merge soundness

These correspond to requirements FR-049, FR-082, FR-141, FR-189 and invariants INV-001 through INV-007.

---

## What we do not test

| Not tested | Why |
|---|---|
| Model output quality | Not our category. See [CLAUDE.md](../../CLAUDE.md#what-we-are-not-building) |
| Agent behavior correctness | That is what our users test **with** us |
| Third-party MCP server correctness | Out of scope. We replay what they returned |
| Performance beyond NFR targets | Model latency dominates; premature |

---

## Test-writing rules

1. **A new assertion without its 11 adversarial evidence tests does not merge.** No exceptions, no follow-up tickets.
2. Conformance cases are **data in `conformance/`**, never code in a test file, so every implementation and platform shares one corpus.
3. Property tests state the property in the docstring. A property test whose property cannot be stated in one sentence is a unit test wearing a costume.
4. A test reproducing a historical defect cites the defect in its docstring.
5. Never assert on wall-clock time, map iteration order, or process scheduling.
