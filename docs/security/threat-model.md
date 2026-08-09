# Threat Model

Scoped to this system. **Not generic security guidance.** Every threat below is specific to recording, replaying, or executing agent tool traffic.

Trust boundaries B1 to B6: [architecture-map.md](../architecture/architecture-map.md#trust-boundaries).

---

## Assets

| Asset | Why it matters |
|---|---|
| MCP server credentials | Grant write access to systems of record |
| Model provider credentials | Billable, and grant access to the customer's model account |
| World artifacts | Contain production-shaped data by assumption (NFR-060) |
| Trajectories | Contain tool arguments and responses |
| CI environment | Holds secrets and can execute arbitrary configured commands |
| Real external systems | The systems an agent can mutate |

---

## Threats

### T1 — Secrets captured in worlds

| | |
|---|---|
| **Asset** | MCP credentials, PII, production data |
| **Attack** | A token appears in a tool argument or response; the world is compiled and committed to a repository, possibly public |
| **Impact** | Credential disclosure. **The most likely real-world harm, and it requires no attacker** |
| **Mitigation** | Redaction before persistence (NFR-041, FR-008); redaction failure is fatal (NFR-042, FR-009); data inventory reviewable alongside the world (NFR-062); server environment and headers stripped by default with opt-in allowlist (NFR-040); **never auto-recommend committing** (FR-191); `.gitignore` proposed by default (FR-194) |
| **Phase** | v0.1 |

> This is the threat to design for first. It has no adversary; a well-intentioned user recording against production is sufficient to cause it.

### T2 — Hostile MCP server

| | |
|---|---|
| **Asset** | Recorder and compiler processes; the resulting world |
| **Attack** | A compromised or malicious server returns crafted output designed to exploit our parsing, or to poison a world that will later be replayed |
| **Impact** | Code execution in our process, or a poisoned world distributed to a team |
| **Mitigation** | **Tool output is treated as opaque data** (NFR-044): never interpreted as instruction, path, template, or code. Safe parsers only. Bounded sizes (NFR-006). The recorder executes only the user-configured command (NFR-047) |
| **Phase** | v0.1 |

### T3 — Malicious world file

| | |
|---|---|
| **Asset** | CI runners, developer machines |
| **Attack** | A pull request adds a world with deep nesting, exponential expansion, path traversal in a path field, or hostile selector expressions |
| **Impact** | Denial of service or code execution in CI |
| **Mitigation** | **World files are untrusted input** (NFR-045): no arbitrary object construction on deserialization, no code evaluation, bounded depth, size, and expansion, path validation on every path field. Selector grammar is **non-Turing-complete** with no function calls and no back-references (NFR-046) |
| **Phase** | v0.1. **Release-blocking test coverage** |

### T4 — Prompt injection via replayed content

| | |
|---|---|
| **Asset** | The agent under test |
| **Attack** | Recorded tool output contains injected instructions; replaying drives the agent to misbehave |
| **Impact** | The agent under test does something unintended |
| **Mitigation** | **Out of scope for us to prevent, in scope for us to make visible.** Content provenance is recorded and this is precisely the behavior assertions exist to catch. **The value proposition is that this happens in a simulated world instead of production** |
| **Phase** | n/a by design |

### T5 — Destructive real writes during a run believed to be replay

| | |
|---|---|
| **Asset** | Real external systems |
| **Attack** | Misconfiguration points the agent at real servers while the user believes replay is active |
| **Impact** | Real writes during testing |
| **Mitigation** | **Credential absence is the safety interlock** (INV-011, NFR-048). REPLAY requires zero MCP credentials, so a misconfigured "replay" run fails to authenticate rather than succeeding destructively. Mode is explicit and displayed on every run |
| **Phase** | v0.1 |

> The interlock is a *design* property, not a check. This is why REPLAY must never accept credentials as a convenience.

### T6 — CI secret exfiltration via forced recording

| | |
|---|---|
| **Asset** | CI secrets, MCP credentials |
| **Attack** | A malicious pull request modifies configuration to record instead of replay, capturing CI secrets into an artifact |
| **Impact** | Credential disclosure |
| **Mitigation** | Replay-only enforced by CI flag; recording requires an explicit flag that fork-PR workflows must not grant; **MCP credentials are never exposed to fork-PR jobs**; HYBRID refuses to start under any CI marker with no override (FR-141) |
| **Phase** | v0.1 |

### T7 — Arbitrary code execution via launcher configuration

| | |
|---|---|
| **Asset** | CI runners, developer machines |
| **Attack** | A pull request changes the agent launcher command |
| **Impact** | Remote code execution in CI |
| **Mitigation** | Launcher commands are allowlisted in a configuration file requiring code-owner review. The recorder never executes anything derived from tool output (NFR-047) |
| **Phase** | v0.1 |

### T8 — Supply-chain compromise

| | |
|---|---|
| **Asset** | Every user's CI, and in record mode their credentials |
| **Attack** | Our package or a dependency is compromised |
| **Impact** | Broad, severe |
| **Mitigation** | Minimal pinned dependency set with hashes (NFR-049); **the core replay path depends on little beyond serialization and stdlib**; signed releases; reproducible builds |
| **Phase** | v0.1 |

### T9 — Artifact tampering

| | |
|---|---|
| **Asset** | Trajectories used as evidence |
| **Attack** | A trajectory is edited to show a passing run |
| **Impact** | False evidence |
| **Mitigation** | Content hashing (NFR-003); signing at v1+ |
| **Phase** | Hashing v0.1, signing v1+ |

> **Until signing exists, trajectories must not be described as audit evidence** in any documentation or marketing surface.

### T10 — Cross-tenant leakage (cloud)

| | |
|---|---|
| **Asset** | Customer worlds and trajectories |
| **Attack** | Worker isolation failure |
| **Impact** | One customer's production-shaped data visible to another |
| **Mitigation** | Per-execution process and filesystem isolation; no shared mutable state; tenant-scoped storage prefixes with enforced access control |
| **Phase** | **v0.5+. Not a v0.1 concern because there is no cloud in v0.1** |

---

## Priority

| Rank | Threat | Reason |
|---|---|---|
| 1 | **T1** | No adversary required. A well-intentioned user recording against production is sufficient |
| 2 | **T3** | Untrusted input crossing into CI. Release-blocking coverage |
| 3 | **T5, T6** | Real side effects and credential exposure. Mitigated by design rather than by checks |
| 4 | T2, T7, T8 | Standard, well-understood mitigations |
| 5 | T9 | Matters only when we make evidence claims. Constrains our language until v1+ |
| 6 | T10 | Not applicable in v0.1 |

---

## Design properties that carry security weight

Three architectural choices are load-bearing for security and must not be traded away for convenience:

1. **REPLAY requires no credentials** (INV-011). Removes T5 and most of T6 structurally rather than procedurally.
2. **Redaction before persistence, fatal on failure** (NFR-041, NFR-042). An interrupted recording never leaves unredacted data on disk.
3. **The selector grammar is non-Turing-complete** (NFR-046). World files remain data and can never become executable.

---

## Out of scope

| Not addressed | Why |
|---|---|
| Sandboxing the agent under test | User responsibility in v0.1, stated explicitly (NFR-050) |
| Model provider security | We never proxy model traffic ([ADR-002](../architecture/adr/ADR-002-protocol-boundary-interception.md)) |
| MCP server hardening | Not our software |
| Preventing prompt injection | T4. We make it visible; preventing it is the agent's job |
