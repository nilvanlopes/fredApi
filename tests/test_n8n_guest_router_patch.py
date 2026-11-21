import importlib.util
from pathlib import Path

import pytest


PATCH_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "n8n"
    / "patch-guest-inviter-router.py"
)
PATCH_SPEC = importlib.util.spec_from_file_location("guest_router_patch", PATCH_PATH)
guest_router_patch = importlib.util.module_from_spec(PATCH_SPEC)
PATCH_SPEC.loader.exec_module(guest_router_patch)


@pytest.mark.parametrize(
    ("text_expression", "expected_text"),
    [
        (
            "$('Send Routed Message to Fred').first().json.correction_notice",
            "={{ $('Send Routed Message to Fred').first().json.correction_notice }}",
        ),
        (
            "$('Send Routed Message to Fred').first().json.correction_text",
            "={{ $('Send Routed Message to Fred').first().json.correction_text }}",
        ),
    ],
)
def test_sender_body_uses_keypair_fields_for_notice_and_correction(
    text_expression, expected_text
):
    node = {
        "parameters": {
            "jsonBody": "={{ malformed old expression }}",
            "contentType": "json",
            "options": {"timeout": 30000},
        }
    }

    guest_router_patch.configure_sender_body(node, text_expression)

    parameters = node["parameters"]
    assert "jsonBody" not in parameters
    assert parameters["specifyBody"] == "keypair"
    assert parameters["bodyParameters"]["parameters"] == [
        {"name": "session", "value": "default"},
        {
            "name": "chatId",
            "value": "={{ $('Normalize Fred Message').first().json.chat_id }}",
        },
        {"name": "text", "value": expected_text},
    ]
    assert parameters["contentType"] == "json"
    assert parameters["options"] == {"timeout": 30000}
