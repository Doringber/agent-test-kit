"""Score-based evals with registration and pytest integration."""

from agent_test_kit.evals.base import (
    Eval,
    EvalReport,
    EvalResult,
    eval_case,
    get_eval,
    register_eval,
    registered_evals,
    run_evals,
)
from agent_test_kit.evals.builtin import RequiredTermsEval, RequiredToolsEval

__all__ = [
    "Eval",
    "EvalReport",
    "EvalResult",
    "RequiredTermsEval",
    "RequiredToolsEval",
    "eval_case",
    "get_eval",
    "register_eval",
    "registered_evals",
    "run_evals",
]
