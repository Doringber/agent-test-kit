# Milestone 0: Architectural Spike

> **COMPLETE. Outcome: GO.** Results in [`spike/results/FINDINGS.md`](../../spike/results/FINDINGS.md)
> and [`spike/results/measurements.json`](../../spike/results/measurements.json).
>
> M0 produced one architecture-level finding, **F-1 (structural fabrication of overlay
> entities)**, resolved by [ADR-006](../architecture/adr/ADR-006-entity-construction-and-structural-fidelity.md)
> and verified by [Milestone 0.1](milestone-0.1.md). The gate below is retained as the
> historical record of what was measured and must not be edited retroactively.
>
> **This is throwaway architectural validation code. Do not prematurely generalize or productionize it.**
> Only `fixture_server/` survives.

**Duration:** 2 weeks, one engineer.
**Authority:** this document contains every architectural decision required. **The implementing engineer makes no architectural decisions.** Anything genuinely undecided is listed in [current-phase.md](current-phase.md#open-implementation-questions) and must be escalated, not resolved locally.

---

## Purpose

Determine whether L2-Core stateful replay is achievable at usable fidelity, and whether the capability declaration burden is acceptable.

M0 exists to end the project cheaply if the answer is no. Two weeks of throwaway code is a much better way to learn that than seventeen weeks of well-structured engineering against an unverified premise.

---

## The nine-step proof

The spike is complete when this loop executes end to end.

| Step | Action | Proves |
|---|---|---|
| 1 | Record tool traffic from a real agent against a real MCP server | Protocol interception ([ADR-002](../architecture/adr/ADR-002-protocol-boundary-interception.md)) |
| 2 | Replay an exact recorded interaction | L1 matching ([ADR-003](../architecture/adr/ADR-003-replay-matching-and-divergence.md)) |
| 3 | Change the prompt so the agent performs a write **not present** in the recorded trajectory | Unrecorded writes are handled |
| 4 | Overlay represents that write | L2-Core mutation ([ADR-004](../architecture/adr/ADR-004-l2-core-state-model.md)) |
| 5 | A subsequent read observes it | **Read-after-write. The core claim** |
| 6 | Reset between executions | Isolation ([INV-006](../architecture/invariants.md#inv-006--per-execution-state-isolation)) |
| 7 | Run again, obtain identical simulated world behavior | Determinism ([INV-007](../architecture/invariants.md#inv-007--determinism-of-the-world)) |
| 8 | Change the prompt so the agent makes an unsupported call | Contract enforcement ([INV-003](../architecture/invariants.md#inv-003--fidelity-contract)) |
| 9 | Receive an explicit, correctly classified divergence rather than a fabricated answer | **The honesty invariant** ([INV-004](../architecture/invariants.md#inv-004--never-fabricate)) |

**Steps 5 and 9 are the two that matter.** Step 5 proves the product is possible. Step 9 proves it is trustworthy.

---

## Components to implement

Six modules. Nothing else.

| Module | Est. lines | Responsibility |
|---|---|---|
| `coordinator.py` | ~250 | Session state: sequence, overlay, clock, minting, divergence log. TCP server on loopback |
| `proxy.py` | ~200 | stdio relay. Frames JSON-RPC, forwards to coordinator, relays response |
| `world.py` | ~150 | Load and save the minimal world YAML; canonicalization |
| `compile.py` | ~250 | Session log to world; capability proposal; interactive confirmation; decision counting |
| `replay.py` | ~350 | Matcher, contract check, overlay, merge, divergence classification |
| `experiment.py` | ~200 | Drives the nine-step loop; captures measurements |
| `fixture_server/` | ~200 | Server C. **The only surviving artifact** |

**Total target: ~1,600 lines. If the spike exceeds 2,500, stop and escalate.** It means a hidden architectural problem is being solved by volume.

---

## Interfaces

Exact signatures. Do not vary them.

```python
# ---------- coordinator.py ----------
class SessionCoordinator:
    def __init__(self, world: World | None, seed: int, mode: Mode) -> None: ...
    def start(self) -> int:                      # returns bound loopback port
        ...
    def register_server(self, server_id: str) -> None: ...
    def handle_call(
        self, server_id: str, tool: str, args: dict
    ) -> CallOutcome:                            # never raises for protocol reasons
        ...
    def reset(self) -> None:                     # step 6: overlay, clock, minting, seq
        ...
    def summary(self) -> SessionSummary: ...
    def stop(self) -> None: ...


# ---------- proxy.py ----------
class StdioProxy:
    def __init__(self, server_id: str, coordinator_port: int,
                 upstream_cmd: list[str] | None) -> None:
        ...                                       # upstream_cmd None => REPLAY
    def run(self) -> int:                         # blocks; returns exit code
        ...


# ---------- replay.py ----------
class ReplayEngine:
    def __init__(self, world: World, seed: int) -> None: ...
    def handle(self, server_id: str, tool: str, args: dict) -> CallOutcome: ...
    def reset(self) -> None: ...
    def stats(self) -> ReplayStats: ...


# ---------- compile.py ----------
def compile_world(session_log: Path, interactive: bool) -> tuple[World, CompileReport]: ...
def propose_capability(tool_schema: dict,
                       observed: list[Interaction]) -> CapabilityProposal: ...
```

---

## Minimal data models

Dataclasses. **No pydantic in the spike**; validation is not the question being answered.

```python
Mode          = Literal["record", "replay", "hybrid"]
Operation     = Literal["read", "write", "unknown"]
CapState      = Literal["confirmed", "proposed", "unknown"]
Fidelity      = Literal["l1", "l2_core"]
Provenance    = Literal["recorded", "overlay", "synthesized"]

Severity      = Literal["fatal", "error", "warn", "info"]
DivergenceCls = Literal[
    "UNKNOWN_TOOL", "OUT_OF_CONTRACT", "NO_RECORDED_INTERACTION",
    "SYNTHESIZED_WRITE_RESPONSE", "UNMERGEABLE_OVERLAY",
    "PAGINATION_OVERLAY_SKIPPED", "STALE_DERIVED_FIELD", "EXTRA_CALL",
]

@dataclass(frozen=True)
class Interaction:
    seq: int
    server: str
    tool: str
    request: dict          # canonical
    response: dict
    status: Literal["success", "error"]

@dataclass(frozen=True)
class Capability:
    operation: Operation
    state: CapState
    fidelity: Fidelity
    entity_type: str | None = None
    id_request_path: str | None = None
    id_response_path: str | None = None
    body_request_path: str | None = None
    collection_response_path: str | None = None
    predicate: dict | None = None            # grammar per ADR-004
    ignored_request_paths: tuple[str, ...] = ()
    pagination_paths: tuple[str, ...] = ()

@dataclass
class Entity:
    entity_type: str
    entity_id: str
    body: dict
    deleted: bool = False

@dataclass(frozen=True)
class Divergence:
    cls: DivergenceCls
    severity: Severity
    seq: int
    server: str
    tool: str
    detail: str

@dataclass(frozen=True)
class CallOutcome:
    served: bool
    response: dict | None
    provenance: Provenance | None
    stale_paths: tuple[str, ...]
    divergence: Divergence | None

@dataclass
class World:
    world_id: str
    seed_epoch: str                       # virtual clock epoch
    volatile_paths: tuple[str, ...]
    tools: dict[tuple[str, str], Capability]
    interactions: list[Interaction]
    entities: dict[str, list[Entity]]
    id_minting: dict[str, str]            # entity_type -> template
    tools_list_hash: str
```

**Deliberately absent:** trajectories, assertions, scenarios, verdicts, `WorldRef`, world patches, schema migration, redaction beyond a stub, content hashing beyond `tools_list_hash`. None bear on the nine steps.

---

## Minimal world representation

```yaml
world_id: m0-issues
seed_epoch: "2026-08-09T00:00:00Z"
volatile_paths: ["$.requestId"]
tools_list_hash: "sha256:abc123"

tools:
  "issues/list_issues":
    operation: read
    state: confirmed
    fidelity: l2_core
    entity_type: issue
    collection_response_path: "$.issues"
    predicate:
      kind: field_equals
      request_path: "$.project"
      entity_path: "$.project"
    ignored_request_paths: ["$.fields"]
    pagination_paths: ["$.limit", "$.offset"]

  "issues/create_issue":
    operation: write
    state: confirmed
    fidelity: l2_core
    entity_type: issue
    id_response_path: "$.id"
    body_request_path: "$.fields"

  "issues/search":            # deliberately L1: query language
    operation: read
    state: confirmed
    fidelity: l1

id_minting:
  issue: "M0-{counter:03d}"   # counter starts at 900

entities:
  issue:
    - entity_id: "M0-001"
      body: {id: "M0-001", project: "QA", title: "Existing issue"}

interactions:
  - seq: 1
    server: issues
    tool: list_issues
    request: {project: "QA"}
    response: {issues: [{id: "M0-001", project: "QA", title: "Existing issue"}], total: 1}
    status: success
```

**Note `total: 1`.** After step 4 creates an entity, step 5's merged read returns two issues while `total` still reads 1. The heuristic sibling rule must mark `$.total` STALE. **This is a required spike observation, not an incidental detail.**

---

## Execution flow

```mermaid
sequenceDiagram
    participant EX as experiment.py
    participant CO as SessionCoordinator
    participant PX as StdioProxy
    participant AG as Agent
    participant SV as Real MCP server

    Note over EX,SV: PHASE 1 - RECORD (step 1)
    EX->>CO: start(mode=record)
    CO-->>EX: port
    EX->>AG: launch(prompt_v1, mcp -> proxy)
    AG->>PX: tools/call
    PX->>CO: next_seq()
    PX->>SV: forward
    SV-->>PX: response
    PX->>CO: log(interaction)
    PX-->>AG: response
    EX->>CO: stop()
    EX->>EX: compile_world(session_log, interactive=True)

    Note over EX,SV: PHASE 2 - REPLAY (steps 2-7, x10)
    loop 10 executions
        EX->>CO: start(world, seed=42, mode=replay)
        EX->>AG: launch(prompt_v2, mcp -> proxy)
        AG->>PX: create_issue (NOT in recording)
        PX->>CO: handle_call
        CO->>CO: mint id, overlay.create
        CO-->>PX: synthesized response + SYNTHESIZED_WRITE_RESPONSE (warn)
        AG->>PX: list_issues
        PX->>CO: handle_call
        CO->>CO: merge(recorded, overlay); mark $.total STALE
        CO-->>PX: 2 issues, provenance=overlay, stale=["$.total"]
        EX->>CO: reset()
        EX->>EX: record outcome hash
    end
    EX->>EX: assert all 10 outcome hashes identical

    Note over EX,SV: PHASE 3 - CONTRACT (steps 8-9)
    EX->>CO: start(world, seed=42, mode=replay)
    EX->>AG: launch(prompt_v3 -> calls issues/search)
    AG->>PX: search(jql=...)
    PX->>CO: handle_call
    CO-->>PX: NO response; OUT_OF_CONTRACT (error)
    EX->>EX: assert response is None and class is OUT_OF_CONTRACT
```

---

## Spike repository layout

```
spike/                              # sibling to src/, deleted after write-up
  coordinator.py
  proxy.py
  world.py
  compile.py
  replay.py
  experiment.py
  models.py
  fixture_server/                   # Server C - THE ONLY SURVIVING ARTIFACT
    server.py                       # CRUD + pagination + error injection + timestamps
    README.md
  worlds/
    m0-issues.yaml
    m0-sql.yaml
    m0-fixture.yaml
  prompts/
    v1_record.txt  v2_write.txt  v3_unsupported.txt
  results/
    measurements.json
    FINDINGS.md
  test_spike.py                     # single file, no framework ceremony
```

**The production `src/` tree is not touched.**

---

## Target servers

| | Server A: Issue/task | Server B: SQL/database | Server C: Fixture |
|---|---|---|---|
| **Example** | GitHub Issues or Jira MCP | Postgres MCP | Ours |
| **Purpose** | Prove normal entity-oriented L2-Core | **Prove the boundary is honest** | Conformance target with fully known semantics |
| **Required tools** | list, get, create, update | query, execute | CRUD, pagination, error injection, timestamps |
| **Expected fidelity** | `l2_core` for CRUD, `l1` for search | **`l1` only. This is the expected and correct outcome** | `l2_core` |
| **Success** | Steps 1 to 9 pass | Every call classified `l1`; **zero fabrication**; `OUT_OF_CONTRACT` where appropriate | Steps 1 to 9 pass; becomes a permanent fixture |

**Server B is not a failure case.** Its purpose is to demonstrate that the architecture recognizes and honestly declares what it cannot simulate. **A spike where Server B is forced into L2-Core is a failed spike.**

**Build Server C first, in days 1 to 2.** It is the only environment where correct behavior is known with certainty, which makes it the debugging substrate for everything else.

---

## Measurements

Written to `results/measurements.json`. **These are the deliverable; the code is not.**

| # | Measurement | Target | Meaning if missed |
|---|---|---|---|
| **M1** | **In-contract correctness**: of calls inside a tool's declared contract, percentage replayed correctly | **100%** | Below 100% means the contract is not a contract. Fatal |
| **M2** | **Out-of-contract fabrication rate**: percentage of out-of-contract calls that received a response | **0%** | Any value above 0 falsifies the honesty invariant. Fatal |
| | *M0 result: 0%. **Necessary but insufficient** — it cannot see a structurally wrong **in-contract** response. See finding F-1 and measurement **M10** in [milestone-0.1.md](milestone-0.1.md)* | | |
| **M3** | **Divergence classification accuracy** | ≥ 95% | Below this, divergence messaging is unusable |
| **M4** | **Manual capability decisions per tool** (median and max) | **median ≤ 3; redesign trigger if > 5** | Above 5 means redesign the capability model before M1 |
| **M5** | **Determinism**: identical outcome hash across 10 executions and across two OSes | 10/10 and cross-OS equal | Any variance is severity-one |
| **M6** | **Replay latency** p50 / p95 including the coordinator hop | p95 < 10 ms | Informational; model latency dominates |
| **M7** | **Nine-step coverage** per server | A and C: 9/9. B: honest L1 classification | |
| **M8** | **Extend-loop closure** (informal): does divergence → passthrough → patch → review → replay close? | Qualitative | Informs whether M2.5 is correctly sized |
| **M9** | **Spike line count** | < 2,500 | Overrun signals a hidden architectural problem |

---

## Explicit non-goals

Building any of these is a spike failure. See [current-phase.md](current-phase.md#explicit-non-goals) for the operative list.

**Two undecided items requiring escalation rather than local resolution:**

1. If the heuristic sibling rule for staleness produces excessive false positives on real responses, **do not invent a replacement heuristic.** Record and escalate (OQ-1).
2. If capability proposal cannot distinguish read from write on a real server's schema, **do not add a fourth question.** Record and escalate; it means the three-question target needs redesign, which is what M4 measures (OQ-2).

---

## Definition of done

All of the following. No exceptions.

1. **Steps 1 through 9 execute end to end against Server A and Server C.**
2. **Server B is fully classified L1 with M2 = 0%.** Every call either matches a recording or produces `OUT_OF_CONTRACT`. No fabrication.
3. **M1 = 100% and M2 = 0%** across all three servers.
4. **M5 passes:** 10 identical outcome hashes, and equality across two operating systems.
5. **M4 recorded** with median and maximum, per server.
6. **`$.total` correctly marked STALE** in the step-5 merged read.
7. **Server C complete** and structured to become a permanent test fixture.
8. **`results/FINDINGS.md` written**, containing: all nine measurements; every case where the engine could not answer and why; every point where the engineer wanted to make an architectural decision and did not; and an explicit **GO / NO-GO / REDESIGN** recommendation.

---

## Gate

| Outcome | Action |
|---|---|
| M1 = 100%, M2 = 0%, M4 median ≤ 3, M5 passes | **GO.** Proceed to Milestone 1 |
| M2 > 0% | **NO-GO.** The honesty invariant is unachievable in this design. Halt, redesign [ADR-003](../architecture/adr/ADR-003-replay-matching-and-divergence.md) |
| M1 < 100% in-contract | **NO-GO.** The contract is not enforceable. Halt, redesign [ADR-004](../architecture/adr/ADR-004-l2-core-state-model.md) |
| M4 median > 5 | **REDESIGN.** Rework the capability model before proceeding to M1 |
| M5 fails | **NO-GO.** Engine non-determinism is severity-one. Halt and find it |
| Steps 1 to 7 pass but step 9 fabricates | **NO-GO.** The worst outcome and the most important to detect. Halt |

Record the outcome in [current-phase.md](current-phase.md).
