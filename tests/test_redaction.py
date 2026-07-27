"""Redaction utility tests."""

from __future__ import annotations

import pytest

from agent_test_kit.reporting.redaction import redact_string, redact_value


@pytest.mark.agent_unit
def test_redact_bearer_token() -> None:
    value = "Authorization: Bearer abc.def.ghi"
    assert "[REDACTED]" in redact_string(value)


@pytest.mark.agent_unit
def test_redact_sensitive_keys() -> None:
    payload = {
        "api_token": "secret-value",
        "run_id": "run_123",
        "items": [{"password": "hidden"}, "token usage is visible"],
    }
    redacted = redact_value(payload)
    assert redacted["api_token"] == "[REDACTED]"
    assert redacted["run_id"] == "run_123"
    assert redacted["items"] == [
        {"password": "[REDACTED]"},
        "token usage is visible",
    ]


@pytest.mark.agent_unit
def test_redaction_preserves_token_usage_metrics() -> None:
    payload = {
        "token_usage": 25,
        "total_token_usage": 25,
        "totalInputTokens": 10,
        "cacheCreationInputTokens": 5,
        "usage": {"input_tokens": 10, "output_tokens": 15},
        "api_token": "secret-value",
    }

    redacted = redact_value(payload)

    assert redacted["token_usage"] == 25
    assert redacted["total_token_usage"] == 25
    assert redacted["totalInputTokens"] == 10
    assert redacted["cacheCreationInputTokens"] == 5
    assert redacted["usage"] == {"input_tokens": 10, "output_tokens": 15}
    assert redacted["api_token"] == "[REDACTED]"


@pytest.mark.agent_regression
def test_redaction_preserves_pr_metadata_with_benign_token_prose() -> None:
    payload = {
        "source_branch": "feature/token-usage-reporting",
        "description": "Report token usage without changing authentication.",
    }

    assert redact_value(payload) == payload


@pytest.mark.agent_regression
def test_redaction_redacts_api_key_assignment_inside_pr_description() -> None:
    description = 'Use "api_key": "test-only-placeholder" when calling the sandbox.'

    redacted = redact_string(description)

    assert redacted == 'Use "api_key": "[REDACTED]" when calling the sandbox.'
    assert "test-only-placeholder" not in redacted


@pytest.mark.agent_regression
def test_redaction_redacts_embedded_authorization_and_assignments() -> None:
    description = (
        "PR metadata: Authorization: Bearer fake.bearer.value; "
        "API_KEY=fake-api-key-value; password=fake-password-value; "
        'JSON={"credential": "fake-credential-value"}; '
        "arguments={'api_token': 'fake-api-token-value'}."
    )

    redacted = redact_string(description)

    assert redacted == (
        "PR metadata: Authorization: Bearer [REDACTED]; "
        "API_KEY=[REDACTED]; password=[REDACTED]; "
        'JSON={"credential": "[REDACTED]"}; '
        "arguments={'api_token': '[REDACTED]'}."
    )
    assert "fake" not in redacted


@pytest.mark.agent_regression
def test_redaction_preserves_benign_security_prose() -> None:
    value = (
        "This PR documents token usage, the bearer token flow, password rotation, "
        "credential management, and authorization behavior."
    )

    assert redact_string(value) == value


@pytest.mark.agent_regression
def test_redaction_redacts_colon_delimited_header_and_yaml_secrets() -> None:
    value = (
        "Authorization: Basic ZmFrZS1vbmx5LXZhbHVl\n"
        "API_KEY: fake-api-key-value\n"
        "password: fake-password-value"
    )

    redacted = redact_string(value)

    assert redacted == (
        "Authorization: Basic [REDACTED]\nAPI_KEY: [REDACTED]\npassword: [REDACTED]"
    )
    assert "fake" not in redacted.lower()


@pytest.mark.agent_regression
def test_redaction_handles_escaped_quotes_without_leaking_secret_remainder() -> None:
    value = r'payload={"api_key": "fake-prefix\"fake-suffix", "message": "keep"}'

    redacted = redact_string(value)

    assert redacted == r'payload={"api_key": "[REDACTED]", "message": "keep"}'
    assert "fake-prefix" not in redacted
    assert "fake-suffix" not in redacted


@pytest.mark.agent_regression
def test_redaction_matches_explicit_sensitive_key_segments_only() -> None:
    payload = {
        "tokenizer": "sentencepiece",
        "passwordless": True,
        "secretary": "team-member",
        "credential_management": "documented",
        "authorization_behavior": "tested",
        "apikey": "fake-api-key",
        "jira_api_token": "fake-api-token",
        "clientSecret": "fake-client-secret",
        "db-password": "fake-database-password",
        "Authorization": "fake-authorization",
    }

    redacted = redact_value(payload)

    assert redacted == {
        "tokenizer": "sentencepiece",
        "passwordless": True,
        "secretary": "team-member",
        "credential_management": "documented",
        "authorization_behavior": "tested",
        "apikey": "[REDACTED]",
        "jira_api_token": "[REDACTED]",
        "clientSecret": "[REDACTED]",
        "db-password": "[REDACTED]",
        "Authorization": "[REDACTED]",
    }


@pytest.mark.agent_regression
def test_redaction_redacts_compound_credential_key_suffixes() -> None:
    payload = {
        "aws_secret_access_key": "fake-aws-secret",
        "openAiApiKey": "fake-openai-key",
        "githubAccessToken": "fake-github-token",
        "run_id": "run_123",
    }

    redacted = redact_value(payload)

    assert redacted == {
        "aws_secret_access_key": "[REDACTED]",
        "openAiApiKey": "[REDACTED]",
        "githubAccessToken": "[REDACTED]",
        "run_id": "run_123",
    }


@pytest.mark.agent_regression
def test_redaction_redacts_prefixed_camelcase_fields_in_strings() -> None:
    value = 'config={"openAiApiKey": "fake-openai-key", "githubAccessToken": "fake-github-token"}'

    redacted = redact_string(value)

    assert redacted == ('config={"openAiApiKey": "[REDACTED]", "githubAccessToken": "[REDACTED]"}')
    assert "fake-openai-key" not in redacted
    assert "fake-github-token" not in redacted


@pytest.mark.agent_regression
def test_redaction_preserves_noncredential_colon_fields() -> None:
    value = (
        "tokenizer: sentencepiece\n"
        "passwordless: enabled\n"
        "secretary: team-member\n"
        "credential_management: documented\n"
        "authorization_behavior: tested"
    )

    assert redact_string(value) == value


@pytest.mark.agent_unit
def test_redact_string_truncates_huge_input_before_regex() -> None:
    """Live agent stream-json can exceed 1MB; regex must not hang for minutes."""
    credential_line = 'stream: {"api_key": "top-secret-value"}'
    huge = "\n".join([credential_line, "x" * 400_000])
    redacted = redact_string(huge)
    assert len(redacted) < len(huge)
    assert "[truncated for redaction]" in redacted
    assert "[REDACTED]" in redacted
    assert "top-secret-value" not in redacted
