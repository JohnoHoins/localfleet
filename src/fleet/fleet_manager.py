"""
FleetManager — Central coordinator for multi-domain fleet simulation.
Owns all assets, steps the simulation, bridges commands to the right
physics engine by domain (CORALL for surface, DroneAgent for air).
"""
import math
import os
import time
import numpy as np
from typing import Dict, List

from src.schemas import (
    FleetCommand, FleetState, AssetState, AssetCommand, Contact,
    DomainType, AssetStatus, GpsMode, MissionType, Waypoint, FormationType,
    DronePattern,
)
from src.dynamics.vessel_dynamics import vessel_dynamics
from src.dynamics.controller import controller
from src.dynamics.actuator_modeling import actuator_modeling
from src.dynamics.drone_dynamics import DroneAgent
from src.core.integration import integration
from src.navigation.planning import waypoint_selection, planning
from src.navigation.land_check import land_repulsion_heading, is_on_land
from src.utils.gps_denied import degrade_position, DeadReckoningState, dead_reckon_step, get_navigated_position
from src.fleet.drone_coordinator import DroneCoordinator
from src.fleet.formations import apply_formation
from src.fleet.threat_detector import assess_threats, ThreatAssessment
from src.fleet.drone_sensor import drone_detect_contacts, TargetingData
from src.fleet.decision_log import DecisionLog

METERS_TO_NMI = 1.0 / 1852.0
SAT_AMP = 20  # actuator saturation amplitude
REPLAN_INTERVAL_STEPS = 40  # 10 seconds at 4Hz
REPLAN_SHIFT_THRESHOLD = 100.0  # meters — only update if intercept drifted this much
THREAT_CHECK_INTERVAL = 4  # Check threats every 4 steps (~1 second at 4Hz)
SIM_DT = 0.25              # nominal sim step (4Hz)
# Sim-seconds of comms denial before autonomous engagement (configurable)
ESCALATION_SECONDS = float(os.environ.get("LOCALFLEET_ESCALATION_SECONDS", "60"))
ESCALATION_STEPS = int(round(ESCALATION_SECONDS / SIM_DT))
CONVERGE_RANGE = 1000.0    # meters — kill chain ENGAGE -> CONVERGE
INTERCEPT_RANGE = 200.0    # meters — target counts as intercepted
GPS_BLEND_SECONDS = 5.0
ESCORT_LEAD_M = 100.0      # meters — escorts steer for a point this far ahead of station


def compute_intercept_point(fleet_x: float, fleet_y: float, fleet_speed: float,
                            target_x: float, target_y: float, target_heading: float,
                            target_speed: float) -> tuple[float, float]:
    """Iterative proportional navigation — predict where the target will be
    when the fleet arrives and return that point."""
    if fleet_speed <= 0:
        return (target_x, target_y)

    pred_x, pred_y = target_x, target_y
    for _ in range(3):
        dist = math.sqrt((pred_x - fleet_x) ** 2 + (pred_y - fleet_y) ** 2)
        if dist < 1.0:
            break
        t = dist / fleet_speed
        pred_x = target_x + target_speed * math.cos(target_heading) * t
        pred_y = target_y + target_speed * math.sin(target_heading) * t
    return (pred_x, pred_y)


class FleetManager:
    def __init__(self):
        # Surface vessels: state = [x, y, psi, r, b, u]
        self.vessels: Dict[str, dict] = {}
        vessel_configs = [
            ("alpha",   0.0,   0.0),
            ("bravo",   200.0, 0.0),
            ("charlie", 400.0, 0.0),
        ]
        for vid, x0, y0 in vessel_configs:
            self.vessels[vid] = {
                "state": np.array([x0, y0, 0.0, 0.0, 0.0, 0.0]),
                "ui_psi1": 0.0,
                "waypoints_x": [x0 * METERS_TO_NMI],  # nmi — start position
                "waypoints_y": [y0 * METERS_TO_NMI],
                "i_wpt": 0,
                "desired_speed": 0.0,
                "cmd_speed": 0.0,
                "sog": 0.0,  # actual speed over ground (m/s)
                "status": AssetStatus.IDLE,
            }

        # Drone
        self.drone = DroneAgent("eagle-1", x=200.0, y=-100.0, altitude=100.0)
        self.drone_coordinator = DroneCoordinator(self.drone)

        # Home positions for return-to-base
        self.home_positions: Dict[str, Waypoint] = {
            vid: Waypoint(x=x0, y=y0) for vid, x0, y0 in vessel_configs
        }
        self.home_positions["eagle-1"] = Waypoint(x=200.0, y=-100.0)

        # Contacts (simulated targets in the operating area)
        self.contacts: Dict[str, Contact] = {}

        # GPS mode
        self.gps_mode = GpsMode.FULL
        self.noise_meters = 25.0

        # Dead reckoning states (per surface vessel, used in DENIED mode)
        self.dr_states: Dict[str, DeadReckoningState] = {}
        for vid, x0, y0 in vessel_configs:
            self.dr_states[vid] = DeadReckoningState(estimated_x=x0, estimated_y=y0)

        # Mission tracking
        self.active_mission: MissionType | None = None
        self.formation = FormationType.INDEPENDENT
        self.comms_lost_behavior: str = "return_to_base"
        self._replan_counter: int = 0

        # Threat detection state
        self.threat_assessments: List[ThreatAssessment] = []
        self.intercept_recommended: bool = False
        self.recommended_target: str | None = None
        self._threat_check_counter: int = 0

        # Kill chain state
        self.kill_chain_phase: str | None = None
        self.kill_chain_target: str | None = None
        self.targeting_data: TargetingData | None = None

        # Comms mode
        self.comms_mode: str = "full"
        self.comms_denied_since: float | None = None
        self.last_command: FleetCommand | None = None
        self.autonomous_actions: list[str] = []
        self.escalation_steps: int = ESCALATION_STEPS

        # Escort tracking
        self._escort_target_id: str | None = None
        self._escort_vessels: list[str] = []

        # Set by hold_position standing orders; cleared by the next command
        self._holding_position: bool = False

        # Surface vessels taking part in the current formation (leader first)
        self._formation_vessels: list[str] = []

        # Targets the fleet has already closed to INTERCEPT_RANGE
        self._intercepted_targets: set[str] = set()

        # Comms-denied fallback one-shot guard
        self._comms_fallback_executed: bool = False
        self._comms_denied_steps: int = 0

        # GPS blend state for smooth restore: per-vessel (dx, dy) offset of
        # the DR estimate from truth at the moment GPS came back. The offset
        # fades to zero over GPS_BLEND_SECONDS so nothing snaps.
        self._gps_blend_alpha: float = 1.0
        self._gps_blending: bool = False
        self._gps_blend_offsets: Dict[str, tuple[float, float]] = {}

        # Decision audit trail
        self.decision_log = DecisionLog()

        # De-duplication guards for decision log (prevent spam)
        self._last_logged_threat_level: Dict[str, str] = {}
        self._last_logged_kc_phase: str | None = None
        self._drone_tracking_contact: str | None = None

    # ------------------------------------------------------------------
    # Contact (target) management
    # ------------------------------------------------------------------
    def spawn_contact(self, contact_id: str, x: float, y: float,
                      heading: float, speed: float,
                      domain: DomainType = DomainType.SURFACE) -> Contact:
        """Create a simulated target moving through the operating area."""
        contact = Contact(
            contact_id=contact_id, x=x, y=y,
            heading=heading, speed=speed, domain=domain,
        )
        self.contacts[contact_id] = contact
        return contact

    def remove_contact(self, contact_id: str) -> bool:
        """Remove a contact by ID. Returns True if it existed."""
        self._last_logged_threat_level.pop(contact_id, None)
        self._intercepted_targets.discard(contact_id)
        if self._drone_tracking_contact == contact_id:
            self._drone_tracking_contact = None
        return self.contacts.pop(contact_id, None) is not None

    # ------------------------------------------------------------------
    # Command dispatch
    # ------------------------------------------------------------------
    def dispatch_command(self, cmd: FleetCommand):
        self._holding_position = False
        self.last_command = cmd
        self.active_mission = cmd.mission_type
        self.formation = cmd.formation
        # None = command didn't mention standing orders; keep the current ones
        if cmd.comms_lost_behavior is not None:
            self.comms_lost_behavior = cmd.comms_lost_behavior
        self._replan_counter = 0

        # --- Predictive intercept: replace surface waypoints with predicted point ---
        if cmd.mission_type == MissionType.INTERCEPT and self.contacts:
            # Find closest contact to fleet centroid
            surface_cmds = [ac for ac in cmd.assets
                            if ac.domain == DomainType.SURFACE and ac.asset_id in self.vessels]
            if surface_cmds:
                cx = np.mean([self.vessels[ac.asset_id]["state"][0] for ac in surface_cmds])
                cy = np.mean([self.vessels[ac.asset_id]["state"][1] for ac in surface_cmds])
                fleet_speed = surface_cmds[0].speed if surface_cmds[0].speed > 0 else 8.0

                # Pick closest contact
                target = min(self.contacts.values(),
                             key=lambda c: (c.x - cx) ** 2 + (c.y - cy) ** 2)
                pred_x, pred_y = compute_intercept_point(
                    cx, cy, fleet_speed,
                    target.x, target.y, target.heading, target.speed,
                )

                # Log intercept solution
                dist = math.sqrt((pred_x - cx)**2 + (pred_y - cy)**2)
                eta = dist / fleet_speed if fleet_speed > 0 else 0
                lead = math.sqrt((pred_x - target.x)**2 + (pred_y - target.y)**2)
                self.decision_log.log(
                    "intercept_solution",
                    f"Intercept: ({pred_x:.0f}, {pred_y:.0f})",
                    f"Target {target.contact_id} at ({target.x:.0f}, {target.y:.0f}) "
                    f"hdg {math.degrees(target.heading):.0f}° spd {target.speed:.1f}m/s. "
                    f"Fleet centroid ({cx:.0f}, {cy:.0f}). ETA {eta:.0f}s. Lead {lead:.0f}m.",
                    confidence=min(1.0, fleet_speed / max(target.speed, 0.1)),
                    assets=[ac.asset_id for ac in surface_cmds],
                )

                # Replace surface vessel waypoints with predicted intercept point
                for ac in cmd.assets:
                    if ac.domain == DomainType.SURFACE and ac.asset_id in self.vessels:
                        ac.waypoints = [Waypoint(x=pred_x, y=pred_y)]

        # --- Apply formation offsets for surface vessels ---
        surface_cmds = [ac for ac in cmd.assets
                        if ac.domain == DomainType.SURFACE and ac.asset_id in self.vessels]
        formation_positions: Dict[str, Waypoint] | None = None
        self._formation_vessels = [ac.asset_id for ac in surface_cmds]
        if (cmd.formation != FormationType.INDEPENDENT
                and len(surface_cmds) >= 2
                and surface_cmds[0].waypoints):
            # Use leader's first waypoint as formation reference
            leader = surface_cmds[0]
            leader_wp = leader.waypoints[-1]  # final destination
            leader_v = self.vessels[leader.asset_id]
            leader_heading = (90 - math.degrees(leader_v["state"][2])) % 360
            vessel_ids = [ac.asset_id for ac in surface_cmds]
            formation_positions = apply_formation(
                leader_wp.x, leader_wp.y, leader_heading,
                vessel_ids, cmd.formation, cmd.spacing_meters,
            )

        # --- Mission-specific waypoint generation ---
        if cmd.mission_type == MissionType.SEARCH:
            # Generate zigzag pattern from center waypoint
            for ac in cmd.assets:
                if ac.domain == DomainType.SURFACE and ac.waypoints:
                    center = ac.waypoints[0]
                    idx = [a.asset_id for a in cmd.assets
                           if a.domain == DomainType.SURFACE].index(ac.asset_id)
                    ac.waypoints = self._generate_search_pattern(
                        center.x, center.y,
                        lateral_offset=idx * cmd.spacing_meters
                    )

        self._escort_vessels = []
        self._escort_target_id = None
        if cmd.mission_type == MissionType.ESCORT and self.contacts:
            # Store closest contact as escort target
            surface_xs = [self.vessels[ac.asset_id]["state"][0]
                          for ac in cmd.assets
                          if ac.domain == DomainType.SURFACE and ac.asset_id in self.vessels]
            surface_ys = [self.vessels[ac.asset_id]["state"][1]
                          for ac in cmd.assets
                          if ac.domain == DomainType.SURFACE and ac.asset_id in self.vessels]
            if surface_xs:
                cx, cy = np.mean(surface_xs), np.mean(surface_ys)
                closest = min(self.contacts.values(),
                              key=lambda c: (c.x - cx)**2 + (c.y - cy)**2)
                self._escort_target_id = closest.contact_id
                self._escort_vessels = [ac.asset_id for ac in cmd.assets
                                        if ac.domain == DomainType.SURFACE
                                        and ac.asset_id in self.vessels]

        if cmd.mission_type == MissionType.AERIAL_RECON:
            # Drone gets wide SWEEP, surface vessels get holding position
            for ac in cmd.assets:
                if ac.domain == DomainType.AIR and ac.waypoints:
                    center = ac.waypoints[0] if ac.waypoints else Waypoint(x=1000, y=1000)
                    sw = Waypoint(x=center.x - 500, y=center.y - 500)
                    ne = Waypoint(x=center.x + 500, y=center.y + 500)
                    ac.waypoints = [sw, ne]
                    ac.drone_pattern = DronePattern.SWEEP
                    ac.altitude = 150.0
                elif ac.domain == DomainType.SURFACE and ac.waypoints:
                    # Surface holds 500m south of recon area
                    center = ac.waypoints[0]
                    ac.waypoints = [Waypoint(x=center.x, y=center.y - 500)]

        for ac in cmd.assets:
            if ac.domain == DomainType.SURFACE and ac.asset_id in self.vessels:
                v = self.vessels[ac.asset_id]
                cur = v["state"]

                # Use formation-adjusted waypoints if available
                if formation_positions and ac.asset_id in formation_positions:
                    fp = formation_positions[ac.asset_id]
                    # Replace final waypoint with formation position
                    adjusted_wps = list(ac.waypoints[:-1]) + [Waypoint(x=fp.x, y=fp.y)] if ac.waypoints else []
                else:
                    adjusted_wps = list(ac.waypoints)

                # Build waypoint lists in nmi; prepend current position as wp 0
                wpts_x = [cur[0] * METERS_TO_NMI]
                wpts_y = [cur[1] * METERS_TO_NMI]
                for wp in adjusted_wps:
                    wpts_x.append(wp.x * METERS_TO_NMI)
                    wpts_y.append(wp.y * METERS_TO_NMI)
                v["waypoints_x"] = wpts_x
                v["waypoints_y"] = wpts_y
                v["i_wpt"] = 1 if len(adjusted_wps) > 0 else 0
                v["desired_speed"] = ac.speed
                v["cmd_speed"] = ac.speed
                v["status"] = AssetStatus.EXECUTING if adjusted_wps else AssetStatus.IDLE
                v["_loiter_orbit"] = False  # reset on new command

            elif ac.domain == DomainType.AIR and ac.asset_id == self.drone.asset_id:
                # For air assets with SWEEP pattern and only 1 waypoint,
                # generate a default sweep area around the center point
                if (ac.domain == DomainType.AIR
                        and ac.drone_pattern == DronePattern.SWEEP
                        and len(ac.waypoints) == 1):
                    center = ac.waypoints[0]
                    ac.waypoints = [
                        Waypoint(x=center.x - 500, y=center.y - 500),
                        Waypoint(x=center.x + 500, y=center.y + 500),
                    ]

                # Use DroneCoordinator for pattern-based commands when
                # enough waypoints are provided for the pattern type
                use_coordinator = (
                    ac.drone_pattern is not None
                    and ac.waypoints
                    and (ac.drone_pattern != DronePattern.SWEEP or len(ac.waypoints) >= 2)
                )
                if use_coordinator:
                    self.drone_coordinator.assign_pattern(
                        ac.drone_pattern, ac.waypoints,
                        altitude=ac.altitude or 100.0,
                    )
                else:
                    self.drone.set_waypoints(ac.waypoints, ac.drone_pattern)
                    if ac.altitude is not None:
                        self.drone.target_altitude = ac.altitude

        # Drone patterns for non-intercept missions
        if cmd.mission_type == MissionType.PATROL:
            wps = [ac.waypoints for ac in cmd.assets
                   if ac.domain == DomainType.SURFACE and ac.waypoints]
            if wps:
                all_wps = wps[0]
                cx = sum(w.x for w in all_wps) / len(all_wps)
                cy = sum(w.y for w in all_wps) / len(all_wps)
                self.drone_coordinator.assign_pattern(
                    DronePattern.ORBIT, [Waypoint(x=cx, y=cy)], altitude=100.0)

        if cmd.mission_type == MissionType.LOITER:
            wps = [ac.waypoints[-1] for ac in cmd.assets
                   if ac.domain == DomainType.SURFACE and ac.waypoints]
            if wps:
                self.drone_coordinator.assign_pattern(
                    DronePattern.ORBIT, [wps[0]], altitude=100.0)

    def _generate_search_pattern(self, center_x: float, center_y: float,
                                  width: float = 500.0, height: float = 500.0,
                                  legs: int = 6,
                                  lateral_offset: float = 0.0) -> list[Waypoint]:
        """Generate zigzag lawnmower search waypoints."""
        wps = []
        leg_spacing = height / legs
        half_w = width / 2
        for i in range(legs):
            y = center_y - height / 2 + i * leg_spacing
            if i % 2 == 0:
                wps.append(Waypoint(x=center_x - half_w + lateral_offset, y=y))
                wps.append(Waypoint(x=center_x + half_w + lateral_offset, y=y))
            else:
                wps.append(Waypoint(x=center_x + half_w + lateral_offset, y=y))
                wps.append(Waypoint(x=center_x - half_w + lateral_offset, y=y))
        return wps

    # ------------------------------------------------------------------
    # Intercept replanning
    # ------------------------------------------------------------------
    def _replan_intercept(self):
        """Recompute predicted intercept point and update surface vessel
        waypoints if the point has shifted significantly."""
        executing = {vid: v for vid, v in self.vessels.items()
                     if v["status"] == AssetStatus.EXECUTING}
        if not executing:
            return

        cx = np.mean([v["state"][0] for v in executing.values()])
        cy = np.mean([v["state"][1] for v in executing.values()])
        # Use first executing vessel's desired speed
        fleet_speed = next(iter(executing.values()))["desired_speed"]
        if fleet_speed <= 0:
            return

        target = min(self.contacts.values(),
                     key=lambda c: (c.x - cx) ** 2 + (c.y - cy) ** 2)

        # Prefer drone targeting data when available
        if self.targeting_data and self.targeting_data.locked:
            target_for_intercept_x = self.targeting_data.contact_x
            target_for_intercept_y = self.targeting_data.contact_y
        else:
            target_for_intercept_x = target.x
            target_for_intercept_y = target.y

        pred_x, pred_y = compute_intercept_point(
            cx, cy, fleet_speed,
            target_for_intercept_x, target_for_intercept_y,
            target.heading, target.speed,
        )

        # Only update if intercept point shifted more than threshold
        shifted_any = False
        max_shift = 0.0
        for vid, v in executing.items():
            wpts_x = v["waypoints_x"]
            wpts_y = v["waypoints_y"]
            if len(wpts_x) < 2:
                continue
            cur_wp_x = wpts_x[-1] / METERS_TO_NMI  # convert nmi back to meters
            cur_wp_y = wpts_y[-1] / METERS_TO_NMI
            shift = math.sqrt((pred_x - cur_wp_x) ** 2 + (pred_y - cur_wp_y) ** 2)
            if shift > REPLAN_SHIFT_THRESHOLD:
                wpts_x[-1] = pred_x * METERS_TO_NMI
                wpts_y[-1] = pred_y * METERS_TO_NMI
                shifted_any = True
                max_shift = max(max_shift, shift)

        if shifted_any:
            self.decision_log.log(
                "replan",
                f"Fleet waypoints replanned, shifted {max_shift:.0f}m",
                f"Target moving. Predicted intercept updated.",
            )

    def _update_formation_positions(self):
        """Continuously update follower waypoints to maintain formation."""
        if self.formation == FormationType.INDEPENDENT:
            return
        if self.active_mission is None:
            return
        # Don't override intercept waypoints — vessels converge on target
        if self.active_mission == MissionType.INTERCEPT:
            return

        # Only the vessels in the commanded formation take part; the leader
        # is the first of them (not necessarily alpha).
        vessel_ids = [vid for vid in self._formation_vessels if vid in self.vessels]
        if len(vessel_ids) < 2:
            return
        leader_id = vessel_ids[0]
        leader_v = self.vessels[leader_id]

        if leader_v["status"] != AssetStatus.EXECUTING:
            return

        leader_state = leader_v["state"]
        leader_x = float(leader_state[0])
        leader_y = float(leader_state[1])
        leader_heading_deg = (90 - math.degrees(float(leader_state[2]))) % 360

        cmd_spacing = 200.0
        if self.last_command:
            cmd_spacing = self.last_command.spacing_meters

        positions = apply_formation(
            leader_x, leader_y, leader_heading_deg,
            vessel_ids, self.formation, cmd_spacing,
        )

        for vid in vessel_ids[1:]:  # Skip leader
            v = self.vessels[vid]
            if v["status"] != AssetStatus.EXECUTING:
                continue
            wpts_x = v["waypoints_x"]
            wpts_y = v["waypoints_y"]
            if len(wpts_x) < 2:
                continue
            fp = positions[vid]
            wpts_x[-1] = fp.x * METERS_TO_NMI
            wpts_y[-1] = fp.y * METERS_TO_NMI

    def _escort_station(self, contact: Contact, slot: int,
                        spacing: float) -> tuple[float, float]:
        """Screening station around the escorted contact.

        Slot 0 takes the bow, then port beam, starboard beam, astern, and
        further rings outward. Stations are in the contact's frame so the
        screen turns with it.
        """
        ring = slot // 4 + 1
        fwd, left = [(1, 0), (0, 1), (0, -1), (-1, 0)][slot % 4]
        fwd *= spacing * ring
        left *= spacing * ring
        ch, sh = math.cos(contact.heading), math.sin(contact.heading)
        return (contact.x + fwd * ch - left * sh,
                contact.y + fwd * sh + left * ch)

    def _update_escort_positions(self):
        """Keep escorting vessels on station around the escort target.

        Vessels stay EXECUTING for as long as the target exists: each one
        steers for its screening station and matches the target's speed
        once it is there, instead of stopping when it first catches up.
        """
        if self.active_mission != MissionType.ESCORT or self._holding_position:
            return
        if not self._escort_target_id or self._escort_target_id not in self.contacts:
            return
        contact = self.contacts[self._escort_target_id]
        spacing = self.last_command.spacing_meters if self.last_command else 200.0
        for slot, vid in enumerate(self._escort_vessels):
            v = self.vessels.get(vid)
            if v is None or v["status"] == AssetStatus.RETURNING:
                continue
            sx, sy = self._escort_station(contact, slot, spacing)
            cur = v["state"]
            ch, sh = math.cos(contact.heading), math.sin(contact.heading)
            # Steer for a point on the station's track ahead of the station,
            # so the vessel rides alongside instead of circling it
            lead = max(ESCORT_LEAD_M, contact.speed * 60.0) if contact.speed > 0.1 else 0.0
            aim_x, aim_y = sx + lead * ch, sy + lead * sh
            # Speed from along-track error: catch up when behind the
            # station, ease off when ahead of it
            if contact.speed > 0.1:
                along = (sx - cur[0]) * ch + (sy - cur[1]) * sh
            else:
                along = math.hypot(sx - cur[0], sy - cur[1])
            max_speed = max(v["cmd_speed"], contact.speed + 2.0)
            v["desired_speed"] = max(0.5, min(max_speed, contact.speed + 0.05 * along))
            v["waypoints_x"] = [cur[0] * METERS_TO_NMI, aim_x * METERS_TO_NMI]
            v["waypoints_y"] = [cur[1] * METERS_TO_NMI, aim_y * METERS_TO_NMI]
            v["i_wpt"] = 1
            v["status"] = AssetStatus.EXECUTING

    # ------------------------------------------------------------------
    # Simulation step
    # ------------------------------------------------------------------
    def step(self, dt: float):
        # Escort tracking — update every threat check interval
        if (self.active_mission == MissionType.ESCORT
                and self._threat_check_counter == 0):
            self._update_escort_positions()

        # Formation tracking — update every threat check interval
        if self._threat_check_counter == 0:
            self._update_formation_positions()

        # Surface vessels
        for vid, v in self.vessels.items():
            state = v["state"]

            # Position the navigation system sees (DR estimate when denied,
            # noisy fix when degraded, blended back to truth after restore).
            # Physics and land avoidance always use the true state.
            nav_x, nav_y, _ = self._nav_position(vid)

            x_nmi = nav_x * METERS_TO_NMI
            y_nmi = nav_y * METERS_TO_NMI

            wpts_x = v["waypoints_x"]
            wpts_y = v["waypoints_y"]
            i_wpt = v["i_wpt"]
            inputs = [0.0, 0.0]  # idle — no thrust, let vessel drift/stop

            if v["status"] in (AssetStatus.EXECUTING, AssetStatus.RETURNING) and i_wpt > 0:
                i_wpt = waypoint_selection(wpts_x, wpts_y, x_nmi, y_nmi, i_wpt)
                v["i_wpt"] = i_wpt

                # Check if we've passed the last waypoint
                go_idle = False
                if i_wpt >= len(wpts_x):
                    # Mission-specific behavior at last waypoint (a vessel
                    # that is RETURNING always finishes at home)
                    mission = (self.active_mission
                               if v["status"] == AssetStatus.EXECUTING else None)
                    if mission in (MissionType.PATROL, MissionType.SEARCH):
                        formation_ids = [fid for fid in self._formation_vessels
                                         if fid in self.vessels]
                        is_leader = bool(formation_ids) and vid == formation_ids[0]
                        if len(wpts_x) <= 2 and (
                            self.formation == FormationType.INDEPENDENT
                            or is_leader
                        ):
                            # Single waypoint — swap start↔dest for out-and-back.
                            # Only for leader/independent; followers have their
                            # target continuously updated by formation tracking
                            # and never spiral.
                            wpts_x[0], wpts_x[1] = wpts_x[1], wpts_x[0]
                            wpts_y[0], wpts_y[1] = wpts_y[1], wpts_y[0]
                        v["i_wpt"] = 1
                        i_wpt = 1
                        # Fall through to navigation below
                    elif mission == MissionType.LOITER:
                        if not v.get("_loiter_orbit"):
                            # Generate orbit waypoints around loiter point
                            lx = wpts_x[-1] / METERS_TO_NMI
                            ly = wpts_y[-1] / METERS_TO_NMI
                            orbit_x = [v["state"][0] * METERS_TO_NMI]
                            orbit_y = [v["state"][1] * METERS_TO_NMI]
                            # Compensate for octagon inscribed radius
                            orbit_radius = 150.0 / math.cos(math.pi / 8)
                            for j in range(8):
                                angle = j * (2 * math.pi / 8)
                                orbit_x.append((lx + orbit_radius * math.cos(angle)) * METERS_TO_NMI)
                                orbit_y.append((ly + orbit_radius * math.sin(angle)) * METERS_TO_NMI)
                            v["waypoints_x"] = orbit_x
                            v["waypoints_y"] = orbit_y
                            v["i_wpt"] = 1
                            v["_loiter_orbit"] = True
                            i_wpt = 1
                            wpts_x = orbit_x
                            wpts_y = orbit_y
                        else:
                            # Already orbiting — loop
                            v["i_wpt"] = 1
                            i_wpt = 1
                    elif (mission == MissionType.ESCORT
                          and vid in self._escort_vessels
                          and self._escort_target_id in self.contacts):
                        # On station — keep screening the moving target.
                        # Station is refreshed by _update_escort_positions.
                        v["i_wpt"] = 1
                        i_wpt = 1
                    elif mission == MissionType.INTERCEPT and self.contacts:
                        # Contact still alive — continuous pursuit
                        target = min(self.contacts.values(),
                                     key=lambda c: (c.x - state[0])**2 + (c.y - state[1])**2)
                        dist = math.sqrt((target.x - state[0])**2 + (target.y - state[1])**2)
                        if dist > 50.0:
                            # Place waypoint 200m beyond contact to prevent
                            # waypoint_selection from immediately marking it reached
                            bearing = math.atan2(target.y - state[1], target.x - state[0])
                            lead_x = target.x + 200.0 * math.cos(bearing)
                            lead_y = target.y + 200.0 * math.sin(bearing)
                        else:
                            # Very close — aim at contact directly
                            lead_x = target.x
                            lead_y = target.y
                        v["desired_speed"] = 8.0  # pursuit speed
                        wpts_x_new = [state[0] * METERS_TO_NMI, lead_x * METERS_TO_NMI]
                        wpts_y_new = [state[1] * METERS_TO_NMI, lead_y * METERS_TO_NMI]
                        v["waypoints_x"] = wpts_x_new
                        v["waypoints_y"] = wpts_y_new
                        v["i_wpt"] = 1
                        i_wpt = 1
                        wpts_x = wpts_x_new
                        wpts_y = wpts_y_new
                    else:
                        # Default: go IDLE
                        v["status"] = AssetStatus.IDLE
                        v["i_wpt"] = len(wpts_x) - 1
                        go_idle = True

                if not go_idle:
                    psi_desired = planning(wpts_x, wpts_y, x_nmi, y_nmi, i_wpt)
                    if psi_desired is None:
                        psi_desired = state[2]

                    # Land avoidance — steer away if heading toward coastline
                    land_corr = land_repulsion_heading(
                        state[0], state[1], psi_desired, look_ahead=75.0,
                    )
                    psi_desired += land_corr

                    # Reduce speed when turning hard to prevent wide arcs
                    heading_err = abs((psi_desired - state[2] + np.pi) % (2 * np.pi) - np.pi)
                    speed_scale = max(0.3, 1.0 - 0.7 * heading_err / np.pi)
                    effective_speed = v["desired_speed"] * speed_scale

                    tau_c, v_c, ui_psi1 = controller(
                        psi_desired, state[2], state[3],
                        effective_speed, state[4], v["ui_psi1"], dt,
                    )
                    v["ui_psi1"] = ui_psi1
                    tau_ac = actuator_modeling(tau_c, SAT_AMP)
                    inputs = [tau_ac, v_c]

            x_dot = vessel_dynamics(state, inputs)
            new_state = integration(state, x_dot, dt)
            v["state"] = new_state

            # Actual motion this step — what a speed log + compass measure.
            # Reported speed and dead reckoning both use this, so the DR
            # error is exactly the modelled drift and nothing else.
            move_x = float(new_state[0] - state[0])
            move_y = float(new_state[1] - state[1])
            v["sog"] = math.hypot(move_x, move_y) / dt if dt > 0 else 0.0
            if self.gps_mode == GpsMode.DENIED:
                course = math.atan2(move_y, move_x) if v["sog"] > 0 else float(state[2])
                dead_reckon_step(self.dr_states[vid], v["sog"], course, dt)

        # Advance GPS blend alpha (once per step, not per vessel)
        if self._gps_blending:
            self._gps_blend_alpha += dt / GPS_BLEND_SECONDS
            if self._gps_blend_alpha >= 1.0:
                self._gps_blend_alpha = 1.0
                self._gps_blending = False
                self._gps_blend_offsets = {}
                # Finalize: reset DR states to true positions
                for vid, v in self.vessels.items():
                    s = v["state"]
                    self.dr_states[vid] = DeadReckoningState(
                        estimated_x=float(s[0]), estimated_y=float(s[1]),
                    )

        # Contacts — straight-line motion
        for contact in self.contacts.values():
            contact.x += contact.speed * math.cos(contact.heading) * dt
            contact.y += contact.speed * math.sin(contact.heading) * dt

        # Intercept replanning — update predicted intercept point every ~10s
        if (self.active_mission == MissionType.INTERCEPT
                and self.contacts
                and any(v["status"] == AssetStatus.EXECUTING for v in self.vessels.values())):
            self._replan_counter += 1
            if self._replan_counter >= REPLAN_INTERVAL_STEPS:
                self._replan_counter = 0
                self._replan_intercept()

        # Threat detection — check every ~1 second
        self._threat_check_counter += 1
        if self._threat_check_counter >= THREAT_CHECK_INTERVAL:
            self._threat_check_counter = 0
            self._check_threats()

        # Comms-denied autonomous behavior
        self._handle_comms_denied()

        # Kill chain progression
        self._advance_kill_chain()

        # Continuous drone tracking — update TRACK target position
        if (self.drone_coordinator._current_pattern == DronePattern.TRACK
                and self.kill_chain_target
                and self.kill_chain_target in self.contacts
                and self._threat_check_counter == 0):
            contact = self.contacts[self.kill_chain_target]
            self.drone_coordinator.assign_pattern(
                DronePattern.TRACK,
                [Waypoint(x=contact.x, y=contact.y)],
                altitude=100.0,
            )

        # Drone
        self.drone.step(dt)

    # ------------------------------------------------------------------
    # Kill chain state machine
    # ------------------------------------------------------------------
    def _advance_kill_chain(self):
        """Progress kill chain based on threat detector + drone sensor.

        DETECT -> TRACK -> LOCK -> ENGAGE -> CONVERGE. The chain stays on one
        target until that target is gone; once the fleet closes to
        INTERCEPT_RANGE the intercept is logged once and the chain holds at
        CONVERGE while the fleet shadows the target (it never restarts on a
        target it has already intercepted).
        """
        if not self.contacts:
            self.kill_chain_phase = None
            self.kill_chain_target = None
            self.targeting_data = None
            return

        old_phase = self.kill_chain_phase

        # Chain target left the area — drop the chain
        if (self.kill_chain_phase is not None
                and self.kill_chain_target not in self.contacts):
            lost = self.kill_chain_target
            self.kill_chain_phase = None
            self.kill_chain_target = None
            self._last_logged_kc_phase = None
            self.decision_log.log(
                "kill_chain_transition",
                f"Kill chain: {old_phase} → NONE",
                f"Target {lost} no longer tracked.",
            )
            old_phase = None

        # Run drone sensor
        drone_hdg_rad = math.radians(90 - self.drone.heading) % (2 * math.pi)
        detections = drone_detect_contacts(
            self.drone.x, self.drone.y, drone_hdg_rad, self.contacts
        )

        # Targeting data — while a chain is running only the chain target
        # counts; otherwise take the best detection.
        if self.kill_chain_phase is not None:
            detections = [d for d in detections
                          if d.contact_id == self.kill_chain_target]
        if detections:
            best = max(detections, key=lambda d: d.confidence)
            if (self.drone_coordinator._current_pattern == DronePattern.TRACK
                    and best.range_m < 3000.0):
                best = TargetingData(
                    contact_id=best.contact_id, bearing=best.bearing,
                    range_m=best.range_m, contact_x=best.contact_x,
                    contact_y=best.contact_y, confidence=best.confidence,
                    locked=True,
                )
            self.targeting_data = best
            if self.kill_chain_phase is None:
                self.kill_chain_target = best.contact_id
        else:
            self.targeting_data = None

        def closest_vessel_range(target: Contact) -> float:
            return min(
                math.hypot(v["state"][0] - target.x, v["state"][1] - target.y)
                for v in self.vessels.values()
            )

        # Phase transitions
        if self.kill_chain_phase is None:
            real_threats = [t for t in self.threat_assessments
                            if t.threat_level != "none"
                            and t.contact_id in self.contacts
                            and t.contact_id not in self._intercepted_targets]
            if real_threats:
                # Highest priority = closest
                top = min(real_threats, key=lambda t: t.distance)
                self.kill_chain_phase = "DETECT"
                self.kill_chain_target = top.contact_id

        elif self.kill_chain_phase == "DETECT":
            if self.drone_coordinator._current_pattern == DronePattern.TRACK:
                self.kill_chain_phase = "TRACK"

        elif self.kill_chain_phase == "TRACK":
            if self.targeting_data and self.targeting_data.locked:
                self.kill_chain_phase = "LOCK"

        elif self.kill_chain_phase == "LOCK":
            if self.active_mission == MissionType.INTERCEPT:
                self.kill_chain_phase = "ENGAGE"

        elif self.kill_chain_phase == "ENGAGE":
            target = self.contacts[self.kill_chain_target]
            if closest_vessel_range(target) < CONVERGE_RANGE:
                self.kill_chain_phase = "CONVERGE"

        elif self.kill_chain_phase == "CONVERGE":
            target = self.contacts[self.kill_chain_target]
            rng = closest_vessel_range(target)
            if (rng < INTERCEPT_RANGE
                    and target.contact_id not in self._intercepted_targets):
                self._intercepted_targets.add(target.contact_id)
                self.decision_log.log(
                    "intercept_complete",
                    f"INTERCEPTED: {target.contact_id}",
                    f"Fleet closed to {rng:.0f}m of {target.contact_id} at "
                    f"({target.x:.0f}, {target.y:.0f}). Shadowing target.",
                    assets=list(self.vessels.keys()),
                )

        if self.kill_chain_phase != old_phase and self.kill_chain_phase is not None:
            # Only log if the destination phase is genuinely new
            if self.kill_chain_phase != self._last_logged_kc_phase:
                self._last_logged_kc_phase = self.kill_chain_phase
                self.decision_log.log(
                    "kill_chain_transition",
                    f"Kill chain: {old_phase or 'NONE'} → {self.kill_chain_phase}",
                    f"Target: {self.kill_chain_target}. "
                    f"Drone {'locked' if self.targeting_data and self.targeting_data.locked else 'searching'}.",
                )

    # ------------------------------------------------------------------
    # Threat detection & auto-response
    # ------------------------------------------------------------------
    def _check_threats(self):
        """Run threat assessment and auto-retask drone if needed."""
        self.threat_assessments = assess_threats(self.vessels, self.contacts)

        # Reset recommendation flags
        self.intercept_recommended = False
        self.recommended_target = None

        # Don't auto-respond if fleet is actively executing an intercept
        active_intercept = (
            self.active_mission == MissionType.INTERCEPT
            and any(v["status"] == AssetStatus.EXECUTING for v in self.vessels.values())
        )

        for ta in self.threat_assessments:
            if ta.threat_level == "critical":
                self.intercept_recommended = True
                self.recommended_target = ta.contact_id

            if ta.threat_level in ("warning", "critical"):
                # Only log when threat level CHANGES for this contact
                prev_level = self._last_logged_threat_level.get(ta.contact_id)
                if prev_level != ta.threat_level:
                    self._last_logged_threat_level[ta.contact_id] = ta.threat_level
                    self.decision_log.log(
                        "threat_assessment",
                        f"{ta.contact_id}: {ta.threat_level.upper()} {ta.distance:.0f}m",
                        ta.reason,
                        confidence=1.0 - (ta.distance / 8000.0),
                    )

            if ta.threat_level in ("warning", "critical") and not active_intercept:
                # Auto-retask drone to TRACK if idle or not already tracking
                if self.drone.status in (AssetStatus.IDLE,) or (
                    self.drone.status == AssetStatus.EXECUTING
                    and self.drone_coordinator._current_pattern != DronePattern.TRACK
                ):
                    contact = self.contacts.get(ta.contact_id)
                    if contact:
                        self.drone_coordinator.assign_pattern(
                            DronePattern.TRACK,
                            [Waypoint(x=contact.x, y=contact.y)],
                            altitude=100.0,
                        )
                        self.drone.status = AssetStatus.EXECUTING
                        # Only log when drone starts tracking a NEW contact
                        if ta.contact_id != self._drone_tracking_contact:
                            self._drone_tracking_contact = ta.contact_id
                            self.decision_log.log(
                                "auto_track",
                                f"Eagle-1 → TRACK {ta.contact_id}",
                                f"Contact {ta.distance:.0f}m ({ta.threat_level}). Fleet "
                                f"{'idle' if not active_intercept else 'not intercepting'}. "
                                f"Drone fastest asset (15 m/s), aerial advantage.",
                                assets=["eagle-1"],
                            )

    # ------------------------------------------------------------------
    # State query
    # ------------------------------------------------------------------
    def _nav_position(self, vid: str) -> tuple[float, float, float]:
        """Position the vessel's navigation system believes it is at.

        Returns (x, y, accuracy_m). Used both for steering and for what the
        dashboard shows, so the operator sees exactly what the fleet sees.
        """
        s = self.vessels[vid]["state"]
        true_x, true_y = float(s[0]), float(s[1])
        if self.gps_mode == GpsMode.DENIED:
            dr = self.dr_states[vid]
            return dr.estimated_x, dr.estimated_y, max(1.0, dr.drift_error)

        if self.gps_mode == GpsMode.DEGRADED:
            x, y, accuracy = degrade_position(true_x, true_y, self.noise_meters)
        else:
            x, y, accuracy = true_x, true_y, 1.0

        # After GPS restore, fade the DR error out instead of snapping
        if self._gps_blending and vid in self._gps_blend_offsets:
            ox, oy = self._gps_blend_offsets[vid]
            remaining = 1.0 - self._gps_blend_alpha
            x += ox * remaining
            y += oy * remaining
            accuracy = max(accuracy, math.hypot(ox, oy) * remaining)
        return x, y, accuracy

    def get_fleet_state(self) -> FleetState:
        assets: List[AssetState] = []

        for vid, v in self.vessels.items():
            s = v["state"]
            x, y, accuracy = self._nav_position(vid)

            assets.append(AssetState(
                asset_id=vid,
                domain=DomainType.SURFACE,
                x=x,
                y=y,
                heading=(90 - math.degrees(s[2])) % 360,
                speed=v["sog"],
                status=v["status"],
                current_waypoint_index=v["i_wpt"],
                total_waypoints=len(v["waypoints_x"]) - 1,  # exclude start wp
                gps_mode=self.gps_mode,
                position_accuracy=accuracy,
            ))

        drone_state = self.drone.get_state()
        if self.gps_mode == GpsMode.DEGRADED:
            nx, ny, acc = degrade_position(drone_state.x, drone_state.y, self.noise_meters)
            drone_state = drone_state.model_copy(update={
                "x": nx, "y": ny,
                "position_accuracy": acc,
            })
        drone_state = drone_state.model_copy(update={"gps_mode": self.gps_mode})
        assets.append(drone_state)

        return FleetState(
            timestamp=time.time(),
            assets=assets,
            active_mission=self.active_mission,
            formation=self.formation,
            gps_mode=self.gps_mode,
            contacts=list(self.contacts.values()),
        )

    def get_fleet_state_dict(self) -> dict:
        """Get fleet state as dict with threat assessment data injected."""
        state = self.get_fleet_state()
        data = state.model_dump()

        # Inject threat assessment data
        data["threat_assessments"] = [
            {
                "contact_id": ta.contact_id,
                "distance": ta.distance,
                "bearing_deg": (90 - math.degrees(ta.bearing)) % 360,
                "closing_rate": ta.closing_rate,
                "threat_level": ta.threat_level,
                "recommended_action": ta.recommended_action,
                "reason": ta.reason,
            }
            for ta in self.threat_assessments
        ]
        data["intercept_recommended"] = self.intercept_recommended
        data["recommended_target"] = self.recommended_target
        data["decisions"] = self.decision_log.to_dicts(n=10)

        # Comms state — sim-time, so it lines up with the escalation delay
        elapsed = 0.0
        if self.comms_mode == "denied" and self.comms_denied_since:
            elapsed = self._comms_denied_steps * SIM_DT
        data["autonomy"] = {
            "comms_mode": self.comms_mode,
            "comms_denied_duration": elapsed,
            "comms_lost_behavior": self.comms_lost_behavior,
            "autonomous_actions": self.autonomous_actions[-10:],
            "kill_chain_phase": self.kill_chain_phase,
            "kill_chain_target": self.kill_chain_target,
        }
        if self.targeting_data:
            data["autonomy"]["targeting"] = {
                "contact_id": self.targeting_data.contact_id,
                "bearing_deg": (90 - math.degrees(self.targeting_data.bearing)) % 360,
                "range_m": self.targeting_data.range_m,
                "confidence": self.targeting_data.confidence,
                "locked": self.targeting_data.locked,
            }

        return data

    # ------------------------------------------------------------------
    # Return to base
    # ------------------------------------------------------------------
    def return_to_base(self):
        """Send all assets back to their starting positions."""
        for vid, v in self.vessels.items():
            home = self.home_positions[vid]
            cur = v["state"]
            dist = math.sqrt((cur[0] - home.x) ** 2 + (cur[1] - home.y) ** 2)
            if dist < 5.0:
                # Already at home — go idle immediately
                v["status"] = AssetStatus.IDLE
                v["desired_speed"] = 0.0
            else:
                wpts_x = [cur[0] * METERS_TO_NMI, home.x * METERS_TO_NMI]
                wpts_y = [cur[1] * METERS_TO_NMI, home.y * METERS_TO_NMI]
                v["waypoints_x"] = wpts_x
                v["waypoints_y"] = wpts_y
                v["i_wpt"] = 1
                v["desired_speed"] = 5.0
                v["status"] = AssetStatus.RETURNING

        home_drone = self.home_positions[self.drone.asset_id]
        drone_dist = math.sqrt(
            (self.drone.x - home_drone.x) ** 2 +
            (self.drone.y - home_drone.y) ** 2
        )
        if drone_dist < 5.0:
            self.drone.status = AssetStatus.IDLE
            self.drone.waypoints = []
        else:
            self.drone.set_waypoints([home_drone], None)
            self.drone.status = AssetStatus.RETURNING

        self.active_mission = None
        self.formation = FormationType.INDEPENDENT

    # ------------------------------------------------------------------
    # GPS mode control
    # ------------------------------------------------------------------
    def set_gps_mode(self, mode: GpsMode, noise_meters: float = 25.0):
        if mode == GpsMode.DENIED and self.gps_mode != GpsMode.DENIED:
            # Start DR from where navigation currently believes each vessel
            # is (true position, or mid-blend position if GPS was only just
            # restored) so the estimate doesn't jump.
            for vid, v in self.vessels.items():
                s = v["state"]
                x, y = float(s[0]), float(s[1])
                if self._gps_blending and vid in self._gps_blend_offsets:
                    ox, oy = self._gps_blend_offsets[vid]
                    remaining = 1.0 - self._gps_blend_alpha
                    x += ox * remaining
                    y += oy * remaining
                self.dr_states[vid] = DeadReckoningState(estimated_x=x, estimated_y=y)
            self._gps_blending = False
            self._gps_blend_alpha = 1.0
            self._gps_blend_offsets = {}
        elif mode != GpsMode.DENIED and self.gps_mode == GpsMode.DENIED:
            # Leaving DENIED mode — fade the DR error out over the blend window
            self._gps_blend_offsets = {}
            for vid, v in self.vessels.items():
                s = v["state"]
                dr = self.dr_states[vid]
                self._gps_blend_offsets[vid] = (
                    dr.estimated_x - float(s[0]), dr.estimated_y - float(s[1]),
                )
            self._gps_blending = True
            self._gps_blend_alpha = 0.0
        self.gps_mode = mode
        self.noise_meters = noise_meters

    # ------------------------------------------------------------------
    # Comms mode control
    # ------------------------------------------------------------------
    def set_comms_mode(self, mode: str):
        """Toggle comms mode between 'full' and 'denied'."""
        if mode == "denied" and self.comms_mode != "denied":
            self.comms_denied_since = time.time()
            self.autonomous_actions = []
            self._comms_fallback_executed = False
            self._comms_denied_steps = 0
            if not self._has_active_mission():
                self._execute_comms_fallback("idle_on_denial")
                # Standing orders already carried out for this episode
                self._comms_fallback_executed = True
        elif mode == "full" and self.comms_mode == "denied":
            duration = time.time() - (self.comms_denied_since or time.time())
            self.autonomous_actions.append(
                f"COMMS RESTORED after {duration:.0f}s"
            )
            self.comms_denied_since = None
        self.comms_mode = mode

    def _has_active_mission(self) -> bool:
        return any(v["status"] in (AssetStatus.EXECUTING, AssetStatus.RETURNING)
                   for v in self.vessels.values())

    def _handle_comms_denied(self):
        """Autonomous behavior when C2 link is down. Called from step()."""
        if self.comms_mode != "denied" or self.comms_denied_since is None:
            return
        self._comms_denied_steps += 1

        # Standing orders — fire once per denial episode
        if not self._comms_fallback_executed:
            behavior = self.comms_lost_behavior
            if behavior == "continue_mission":
                if not self._has_active_mission():
                    self._execute_comms_fallback("idle_during_denial")
            else:
                # hold_position and return_to_base ALWAYS execute
                self._execute_comms_fallback("comms_denied_standing_order")
            self._comms_fallback_executed = True

        # Level 3: auto-engage after escalation delay (sim-time based)
        if (self.intercept_recommended
                and self._comms_denied_steps >= self.escalation_steps
                and self.active_mission != MissionType.INTERCEPT):
            self._auto_engage_threat()

    def _execute_comms_fallback(self, trigger: str):
        """Execute comms_lost_behavior standing orders."""
        behavior = self.comms_lost_behavior
        self.decision_log.log(
            "comms_fallback",
            f"AUTO-{behavior.upper()}: {trigger}",
            f"Comms denied. Standing orders: {behavior}.",
            confidence=1.0,
        )
        if behavior == "return_to_base":
            # Check if already returning
            if any(v["status"] == AssetStatus.RETURNING for v in self.vessels.values()):
                return
            self.return_to_base()
            self.autonomous_actions.append(
                f"AUTO-RTB: {trigger}, standing orders = return_to_base"
            )
        elif behavior == "hold_position":
            self._holding_position = True
            for vid, v in self.vessels.items():
                if v["status"] in (AssetStatus.EXECUTING,):
                    v["status"] = AssetStatus.IDLE
                    v["desired_speed"] = 0.0
            self.autonomous_actions.append(
                f"AUTO-HOLD: {trigger}, standing orders = hold_position"
            )
        # "continue_mission" = do nothing

    def _auto_engage_threat(self):
        """Fully autonomous intercept — no human in the loop."""
        target_id = self.recommended_target
        if not target_id or target_id not in self.contacts:
            return
        # Guard: don't re-engage if already intercepting this target
        if (self.active_mission == MissionType.INTERCEPT
                and self.kill_chain_target == target_id):
            return
        contact = self.contacts[target_id]
        surface_cmds = []
        for vid in self.vessels:
            surface_cmds.append(AssetCommand(
                asset_id=vid, domain=DomainType.SURFACE,
                waypoints=[Waypoint(x=contact.x, y=contact.y)],
                speed=8.0,
            ))
        cmd = FleetCommand(
            mission_type=MissionType.INTERCEPT,
            assets=surface_cmds,
            formation=self.formation,
        )
        # Sim-time, so the number matches the escalation delay at any sim speed
        elapsed = self._comms_denied_steps * SIM_DT
        self.decision_log.log(
            "auto_engage",
            f"AUTO-INTERCEPT: {target_id}",
            f"Comms denied {elapsed:.0f}s. {target_id} critical range. "
            f"No operator. Timeout escalation.",
            confidence=0.7,
            assets=list(self.vessels.keys()) + ["eagle-1"],
        )
        self.dispatch_command(cmd)
        self.autonomous_actions.append(
            f"AUTO-INTERCEPT: {target_id} at ({contact.x:.0f}, {contact.y:.0f}) "
            f"— comms denied {elapsed:.0f}s, threat critical, no operator"
        )
