"""The generated frontend contract (frontend/src/types/api.gen.ts) matches the API.

A backend change to a request or response model, or to a route, must be followed
by `python scripts/gen_api_contract.py`, so the frontend's typecheck and contract
test (src/types/contract.ts, contract.test.ts) see it. This test fails otherwise.
"""

import importlib.util
import re

import pytest

from tests.conftest import BACKEND_DIR

SCRIPT = BACKEND_DIR.parent / "scripts" / "gen_api_contract.py"


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location("gen_api_contract", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def openapi(gen):
    return gen.load_spec()


def test_generated_contract_is_current(gen, openapi):
    committed = gen.OUTPUT.read_text(encoding="utf-8")
    assert committed == gen.render(openapi), (
        "frontend/src/types/api.gen.ts is out of date: run "
        "`python scripts/gen_api_contract.py` and commit the result"
    )


def test_every_api_operation_is_listed(gen, openapi):
    ops = gen.operations(openapi)
    assert "GET /jobs/{job_id}" in ops
    assert "POST /automation/submissions/{submission_id}/submit" in ops
    assert all(not op.split(" ")[1].startswith("/health") for op in ops)
    assert len(ops) == len(set(ops)) >= 60


def test_responses_list_every_field_as_sent(gen):
    """A field with a default is optional in a request but always present in a response."""
    node = {
        "type": "object",
        "properties": {"a": {"type": "string"}, "b": {"type": "integer"}},
        "required": ["a"],
    }
    assert "b: number;" in gen.ts_type(node, all_required=True)
    assert "b?: number;" in gen.ts_type(node, all_required=False)


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        ({"anyOf": [{"type": "string"}, {"type": "null"}]}, "string | null"),
        ({"enum": ["a", "b"]}, '"a" | "b"'),
        ({"const": "APPROVAL_MODE"}, '"APPROVAL_MODE"'),
        ({"type": "array", "items": {"enum": ["x", "y"]}}, '("x" | "y")[]'),
        ({"type": "object", "additionalProperties": {"type": "integer"}}, "Record<string, number>"),
        ({"type": "object"}, "Record<string, unknown>"),
        ({}, "unknown"),
        ({"$ref": "#/components/schemas/Page[JobSummary]"}, "Page_JobSummary_"),
    ],
)
def test_type_mapping(gen, node, expected):
    assert gen.ts_type(node, all_required=True) == expected


def test_request_shapes_get_an_input_suffix(gen):
    ref = {"$ref": "#/components/schemas/SettingsUpdate"}
    assert gen.ts_type(ref, all_required=False) == "SettingsUpdateInput"


def test_autonomous_mode_is_not_in_the_contract(gen, openapi):
    """ADR-016: the API neither accepts nor reports anything but approval mode."""
    rendered = gen.render(openapi)
    assert "AUTONOMOUS_MODE" not in rendered
    settings_in = re.search(r"export type SettingsUpdateInput = \{(.*?)\n\};", rendered, re.S)
    assert settings_in and "application_mode" not in settings_in.group(1)
