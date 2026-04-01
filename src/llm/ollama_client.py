"""
Ollama LLM Client — Local inference for multi-domain fleet commands.
Sends natural language to Ollama, gets back structured FleetCommand JSON.
"""
import logging
import os
import threading
import httpx
from ollama import chat
from src.schemas import FleetCommand

logger = logging.getLogger(__name__)

LLM_TIMEOUT_SECONDS = int(os.environ.get("LOCALFLEET_LLM_TIMEOUT", "30"))


MODEL = os.environ.get("LOCALFLEET_MODEL", "qwen2.5:72b")

SYSTEM_PROMPT = """You are a multi-domain naval fleet command parser. Convert natural language into structured JSON.

FLEET ROSTER (you MUST only use these exact asset_id values):
  Surface: "alpha" (domain:"surface"), "bravo" (domain:"surface"), "charlie" (domain:"surface")
  Air:     "eagle-1" (domain:"air")

VOICE TRANSCRIPTION ALIASES — the user may say any of these, always map to the correct asset_id:
  "alpha", "Alpha", "alfa", "Alfa" → asset_id: "alpha"
  "bravo", "Bravo" → asset_id: "bravo"
  "charlie", "Charlie" → asset_id: "charlie"
  "eagle", "Eagle", "eagle one", "Eagle One", "eagle 1", "Eagle 1", "eagle-one", "drone" → asset_id: "eagle-1"

CRITICAL RULES:
1. If the user mentions "eagle", "eagle-1", "drone", or "aerial", you MUST include an asset entry with asset_id:"eagle-1", domain:"air", with altitude (50-200m) and drone_pattern set.
2. If the user says "all assets" or "all vessels and drone", include ALL FOUR assets.
3. "All vessels" = alpha + bravo + charlie (surface only). "All assets" = all four including eagle-1.
4. For air assets: ALWAYS set altitude, drone_pattern (orbit/sweep/track/station), and speed 10-20.
5. For surface assets: speed 3-8 m/s, domain:"surface".
6. Generate waypoints in meters, range 0-2000. Never exceed 5000 in any axis.
7. Pick the best mission_type: patrol, search, escort, loiter, aerial_recon.
8. If no formation specified, use "independent".

DO NOT:
- Create asset IDs that are not in the roster above. There is no "delta", "eagle-2", or "drone-1".
- Set altitude for surface vessels. Altitude is ONLY for eagle-1 (air domain).
- Generate waypoints with negative coordinates or values above 5000.
- Leave the waypoints array empty for an asset that should be moving.

EXAMPLE 1 — "All vessels patrol 600,400 in echelon. Eagle-1 orbit over 900,600 at 150m":
The assets array MUST contain 4 entries: alpha(surface), bravo(surface), charlie(surface), eagle-1(air with drone_pattern:"orbit", altitude:150).

EXAMPLE 2 — "Send alpha and bravo to patrol around 800 600":
assets: [alpha(surface, waypoints:[{x:800,y:600}], speed:5), bravo(surface, waypoints:[{x:800,y:600}], speed:5)], mission_type:"patrol", formation:"independent".

EXAMPLE 3 — "Eagle one, orbit over position 500 300 at 200 meters":
assets: [eagle-1(air, waypoints:[{x:500,y:300}], speed:15, altitude:200, drone_pattern:"orbit")], mission_type:"aerial_recon".

EXAMPLE 4 — "All vessels move to 100 100":
assets: [alpha(surface, waypoints:[{x:100,y:100}], speed:5), bravo(surface, waypoints:[{x:100,y:100}], speed:5), charlie(surface, waypoints:[{x:100,y:100}], speed:5)], mission_type:"patrol", formation:"independent".

EXAMPLE 5 — "Search the northern area":
Generate reasonable waypoints in the operating area, e.g. assets: [alpha(surface, waypoints:[{x:400,y:1500}], speed:5), bravo(surface, waypoints:[{x:800,y:1500}], speed:5)], mission_type:"search"."""


def test_connection() -> bool:
    """Ping Ollama to verify it's running."""
    try:
        r = httpx.get("http://localhost:11434/api/tags", timeout=5.0)
        return r.status_code == 200
    except Exception:
        return False


class LLMTimeoutError(Exception):
    """Raised when LLM inference exceeds the timeout."""
    pass


def _chat_with_timeout(messages, timeout_seconds=LLM_TIMEOUT_SECONDS, temperature=0):
    """Call ollama chat() with a thread-based timeout."""
    result = {}
    error = {}

    def _run():
        try:
            result["response"] = chat(
                model=MODEL,
                messages=messages,
                format=FleetCommand.model_json_schema(),
                options={"temperature": temperature},
            )
        except Exception as e:
            error["exc"] = e

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)

    if thread.is_alive():
        raise LLMTimeoutError(
            f"LLM inference timed out after {timeout_seconds}s"
        )
    if "exc" in error:
        raise error["exc"]
    return result["response"]


# Retry hint appended on 2nd and 3rd attempts
_RETRY_HINTS = [
    "",
    "\nIMPORTANT: Your previous response was invalid. Please ensure your response is valid JSON matching the schema exactly. Use only asset IDs from the roster.",
    "\nCRITICAL: Respond with ONLY valid JSON. asset_id must be one of: alpha, bravo, charlie, eagle-1. All waypoints must have numeric x and y fields.",
]


def parse_fleet_command(natural_language: str) -> FleetCommand:
    """Parse natural language into a FleetCommand via local LLM.

    Retries up to 3 times on failure with varied prompts. Raises on total failure.
    """
    last_error = None
    for attempt in range(3):
        try:
            user_content = natural_language + _RETRY_HINTS[attempt]
            temperature = 0 if attempt == 0 else 0.1 * attempt

            response = _chat_with_timeout(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=temperature,
            )
            command = FleetCommand.model_validate_json(response.message.content)
            command.raw_text = natural_language
            return command
        except LLMTimeoutError:
            raise  # Don't retry timeouts
        except Exception as e:
            logger.warning("LLM parse attempt %d failed: %s", attempt + 1, e)
            last_error = e
    raise RuntimeError(f"Failed after 3 attempts: {last_error}")
