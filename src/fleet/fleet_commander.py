"""
FleetCommander — Bridges natural language to FleetManager.
Two-tier command parsing: fast deterministic parser for structured commands
(< 1ms), with LLM fallback for ambiguous natural language.
Shadow verification runs the LLM in background to confirm fast parse results.
"""
import logging
import os
import re
import threading
import time
from typing import TYPE_CHECKING

from src.schemas import (
    FleetCommand, CommandRequest, CommandResponse, GpsMode, GpsDeniedRequest,
    AssetCommand, Waypoint, DomainType, MissionType, FormationType, DronePattern,
)
from src.llm.ollama_client import parse_fleet_command
from src.fleet.fleet_manager import FleetManager

if TYPE_CHECKING:
    from src.logging.mission_logger import MissionLogger

logger = logging.getLogger(__name__)

# Validation constants
VALID_ASSET_IDS = {"alpha", "bravo", "charlie", "eagle-1"}
MAX_RANGE = 5000  # meters — operating area bounds
MIN_SURFACE_SPEED = 1.0
MAX_SURFACE_SPEED = 10.0
MIN_AIR_SPEED = 5.0
MAX_AIR_SPEED = 25.0
MIN_ALTITUDE = 10.0
MAX_ALTITUDE = 500.0

# Shadow verification: LLM confirms fast parse in background
# Set LOCALFLEET_SHADOW_VERIFY=1 to enable
SHADOW_VERIFY = os.environ.get("LOCALFLEET_SHADOW_VERIFY", "0") == "1"


# ══════════════════════════════════════════════════════════════════════
# Fast deterministic parser — handles structured commands in <1ms
# Falls back to LLM for anything it can't confidently parse.
# ══════════════════════════════════════════════════════════════════════

_WORD_NUM = {
    'zero': 0, 'oh': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4,
    'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
    'eleven': 11, 'twelve': 12, 'thirteen': 13, 'fourteen': 14, 'fifteen': 15,
    'sixteen': 16, 'seventeen': 17, 'eighteen': 18, 'nineteen': 19, 'twenty': 20,
    'thirty': 30, 'forty': 40, 'fifty': 50,
}

# Contact name aliases — "bogey one" → "bogey-1", "bogey bravo" → "bogey-B"
_TARGET_SUFFIX = {
    'one': '1', 'two': '2', 'three': '3', 'four': '4', 'five': '5',
    'alpha': 'A', 'alfa': 'A', 'bravo': 'B', 'charlie': 'C', 'delta': 'D',
    'echo': 'E', 'foxtrot': 'F',
    'a': 'A', 'b': 'B', 'c': 'C', 'd': 'D',
}

_FORMATIONS = {
    'echelon': FormationType.ECHELON,
    'column': FormationType.COLUMN, 'single file': FormationType.COLUMN,
    'line abreast': FormationType.LINE_ABREAST, 'line': FormationType.LINE_ABREAST,
    'abreast': FormationType.LINE_ABREAST,
    'spread': FormationType.SPREAD, 'spread out': FormationType.SPREAD,
}

# Asset name resolution — voice might say any of these
_ASSET_ALIASES = {
    'alpha': 'alpha', 'alfa': 'alpha',
    'bravo': 'bravo',
    'charlie': 'charlie',
    'eagle': 'eagle-1', 'eagle one': 'eagle-1', 'eagle 1': 'eagle-1',
    'eagle-1': 'eagle-1', 'drone': 'eagle-1', 'the drone': 'eagle-1',
}

# Mission type aliases — variations people actually say
_MISSION_ALIASES = {
    'patrol': MissionType.PATROL, 'patrol to': MissionType.PATROL,
    'move to': MissionType.PATROL, 'move everyone': MissionType.PATROL,
    'navigate to': MissionType.PATROL, 'navigate': MissionType.PATROL,
    'head to': MissionType.PATROL, 'go to': MissionType.PATROL,
    'proceed to': MissionType.PATROL, 'transit to': MissionType.PATROL,
    'send to': MissionType.PATROL, 'deploy to': MissionType.PATROL,
    'search': MissionType.SEARCH, 'search area': MissionType.SEARCH,
    'sweep': MissionType.SEARCH, 'scan': MissionType.SEARCH,
    'search the area': MissionType.SEARCH,
    'intercept': MissionType.INTERCEPT, 'engage': MissionType.INTERCEPT,
    'go after': MissionType.INTERCEPT, 'converge on': MissionType.INTERCEPT,
    'loiter': MissionType.LOITER, 'orbit': MissionType.LOITER,
    'hold at': MissionType.LOITER, 'circle': MissionType.LOITER,
    'station at': MissionType.LOITER,
    'escort': MissionType.ESCORT, 'escort the': MissionType.ESCORT,
    'aerial recon': MissionType.AERIAL_RECON, 'recon': MissionType.AERIAL_RECON,
    'reconnaissance': MissionType.AERIAL_RECON,
}

# Standing orders phrasing
_STANDING_ORDERS = {
    'hold_position': [
        'hold position standing order', 'hold position on comms',
        'hold if comms', 'stop on comms loss', 'hold on comms loss',
    ],
    'continue_mission': [
        'continue mission standing order', 'continue mission on comms',
        'keep going on comms', 'continue on comms loss', 'continue if comms',
    ],
    'return_to_base': [
        'return to base standing order', 'rtb standing order',
        'return on comms loss', 'rtb on comms',
    ],
}


def _extract_numbers(text: str) -> list[float]:
    """Pull numbers from text — digits or word-numbers. Splits after thousand/hundred."""
    tokens = text.lower().replace(',', ' ').split()
    nums: list[float] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i].rstrip('.')
        # Digit?
        try:
            nums.append(float(tok))
            i += 1
            continue
        except ValueError:
            pass
        # Word-number?
        if tok in _WORD_NUM:
            val = _WORD_NUM[tok]
            i += 1
            if i < len(tokens) and tokens[i] == 'thousand':
                val *= 1000
                i += 1
            elif i < len(tokens) and tokens[i] == 'hundred':
                val *= 100
                i += 1
            nums.append(float(val))
        else:
            i += 1
    return nums


def _resolve_target(text: str, contacts: dict) -> str | None:
    """Map voice target names to live contact IDs.

    Handles: 'bogey one' → 'bogey-1', 'bogey bravo' → 'bogey-B',
    'contact alpha' → 'contact-A', 'bogey-1' → 'bogey-1', etc.
    """
    # Try multiple patterns for finding the target name after action words
    for pattern in (
        r'(?:intercept|engage|go after|converge on|track)\s+([\w][\w-]*(?:\s+\w+)?)',
        r'(?:target|contact|bogey|hostile)\s+([\w][\w-]*(?:\s+\w+)?)',
    ):
        m = re.search(pattern, text)
        if m:
            raw = m.group(1).strip()
            # Remove trailing formation/speed words
            for noise in ('in', 'at', 'with', 'formation', 'echelon', 'column'):
                if raw.endswith(' ' + noise):
                    raw = raw[:-(len(noise) + 1)]
            break
    else:
        return None

    # Direct match
    if raw in contacts:
        return raw

    # "bogey one" → "bogey-1", "bogey bravo" → "bogey-B"
    parts = raw.split()
    if len(parts) >= 2:
        base = parts[0]
        suffix = parts[-1]
        # Try name alias
        if suffix in _TARGET_SUFFIX:
            candidate = f"{base}-{_TARGET_SUFFIX[suffix]}"
            if candidate in contacts:
                return candidate
        # Try word-number
        if suffix in _WORD_NUM:
            candidate = f"{base}-{_WORD_NUM[suffix]}"
            if candidate in contacts:
                return candidate

    # Fuzzy: any contact whose ID matches with dashes/spaces normalized
    normalized = raw.replace(' ', '-').replace('_', '-')
    for cid in contacts:
        if normalized == cid or raw.replace(' ', '') == cid.replace('-', ''):
            return cid

    # Partial match: "bogey b" matches "bogey-B"
    for cid in contacts:
        if raw.replace(' ', '-').lower() == cid.lower():
            return cid

    return None


def _resolve_assets(text: str) -> tuple[list[str], bool] | None:
    """Determine which assets the command targets.

    Returns (surface_ids, include_drone) or None if can't determine.
    """
    t = text.lower()
    all_surface = list(["alpha", "bravo", "charlie"])

    # ── Fleet-wide scope ──
    if any(p in t for p in (
        'all assets', 'all vessels and drone', 'entire fleet',
        'fleet wide', 'everyone', 'everything', 'the fleet',
    )):
        return all_surface, True

    if any(p in t for p in (
        'all vessels', 'all ships', 'all surface', 'all boats',
        'the vessels', 'surface fleet', 'the ships',
    )):
        return all_surface, False

    # ── Implied fleet scope (bare command with no asset named) ──
    # If the command starts with a mission verb and has no specific asset,
    # assume all surface + drone
    if re.match(r'^(patrol|search|intercept|engage|loiter|escort|go|move|head|proceed|sweep|scan)\b', t):
        return all_surface, True

    # ── Individual or subset ──
    found_surface = []
    found_drone = False

    # Check for named assets
    for alias, asset_id in _ASSET_ALIASES.items():
        # Use word boundaries to avoid "eagle" matching inside other words
        if re.search(r'\b' + re.escape(alias) + r'\b', t):
            if asset_id == 'eagle-1':
                found_drone = True
            elif asset_id not in found_surface:
                found_surface.append(asset_id)

    if found_surface or found_drone:
        return found_surface, found_drone

    # ── Implied "send the fleet" / bare command ──
    if any(p in t for p in ('send ', 'move ', 'dispatch ')):
        return all_surface, True

    return None


def try_fast_parse(text: str, fleet_manager: "FleetManager") -> FleetCommand | None:
    """Instant parse for structured commands. Returns None → LLM fallback.

    Handles:
    - Fleet/asset scope: "all assets", "all vessels", "alpha", "alpha and bravo",
      "eagle one", "the drone"
    - Missions: patrol, search, intercept, loiter, escort, recon + aliases
      (move to, go to, sweep, engage, orbit, circle, etc.)
    - Formations: echelon, column, line abreast, spread
    - Coordinates: digits (2000 1000) and words (two thousand one thousand)
    - Speed: "at 5 meters per second", "at five m/s", "speed 8"
    - Standing orders: "with hold position standing orders", "continue mission on comms loss"
    - Intercept targets: "bogey one", "bogey-1", "bogey bravo", "contact alpha"
    """
    t = text.lower().strip()

    # ── Assets ──
    asset_result = _resolve_assets(t)
    if not asset_result:
        return None
    surface_ids, with_drone = asset_result

    # ── Mission ──
    mission = None
    # Check longest aliases first to avoid partial matches
    for alias in sorted(_MISSION_ALIASES, key=len, reverse=True):
        if alias in t:
            mission = _MISSION_ALIASES[alias]
            break
    if not mission:
        return None

    # ── Formation ──
    formation = FormationType.INDEPENDENT
    for key in sorted(_FORMATIONS, key=len, reverse=True):
        if key in t:
            formation = _FORMATIONS[key]
            break

    # ── Standing orders ──
    clb = 'return_to_base'
    for behavior, phrases in _STANDING_ORDERS.items():
        if any(p in t for p in phrases):
            clb = behavior
            break

    # ── Speed ──
    speed = 5.0
    # "at N meters per second" / "at N m/s"
    sp = re.search(r'at\s+(\S+)\s+(?:meters?\s*(?:per\s*)?second|m/?s)', t)
    if sp:
        try:
            speed = float(sp.group(1))
        except ValueError:
            speed = float(_WORD_NUM.get(sp.group(1), 5))
    else:
        # "speed N" / "at speed N"
        sp = re.search(r'(?:speed|spd)\s+(\S+)', t)
        if sp:
            try:
                speed = float(sp.group(1))
            except ValueError:
                speed = float(_WORD_NUM.get(sp.group(1), 5))
        # "at N knots" (1 knot ≈ 0.514 m/s)
        sp = re.search(r'at\s+(\S+)\s+knots?', t)
        if sp:
            try:
                speed = float(sp.group(1)) * 0.514
            except ValueError:
                speed = float(_WORD_NUM.get(sp.group(1), 10)) * 0.514
    speed = max(MIN_SURFACE_SPEED, min(MAX_SURFACE_SPEED, speed))

    # ── Altitude (drone) ──
    altitude = 100.0
    alt = re.search(r'at\s+(\S+)\s+(?:meters?|m)\s*(?:altitude|alt|high)', t)
    if not alt:
        alt = re.search(r'altitude\s+(\S+)', t)
    if alt:
        try:
            altitude = float(alt.group(1))
        except ValueError:
            altitude = float(_WORD_NUM.get(alt.group(1), 100))
        altitude = max(MIN_ALTITUDE, min(MAX_ALTITUDE, altitude))

    # ── Waypoint / target ──
    if mission == MissionType.INTERCEPT:
        target_id = _resolve_target(t, fleet_manager.contacts)
        if not target_id:
            return None  # can't find contact → LLM
        contact = fleet_manager.contacts[target_id]
        wp = Waypoint(x=contact.x, y=contact.y)
    else:
        # Strip speed/altitude phrases so their numbers don't pollute coordinates
        coord_text = t
        for pattern in (
            r'at\s+\S+\s+meters?\s*(?:per\s*)?second',
            r'at\s+\S+\s+m/?s',
            r'at\s+\S+\s+knots?',
            r'(?:speed|spd)\s+\S+',
            r'at\s+\S+\s+(?:meters?|m)\s*(?:altitude|alt|high)',
            r'altitude\s+\S+',
        ):
            coord_text = re.sub(pattern, '', coord_text)
        nums = _extract_numbers(coord_text)
        if len(nums) < 2:
            return None  # not enough coords → LLM
        wp = Waypoint(x=nums[0], y=nums[1])

    # ── Build asset commands ──
    surface = [
        AssetCommand(asset_id=vid, domain=DomainType.SURFACE,
                     waypoints=[wp], speed=speed)
        for vid in surface_ids
    ]

    drone_pattern = {
        MissionType.PATROL: DronePattern.ORBIT,
        MissionType.SEARCH: DronePattern.SWEEP,
        MissionType.LOITER: DronePattern.ORBIT,
        MissionType.ESCORT: DronePattern.ORBIT,
        MissionType.INTERCEPT: DronePattern.TRACK,
        MissionType.AERIAL_RECON: DronePattern.ORBIT,
    }.get(mission, DronePattern.ORBIT)

    drone = [AssetCommand(
        asset_id='eagle-1', domain=DomainType.AIR,
        waypoints=[wp], speed=15.0, altitude=altitude,
        drone_pattern=drone_pattern,
    )] if with_drone else []

    return FleetCommand(
        mission_type=mission,
        assets=surface + drone,
        formation=formation,
        comms_lost_behavior=clb,
        raw_text=text,
    )


# ── Shadow LLM verification ──────────────────────────────────────────

def _shadow_verify(text: str, fast_cmd: FleetCommand):
    """Background LLM verification of a fast-parsed command.
    Logs agreement or discrepancy — never overrides the fast parse."""
    try:
        llm_cmd = parse_fleet_command(text)
        mismatches = []
        if llm_cmd.mission_type != fast_cmd.mission_type:
            mismatches.append(f"mission: fast={fast_cmd.mission_type} llm={llm_cmd.mission_type}")
        if llm_cmd.formation != fast_cmd.formation:
            mismatches.append(f"formation: fast={fast_cmd.formation} llm={llm_cmd.formation}")
        fast_ids = sorted(a.asset_id for a in fast_cmd.assets)
        llm_ids = sorted(a.asset_id for a in llm_cmd.assets)
        if fast_ids != llm_ids:
            mismatches.append(f"assets: fast={fast_ids} llm={llm_ids}")
        if mismatches:
            logger.warning("Shadow mismatch: '%s' → %s", text[:60], "; ".join(mismatches))
        else:
            logger.debug("Shadow OK: '%s'", text[:60])
    except Exception as e:
        logger.debug("Shadow LLM failed: %s", e)


def validate_command(command: FleetCommand) -> list[str]:
    """Validate and sanitize a parsed FleetCommand. Returns list of warnings."""
    warnings = []

    # Filter out invalid asset IDs
    valid_assets = []
    for ac in command.assets:
        if ac.asset_id not in VALID_ASSET_IDS:
            warnings.append(f"Unknown asset_id '{ac.asset_id}' removed")
            continue
        valid_assets.append(ac)
    command.assets = valid_assets

    for ac in command.assets:
        # Clamp waypoints to operating area
        for wp in ac.waypoints:
            clamped_x = max(-MAX_RANGE, min(MAX_RANGE, wp.x))
            clamped_y = max(-MAX_RANGE, min(MAX_RANGE, wp.y))
            if clamped_x != wp.x or clamped_y != wp.y:
                warnings.append(
                    f"{ac.asset_id}: waypoint ({wp.x}, {wp.y}) clamped to ({clamped_x}, {clamped_y})"
                )
                wp.x = clamped_x
                wp.y = clamped_y

        # Clamp speed based on domain
        if ac.domain == DomainType.SURFACE:
            original = ac.speed
            ac.speed = max(MIN_SURFACE_SPEED, min(MAX_SURFACE_SPEED, ac.speed))
            if ac.speed != original:
                warnings.append(f"{ac.asset_id}: speed clamped {original} → {ac.speed}")
        elif ac.domain == DomainType.AIR:
            original = ac.speed
            ac.speed = max(MIN_AIR_SPEED, min(MAX_AIR_SPEED, ac.speed))
            if ac.speed != original:
                warnings.append(f"{ac.asset_id}: speed clamped {original} → {ac.speed}")

            # Clamp altitude for air assets
            if ac.altitude is not None:
                original = ac.altitude
                ac.altitude = max(MIN_ALTITUDE, min(MAX_ALTITUDE, ac.altitude))
                if ac.altitude != original:
                    warnings.append(
                        f"{ac.asset_id}: altitude clamped {original} → {ac.altitude}"
                    )

    return warnings


class FleetCommander:
    def __init__(
        self,
        fleet_manager: FleetManager | None = None,
        logger: "MissionLogger | None" = None,
    ):
        self.fleet_manager = fleet_manager or FleetManager()
        self.last_command: FleetCommand | None = None
        self.logger = logger

    def handle_command(self, request: CommandRequest) -> CommandResponse:
        """Parse NL text into FleetCommand and dispatch to fleet manager.
        Tries fast deterministic parser first; falls back to LLM."""
        t0 = time.time()
        try:
            command = try_fast_parse(request.text, self.fleet_manager)
            if command:
                logger.info("Fast parse: %s → %s", request.text[:60], command.mission_type)
                if SHADOW_VERIFY:
                    threading.Thread(
                        target=_shadow_verify,
                        args=(request.text, command),
                        daemon=True,
                    ).start()
            else:
                logger.info("LLM parse: %s", request.text[:60])
                command = parse_fleet_command(request.text)
            elapsed_ms = (time.time() - t0) * 1000.0

            # Validate and sanitize the parsed command
            warnings = validate_command(command)
            for w in warnings:
                logger.warning("Command validation: %s", w)

            if not command.assets:
                return CommandResponse(
                    success=False,
                    error="No valid assets in command after validation",
                    llm_response_time_ms=elapsed_ms,
                )

            self.fleet_manager.dispatch_command(command)
            self.last_command = command

            if self.logger:
                self.logger.log_command(command)

            # Build dispatch summary
            activated = [ac.asset_id for ac in command.assets]
            summary_parts = [f"Activated: {', '.join(activated)}"]
            if warnings:
                summary_parts.append(f"Warnings: {'; '.join(warnings)}")
            summary = ". ".join(summary_parts)

            return CommandResponse(
                success=True,
                fleet_command=command,
                llm_response_time_ms=elapsed_ms,
                error=summary if warnings else None,
            )
        except Exception as e:
            elapsed_ms = (time.time() - t0) * 1000.0
            return CommandResponse(
                success=False,
                error=str(e),
                llm_response_time_ms=elapsed_ms,
            )

    def handle_text(self, text: str) -> CommandResponse:
        """Convenience: accept raw string instead of CommandRequest."""
        return self.handle_command(CommandRequest(text=text))

    def handle_gps_mode(self, request: GpsDeniedRequest):
        """Toggle GPS degradation on the fleet manager."""
        self.fleet_manager.set_gps_mode(request.mode, request.noise_meters)
        if self.logger:
            self.logger.log_gps_change(request.mode, request.noise_meters)

    def return_to_base(self):
        """Trigger comms_lost_behavior: return all assets to base."""
        self.fleet_manager.return_to_base()

    def step(self, dt: float = 0.25):
        """Advance the simulation one tick."""
        self.fleet_manager.step(dt)

    def get_state(self):
        """Get current fleet state."""
        return self.fleet_manager.get_fleet_state()

    def get_state_dict(self) -> dict:
        """Get fleet state as dict with threat data included."""
        return self.fleet_manager.get_fleet_state_dict()
