"""
Ollama LLM Client — Local inference for multi-domain fleet commands.
Sends natural language to Ollama, gets back structured FleetCommand JSON.
"""
import os
import httpx
from ollama import chat
from src.schemas import FleetCommand


MODEL = os.environ.get("LOCALFLEET_MODEL", "qwen2.5:72b")

SYSTEM_PROMPT = """You are a multi-domain naval fleet command parser. Convert natural language into structured JSON.

FLEET ROSTER (you MUST only use these exact asset_id values):
  Surface: "alpha" (domain:"surface"), "bravo" (domain:"surface"), "charlie" (domain:"surface")
  Air:     "eagle-1" (domain:"air")

CRITICAL RULES:
1. If the user mentions "eagle", "eagle-1", "drone", or "aerial", you MUST include an asset entry with asset_id:"eagle-1", domain:"air", with altitude (50-200m) and drone_pattern set.
2. If the user says "all assets" or "all vessels and drone", include ALL FOUR assets.
3. "All vessels" = alpha + bravo + charlie (surface only). "All assets" = all four including eagle-1.
4. For air assets: ALWAYS set altitude, drone_pattern (orbit/sweep/track/station), and speed 10-20.
5. For surface assets: speed 3-8 m/s, domain:"surface".
6. Generate waypoints in meters, range 0-2000.
7. Pick the best mission_type: patrol, search, escort, loiter, aerial_recon.
8. If no formation specified, use "independent".

EXAMPLE — user says "All vessels patrol 600,400 in echelon. Eagle-1 orbit over 900,600 at 150m":
The assets array MUST contain 4 entries: alpha(surface), bravo(surface), charlie(surface), eagle-1(air with drone_pattern:"orbit", altitude:150)."""


def test_connection() -> bool:
    """Ping Ollama to verify it's running."""
    try:
        r = httpx.get("http://localhost:11434/api/tags", timeout=5.0)
        return r.status_code == 200
    except Exception:
        return False


def parse_fleet_command(natural_language: str) -> FleetCommand:
    """Parse natural language into a FleetCommand via local LLM.

    Retries up to 3 times on failure. Raises on total failure.
    """
    last_error = None
    for attempt in range(3):
        try:
            response = chat(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": natural_language},
                ],
                format=FleetCommand.model_json_schema(),
                options={"temperature": 0},
            )
            command = FleetCommand.model_validate_json(response.message.content)
            command.raw_text = natural_language
            return command
        except Exception as e:
            last_error = e
    raise RuntimeError(f"Failed after 3 attempts: {last_error}")
