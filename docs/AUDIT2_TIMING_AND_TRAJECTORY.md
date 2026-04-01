# AUDIT 2: Timing, Speed & Trajectory — Why Vessels Loop and Never Leave Harbor

## Goal
Fix why vessels make wide loops/figure-8s, appear to never leave the harbor, and take unreasonably long to reach destinations or return to base.

## Context

The simulation physics chain is:

1. `src/navigation/planning.py` — `planning()` computes desired heading using cross-track error correction with a look-ahead distance `rho = 2200/1852 ≈ 1.19 NMI ≈ 2200m`.

2. `src/dynamics/controller.py` — PID yaw controller: `kp=100, kd=-500, ki=0`. Outputs `tau_c` (yaw torque).

3. `src/dynamics/actuator_modeling.py` — Saturates tau_c to ±20 (`SAT_AMP = 20`).

4. `src/dynamics/vessel_dynamics.py` — Nomoto model with:
   - `k_psi = 0.01` (rudder gain)
   - `t_psi = 30.0` (yaw time constant, seconds)
   - `k_v = 1.0, t_v = 50.0` (speed time constant)
   - Random yaw bias: `w_b = 0.5 * np.random.randn()` (noise injected EVERY tick)

5. `src/core/integration.py` — Euler integration: `x_new = x + x_dot * dt`

6. `src/fleet/fleet_manager.py:141` — `step()` runs the full chain every tick at dt=0.25s.

## Measured Behavior (from diagnostic runs)

### Speed ramp-up is fake
The vessel dynamics compute position as `x_dot = u_c * cos(psi)` where `u_c` is the **commanded** speed input, NOT the actual velocity state `u`. The speed state `u` has a 50-second time constant (takes ~150s to reach 95% of target), but this state is NEVER USED for position updates. Vessels instantly move at commanded speed (5 m/s).

### Turn rate is very slow
- Max actuator output: ±20 (hard-clamped by `actuator_modeling`)
- Max steady-state yaw rate: `r_ss = k_psi * SAT_AMP = 0.01 * 20 = 0.2 rad/s ≈ 11.5 deg/s`
- Time for 180° turn: ~16 seconds minimum
- Distance traveled during 180° turn at 5 m/s: ~80 meters
- **This creates the wide loops** — the vessel covers massive distance while slowly turning

### Waypoint acceptance circle is huge
- `Circ = 200/1852 NMI ≈ 108 meters` in waypoint_selection()
- A vessel goes IDLE when 108m from the waypoint — it never actually reaches the target
- For short missions (harbor patrol), 108m might be larger than the intended patrol path

### Yaw bias noise creates drift
- `w_b = 0.5 * np.random.randn()` is applied EVERY integration step (every 0.25s)
- This random walk in the bias term `b` causes persistent heading drift
- The bias time constant is `t_b = 20 * t_psi = 600 seconds` — once perturbed, it lingers
- Over a 160-second mission, accumulated bias can push the vessel 10-15m off track

### Return-to-base creates a wide loop
Measured trajectory returning from (500, 300) to home (0, 0):
- Vessel starts heading NE (psi ≈ 29°), but home is to the SW
- Takes 20+ seconds (100m) traveling the WRONG direction while turning
- Only after 40 seconds does it finally point toward home
- Total return time: 127 seconds for 583m (effective speed ~4.6 m/s)
- The initial loop looks like a figure-8 on the dashboard

### Real timing table
| Distance | Commanded Speed | Approx Time | Notes |
|----------|----------------|-------------|-------|
| 200m | 5 m/s | ~45s | Plus turn-around time if heading is wrong |
| 500m | 5 m/s | ~105s | 1.75 minutes |
| 1000m | 5 m/s | ~160s | 2.7 minutes, goes IDLE at ~800m due to acceptance circle |
| 2000m | 5 m/s | ~360s | 6 minutes |
| Add 180° turn | any | +16-25s | +80-125m of looping before course correction |

## Known Issues to Investigate and Fix

### A) The wide-loop / figure-8 turn problem (PRIMARY FIX)
When a vessel needs to change heading by more than ~45°, it makes a wide arc because it maintains full speed while slowly turning. Two options:

**Option A1 — Reduce speed during large heading errors:**
In `fleet_manager.py step()`, scale commanded speed by heading error:
```python
heading_error = abs(psi_desired - state[2])
# Wrap to [-pi, pi]
heading_error = (heading_error + np.pi) % (2 * np.pi) - np.pi
speed_scale = max(0.2, 1.0 - abs(heading_error) / np.pi)
effective_speed = v["desired_speed"] * speed_scale
```
This makes the vessel slow down when it needs to turn hard, producing tighter turns.

**Option A2 — Increase yaw responsiveness:**
In `vessel_dynamics.py`, reduce `t_psi` from 30 to 10-15 and/or increase `k_psi` from 0.01 to 0.03. This makes the rudder respond faster. BUT: this changes the CORALL-upstream physics model and may break COLREGs behavior.

**Option A3 — Both**: Speed scaling is the safest fix (doesn't touch physics). Optionally also tune t_psi if vessels still feel sluggish.

### B) Random yaw bias noise is too aggressive
In `vessel_dynamics.py:31`, `w_b = 0.5 * np.random.randn()` injects noise every 0.25s tick. Over 100 steps, this accumulates significant heading bias. Consider:
- Reducing magnitude to `0.1 * np.random.randn()` or less
- Making it proportional to dt: `0.5 * np.sqrt(dt) * np.random.randn()`
- Or removing it entirely for deterministic testing

### C) Waypoint acceptance circle may be too large for short missions
108m acceptance radius means the vessel goes IDLE when still 108m from target. For a harbor patrol with waypoints 300m apart, the vessel skips to the next waypoint before it's even close. Consider:
- Reducing `Circ` to `50/1852` (~50m) for tighter waypoint tracking
- Or making it proportional to speed: faster vessels get larger circles

### D) Cross-track error correction may cause oscillation near waypoints
In `planning.py`, the cross-track error term uses `rho = 2200/1852 ≈ 1.19 NMI`. When the vessel is very close to the waypoint, the bearing to waypoint flips rapidly while the cross-track correction lags. This can cause heading oscillation (wobble) near the target. Consider:
- Switching to pure pursuit (just steer toward the waypoint) when distance < 2*rho
- Or reducing rho to something smaller for tighter path following

### E) Heading angle wrapping may cause full-circle turns
The PID controller computes `e_psi = psi_p - psi` without wrapping to [-pi, pi]. If psi_p = -170° and psi = +170°, the error is -340° instead of +20°. The vessel turns 340° the wrong way instead of 20° the right way. Check if heading wrapping is needed in `controller.py`.

### F) vessel_dynamics uses u_c for position instead of u
`x_dot = u_c * cos(psi)` means the vessel has no speed dynamics — it instantly moves at commanded speed. The `u` state (with 50s time constant) is computed but never affects position. This should either:
- Use `u` for position: `x_dot = u * cos(psi)` (gives realistic speed ramp-up)
- Or document that instant speed is intentional and remove the unused u state

## Deliverables
1. Fix the wide-loop turn problem (Option A1 recommended — speed scaling)
2. Fix heading angle wrapping in the PID controller
3. Reduce or scale the yaw bias noise
4. Add a timing-aware test that verifies:
   - A vessel starting at heading 0° and targeting a waypoint at heading 180° does NOT travel more than 150m before pointing within 30° of the correct heading
   - A vessel completes a 500m return-to-base in under 200 seconds
   - A vessel's trajectory stays within 50m of the straight-line path for a simple 1000m transit
5. Add a `TIMING_REFERENCE.md` or docstring documenting the real speed/distance/time relationships for the simulation, so future sessions understand how long things actually take

## Files to Modify
- `src/fleet/fleet_manager.py` — speed scaling during turns (Issue A)
- `src/dynamics/controller.py` — heading angle wrapping (Issue E)
- `src/dynamics/vessel_dynamics.py` — yaw bias noise (Issue B), possibly speed state (Issue F)
- `src/navigation/planning.py` — possibly reduce acceptance circle (Issue C) and rho (Issue D)
- `tests/test_fleet_manager.py` — timing-aware trajectory tests
