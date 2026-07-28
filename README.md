<p align="center">
  <img src="docs/assets/readme-banner.png" alt="Agent Test Kit — sci-fi pytest framework for AI agents" width="900">
</p>

<pre align="center">
    _                    _       _____         _  __ _  _
   / \   __ _  ___ _ __ | |_    |_   _|__  ___| |/ _| || |
  / _ \ / _` |/ _ \ '_ \| __|_____| |/ _ \ / _ \ | |_| || |
 / ___ \ (_| |  __/ | | | ||_____| |  __/  __/ |  _|__   _|
/_/   \_\__, |\___|_| |_|\__|    |_|\___|\___|_|_|    |_|
        |___/
</pre>

<p align="center">
  <strong>Shared pytest framework for testing AI agents.</strong><br>
  Mock in CI · live HTTP when you opt in · HTML reports humans actually open.
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#the-report-is-the-product">Reports</a> ·
  <a href="#step-by-step-use-in-your-agent-repo">Full guide</a> ·
  <a href="docs/AGENT_E2E_FULL_FLOW.md">E2E flow</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11+-3776AB?logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/pytest-8.2+-0A9EDC?logo=pytest&logoColor=white" alt="pytest">
  <img src="https://img.shields.io/badge/version-0.1.2-blue" alt="0.1.2">
</p>

---

## The report is the product

Most agent tests dump JSON into CI logs nobody reads. **agent-test-kit** generates a single self-contained HTML file — tool-flow strips, MCP chips, prompt review diffs, golden guard outcomes — the same UI whether you ran mock tests or live E2E.

```
┌─ Agent test report ─────────────────────────────────────────────┐
│  Agent: billing-agent          Env: integration                 │
├─────────────────────────────────────────────────────────────────┤
│  Scenarios 6   Passed 6   Tool calls 14   Tokens 2.1k           │
├─────────────────────────────────────────────────────────────────┤
│  MCP tool flow                                                  │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐                   │
│  │ READ     │ →  │ READ     │ →  │ WRITE    │                   │
│  │ billing/ │    │ jira/    │    │ jira/    │                   │
│  │ get_inv… │    │ get_iss… │    │ create…  │                   │
│  └──────────┘    └──────────┘    └──────────┘                   │
├─────────────────────────────────────────────────────────────────┤
│  ▾ Assertions  ▾ Tool calls  ▾ Timeline  ▾ Side effects       │
└─────────────────────────────────────────────────────────────────┘
```

```bash
pytest tests/ -v \
  --agent-report-json=reports/results.json \
  --agent-report-html=reports/results.html

open reports/results.html
```

Redaction is on by default — tokens, credentials, and sensitive args never hit disk.

---

## Split of responsibility

**Your agent repo owns:** test cases, prompts, fixtures, domain verifiers, cleanup hooks.

**This package provides:** HTTP/Cursor clients, normalized traces, workflow assertions, JSON/HTML reports, verifier orchestration.

The pytest plugin loads automatically when installed — no `pytest_plugins` line needed.

---

## Quick start

### Install

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install --upgrade pip
```

From Pango CodeArtifact (CI / internal):

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

pip install agent-test-kit==0.1.2 pytest>=8.2 pytest-asyncio>=0.23
```

From a local wheel (dev / GitHub):

```bash
pip install --index-url https://pypi.org/simple \
  /path/to/agent_test_kit-0.1.2-py3-none-any.whl \
  pytest>=8.2 pytest-asyncio>=0.23
```

```bash
python -c "import agent_test_kit; print(agent_test_kit.__version__)"
pytest --version
```

### pytest.ini

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

### First test

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
    agent_scenario.attach_execution_result(result)

    result.assert_success()
    result.assert_tool_called("get_customer_invoices", server="billing")
    result.assert_read_only()
```

Use `agent_client` / `cursor_agent_client` fixtures in integration tests — they auto-attach results on every `execute()`.

---

## prompt-ai-helper: review pipeline + agent E2E

| Endpoint | URL |
|----------|-----|
| Review API | `https://prompt-ai-helper-int.nonprod.pango.local/prompt/review` |
| Health | `https://prompt-ai-helper-int.nonprod.pango.local/prompt/health` |
| Agent | `https://prompt-ai-helper-int.nonprod.pango.local/agent` |
| Stream (SSE) | `https://prompt-ai-helper-int.nonprod.pango.local/stream` |

```bash
export ENABLE_REAL_AGENT_TEST=1
export PROMPT_AI_HELPER_ENV=integration

pytest tests/test_prompt_ai_helper_integration.py -m agent_e2e -v \
  --agent-report-json=reports/prompt-ai-helper.json \
  --agent-report-html=reports/prompt-ai-helper.html
```

Golden guard dataset: `tests/data/golden_prompt_guard.yaml` — fixed inputs, adversarial cases, replayed on every change ([Prefactor golden datasets](https://prefactor.tech/learn/golden-datasets-for-agents), [superagent-guard](https://huggingface.co/datasets/superagent-ai/superagent-guard) taxonomy).

Runbook: [`.cursor/skills/prompt-ai-helper-e2e/SKILL.md`](.cursor/skills/prompt-ai-helper-e2e/SKILL.md) · Full guide: [`docs/AGENT_E2E_FULL_FLOW.md`](docs/AGENT_E2E_FULL_FLOW.md)

---

## Step-by-step: use in your agent repo

### Step 1 — Install the package

Same as [Quick start](#quick-start). Copy `agent-qa-helper/scripts/install_agent_test_kit.sh` for CI/local fallback (CodeArtifact → sibling wheel → `AGENT_TEST_KIT_WHEEL`).

### Step 2 — Add test dependencies

```text
# requirements-dev.txt
pytest>=8.2
pytest-asyncio>=0.23
agent-test-kit==0.1.2
```

### Step 3 — Configure pytest

See [pytest.ini](#pytestini) above.

Environment variables (`AGENT_TEST_` prefix):

| Variable | Example | Purpose |
|----------|---------|---------|
| `AGENT_TEST_BASE_URL` | `http://my-agent-int.nonprod.pango.local` | Agent base URL |
| `AGENT_TEST_AGENT_ID` | `billing-agent` | Report metadata |
| `AGENT_TEST_ENVIRONMENT` | `integration` | Report metadata |
| `AGENT_TEST_TIMEOUT_SECONDS` | `900` | HTTP timeout |

### Step 4 — Pick the right client

| Your agent exposes | Use | Endpoint |
|--------------------|-----|----------|
| JSON execute API + structured `trace.tool_calls` | `AgentClient` | Default `/api/v1/execute` |
| Cursor agent-base `POST /agent` + `stream-json` | `CursorAgentClient` | Always `/agent` |

```python
from agent_test_kit import AgentClient, AgentTestConfig

client = AgentClient(AgentTestConfig(
    base_url="http://billing-agent-int.nonprod.pango.local",
    agent_id="billing-agent",
    environment="integration",
))
result = await client.execute({"account_id": 12345})
```

```python
from agent_test_kit import CursorAgentClient, AgentTestConfig

client = CursorAgentClient(AgentTestConfig(
    base_url="http://qa-helper-int.nonprod.pango.local",
    agent_id="qa-helper",
    environment="integration",
))
result = await client.execute_prompt("Summarize open invoices for account 12345")
```

### Step 5 — Write fast unit tests (mock transport)

See [First test](#first-test). Reference: `agent-qa-helper/tests/test_agent_test_kit.py`

### Step 6 — Use pytest fixtures

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
    result.assert_tool_sequence([("billing", "get_customer_invoices")])
```

### Step 7 — Assert workflows

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

### Step 8 — Verify real side effects

Implement `SideEffectVerifier` in **your** agent repo:

```python
from agent_test_kit import SideEffectVerifier, VerificationContext, VerificationResult


class InvoiceCreatedVerifier:
    name = "invoice_created"

    async def verify(self, context: VerificationContext) -> VerificationResult:
        invoice_id = context.metadata["invoice_id"]
        return VerificationResult(passed=True, message=f"invoice {invoice_id} exists")
```

```python
summary = await agent_scenario.verify(
    [InvoiceCreatedVerifier()],
    metadata={"invoice_id": 999},
    timeout_seconds=15,
)
assert summary.passed
```

Reference: `agent-qa-helper/tests/verifiers/mcp_verifiers.py`

### Step 9 — Register cleanup before writes

```python
async def test_write_with_cleanup(cursor_agent_client, agent_cleanup):
    agent_cleanup.register(cleanup_jira_issue, issue_key="PNG-123")
    result = await cursor_agent_client.execute_prompt("...")
    result.assert_success()
    # cleanup runs even if assertions fail
```

### Step 10 — Live E2E (opt-in)

```bash
export ENABLE_REAL_AGENT_TEST=1
export AGENT_TEST_BASE_URL=http://my-agent-int.nonprod.pango.local
export AGENT_TEST_ENVIRONMENT=integration

pytest tests/test_my_agent_real.py -m agent_e2e \
  --agent-report-json=reports/live.json \
  --agent-report-html=reports/live.html
```

Write tests (real side effects):

```bash
ENABLE_REAL_AGENT_TEST=1 ENABLE_AGENT_WRITE_ACTIONS=1 \
pytest tests/test_my_agent_real.py -m agent_write_action
```

### Step 11 — Generate reports

```bash
pytest tests/ \
  --agent-report-json=reports/agent-results.json \
  --agent-report-html=reports/agent-results.html
```

Tool-flow data appears when you attach execution results — via fixtures, `agent_scenario.attach_execution_result(result)`, or `store_execution_result(...)`.

### Step 12 — Wire into CI

```bash
pytest tests/ -m "not agent_e2e and not agent_write_action" -q \
  --agent-report-json=reports/ci-results.json \
  --agent-report-html=reports/ci-results.html
```

Store `reports/` as a CI artifact.

For **pipline-ai-publisher** agents: `run-agent-test-kit.sh build` / `post-deploy`. Hard-gate with `AGENT_TEST_KIT_SOFT_FAIL=false`.

---

## Minimal repo layout

```text
my-agent/
├── pytest.ini
├── requirements-dev.txt
├── scripts/install_agent_test_kit.sh
└── tests/
    ├── conftest.py
    ├── test_my_agent.py
    ├── test_my_agent_real.py
    ├── support/
    └── verifiers/
```

Reference consumer: **agent-qa-helper** (`tests/test_agent_test_kit.py`, `tests/test_agent_test_kit_real.py`).

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

## Framework development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest --cov=agent_test_kit --cov-fail-under=85
bash scripts/build-package.sh
bash scripts/verify-package.sh
```

---

## Public API

```python
from agent_test_kit import (
    AgentClient,
    CursorAgentClient,
    AgentTestConfig,
    AgentExecutionResult,
    CleanupManager,
    HtmlReportWriter,
    JsonReportWriter,
    PromptReviewClient,
    get_profile,
    run_verifiers,
    SideEffectVerifier,
    VerificationContext,
    VerificationResult,
)
```

See `agent_test_kit.__all__` for the full export list.
