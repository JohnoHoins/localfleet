"""
Ollama LLM Client — Local inference for multi-domain fleet commands.
Sends natural language to Ollama, gets back structured FleetCommand JSON.
"""
import os
import httpx
from ollama import chat
from src.schemas import FleetCommand


MODEL = os.environ.get("LOCALFLEET_MODEL", "qwen2.5:72b")

SYSTEM_PROMPT = """You are a multi-domain naval fleet command parser. You convert natural language orders into structured JSON commands.

Available surface assets: alpha, bravo, charlie
  - Domain: "surface"
  - Capabilities: patrol, search, escort, loiter
  - Speed: typically 3-8 m/s
  - These are vessels that operate on the water surface

Available air assets: eagle-1
  - Domain: "air"
  - Capabilities: aerial_recon, orbit, sweep, track
  - Speed: typically 10-20 m/s
  - Altitude: typically 50-200 meters
  - Set drone_pattern for air assets (orbit, sweep, track, station)

Rules:
- Set domain to "surface" for vessels, "air" for drones
- Generate realistic waypoints (x, y in meters, range 0-2000)
- For air assets, always set altitude (50-200m) and drone_pattern
- Pick the best mission_type for the overall command
- If no formation specified, use "independent"
- colregs_compliance is always true for surface assets"""


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
