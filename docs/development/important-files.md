# Important Files

Files with architectural significance and why. **Grows as implementation progresses.**

Not an inventory. If a file is here, touching it has consequences beyond itself.

---

## Documentation

| Path | Why it matters | Related |
|---|---|---|
| `CLAUDE.md` | Layer 1 context, loaded every session. **Keep under 200 lines** | all |
| `docs/development/current-phase.md` | **The authority on current scope.** Living document | all |
| `docs/architecture/invariants.md` | Hard rules. Violations are defects regardless of convenience | ADR-002 to 005 |
| `docs/architecture/adr/` | Closed decisions. Immutable | INV-015 |
| `docs/requirements/functional-requirements.md` | Traceability. IDs never reused | all |
| `docs/domain/glossary.md` | Prevents terminology drift. **Three distinct UNKNOWNs are disambiguated here** | ADR-004, ADR-005 |

---

## Superseded implementation: `src/agent_test_kit/`

**Retained for code harvest, not extension.** Do not add features. Do not fix defects unless harvesting.

### Harvest, largely intact (~900 lines)

| Path | Why | Destination |
|---|---|---|
| `assertions/flow.py` | Argument subset matching with recursive `Mapping` descent, status filters, and the `ToolStep`/`OptionalStep`/`AnyOfStep` sequence matcher are good design. **Trim 16 methods to 9** | `assertions/primitives.py` |
| `verifiers/protocols.py`, `verifiers/runner.py` | Concurrent, failure-isolated, individually timed out. Correct as written | `verifiers/` |
| `cleanup/manager.py` | `asyncio.shield` cancellation-preservation is subtle and correct. **Do not rewrite** | `execution/cleanup.py` |
| `reporting/redaction.py` | Key classifier, camel-case segmentation, ReDoS bounds (8 KiB/line, chunked). **Move, do not reimplement** | `redaction/` |
| `models/run_context.py` | Correlation id primitive. Extend with execution id | `domain/` |
| `models/tool_call.py` | Field set is correct. **`operation_kind` changes source: declared, never inferred** | `domain/trajectory.py` |
| `agent_test_kit_pytest_entrypoint.py` | Two-stage plugin registration solves coverage measurement of the plugin itself. Non-obvious. **Preserve the pattern verbatim** | `integrations/pytest/` |

### Cautionary, read before designing the replacement

| Path | The lesson |
|---|---|
| `client/tool_inference.py` | Name heuristics. Verified: `open_pull_request` → READ (mutation passes read-only), `refund_payment` → UNKNOWN (double refund passes duplicate-write). **Why [ADR-004](../architecture/adr/ADR-004-l2-core-state-model.md) requires declared capabilities** |
| `models/execution.py` | Assertions return PASS on empty trajectories. Verified for three assertions. **Why [ADR-005](../architecture/adr/ADR-005-evidence-semantics.md) centralizes `evidence_sufficient`** |
| `client/cursor_trace.py` | 437 lines parsing one vendor's stdout. **Why [ADR-002](../architecture/adr/ADR-002-protocol-boundary-interception.md) intercepts at the protocol boundary** |
| `reporting/json_report.py:178` | Passes `expected_mcp_servers` to a model lacking the field; pydantic silently drops it; the consumer at `html_report.py:353` is permanently dead. **Why NFR-081 requires preserved unknown fields** |
| `client/prompt_ai_helper_profiles.py:20` | `verify_ssl: bool = False` silently overrides a correct default. **Why security defaults are reviewed, not inherited** |
| `plugin/pytest_plugin.py:43` | Per-process stash prevents xdist support. **Why FR-109 requires per-worker isolation by design** |

### Delete on migration

`client/prompt_review_client.py`, `client/prompt_ai_helper_profiles.py`, `publishing.py`, `reporting/markdown_status.py`, `reporting/html_report.py`, `models/execution.py::AgentFlowResult`, `tests/data/golden_prompt_guard.yaml`, `tests/support/prompt_injection_dataset.py`, `docs/AGENT_E2E_FULL_FLOW.md`.

> `tests/support/prompt_injection_dataset.py` scores an adversarial rewrite as "GOLDEN MET" when it is semantically worse than the attack. Verified. It must not migrate in any form.

---

## Milestone 0 spike (not yet created)

Populate as built. See [milestone-0.md](milestone-0.md#spike-repository-layout).

| Path | Why it will matter | Related |
|---|---|---|
| `spike/replay.py` | **The highest-risk code in the system.** Matcher, contract check, merge | ADR-003, ADR-004, M1/M2 |
| `spike/coordinator.py` | Session state ownership. Determinism depends on it | INV-006, INV-007 |
| `spike/compile.py` | Capability proposal. **M4 is measured here** | ADR-004, FR-160 to FR-165 |
| `spike/fixture_server/` | **The only surviving artifact.** Becomes a permanent conformance fixture | testing-strategy |
| `spike/results/FINDINGS.md` | **The actual deliverable of M0.** The code is not | gate criteria |

---

## Production tree (not yet created)

Reserved. Populate at M1.

| Path | Significance |
|---|---|
| `src/agenttest/domain/` | **Imports nothing.** CI lint enforced (INV-008) |
| `src/agenttest/replay/merge.py` | Identified in architecture review as **the component most likely to kill the project** |
| `src/agenttest/assertions/evidence.py` | Owns `evidence_sufficient`. Single enforcement point for INV-001/002 |
| `src/agenttest/session/coordinator.py` | Owns all per-execution state |
| `spec/` | Language-neutral format specs. Must be implementable without reading our source (NFR-073) |
| `conformance/` | Shared by every implementation and OS. Release-blocking |
| `tests/determinism/` | Cross-OS trajectory hash equality (NFR-015). Release-blocking |

---

## Configuration

| Path | Why |
|---|---|
| `pyproject.toml` | Will need the import-linter rule enforcing INV-008 and the dependency direction |
| `.github/workflows/ci.yml` | Currently runs the superseded suite. Will need: conformance, determinism (multi-OS), adversarial evidence, security. Note the current matrix covers only 3.11 and 3.12 despite `requires-python = ">=3.11"` |
| `.gitignore` | Will need world-directory guidance per FR-194 |
