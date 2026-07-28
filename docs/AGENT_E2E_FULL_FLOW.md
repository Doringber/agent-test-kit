# Agent E2E testing — full flow, how to write tests, CI setup

Step-by-step guide for using **agent-test-kit** in a Pango agent repo: local tests → post-deploy CI → S3 HTML report.

**Reference implementation:** `agent-prompt-ai-helper` (build #14, 20 live E2E tests).

---

## 1. Mental model — two test phases

| Phase | When | Where tests live | Needs live pod? | Blocks pipeline? |
|-------|------|------------------|-----------------|------------------|
| **Build / unit** | Docker build (`UnitTests.sh`) | `tests/` (exclude `agent_e2e/`) | No — mocks only | Yes (hard fail) |
| **Post-deploy E2E** | After deploy to int/stg | `tests/agent_e2e/` | Yes | Soft by default |

```
main merge
  │
  ├─ Create Version
  ├─ Build and Push          ← UnitTests.sh (no agent_test_kit, no live agent)
  ├─ Security scan
  ├─ Deploy Integration      ← pod running in EKS
  ├─ Agent Integration Tests ← agent-test-kit live E2E + HTML report + S3 upload
  ├─ Write LSV
  ├─ Create Git Tag
  └─ Notify Portal / Slack
```

**Why split?** Docker build must not install `agent-test-kit` or call a deployed agent. Live tests run only when the pod exists.

---

## 2. Repo layout (copy this structure)

```
your-agent/
├── agent.yaml
├── bitbucket-pipelines.yml      # includes Agent Integration Tests step (from publisher template)
├── pytest.ini
├── requirements-dev.txt         # pytest, pytest-asyncio, pytest-timeout
├── UnitTests.sh                 # --ignore tests/agent_e2e
├── scripts/
│   └── install_agent_test_kit.sh
└── tests/
    ├── test_*.py                # fast unit tests (build phase)
    ├── test_agent_flow.py       # optional: mock agent-test-kit (agent_unit marker)
    └── agent_e2e/               # LIVE tests — post-deploy only
        ├── test_agent_integration_full.py
        ├── test_agent_flow.py   # optional local mock
        ├── data/
        │   └── golden_prompt_guard.yaml   # optional security dataset
        └── support/
            └── prompt_injection_dataset.py
```

---

## 3. Step-by-step — add E2E to a new agent

### Step 1 — Install agent-test-kit locally

```bash
bash scripts/install_agent_test_kit.sh
# or: pip install agent-test-kit==0.1.2  (CodeArtifact)
pip install -r requirements-dev.txt
```

### Step 2 — Configure pytest

`pytest.ini`:

```ini
[pytest]
markers =
    agent_unit: mock flow tests (optional CI build)
    agent_integration: deployed agent helpers
    agent_e2e: live HTTP (post-deploy CI)
    agent_security: golden guard / injection dataset
    agent_write_action: creates real side effects (never default CI)

addopts = -m "not agent_e2e and not agent_write_action"
asyncio_mode = auto
```

### Step 3 — Exclude E2E from Docker build

`UnitTests.sh` must ignore `tests/agent_e2e/`:

```bash
pytest tests/ -q \
  --ignore=tests/agent_e2e \
  -m "not integration and not agent_e2e and not agent_write_action"
```

### Step 4 — Write mock tests (optional, fast CI)

Use `agent_unit` + httpx mock transport — no network:

```python
@pytest.mark.agent_unit
@pytest.mark.asyncio
async def test_review_mock(agent_scenario):
    client = PromptReviewClient(profile, transport=_MockTransport())
    result = await client.review("test", repo_slug="my-agent")
    agent_scenario.attach_execution_result(result)
    result.assert_success()
```

Enable in build only if you want: repo variable `AGENT_TEST_KIT_RUN_BUILD_MOCKS=true`.

### Step 5 — Write live E2E tests

Create `tests/agent_e2e/test_agent_integration_full.py`:

```python
import os
import pytest

pytestmark = [pytest.mark.agent_e2e, pytest.mark.agent_integration]

def _require_live() -> None:
    if os.getenv("ENABLE_REAL_AGENT_TEST", "").strip() != "1":
        pytest.skip("Set ENABLE_REAL_AGENT_TEST=1")

@pytest.mark.asyncio
async def test_health_live(agent_scenario) -> None:
    _require_live()
    # httpx GET /health or PromptReviewClient.health()
    ...

@pytest.mark.asyncio
async def test_agent_read_only_live(cursor_agent_client, agent_scenario) -> None:
    _require_live()
    result = await cursor_agent_client.execute_prompt(
        "Return JSON: {\"ok\": true}",
        mode="ask",
        timeout_seconds=90.0,
    )
    agent_scenario.attach_execution_result(result)
    result.assert_success()
    result.assert_read_only()
    result.assert_tool_called("echo", server="my-mcp")  # if applicable
```

**Always:**

1. Gate with `_require_live()` / `ENABLE_REAL_AGENT_TEST=1`.
2. Call `agent_scenario.attach_execution_result(result)` (or use `cursor_agent_client` fixture — auto-attaches).
3. Call `result.assert_success()` **before** reading `result.response`.
4. Mark `agent_write_action` only for tests that create Jira tickets, DB rows, etc. — exclude from CI.

### Step 6 — Run locally against integration

```bash
export ENABLE_REAL_AGENT_TEST=1
export AGENT_TEST_BASE_URL=https://your-agent-int.nonprod.pango.local
export AGENT_TEST_ENVIRONMENT=integration
export AGENT_TEST_AGENT_ID=your-agent

bash scripts/install_agent_test_kit.sh
pytest tests/agent_e2e/ -m "agent_e2e and not agent_write_action" -v \
  --agent-report-html=reports/local-e2e.html \
  --timeout=120
open reports/local-e2e.html
```

For **prompt-ai-helper** also set `PROMPT_AI_HELPER_ENV=integration`.

### Step 7 — Add pipeline step (publisher template)

In `bitbucket-pipelines.yml` (sync from `pipline-ai-publisher/templates/pipeline/`):

```yaml
- step: &agent-integration-tests-integration
    name: Agent Integration Tests (Integration)
    script:
      - bash /tmp/publisher/scripts/ci/agent-integration-tests.sh integration
    artifacts:
      - reports/**
      - reports/report-url.env
```

On `main` branch pipeline, place **after** `Deploy to Integration`:

```yaml
branches:
  main:
    - step: *create-version
    - step: *build
    - step: *security-scan
    - step: *deploy-integration
    - step: *agent-integration-tests-integration   # ← here
    - step: *write-lsv-integration
    ...
```

**Skip conditions (automatic):** MCP repos, no `agent.yaml`, no `tests/agent_e2e/`, production env.

### Step 8 — Bitbucket repo variables (optional)

| Variable | Default | Purpose |
|----------|---------|---------|
| `AGENT_TEST_KIT_SOFT_FAIL` | `true` | `false` = hard-gate pipeline on E2E failure |
| `AGENT_TEST_KIT_GIT_REF` | `main` (post-deploy) | Pin agent-test-kit version from git |
| `AGENT_TEST_KIT_SKIP` | unset | `true` = bypass all agent-test-kit |
| `AGENT_TEST_BASE_URL` | auto (ingress / port-forward) | Override agent URL |

### Step 9 — Verify CI output

After pipeline run:

- **Bitbucket artifacts:** `reports/agent-test-kit-post-deploy.html`
- **S3:**
  ```
  s3://app-mobile-versions/agent-ci-reports/{repo-slug}/{env}/{build}/agent-test-kit-post-deploy.html
  s3://app-mobile-versions/agent-ci-reports/{repo-slug}/{env}/latest.html
  ```
- **DynamoDB:** `e2e_report_s3_uri` on `ai-agents` row (when upload succeeds)

---

## 4. Which client to use

| Your agent exposes | Client | Example |
|--------------------|--------|---------|
| JSON API (`POST /execute`) | `AgentClient` / `agent_client` fixture | billing-style agents |
| Cursor CLI proxy (`POST /agent`) | `CursorAgentClient` / `cursor_agent_client` | prompt-ai-helper |
| Prompt review hook (`POST /prompt/review`) | `PromptReviewClient` + `get_profile()` | prompt-ai-helper |

### Assertions (after `assert_success()`)

```python
result.assert_read_only()                              # no write tool calls
result.assert_tool_called("echo", server="atlassian-platform")
result.trace.connected_mcp_servers                     # MCP wiring check
```

---

## 5. Test types — what to cover

| Layer | Example test | Marker |
|-------|--------------|--------|
| Health | `GET /health` → 200 | `agent_e2e` |
| Core API | `/prompt/review` returns suggested prompt | `agent_e2e` |
| Real MCP | Agent calls `echo` / `get_datetime` on live MCP | `agent_e2e` |
| Security golden | Injection/guard dataset → review must mutate prompt | `agent_security` |
| Ask/agent sanity | Short `mode="ask"` JSON response | `agent_e2e` |
| Side effects | Create Jira issue, charge account | `agent_write_action` — **never CI default** |

### Parametrize for many cases

```python
CASES = [{"id": "vague", "prompt": "test", ...}]

@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
@pytest.mark.asyncio
async def test_review_live(case, agent_scenario):
    ...
```

Keep datasets in `tests/agent_e2e/data/*.yaml` for golden guard / injection cases.

---

## 6. Best practices

### Do

- **Separate** `tests/agent_e2e/` from unit tests; exclude in `UnitTests.sh`.
- **Gate live tests** with `ENABLE_REAL_AGENT_TEST=1` so `pytest tests/` never hits prod/int by accident.
- **Attach results** to `agent_scenario` for rich HTML reports.
- **Use READ-ONLY prompts** in CI (`"READ-ONLY: ... No writes."`).
- **Set timeouts:** client `timeout_seconds=90–180`, `@pytest.mark.timeout(120)` on slow tests.
- **Start soft-fail** (`AGENT_TEST_KIT_SOFT_FAIL=true`); hard-gate when stable.
- **One MCP smoke per server** you care about (echo/datetime), not every tool.
- **Parametrize** review/guard cases; keep IDs stable for report readability.

### Don't

- Don't import `agent_test_kit` in build-phase tests without `--ignore agent_e2e`.
- Don't read `result.response` before `assert_success()` (timeout → `None`).
- Don't run `agent_write_action` in default CI markers.
- Don't rely on 600s pytest timeout — fix hangs (e.g. huge stdout redaction).
- Don't assume S3 upload works without CI role `s3:PutObject` on `agent-ci-reports/*`.

### Time budgets (prompt-ai-helper reference)

| Suite | Tests | Typical duration |
|-------|-------|------------------|
| Full E2E | 20 | ~8–12 min |
| Health + 1 review | 2 | ~1 min |
| Golden guard only | 12 | ~5–8 min |

Run subset locally: `-m "agent_e2e and not agent_security"`.

---

## 7. HTML report flags

```bash
pytest tests/agent_e2e/ \
  --agent-report-json=reports/agent-test-kit-post-deploy.json \
  --agent-report-html=reports/agent-test-kit-post-deploy.html
```

Report includes: scenario pass/fail, tool-flow strips, MCP servers, prompt review diff, golden guard chips, redacted credentials.

---

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Build fails: `No module named agent_test_kit` | E2E collected in UnitTests | `--ignore tests/agent_e2e` |
| E2E step skipped | No `tests/agent_e2e/` | Add folder + tests |
| `NoneType` on `.get()` | Review timeout | `assert_success()` first; increase timeout |
| Step runs 20+ min | Redaction hang / no timeout | Upgrade agent-test-kit ≥0.1.2 |
| No S3 report | IAM or no HTML generated | Check log for `[agent-test-report]` |
| Port-forward timeout | Ingress unreachable | Set `AGENT_TEST_BASE_URL` |

---

## 9. Checklist — new agent onboarding

- [ ] `tests/agent_e2e/` with at least health + one happy-path test
- [ ] `pytest.ini` markers + `addopts` excludes live tests locally
- [ ] `UnitTests.sh` ignores `tests/agent_e2e`
- [ ] `scripts/install_agent_test_kit.sh` present
- [ ] `requirements-dev.txt` includes pytest-asyncio, pytest-timeout
- [ ] Pipeline has `Agent Integration Tests` step after deploy
- [ ] Local run green with `ENABLE_REAL_AGENT_TEST=1`
- [ ] CI artifact + S3 report verified once
- [ ] (Optional) Flip `AGENT_TEST_KIT_SOFT_FAIL=false` when stable

---

## 10. Links

- Package README: `agent-test-kit/README.md`
- prompt-ai-helper CI notes: `agent-prompt-ai-helper/docs/AGENT_TEST_CI.md`
- Publisher scripts: `pipline-ai-publisher/scripts/ci/run-agent-test-kit.sh`, `upload-agent-test-report.sh`
- Live example tests: `agent-prompt-ai-helper/tests/agent_e2e/test_agent_integration_full.py`
