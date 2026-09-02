import pytest

from video_to_notes.handoff.model_routing import (
    resolve_required_model,
    resolved_model_routing,
)


def test_default_model_routing_uses_luna_high_minimum():
    config = {}
    routing = resolved_model_routing(config)
    assert routing == {
        "reconstruction": "terra",
        "completion": "terra",
        "review": {
            "factual": "luna-high",
            "math": "sol",
            "pedagogical": "terra",
        },
    }


def test_luna_high_alias_is_normalized():
    config = {
        "codex": {
            "model_routing": {
                "review": {"factual": "Luna High"},
            }
        }
    }
    assert resolve_required_model(config, "factual") == "luna-high"


def test_reject_luna_below_high():
    config = {
        "codex": {
            "model_routing": {
                "review": {"factual": "luna"},
            }
        }
    }
    with pytest.raises(Exception, match="最低必须使用 luna-high"):
        resolve_required_model(config, "factual")
