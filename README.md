# agent-test-kit

Shared pytest framework for testing Pango AI agents. Agent repositories own their
test cases, data, and environment-specific verifiers; this package provides
execution clients, normalized trace models, workflow assertions, and reporting.

## Install (CodeArtifact)

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

pip install agent-test-kit==0.1.0
```

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Build and verify

```bash
bash scripts/build-package.sh
bash scripts/verify-package.sh
```

## Publish (manual)

```bash
bash scripts/publish-codeartifact.sh
```

## Consumer example

```python
import pytest

@pytest.mark.asyncio
@pytest.mark.agent_integration
async def test_agent_flow(agent_client):
    result = await agent_client.execute(
        input={"repository": "test-repository", "pull_request_id": 125},
    )
    result.assert_success()
    result.assert_tool_called("bitbucket_get_pull_request", server="bitbucket")
    result.assert_tool_not_called("bitbucket_merge_pull_request", server="bitbucket")
```

## Pytest markers

- `agent_unit`, `agent_contract`, `agent_integration`, `agent_e2e`
- `agent_regression`, `agent_security`, `agent_write_action`
- `agent_nondeterministic`, `agent_multi_mcp`

## JSON report

```bash
pytest --agent-report-json=reports/agent-results.json
```
