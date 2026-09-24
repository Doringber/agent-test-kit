"""Semantic assertion tests using a stand-in for the pytest-jev fixture."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import pytest

from agent_test_kit.assertions.semantic import response_text
from agent_test_kit.models.execution import AgentExecutionResult


@dataclass
class _Claim:
    claim: str
    expect: str
    p: float

    @property
    def passed(self) -> bool:
        if self.expect == "holds":
            return self.p >= 0.8
        return self.p <= 0.2


class _FakeJev:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def expect(
        self,
        text: Any,
        *,
        holds: str | Iterable[str] = (),
        lacks: str | Iterable[str] = (),
        context: Mapping[str, Any] | None = None,
        threshold: float | None = None,
    ) -> list[_Claim]:
        self.calls.append(
            {
                "text": text,
                "holds": list(holds) if not isinstance(holds, str) else [holds],
                "lacks": list(lacks) if not isinstance(lacks, str) else [lacks],
                "context": context,
                "threshold": threshold,
            }
        )
        if self.fail:
            raise AssertionError(
                "jev: 1 of 1 claims failed\n"
                "  ✗ holds  p=0.04  apologizes to the customer  (needs >= 0.80)"
            )
        return [
            _Claim(claim=claim, expect="holds", p=0.91)
            for claim in self.calls[-1]["holds"]
        ] + [
            _Claim(claim=claim, expect="lacks", p=0.02)
            for claim in self.calls[-1]["lacks"]
        ]


@pytest.mark.agent_unit
def test_assert_means_records_claim_probabilities() -> None:
    jev = _FakeJev()
    result = AgentExecutionResult(
        success=True,
        run_id="run_1",
        response={"summary": "Sorry — the duplicate charge was refunded."},
    )
    claims = result.assert_means(
        jev,
        holds="apologizes to the customer",
        lacks=["asks for a password"],
        threshold=0.9,
    )
    assert jev.calls[0]["text"] == "Sorry — the duplicate charge was refunded."
    assert jev.calls[0]["threshold"] == 0.9
    assert len(claims) == 2
    outcome = result.assertion_outcomes[-1]
    assert outcome.name == "assert_means"
    assert outcome.passed is True
    assert outcome.actual == [
        {
            "claim": "apologizes to the customer",
            "expect": "holds",
            "p": 0.91,
            "passed": True,
        },
        {
            "claim": "asks for a password",
            "expect": "lacks",
            "p": 0.02,
            "passed": True,
        },
    ]


@pytest.mark.agent_unit
def test_assert_means_records_failure_then_raises() -> None:
    result = AgentExecutionResult(
        success=True,
        run_id="run_1",
        response="Double charges happen when you click twice.",
    )
    with pytest.raises(AssertionError, match="apologizes to the customer"):
        result.assert_means(_FakeJev(fail=True), holds=["apologizes to the customer"])
    outcome = result.assertion_outcomes[-1]
    assert outcome.passed is False
    assert outcome.actual == "Double charges happen when you click twice."
    assert "p=0.04" in (outcome.message or "")


@pytest.mark.agent_unit
def test_assert_means_requires_a_claim() -> None:
    result = AgentExecutionResult(success=True, run_id="run_1", response="ok")
    with pytest.raises(ValueError, match="at least one claim"):
        result.assert_means(_FakeJev(), holds=[], lacks=[])


@pytest.mark.agent_unit
@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ("plain reply", "plain reply"),
        ({"summary": "from summary"}, "from summary"),
        ({"suggested_prompt": "rewrite this"}, "rewrite this"),
        ({"ticket": 12}, '{"ticket": 12}'),
    ],
)
def test_response_text_prefers_known_fields(response: object, expected: str) -> None:
    assert response_text(response) == expected


@pytest.mark.agent_unit
def test_response_text_rejects_empty_payload() -> None:
    result = AgentExecutionResult(success=True, run_id="run_1", response=None)
    with pytest.raises(ValueError, match="empty"):
        result.assert_means(_FakeJev(), holds=["says hello"])
    blank = AgentExecutionResult(success=True, run_id="run_1", response="   ")
    with pytest.raises(ValueError, match="empty"):
        _ = blank.response_text
