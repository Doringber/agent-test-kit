# ADR-002: Protocol-boundary interception

**Status:** Accepted
**Date:** 2026-08-09
**Supersedes:** none
**Superseded by:** none

---

## Context

An agent's tool traffic must be observable in RECORD mode and substitutable in REPLAY mode. Four mechanisms were considered: an in-process SDK shim wrapping the MCP client, a protocol proxy on the wire, framework callback registration, and OS-level syscall interception.

The superseded implementation in this repository demonstrates the cost of the alternative empirically:

- `src/agent_test_kit/client/cursor_trace.py` is 437 lines dedicated to parsing one vendor's CLI stdout format.
- `src/agent_test_kit/client/tool_inference.py` hardcodes a specific organization's MCP server inventory.

Both exist because interception happened at the agent-response layer rather than at the protocol layer.

---

## Decision

**Intercept at the protocol boundary using a proxy. Do not build framework-specific SDK shims. Accept a configuration change; refuse to require an agent source-code change.**

- **v0.1 transport: stdio only.** HTTP and SSE are deferred to v0.5.
- The proxy is spawned by the agent's own MCP client as the configured server command. In RECORD and HYBRID modes it spawns the real server as a child.
- Configuration transformation is automated by `agent-test init`, which discovers configured MCP servers and generates an alternate test configuration (FR-182). A documented manual wrapper exists where discovery is impossible (FR-183).
- All proxy endpoints in one execution register with a single **Session Coordinator** process, which owns sequence numbering and, in replay, the overlay and clock.
- **We never proxy model traffic.**

---

## Rationale

1. **Symmetry.** The recorder and the replayer occupy the same topological position and use the same adapter. One interception mechanism serves both modes, eliminating an entire class of "recorded differently than it replayed" defects.
2. **Neutrality.** Framework-agnostic and language-agnostic by construction. This is the only option that makes [INV-008](../invariants.md#inv-008--protocol-neutrality) achievable rather than aspirational.
3. **The cost of the alternative is measurable**, not theoretical: 437 lines of vendor-specific parsing already exist in this repository, and the protocol approach deletes all of it.
4. **The configuration change is one line per server** in a file the user already maintains, and `init` removes even that in the common case.

### Why we never proxy the model

Proxying model traffic would allow full determinism in world replay. It is rejected because it places us in the credential path for the customer's most sensitive key, doubles our availability obligation, multiplies privacy exposure by persisting full prompts, and does not actually deliver the benefit: constraining the agent to a recorded decision path is **Trajectory Replay**, achievable by recording agent decisions rather than proxying the provider.

---

## Consequences

### Accepted

- We lose visibility into agent-internal state (model calls, reasoning). Trajectory Replay (v0.5) requires an optional framework callback to recover it. That is the one place a framework-specific integration is justified, and it is optional and additive.
- Process overhead: one proxy per server plus one coordinator per execution. Bounded within [NFR-035](../../requirements/non-functional-requirements.md#scalability).
- Streaming responses are materialized whole. Agents branching on partial reception will not replay faithfully. Documented limitation.
- HTTP/SSE agents are unsupported until v0.5.

### Gained

- **Replay requires zero MCP credentials**, which is both a security property ([INV-011](../invariants.md#inv-011--replay-carries-no-credentials), threats T5 and T6) and the enabler of fork-PR CI.
- New agent frameworks require zero work.
- HTTP/SSE can be added later behind the same adapter interface without touching the engine.

### Rejected, and why

| Option | Reason |
|---|---|
| In-process SDK shim | N implementations across N frameworks and M languages; requires user code changes; is the exact failure mode already present in this repository |
| Framework callbacks | Same multiplication problem. Retained only as an optional enrichment for Trajectory Replay |
| Syscall / eBPF interception | Privileged, platform-specific, hostile to debugging |

---

## Related

- Requirements: FR-001, FR-002 (deferred), FR-005, FR-180, FR-181, FR-182, FR-183
- Invariants: [INV-008](../invariants.md#inv-008--protocol-neutrality), [INV-011](../invariants.md#inv-011--replay-carries-no-credentials)
- Components: C3 Recorder Proxy, C4 Protocol Adapter, C10 Session Coordinator ([architecture-map.md](../architecture-map.md))
