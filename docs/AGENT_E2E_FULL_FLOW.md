# Agent E2E testing — full flow, how to write tests, CI setup

Step-by-step guide for using **agent-test-kit** in an agent repo: local tests → post-deploy CI → HTML report artifact (and optional S3 upload).

**Reference tests in this repo:** `tests/test_prompt_ai_helper_integration.py`, `tests/test_task4_pr_review_acceptance.py`, `examples/consumer_test_example.py`.

---

## 1. Mental model — two test phases

| Phase | When | Where tests live | Needs live agent? | Blocks pipeline? |
|-------|------|------------------|-------------------|------------------|
| **Build / unit** | Every push / PR | `tests/` (exclude `agent_e2e/`) | No — mocks only | Yes (hard fail) |
| **Post-deploy E2E** | After deploy to staging/int | `tests/agent_e2e/` | Yes | Soft by default |

```
main merge
  │
  ├─ Lint + unit tests          ← mock transport, fast
  ├─ Build / deploy             ← your agent image or service
  ├─ Agent integration tests    ← agent-test-kit live E2E + HTML report
  ├─ Upload report artifact     ← GitHub Actions artifact and/or S3
  └─ Tag / release (optional)
```

**Why split?** CI build must not require a deployed agent. Live tests run only when the service URL is reachable.

---

## 2. Repo layout (copy this structure)

```
your-agent/
├── agent.yaml                   # optional metadata (agent_id, version)
├── .github/workflows/ci.yml     # unit tests + optional post-deploy E2E
├── pytest.ini
├── requirements-dev.txt         # pytest, pytest-asyncio, pytest-timeout
└── tests/
    ├── test_*.py                # fast unit tests (every CI run)
    ├── test_agent_flow.py       # optional: mock agent-test-kit (agent_unit marker)
    └── agent_e2e/               # LIVE tests — post-deploy only
        ├── test_agent_integration_full.py
        ├── data/
        │   └── golden_prompt_guard.yaml   # optional security dataset
        └── support/
            └── helpers.py
```

---

## 3. Step-by-step — add E2E to a new agent

### Step 1 — Install agent-test-kit locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip
pip install agent-test-kit pytest>=8.2 pytest-asyncio>=0.23
# or from a local wheel:
# pip install /path/to/agent_test_kit-0.1.2-py3-none-any.whl
```

### Step 2 — Configure pytest

`pytest.ini`:

```ini
[pytest]
markers =
    agent_unit: mock flow tests (default CI)
    agent_integration: deployed agent helpers
    agent_e2e: live HTTP (post-deploy CI)
    agent_security: golden guard / injection dataset
    agent_write_action: creates real side effects (never default CI)

addopts = -m "not agent_e2e and not agent_write_action"
asyncio_mode = auto
```

### Step 3 — Exclude E2E from default CI

Unit job must ignore `tests/agent_e2e/`:

```bash
pytest tests/ -q \
  --ignore=tests/agent_e2e \
  -m "not agent_e2e and not agent_write_action"
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
4. Mark `agent_write_action` only for tests that create tickets, DB rows, etc. — exclude from CI.

### Step 6 — Run locally against integration

```bash
export ENABLE_REAL_AGENT_TEST=1
export AGENT_TEST_BASE_URL=https://your-agent-int.example.com
export AGENT_TEST_ENVIRONMENT=integration
export AGENT_TEST_AGENT_ID=your-agent

pytest tests/agent_e2e/ -m "agent_e2e and not agent_write_action" -v \
  --agent-report-html=reports/local-e2e.html \
  --timeout=120
open reports/local-e2e.html
```

For **prompt-ai-helper** profiles also set `PROMPT_AI_HELPER_ENV=integration`.

### Step 7 — GitHub Actions (unit + post-deploy E2E)

`.github/workflows/ci.yml` (minimal pattern):

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install agent-test-kit pytest pytest-asyncio
      - run: |
          pytest tests/ -q \
            --ignore=tests/agent_e2e \
            -m "not agent_e2e and not agent_write_action" \
            --agent-report-html=reports/ci-unit.html
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: agent-test-report-unit
          path: reports/

  e2e-post-deploy:
    if: github.ref == 'refs/heads/main'
    needs: unit
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install agent-test-kit pytest pytest-asyncio pytest-timeout
      - env:
          ENABLE_REAL_AGENT_TEST: "1"
          AGENT_TEST_BASE_URL: ${{ secrets.AGENT_TEST_BASE_URL }}
          AGENT_TEST_ENVIRONMENT: integration
          AGENT_TEST_AGENT_ID: your-agent
        run: |
          pytest tests/agent_e2e/ -m "agent_e2e and not agent_write_action" -v \
            --agent-report-json=reports/agent-test-kit-post-deploy.json \
            --agent-report-html=reports/agent-test-kit-post-deploy.html \
            --timeout=120
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: agent-test-report-e2e
          path: reports/
```

Set repository secret `AGENT_TEST_BASE_URL` to your deployed agent URL.

### Step 8 — CI variables (optional)

| Variable | Default | Purpose |
|----------|---------|---------|
| `AGENT_TEST_KIT_SOFT_FAIL` | `true` | `false` = hard-gate pipeline on E2E failure |
| `AGENT_TEST_BASE_URL` | unset | Override agent URL in CI |
| `ENABLE_REAL_AGENT_TEST` | unset | Must be `1` for live E2E job |

### Step 9 — Verify CI output

After a pipeline run:

- **GitHub Actions artifacts:** `agent-test-report-unit`, `agent-test-report-e2e`
- **Optional S3 upload** (your bucket + IAM role):

  ```
  s3://your-reports-bucket/agent-ci-reports/{repo}/{env}/{run-id}/agent-test-kit-post-deploy.html
  s3://your-reports-bucket/agent-ci-reports/{repo}/{env}/latest.html
  ```

Example upload step (requires `aws-actions/configure-aws-credentials` + `s3:PutObject`):

```yaml
      - name: Upload HTML report to S3
        if: always()
        env:
          REPORT_BUCKET: your-reports-bucket
          REPORT_PREFIX: agent-ci-reports/${{ github.repository }}/${{ github.run_id }}
        run: |
          aws s3 cp reports/agent-test-kit-post-deploy.html \
            "s3://${REPORT_BUCKET}/${REPORT_PREFIX}/agent-test-kit-post-deploy.html"
          aws s3 cp reports/agent-test-kit-post-deploy.html \
            "s3://${REPORT_BUCKET}/agent-ci-reports/${{ github.repository }}/latest.html"
```

---

## 4. Which client to use

| Your agent exposes | Client | Example |
|--------------------|--------|---------|
| JSON API (`POST /execute`) | `AgentClient` / `agent_client` fixture | billing-style agents |
| Cursor CLI proxy (`POST /agent`) | `CursorAgentClient` / `cursor_agent_client` | prompt review agents |
| Prompt review hook (`POST /prompt/review`) | `PromptReviewClient` + `get_profile()` | review pipeline |

### Assertions (after `assert_success()`)

See README [Agent assertions reference](../README.md#agent-assertions-reference).

```python
result.assert_read_only()
result.assert_tool_called("echo", server="atlassian-platform")
result.trace.connected_mcp_servers
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
| Side effects | Create ticket, charge account | `agent_write_action` — **never CI default** |

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

- **Separate** `tests/agent_e2e/` from unit tests; exclude in default CI job.
- **Gate live tests** with `ENABLE_REAL_AGENT_TEST=1`.
- **Attach results** to `agent_scenario` for rich HTML reports.
- **Use READ-ONLY prompts** in CI (`"READ-ONLY: ... No writes."`).
- **Set timeouts:** client `timeout_seconds=90–180`, `@pytest.mark.timeout(120)` on slow tests.
- **Start soft-fail** on E2E; hard-gate when stable.
- **One MCP smoke per server** you care about, not every tool.
- **Parametrize** review/guard cases; keep IDs stable for report readability.

### Don't

- Don't collect `tests/agent_e2e/` in the unit job.
- Don't read `result.response` before `assert_success()` (timeout → `None`).
- Don't run `agent_write_action` in default CI markers.
- Don't assume S3 upload works without IAM `s3:PutObject` on your prefix.

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
| Unit job fails: `No module named agent_test_kit` | E2E collected in unit job | `--ignore tests/agent_e2e` |
| E2E job skipped all tests | `ENABLE_REAL_AGENT_TEST` unset | Set env var to `1` |
| `NoneType` on `.get()` | Review timeout | `assert_success()` first; increase timeout |
| No HTML in artifact | Report flags missing | Pass `--agent-report-html=...` |
| No S3 object | IAM or wrong bucket | Check upload step logs |
| Connection refused | Wrong URL | Set `AGENT_TEST_BASE_URL` secret |

---

## 9. Checklist — new agent onboarding

- [ ] `tests/agent_e2e/` with at least health + one happy-path test
- [ ] `pytest.ini` markers + `addopts` excludes live tests locally
- [ ] Unit CI job ignores `tests/agent_e2e`
- [ ] `requirements-dev.txt` includes pytest-asyncio, pytest-timeout
- [ ] GitHub Actions (or your CI) uploads `reports/` artifact
- [ ] Local run green with `ENABLE_REAL_AGENT_TEST=1`
- [ ] (Optional) S3 upload verified once with your bucket/role

---

## 10. Links

- Package README: [README.md](../README.md)
- Assertions catalog: [Agent assertions reference](../README.md#agent-assertions-reference)
- Example consumer test: [examples/consumer_test_example.py](../examples/consumer_test_example.py)
- Live integration tests: [tests/test_prompt_ai_helper_integration.py](../tests/test_prompt_ai_helper_integration.py)
