# agent-test-kit

Shared pytest framework for testing Pango AI agents.

**Agent repos own:** test cases, prompts, fixtures, and environment-specific verifiers.  
**This package provides:** HTTP/Cursor clients, normalized traces, workflow assertions, JSON/HTML reports, cleanup, and verifier orchestration.

**Current version:** `0.1.1`

---

## Quick start — pip install to HTML report

Follow these steps in order the first time you use the package in an agent repo.

### 1. Create a virtualenv and install

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install --upgrade pip
```

**Option A — from Pango CodeArtifact (recommended for CI / internal use):**

```bash
export CODEARTIFACT_DOMAIN=pango-pypi-server
export CODEARTIFACT_DOMAIN_OWNER=609081136822
export CODEARTIFACT_REPOSITORY=pango-pypi
export AWS_DEFAULT_REGION=eu-west-1

aws codeartifact login \
  --tool pip \
  --domain "${CODEARTIFACT_DOMAIN}" \
  --domain-owner "${CODEARTIFACT_DOMAIN_OWNER}" \
  --repository "${CODEARTIFACT_REPOSITORY}" \
  --region "${AWS_DEFAULT_REGION}"

pip install agent-test-kit==0.1.1 pytest>=8.2 pytest-asyncio>=0.23
```

**Option B — from a local wheel (dev / offline):**

```bash
pip install --index-url https://pypi.org/simple \
  /path/to/agent_test_kit-0.1.1-py3-none-any.whl \
  pytest>=8.2 pytest-asyncio>=0.23
```

**Verify the install:**

```bash
python -c "import agent_test_kit; print(agent_test_kit.__version__)"
pytest --version
# agent-test-kit plugin loads automatically — no pytest_plugins line needed
```

---

### 2. Add `pytest.ini` to your agent repo

```ini
[pytest]
testpaths = tests
asyncio_mode = auto
markers =
    agent_unit: fast mock tests (run in CI)
    agent_integration: deployed agent, read-only
    agent_e2e: live HTTP (opt-in)
    agent_write_action: real writes (opt-in)
addopts = -m "not agent_e2e and not agent_write_action"
```

---

### 3. Write your first test (mock — no real agent needed)

Create `tests/test_my_agent.py`:

```python
import httpx
import pytest
from agent_test_kit import AgentClient, AgentTestConfig


class _FakeTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "success": True,
            "run_id": "run_demo",
            "response": {"summary": "ok"},
            "trace": {
                "tool_calls": [
                    {
                        "server": "billing",
                        "name": "get_customer_invoices",
                        "operation_kind": "read",
                        "status": "success",
                    },
                ],
            },
        })


@pytest.mark.asyncio
@pytest.mark.agent_unit
async def test_billing_read_flow(agent_scenario):
    client = AgentClient(
        AgentTestConfig(base_url="http://test", agent_id="billing-agent"),
        transport=_FakeTransport(),
    )
    result = await client.execute({"account_id": 12345})

    # Attach result so HTML report includes tool-flow data
    agent_scenario.attach_execution_result(result)

    result.assert_success()
    result.assert_tool_called("get_customer_invoices", server="billing")
    result.assert_read_only()
```

> **Tip:** for integration/E2E tests, prefer the `agent_client` or `cursor_agent_client` fixture — it auto-attaches results on every `execute()` so you don't need `attach_execution_result` manually.

---

### 4. Run pytest and generate the HTML report

```bash
mkdir -p reports
pytest tests/test_my_agent.py -v \
  --agent-report-json=reports/agent-results.json \
  --agent-report-html=reports/agent-results.html
```

Open the report in a browser:

```bash
open reports/agent-results.html   # macOS
# xdg-open reports/agent-results.html   # Linux
```

You should see:
- Run metadata (agent id, environment, timestamps)
- A **Tool flow** strip: `READ billing/get_customer_invoices`
- Expandable tables for assertions, tool args/outputs, and timeline

---

### 5. Run against a real agent (optional, opt-in)

Set env vars and enable live tests:

```bash
export AGENT_TEST_BASE_URL=http://my-agent-int.nonprod.pango.local
export AGENT_TEST_AGENT_ID=billing-agent
export AGENT_TEST_ENVIRONMENT=integration
export ENABLE_REAL_AGENT_TEST=1

pytest tests/test_my_agent_real.py -m agent_e2e \
  --agent-report-json=reports/live.json \
  --agent-report-html=reports/live.html
```

For **Cursor agents** (`POST /agent`), use `cursor_agent_client` instead of `agent_client`:

```python
@pytest.mark.asyncio
@pytest.mark.agent_e2e
async def test_live(cursor_agent_client):
    result = await cursor_agent_client.execute_prompt(
        "Summarize open invoices for account 12345"
    )
    result.assert_success()
```

---

### 6. Add to CI

```bash
# Install (CodeArtifact login + pip install agent-test-kit==0.1.1)
pytest tests/ -m "not agent_e2e and not agent_write_action" -q \
  --agent-report-json=reports/ci-results.json \
  --agent-report-html=reports/ci-results.html
```

Store `reports/` as a CI artifact so reviewers can open the HTML report.

---

## Table of contents

| Step | Topic |
|------|-------|
| [Quick start](#quick-start--pip-install-to-html-report) | Install pip package → first test → HTML report |
| [Step 1–12](#step-by-step-use-in-your-agent-repo) | Detailed reference for each feature |
| [Repo layout](#minimal-repo-layout-consumer) | Where files go in your agent repo |
| [Reference consumer](#reference-consumer) | `agent-qa-helper` examples |
| [Markers](#pytest-markers) | `agent_unit`, `agent_e2e`, etc. |
| [Public API](#public-api-011) | Import list |

---

## Step-by-step: use in your agent repo

### Step 1 — Install the package

**From CodeArtifact (CI / AWS creds):**

```bash
export CODEARTIFACT_DOMAIN=pango-pypi-server
export CODEARTIFACT_DOMAIN_OWNER=609081136822
export CODEARTIFACT_REPOSITORY=pango-pypi
export AWS_DEFAULT_REGION=eu-west-1

aws codeartifact login \
  --tool pip \
  --domain "${CODEARTIFACT_DOMAIN}" \
  --domain-owner "${CODEARTIFACT_DOMAIN_OWNER}" \
  --repository "${CODEARTIFACT_REPOSITORY}" \
  --region "${AWS_DEFAULT_REGION}"

pip install agent-test-kit==0.1.1
```

**From a local wheel (dev / before publish):**

```bash
pip install --index-url https://pypi.org/simple \
  /path/to/agent_test_kit-0.1.1-py3-none-any.whl
```

**Verify:**

```bash
python -c "import agent_test_kit; print(agent_test_kit.__version__)"
# 0.1.1
```

Copy `agent-qa-helper/scripts/install_agent_test_kit.sh` into your repo if you want the same CI/local fallback logic (CodeArtifact → sibling wheel → explicit `AGENT_TEST_KIT_WHEEL`).

---

### Step 2 — Add test dependencies

In `requirements-dev.txt`:

```text
pytest>=8.2
pytest-asyncio>=0.23
agent-test-kit==0.1.1   # or install via script in CI before pytest
```

The pytest plugin loads automatically when the package is installed (no extra `pytest_plugins` line needed).

---

### Step 3 — Configure pytest

In `pytest.ini`:

```ini
[pytest]
markers =
    agent_unit: fast tests with mock transport (default in CI)
    agent_integration: tests against a deployed agent
    agent_e2e: live HTTP tests (opt-in)
    agent_write_action: creates real external side effects (opt-in)

addopts = -m "not agent_e2e and not agent_write_action"

asyncio_mode = strict
asyncio_default_fixture_loop_scope = function
```

**Environment variables** (read by `AgentTestConfig`, prefix `AGENT_TEST_`):

| Variable | Example | Purpose |
|----------|---------|---------|
| `AGENT_TEST_BASE_URL` | `http://my-agent-int.nonprod.pango.local` | Agent base URL |
| `AGENT_TEST_AGENT_ID` | `billing-agent` | Report metadata |
| `AGENT_TEST_ENVIRONMENT` | `integration` | Report metadata |
| `AGENT_TEST_TIMEOUT_SECONDS` | `900` | HTTP timeout |

Optional: create `.env` in the agent repo (do not commit secrets).

---

### Step 4 — Pick the right client

| Your agent exposes | Use | Endpoint |
|--------------------|-----|----------|
| JSON execute API + structured `trace.tool_calls` | `AgentClient` | Default `/api/v1/execute` (configurable) |
| Cursor agent-base `POST /agent` + `stream-json` | `CursorAgentClient` | Always `/agent` |

**Generic JSON agent:**

```python
from agent_test_kit import AgentClient, AgentTestConfig

client = AgentClient(AgentTestConfig(
    base_url="http://billing-agent-int.nonprod.pango.local",
    agent_id="billing-agent",
    environment="integration",
))
result = await client.execute({"account_id": 12345})
```

**Cursor agent:**

```python
from agent_test_kit import CursorAgentClient, AgentTestConfig

client = CursorAgentClient(AgentTestConfig(
    base_url="http://qa-helper-int.nonprod.pango.local",
    agent_id="qa-helper",
    environment="integration",
))
result = await client.execute_prompt("Summarize open invoices for account 12345")
```

---

### Step 5 — Write fast unit tests (mock transport)

Use a mock `httpx` transport so CI never calls real agents.

```python
import json
import httpx
import pytest
from agent_test_kit import AgentClient, AgentTestConfig


class _FakeAgentTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "success": True,
            "run_id": "run_demo",
            "response": {"summary": "ok"},
            "trace": {
                "tool_calls": [
                    {"server": "billing", "name": "get_customer_invoices", "operation_kind": "read"},
                ],
            },
        })


@pytest.mark.asyncio
@pytest.mark.agent_unit
async def test_billing_read_flow() -> None:
    client = AgentClient(
        AgentTestConfig(base_url="http://test", agent_id="billing-agent"),
        transport=_FakeAgentTransport(),
    )
    result = await client.execute({"account_id": 12345})

    result.assert_success()
    result.assert_tool_called("get_customer_invoices", server="billing")
    result.assert_read_only()
```

**Reference:** `agent-qa-helper/tests/test_agent_test_kit.py`

---

### Step 6 — Use pytest fixtures (recommended)

When the package is installed, these fixtures are available:

| Fixture | Purpose |
|---------|---------|
| `agent_test_config` | `AgentTestConfig` from env / defaults |
| `agent_client` | `AgentClient` + auto report attachment |
| `cursor_agent_client` | `CursorAgentClient` + auto report attachment |
| `agent_scenario` | Attach results + run verifiers |
| `agent_cleanup` | Async cleanup manager (runs on teardown) |

```python
@pytest.mark.asyncio
@pytest.mark.agent_integration
async def test_flow(agent_client):
    result = await agent_client.execute({"account_id": 12345})
    result.assert_success()
    result.assert_tool_sequence([
        ("billing", "get_customer_invoices"),
    ])
```

---

### Step 7 — Assert workflows (common patterns)

```python
result.assert_success()
result.assert_tool_called("jira_create_issue", server="jira")
result.assert_tool_not_called("bitbucket_merge_pull_request", server="bitbucket")
result.assert_write_tool_called_once(server="jira", tool="jira_create_issue")
result.assert_read_before_write(
    read_tool=("bitbucket", "bitbucket_get_pr_diff"),
    write_tool=("jira", "jira_create_issue"),
)
result.assert_tool_sequence([
    ("bitbucket", "bitbucket_get_pullrequest_by_id"),
    ("jira", "jira_create_issue"),
], allow_additional_read_tools=False)
result.assert_max_retries(1)
result.assert_no_duplicate_tool_writes()
result.assert_no_failed_tool_calls()
```

Custom tool → server/kind mapping when trace metadata is incomplete:

```python
AgentTestConfig(
    tool_server_mappings={"get_customer_invoices": "billing"},
    tool_operation_mappings={"get_customer_invoices": ToolOperationKind.READ},
)
```

---

### Step 8 — Verify real side effects (your repo implements this)

Implement `SideEffectVerifier` in **your** agent repo (not in agent-test-kit):

```python
from agent_test_kit import SideEffectVerifier, VerificationContext, VerificationResult


class InvoiceCreatedVerifier:
    name = "invoice_created"

    async def verify(self, context: VerificationContext) -> VerificationResult:
        invoice_id = context.metadata["invoice_id"]
        # query DB / MCP independently of agent trace
        return VerificationResult(passed=True, message=f"invoice {invoice_id} exists")
```

Run verifiers from a test:

```python
async def test_write_flow(cursor_agent_client, agent_scenario, agent_cleanup):
    result = await cursor_agent_client.execute_prompt("Create invoice...")
    result.assert_success()

    summary = await agent_scenario.verify(
        [InvoiceCreatedVerifier()],
        metadata={"invoice_id": 999},
        timeout_seconds=15,
    )
    assert summary.passed
```

**Reference:** `agent-qa-helper/tests/verifiers/mcp_verifiers.py`

---

### Step 9 — Register cleanup before writes

For tests that create Jira issues, PR comments, DB rows, etc.:

```python
async def test_write_with_cleanup(cursor_agent_client, agent_cleanup):
    agent_cleanup.register(cleanup_jira_issue, issue_key="PNG-123")
    agent_cleanup.register(cleanup_pr_comment, pr_id=29)

    result = await cursor_agent_client.execute_prompt("...")
    result.assert_success()
    # cleanup runs even if assertions fail
```

Use `async with CleanupManager()` or the `agent_cleanup` fixture (async tests only).

---

### Step 10 — Live E2E (opt-in, not in default CI)

Gate live tests so `pytest` in CI stays fast and safe:

```python
import os
import pytest

def require_live_agent() -> None:
    if os.getenv("ENABLE_REAL_AGENT_TEST", "") != "1":
        pytest.skip("Set ENABLE_REAL_AGENT_TEST=1")


@pytest.mark.agent_e2e
@pytest.mark.asyncio
async def test_live_health(real_agent_config):
    require_live_agent()
    ...
```

Run read-only live suite:

```bash
ENABLE_REAL_AGENT_TEST=1 \
AGENT_TEST_BASE_URL=http://my-agent-int.nonprod.pango.local \
AGENT_TEST_ENVIRONMENT=integration \
pytest tests/test_my_agent_real.py -m "agent_e2e and not agent_write_action" \
  --agent-report-json=reports/live.json \
  --agent-report-html=reports/live.html
```

Run write tests (creates real side effects — use only in controlled env):

```bash
ENABLE_REAL_AGENT_TEST=1 \
ENABLE_AGENT_WRITE_ACTIONS=1 \
pytest tests/test_my_agent_real.py -m agent_write_action
```

**Reference:** `agent-qa-helper/tests/test_agent_test_kit_real.py`, `tests/conftest.py`, `tests/support/agent_e2e.py`

---

### Step 11 — Generate reports

```bash
pytest tests/ \
  --agent-report-json=reports/agent-results.json \
  --agent-report-html=reports/agent-results.html
```

Reports are redacted (tokens, credentials, sensitive args/outputs).

**Tool flow data in reports:** scenarios are recorded for every test, but **tool calls, timeline, and assertions** appear only when the test attaches an execution result. Use one of:

| Approach | When to use |
|----------|-------------|
| `agent_client` / `cursor_agent_client` fixture | Recommended — auto-attaches on `execute()` |
| `agent_scenario.attach_execution_result(result)` | Manual `AgentClient(...)` without fixture |
| `store_execution_result(config, nodeid, result)` | Advanced / custom pytest hooks |

If you construct `AgentClient(...)` directly without `on_result` or `attach_execution_result`, the HTML report will show an empty tool-flow section even when the agent ran successfully.

The HTML report includes a **visual tool-flow strip** (read/write badges and server/tool sequence) plus expandable tables for arguments, outputs, timeline, and verifiers.

---

### Step 12 — Wire into CI

Example (same pattern as `agent-qa-helper/UnitTests.sh`):

```bash
# Install framework
bash scripts/install_agent_test_kit.sh

# Fast unit tests only
pytest tests/ -m "not agent_e2e and not agent_write_action" -q

# Optional nightly: live read-only
# ENABLE_REAL_AGENT_TEST=1 pytest -m agent_e2e ...
```

---

## Minimal repo layout (consumer)

```text
my-agent/
├── agent.yaml                 # agent_id, version (your metadata)
├── pytest.ini
├── requirements-dev.txt
├── scripts/
│   └── install_agent_test_kit.sh
└── tests/
    ├── conftest.py            # live E2E fixtures (optional)
    ├── test_my_agent.py       # mock / unit tests
    ├── test_my_agent_real.py  # gated live E2E (optional)
    ├── support/               # prompts, MCP helpers
    └── verifiers/             # SideEffectVerifier implementations
```

---

## Reference consumer

**agent-qa-helper** is the reference integration:

| File | What it shows |
|------|----------------|
| `tests/test_agent_test_kit.py` | Mock transport + flow assertions |
| `tests/test_agent_test_kit_real.py` | Live read-only + write/replay E2E |
| `scripts/install_agent_test_kit.sh` | CodeArtifact / wheel install |
| `tests/verifiers/mcp_verifiers.py` | Independent MCP verifiers |

---

## Framework development (this repo)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest --cov=agent_test_kit --cov-fail-under=85
bash scripts/build-package.sh
bash scripts/verify-package.sh
bash scripts/publish-codeartifact.sh   # manual publish
```

Deterministic local acceptance (no external writes):

```bash
pytest -q tests/test_task4_pr_review_acceptance.py
```

---

## Pytest markers

| Marker | Use |
|--------|-----|
| `agent_unit` | Mock transport, fast |
| `agent_contract` | Schema / API contract |
| `agent_integration` | Deployed agent, read-only |
| `agent_e2e` | Live HTTP suite |
| `agent_write_action` | Real writes — gate carefully |
| `agent_regression` | Regression case files |
| `agent_security` | Safety / redaction checks |
| `agent_multi_mcp` | Multi-MCP orchestration |

---

## Publishing results to a dashboard

```python
from agent_test_kit import HttpResultPublisher, ResultPublisherConfig

publisher = HttpResultPublisher(ResultPublisherConfig(
    dashboard_url="https://dashboard.example/results",
    token_env="AGENT_TEST_DASHBOARD_TOKEN",
))
publisher.publish(report)
```

Set `AGENT_TEST_DASHBOARD_URL` and `AGENT_TEST_DASHBOARD_TOKEN` in the environment.

---

## Public API (0.1.1)

```python
from agent_test_kit import (
    AgentClient,
    CursorAgentClient,
    AgentTestConfig,
    AgentExecutionResult,
    CleanupManager,
    JsonReportWriter,
    HtmlReportWriter,
    run_verifiers,
    SideEffectVerifier,
    VerificationContext,
    VerificationResult,
)
```

See `agent_test_kit.__all__` for the full export list.
