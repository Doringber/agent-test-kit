"""Semantic check of an agent reply with pytest-jev.

Copy into an agent repo's tests/ after:

    pip install "agent-test-kit[jev]"

Set OPENROUTER_API_KEY or TYPESAFE_API_KEY. Without a key, pytest-jev skips
the test. ``pytest -m "not jev"`` runs everything else offline.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_refund_reply_means(agent_client: object, jev: object) -> None:
    result = await agent_client.execute(  # type: ignore[attr-defined]
        input={"ticket": "I was charged twice for order #1042."},
    )
    result.assert_success()
    result.assert_means(
        jev,
        holds=[
            "apologizes to the customer",
            "says the duplicate payment was refunded",
        ],
        lacks=["asks for a password or a full card number"],
    )
