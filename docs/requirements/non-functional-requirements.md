# Non-Functional Requirements

Canonical catalog. IDs are stable and never reused. Extracted from ARCH-002.

---

## Reliability

Owner: all components. Invariant: [INV-001](../architecture/invariants.md#inv-001--no-false-green).

| ID | Requirement | Phase | Verification |
|---|---|---|---|
| NFR-001 | **No false green.** No path produces PASS without positive evidence. **Supersedes every requirement in conflict** | v0.1 | Adversarial evidence, release-blocking |
| NFR-002 | Artifact writes are atomic: temp, fsync, rename. A crash never leaves a half-written artifact | v0.1 | Unit + fault injection |
| NFR-003 | Every artifact carries a content hash; mismatch on load is FATAL, never a warning | v0.1 | Unit |
| NFR-004 | A crashed execution reduces sample size and is recorded as such; never silently shrinks the denominator | v0.1 | Unit |
| NFR-005 | Replay engine crash yields a partial trajectory and UNKNOWN for that execution | v0.1 | Fault injection |
| NFR-006 | Recorder buffers at most 64 MiB unpersisted; on overrun it terminates rather than dropping records | v0.1 | Unit |
| NFR-007 | Replay is memory-bounded with respect to world size | v0.1 | Benchmark |

---

## Determinism

Owner: C6, C10. Invariant: [INV-007](../architecture/invariants.md#inv-007--determinism-of-the-world).

**Definition, stated precisely.** Two modes make different guarantees:

| Mode | Agent decisions | World responses | Guarantee |
|---|---|---|---|
| **World replay** (testing) | Live model, non-deterministic | Deterministic function of (world, seed, decision sequence) | Same decisions produce byte-identical world behavior |
| **Trajectory replay** (diagnostic) | Replayed, zero model calls | Deterministic | Byte-identical end to end, any machine, forever |

| ID | Requirement | Phase | Verification |
|---|---|---|---|
| NFR-010 | Given identical world, seed, and tool-call sequence, the engine returns byte-identical responses in identical order. **It does not mean the agent behaves identically** | v0.1 | Determinism suite |
| NFR-011 | Sources we control: tool responses, entity ids, timestamps, error injection, concurrent-call ordering, collection ordering. All seed-derived or declared | v0.1 | Determinism suite |
| NFR-012 | Sources we cannot control: model sampling, provider drift, provider latency, agent-internal concurrency and randomness. **Surfaced in the trajectory, never suppressed** | v0.1 | Code review |
| NFR-013 | Residual non-determinism inside the engine is a **severity-one defect**. Hash-map iteration order, wall-clock reads, and unseeded randomness are prohibited in engine code | v0.1 | Determinism suite + lint |
| NFR-014 | Trajectory replay makes zero outbound network calls | v0.5 | Network isolation test |
| NFR-015 | Two trajectory-replay executions on different machines and OSes produce identical trajectory hashes | v0.1 | Cross-OS determinism, release-blocking |
| NFR-016 | Overlay collection ordering is a deterministic function of insertion order and a declared sort key, never map iteration | v0.1 | Property |

---

## Performance

Initial targets: achievable and meaningful rather than impressive. **World replay is dominated by model latency by two to three orders of magnitude, so these are comfort targets, not constraints.**

| ID | Metric | Target | Phase |
|---|---|---|---|
| NFR-020 | Recording overhead per tool call, p95 (includes one coordinator round trip) | < 15 ms | v0.1 |
| NFR-021 | Replay response, p95 | < 10 ms | v0.1 |
| NFR-022 | Coordinator startup plus world load, 10,000 interactions | < 500 ms | v0.1 |
| NFR-023 | World parse and index, cached / uncached (1,000 interactions) | < 50 ms / < 200 ms | v0.1 |
| NFR-024 | Trajectory-replay execution, 20 tool calls, no model | < 1 s | v0.5 |
| NFR-025 | Local parallelism | 10 concurrent executions on 8 cores / 16 GiB without swapping | v0.1 |
| NFR-026 | CLI startup to first output | < 300 ms | v0.1 |

---

## Scalability

**Practical v0.1 envelope. Everything beyond this is explicitly "not yet designed for."** Speculative figures from ARCH-001 (10^8 trajectories, 10^6 entities, 1,000 concurrent jobs) were struck because they anchored engineering at the wrong scale.

| ID | Dimension | v0.1 target |
|---|---|---|
| NFR-030 | Scenarios per project | 100 |
| NFR-031 | Executions per scenario (N), local | 20 |
| NFR-032 | World size | 25 MiB |
| NFR-033 | Interactions per world | 10,000 |
| NFR-034 | Overlay entities per execution | 10,000 |
| NFR-035 | Parallel local executions | 10 |

---

## Security

Threat detail: [threat-model.md](../security/threat-model.md).

| ID | Requirement | Phase | Verification |
|---|---|---|---|
| NFR-040 | Credentials never enter a world. Recorder strips server environment and headers by default; non-secret allowlist opt-in | v0.1 | Security suite |
| NFR-041 | Redaction runs **before persistence**, on requests and responses, on keys and string values | v0.1 | Security suite |
| NFR-042 | Redaction failure is fatal to the recording session | v0.1 | Security suite |
| NFR-043 | Worlds stored unencrypted locally by default and this is documented prominently; encryption available | v0.1 | Manual review |
| NFR-044 | **Tool output is untrusted.** Never interpreted as instruction, path, template, or code. Values are data only | v0.1 | Security suite |
| NFR-045 | **World files are untrusted input.** Safe against adversarial content: no arbitrary object construction, no code eval, no path traversal, bounded depth, size, expansion | v0.1 | Security suite, release-blocking |
| NFR-046 | Selector and path expressions use a restricted, **non-Turing-complete** subset: no function calls, no back-references | v0.1 | Unit |
| NFR-047 | The recorder executes only the command the user configured, never anything a server sends | v0.1 | Code review |
| NFR-048 | Replay requires no MCP credentials. **A security feature, not an accident** | v0.1 | Integration |
| NFR-049 | Minimal pinned dependency set; the core replay path depends on little beyond serialization and stdlib | v0.1 | Dependency audit |
| NFR-050 | Sandboxing the agent under test is the user's responsibility in v0.1, stated explicitly | v0.1 | Documentation |

---

## Privacy

| ID | Requirement | Phase |
|---|---|---|
| NFR-060 | Assume every world contains production-shaped data. Design accordingly rather than caveating | v0.1 |
| NFR-061 | Recording is opt-in per server, never global by default | v0.1 |
| NFR-062 | The compiler emits a data inventory: fields retained, redacted, dropped. Reviewable alongside the world | v0.1 |
| NFR-063 | Field-level exclusion policy, configurable per project, enforced at compile time | v0.1 |
| NFR-064 | **No telemetry from any component. None** | v0.1 |
| NFR-065 | Cloud residency, retention, hard delete, subprocessor list | v0.5 |

---

## Portability

Invariant: [INV-008](../architecture/invariants.md#inv-008--protocol-neutrality).

| ID | Requirement | Phase | Verification |
|---|---|---|---|
| NFR-070 | No dependency on any specific agent framework. Interception at the protocol boundary is what makes this achievable | v0.1 | Code review |
| NFR-071 | No dependency on any specific model provider. **We never proxy model traffic** | v0.1 | Code review |
| NFR-072 | No dependency on a specific MCP SDK; we speak the wire protocol | v0.1 | Code review |
| NFR-072a | `domain/` contains **no MCP-specific identifier, type, or assumption** | v0.1 | CI import lint |
| NFR-072b | The normalized `ToolInteraction` is the sole boundary type between adapters and everything above | v0.1 | Code review |
| NFR-072c | If MCP standardizes operation type, idempotency, or capability metadata, the compiler consumes it and **reduces our declaration burden. No design decision may be made whose purpose is to preserve the value of that burden** | v0.1 | Code review |
| NFR-073 | World and trajectory formats are language-neutral and fully specified in `spec/`, implementable without reading our source | v0.1 | Spec review |
| NFR-074 | Linux and macOS first class; Windows supported for CLI and replay engine. **Platform coverage is explicit, not incidental** | v0.1 | CI matrix |

---

## Extensibility

| ID | Requirement | Phase |
|---|---|---|
| NFR-080 | Exactly two public extension points in v0.1: `AgentLauncher`, `SideEffectVerifier`. Everything else internal | v0.1 |
| NFR-081 | World schema preserves unknown fields under a reserved namespace on round-trip and **never silently drops them** | v0.1 |
| NFR-082 | Adding an assertion requires no change to the engine, trajectory schema, or renderer | v0.1 |
| NFR-083 | Protocol adapters isolated behind one interface; a new protocol requires no change to the replay engine | v0.1 |

> NFR-081 exists because the superseded implementation had the opposite behavior: a report writer passed a field to a model that lacked it, pydantic silently discarded it, and the consuming render code was permanently dead. Verified. Silent field loss must be structurally impossible.

---

## Observability

Of the platform itself, not of the user's agent.

| ID | Requirement | Phase |
|---|---|---|
| NFR-090 | Structured logs with a correlation id spanning recorder, session, execution, verdict | v0.1 |
| NFR-091 | Metrics: replay match rate, divergence rate by class, overlay hit rate, latency, outcome distribution | v0.1 |
| NFR-092 | **Replay match rate is the primary product health metric** and must be visible to the user on every run, not only to us | v0.1 |
| NFR-093 | Debug mode emitting every matcher decision with its reason. Without this the engine is unsupportable | v0.1 |
| NFR-094 | Internal errors distinguishable from user errors in logs, exit codes, and messages | v0.1 |

---

## Developer Experience

| ID | Requirement | Phase | Verification |
|---|---|---|---|
| NFR-100 | Install to first replayed test in **under 30 minutes**, unaided, measured with real users | v0.1 | Timed onboarding |
| NFR-101 | Install is one command: no account, no key, no signup | v0.1 | Manual |
| NFR-102 | Configuration is one file with fewer than 10 required keys; zero-config works for the common case | v0.1 | Manual |
| NFR-103 | A first passing test is under 10 lines of user code | v0.1 | Manual |
| NFR-104 | Every error states what happened, which artifact or tool, and the single next command | v0.1 | Error-path review |
| NFR-105 | Divergence messages show expected, observed, and a minimal diff | v0.1 | Error-path review |
| NFR-106 | `--explain` prints the matcher decision trace in human-readable form | v0.1 | Manual |
