"""
FleetManager — Central coordinator for multi-domain fleet simulation.
Owns all assets, steps the simulation, bridges commands to the right
physics engine by domain (CORALL for surface, DroneAgent for air).
"""
import math
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
from src.utils.gps_denied import degrade_position
from src.fleet.drone_coordinator import DroneCoordinator
from src.fleet.formations import apply_formation

METERS_TO_NMI = 1.0 / 1852.0
SAT_AMP = 20  # actuator saturation amplitude


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

        # Mission tracking
        self.active_mission: MissionType | None = None
        self.formation = FormationType.INDEPENDENT
        self.comms_lost_behavior: str = "return_to_base"

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
        return self.contacts.pop(contact_id, None) is not None

    # ------------------------------------------------------------------
    # Command dispatch
    # ------------------------------------------------------------------
    def dispatch_command(self, cmd: FleetCommand):
        self.active_mission = cmd.mission_type
        self.formation = cmd.formation
        self.comms_lost_behavior = cmd.comms_lost_behavior

        # --- Apply formation offsets for surface vessels ---
        surface_cmds = [ac for ac in cmd.assets
                        if ac.domain == DomainType.SURFACE and ac.asset_id in self.vessels]
        formation_positions: Dict[str, Waypoint] | None = None
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
                v["status"] = AssetStatus.EXECUTING if adjusted_wps else AssetStatus.IDLE

            elif ac.domain == DomainType.AIR and ac.asset_id == self.drone.asset_id:
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

    # ------------------------------------------------------------------
    # Simulation step
    # ------------------------------------------------------------------
    def step(self, dt: float):
        # Surface vessels
        for vid, v in self.vessels.items():
            state = v["state"]
            x_nmi = state[0] * METERS_TO_NMI
            y_nmi = state[1] * METERS_TO_NMI

            wpts_x = v["waypoints_x"]
            wpts_y = v["waypoints_y"]
            i_wpt = v["i_wpt"]

            if v["status"] in (AssetStatus.EXECUTING, AssetStatus.RETURNING) and i_wpt > 0:
                i_wpt = waypoint_selection(wpts_x, wpts_y, x_nmi, y_nmi, i_wpt)
                v["i_wpt"] = i_wpt

                # Check if we've passed the last waypoint
                if i_wpt >= len(wpts_x):
                    v["status"] = AssetStatus.IDLE
                    v["i_wpt"] = len(wpts_x) - 1
                    inputs = [0.0, 0.0]
                    x_dot = vessel_dynamics(state, inputs)
                    v["state"] = integration(state, x_dot, dt)
                    continue

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
            else:
                # Idle — no thrust, let vessel drift/stop
                inputs = [0.0, 0.0]

            x_dot = vessel_dynamics(state, inputs)
            v["state"] = integration(state, x_dot, dt)

        # Contacts — straight-line motion
        for contact in self.contacts.values():
            contact.x += contact.speed * math.cos(contact.heading) * dt
            contact.y += contact.speed * math.sin(contact.heading) * dt

        # Drone
        self.drone.step(dt)

    # ------------------------------------------------------------------
    # State query
    # ------------------------------------------------------------------
    def get_fleet_state(self) -> FleetState:
        assets: List[AssetState] = []

        for vid, v in self.vessels.items():
            s = v["state"]
            x, y = float(s[0]), float(s[1])
            accuracy = 1.0

            if self.gps_mode == GpsMode.DEGRADED:
                x, y, accuracy = degrade_position(x, y, self.noise_meters)

            assets.append(AssetState(
                asset_id=vid,
                domain=DomainType.SURFACE,
                x=x,
                y=y,
                heading=(90 - math.degrees(s[2])) % 360,
                speed=float(s[5]),
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
                "gps_mode": self.gps_mode,
                "position_accuracy": acc,
            })
        assets.append(drone_state)

        return FleetState(
            timestamp=time.time(),
            assets=assets,
            active_mission=self.active_mission,
            formation=self.formation,
            gps_mode=self.gps_mode,
            contacts=list(self.contacts.values()),
        )

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
        self.gps_mode = mode
        self.noise_meters = noise_meters
