"""Tests for Ollama LLM client — connection and multi-domain parsing."""
import time
import pytest
from unittest.mock import patch, MagicMock
from src.llm.ollama_client import (
    test_connection, parse_fleet_command, LLMTimeoutError, SYSTEM_PROMPT,
    _RETRY_HINTS,
)
from src.schemas import DomainType, FleetCommand, MissionType


def test_ollama_connection():
    assert test_connection() is True
    print("Connection OK")


def test_parse_multi_domain():
    cmd = parse_fleet_command(
        "Send eagle-1 to do aerial recon at 120 meters with sweep pattern. "
        "Alpha patrol the harbor."
    )
    asset_ids = [a.asset_id for a in cmd.assets]
    domains = {a.asset_id: a.domain for a in cmd.assets}

    assert len(cmd.assets) >= 2, f"Expected 2+ assets, got {len(cmd.assets)}"
    assert "eagle-1" in asset_ids, "Missing eagle-1"
    assert "alpha" in asset_ids, "Missing alpha"
    assert domains["eagle-1"] == DomainType.AIR
    assert domains["alpha"] == DomainType.SURFACE

    eagle = [a for a in cmd.assets if a.asset_id == "eagle-1"][0]
    assert eagle.altitude is not None, "Eagle missing altitude"
    print(f"Multi-domain parse OK — {len(cmd.assets)} assets")


# ================================================================
# Audit 7 — Mock-based edge case tests
# ================================================================

_VALID_JSON = '{"mission_type":"patrol","assets":[{"asset_id":"alpha","domain":"surface","waypoints":[{"x":500,"y":300}],"speed":5.0}],"formation":"independent","spacing_meters":200,"colregs_compliance":true,"comms_lost_behavior":"return_to_base"}'


@patch("src.llm.ollama_client.chat")
def test_parse_timeout(mock_chat):
    """LLM call that exceeds timeout raises LLMTimeoutError."""
    def slow_chat(**kwargs):
        time.sleep(5)  # will exceed our short timeout
        return MagicMock()

    mock_chat.side_effect = slow_chat

    with patch("src.llm.ollama_client.LLM_TIMEOUT_SECONDS", 1):
        with pytest.raises(LLMTimeoutError, match="timed out"):
            # Call with a patched short timeout
            from src.llm.ollama_client import _chat_with_timeout
            _chat_with_timeout(
                messages=[{"role": "user", "content": "test"}],
                timeout_seconds=1,
            )


@patch("src.llm.ollama_client.chat")
def test_retry_varies_prompt(mock_chat):
    """On retry, the user message includes a hint and temperature increases."""
    call_count = 0
    call_args = []

    def fail_then_succeed(**kwargs):
        nonlocal call_count
        call_args.append(kwargs)
        call_count += 1
        if call_count < 3:
            raise ValueError("bad JSON")
        resp = MagicMock()
        resp.message.content = _VALID_JSON
        return resp

    mock_chat.side_effect = fail_then_succeed
    cmd = parse_fleet_command("patrol harbor")

    assert call_count == 3
    # First call has no hint
    assert "previous response was invalid" not in call_args[0]["messages"][1]["content"]
    # Second call has retry hint
    assert "previous response was invalid" in call_args[1]["messages"][1]["content"]
    # Third call has stronger hint
    assert "CRITICAL" in call_args[2]["messages"][1]["content"]
    # Temperature should increase on retries
    assert call_args[0]["options"]["temperature"] == 0
    assert call_args[1]["options"]["temperature"] > 0
    assert cmd.mission_type == MissionType.PATROL


@patch("src.llm.ollama_client.chat")
def test_parse_success_first_try(mock_chat):
    """Successful parse on first attempt returns correct command."""
    resp = MagicMock()
    resp.message.content = _VALID_JSON
    mock_chat.return_value = resp

    cmd = parse_fleet_command("alpha patrol 500 300")
    assert cmd.mission_type == MissionType.PATROL
    assert cmd.assets[0].asset_id == "alpha"
    assert cmd.raw_text == "alpha patrol 500 300"
    mock_chat.assert_called_once()


@patch("src.llm.ollama_client.chat")
def test_parse_all_retries_fail(mock_chat):
    """All 3 retries failing raises RuntimeError."""
    mock_chat.side_effect = ValueError("invalid JSON")

    with pytest.raises(RuntimeError, match="Failed after 3 attempts"):
        parse_fleet_command("gibberish input")


def test_system_prompt_has_voice_aliases():
    """System prompt includes voice transcription aliases."""
    assert "eagle one" in SYSTEM_PROMPT.lower() or "Eagle One" in SYSTEM_PROMPT
    assert "alfa" in SYSTEM_PROMPT.lower() or "Alfa" in SYSTEM_PROMPT
    assert "eagle-1" in SYSTEM_PROMPT


def test_system_prompt_has_negative_rules():
    """System prompt includes DO NOT rules."""
    assert "DO NOT" in SYSTEM_PROMPT
    assert "delta" in SYSTEM_PROMPT
    assert "eagle-2" in SYSTEM_PROMPT


def test_system_prompt_has_multiple_examples():
    """System prompt has multiple examples."""
    example_count = SYSTEM_PROMPT.count("EXAMPLE")
    assert example_count >= 4, f"Expected 4+ examples, got {example_count}"


if __name__ == "__main__":
    test_ollama_connection()
    test_parse_multi_domain()
    print("\nAll ollama client tests passed!")
