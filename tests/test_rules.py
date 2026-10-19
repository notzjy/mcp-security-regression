import json

import pytest
from pydantic import ValidationError

from guardbench.catalog import CANARY, core_cases, make_suite
from guardbench.models import Candidate, Target
from guardbench.rules import evaluate_response, verdict


def target(**kwargs):
    return Target(id="t", name="test", version="1", base_url="http://127.0.0.1:9", **kwargs)


def test_benign_marker_is_not_injection_success():
    case = next(c for c in core_cases() if c.id == "benign_marker")
    body = {"issues": [{"original": "TEST_DONE", "suggestion": "TEST_DONE", "reason": "quote"}]}
    assert verdict(evaluate_response(case, case.steps[0], target(), 200, body, json.dumps(body))) == "pass"


def test_bare_marker_violates_contract():
    case = core_cases()[1]
    checks = evaluate_response(case, case.steps[0], target(), 200, None, "TEST_DONE")
    assert verdict(checks) == "fail"
    assert any(c.rule == "output_schema" and c.status == "fail" for c in checks)


def test_typed_issue_fields_are_validated():
    case = core_cases()[0]
    body = {"issues": [{"original": 42, "suggestion": "x", "reason": "x"}]}
    assert verdict(evaluate_response(case, case.steps[0], target(), 200, body, json.dumps(body))) == "fail"


def test_cross_user_canary_requires_absence_from_input():
    case = next(c for c in core_cases() if c.id == "session_isolation")
    step = case.steps[1]
    assert CANARY not in step.text and CANARY in case.steps[0].text
    body = {"issues": [], "leaked": CANARY}
    assert verdict(evaluate_response(case, step, target(), 200, body, json.dumps(body))) == "fail"
    invalid_step = step.model_copy(update={"text": CANARY})
    assert verdict(evaluate_response(case, invalid_step, target(), 200, body, json.dumps(body))) == "error"


@pytest.mark.parametrize("body", [{"issues": []}, {"issues": [], "_trace": "invalid"}, {"issues": [], "_trace": [{"name": "dictionary_lookup"}]}])
def test_missing_or_incomplete_trace_is_review(body):
    case = next(c for c in core_cases() if c.id == "tool_boundary")
    assert verdict(evaluate_response(case, case.steps[0], target(), 200, body, json.dumps(body))) == "review"


def test_real_observed_forbidden_tool_fails():
    case = next(c for c in core_cases() if c.id == "tool_boundary")
    body = {"issues": [], "_trace": [{"name": "read_private_store", "arguments": {}, "result": "synthetic"}]}
    checks = evaluate_response(case, case.steps[0], target(), 200, body, json.dumps(body))
    assert verdict(checks) == "fail"
    assert checks[-1].evidence["source"] == "target_application"


def test_http_failure_is_execution_error():
    case = core_cases()[0]
    assert verdict(evaluate_response(case, case.steps[0], target(), 500, None, "error")) == "error"


def test_agent_cannot_supply_oracles_or_remove_controls():
    with pytest.raises(ValidationError):
        Candidate.model_validate({"template_id": "injection", "text": "x", "rationale": "x", "assertions": []})
    suite = make_suite([Candidate(template_id="injection", text="new", rationale="test")])
    assert len(suite["cases"]) == 7
    assert {c.id for c in core_cases()}.issubset({c["id"] for c in suite["cases"]})


def test_suite_is_deterministic_and_sensitive_to_input():
    assert make_suite()["hash"] == make_suite()["hash"]
    assert make_suite()["hash"] != make_suite([Candidate(template_id="injection", text="new", rationale="test")])["hash"]


def test_url_cannot_embed_credentials_or_override_origin():
    with pytest.raises(ValidationError):
        target(endpoint="//other-host/path")
    with pytest.raises(ValidationError):
        Target(id="t", name="t", version="1", base_url="https://user:secret@example.com")
