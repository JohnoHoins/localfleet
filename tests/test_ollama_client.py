"""Tests for Ollama LLM client — connection and multi-domain parsing."""
from src.llm.ollama_client import test_connection, parse_fleet_command
from src.schemas import DomainType


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


if __name__ == "__main__":
    test_ollama_connection()
    test_parse_multi_domain()
    print("\nAll ollama client tests passed!")
