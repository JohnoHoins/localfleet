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
    FleetCommand, FleetState, AssetState, AssetCommand,
    DomainType, AssetStatus, GpsMode, MissionType, Waypoint, FormationType,
)
from src.dynamics.vessel_dynamics import vessel_dynamics
from src.dynamics.controller import controller
from src.dynamics.actuator_modeling import actuator_modeling
from src.dynamics.drone_dynamics import DroneAgent
from src.core.integration import integration
from src.navigation.planning import waypoint_selection, planning
from src.utils.gps_denied import degrade_position

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

        # GPS mode
        self.gps_mode = GpsMode.FULL
        self.noise_meters = 25.0

        # Mission tracking
        self.active_mission: MissionType | None = None
        self.formation = FormationType.INDEPENDENT

    # ------------------------------------------------------------------
    # Command dispatch
    # ------------------------------------------------------------------
    def dispatch_command(self, cmd: FleetCommand):
        self.active_mission = cmd.mission_type
        self.formation = cmd.formation

        for ac in cmd.assets:
            if ac.domain == DomainType.SURFACE and ac.asset_id in self.vessels:
                v = self.vessels[ac.asset_id]
                # Build waypoint lists in nmi; prepend current position as wp 0
                cur = v["state"]
                wpts_x = [cur[0] * METERS_TO_NMI]
                wpts_y = [cur[1] * METERS_TO_NMI]
                for wp in ac.waypoints:
                    wpts_x.append(wp.x * METERS_TO_NMI)
                    wpts_y.append(wp.y * METERS_TO_NMI)
                v["waypoints_x"] = wpts_x
                v["waypoints_y"] = wpts_y
                v["i_wpt"] = 1 if len(ac.waypoints) > 0 else 0
                v["desired_speed"] = ac.speed
                v["status"] = AssetStatus.EXECUTING if ac.waypoints else AssetStatus.IDLE

            elif ac.domain == DomainType.AIR and ac.asset_id == self.drone.asset_id:
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

            if v["status"] == AssetStatus.EXECUTING and i_wpt > 0:
                i_wpt = waypoint_selection(wpts_x, wpts_y, x_nmi, y_nmi, i_wpt)
                v["i_wpt"] = i_wpt

                # Check if we've passed the last waypoint
                if i_wpt >= len(wpts_x):
                    v["status"] = AssetStatus.IDLE
                    v["i_wpt"] = len(wpts_x) - 1
                    i_wpt = v["i_wpt"]

                psi_desired = planning(wpts_x, wpts_y, x_nmi, y_nmi, i_wpt)
                if psi_desired is None:
                    psi_desired = state[2]

                tau_c, v_c, ui_psi1 = controller(
                    psi_desired, state[2], state[3],
                    v["desired_speed"], state[4], v["ui_psi1"], dt,
                )
                v["ui_psi1"] = ui_psi1
                tau_ac = actuator_modeling(tau_c, SAT_AMP)
                inputs = [tau_ac, v_c]
            else:
                # Idle — no thrust, let vessel drift/stop
                inputs = [0.0, 0.0]

            x_dot = vessel_dynamics(state, inputs)
            v["state"] = integration(state, x_dot, dt)

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
                heading=math.degrees(s[2]) % 360,
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
        )

    # ------------------------------------------------------------------
    # GPS mode control
    # ------------------------------------------------------------------
    def set_gps_mode(self, mode: GpsMode, noise_meters: float = 25.0):
        self.gps_mode = mode
        self.noise_meters = noise_meters
