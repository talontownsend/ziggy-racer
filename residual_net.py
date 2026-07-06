#!/usr/bin/env python3
"""Residual corrector net for the FH6 follower (residual policy learning).

A tiny MLP that outputs a SMALL bounded TRIM on top of the hand-built follower's nominal
control. The stable base controller makes the residual safe to train; the net only nudges,
so even a bad candidate can't wreck the farm. Trained on lap time by black-box optimization
(evolution strategy) -- see train_residual.py.

GLOBAL by construction: every input is car-relative / physical (speeds, accelerations, angular
rates, attitude, per-wheel grip) or LINE-relative (cross-track distance, heading error, curvature
ahead) -- NEVER absolute position / world heading / track station / lap number. So it learns the
CAR's corrective dynamics ("at this slip + understeer, trim steer this way"), which transfer to
any track. numpy-only, sub-millisecond forward pass for the control loop.
"""
import numpy as np

# (name, center, scale): normalized = clip((raw - center)/scale, -4, 4) -> ~[-1, 1] for the tanh.
FEATURE_SPEC = [
    # --- car dynamics (car-local / physical) ---
    ("speed_mps",   35.0, 35.0),   # 0..70 m/s
    ("ax_mss",       0.0, 25.0),   # lateral accel m/s^2 (~2.5 g) = measured lateral grip
    ("ay_mss",       9.8, 12.0),   # vertical accel (gravity + downforce load)
    ("az_mss",       0.0, 25.0),   # longitudinal accel (brake -/throttle +)
    ("vel_x",        0.0,  5.0),   # lateral velocity, car-local (sideways slide)
    ("vel_y",        0.0,  3.0),   # vertical velocity
    ("angvel_x",     0.0,  1.0),   # roll rate rad/s
    ("angvel_y",     0.0,  1.0),   # yaw rate rad/s
    ("angvel_z",     0.0,  1.0),   # pitch rate rad/s
    ("pitch",        0.0,  0.25),  # rad
    ("roll",         0.0,  0.25),  # rad
    ("rpm_frac",     0.6,  0.4),   # rpm / max_rpm (powerband position)
    ("gear",         5.0,  5.0),
    # --- per-wheel grip state (understeer = front cslip high; oversteer = rear high) ---
    ("cslip_fl",     1.0,  1.0),   # combined slip ~1.0 = friction limit
    ("cslip_fr",     1.0,  1.0),
    ("cslip_rl",     1.0,  1.0),
    ("cslip_rr",     1.0,  1.0),
    ("drive_slip",   1.0,  1.0),   # follower's computed drive slip
    ("sideslip_deg", 0.0, 15.0),   # car slip angle (deg)
    # --- line-relative state (the 4 sparse curvature samples are REPLACED by the 3D preview below) ---
    ("cte",          0.0,  4.0),   # cross-track offset (DISTANCE to racing line, signed)
    ("cte_dot",      0.0,  8.0),   # d(cte)/dt -- lateral drift rate toward/away from line
    ("alpha",        0.0,  0.4),   # heading error to the lookahead point (rad)
    ("fc_frac",      0.5,  0.5),   # friction-circle headroom (0..1)
    ("v_err",        0.0, 10.0),   # target_v - speed (m/s)
    ("vcurve",      35.0, 35.0),   # corner-speed cap (m/s)
    # --- the follower's NOMINAL output (so the net knows what it is trimming) ---
    ("nom_steer",    0.0,  1.0),
    ("nom_thr",      0.5,  0.5),
    ("nom_brk",      0.2,  0.5),
]
# --- 3D PREVIEW (the vision): per left/right/line point at 15/30/50/80 m ahead, the car-frame
#     (forward, lateral, vertical) offset + total 3D distance = 48 features. Replaces the old sparse
#     curvature samples + current-point edge margins. Order MUST match track_features.boundary_preview3d. ---
for _d in (15, 30, 50, 80):
    for _nm in ("L", "R", "C"):
        FEATURE_SPEC += [(f"{_nm}{_d}_fwd", float(_d), 40.0), (f"{_nm}{_d}_lat", 0.0, 12.0),
                         (f"{_nm}{_d}_vert", 0.0, 8.0), (f"{_nm}{_d}_dist", float(_d), 40.0)]
FEATURE_NAMES = [n for n, _, _ in FEATURE_SPEC]
CENTERS = np.array([c for _, c, _ in FEATURE_SPEC], float)
SCALES = np.array([s for _, _, s in FEATURE_SPEC], float)
N_FEAT = len(FEATURE_SPEC)


class ResidualNet:
    """MLP: N_FEAT -> n_hidden (tanh) -> 3 (tanh * bounds). Output = [d_steer, d_throttle, d_brake].
    Zero weights => zero residual (a no-op == today's follower). Set per-output bound to 0 to
    disable that control (e.g. bounds=(0.15, 0, 0) for steer-only)."""

    def __init__(self, n_hidden=16, bounds=(0.15, 0.20, 0.20)):
        self.n_in = N_FEAT
        self.n_hidden = int(n_hidden)
        self.bounds = np.asarray(bounds, float)
        self.W1 = np.zeros((self.n_in, self.n_hidden))
        self.b1 = np.zeros(self.n_hidden)
        self.W2 = np.zeros((self.n_hidden, 3))
        self.b2 = np.zeros(3)

    @property
    def n_params(self):
        return self.W1.size + self.b1.size + self.W2.size + self.b2.size

    def get_flat(self):
        return np.concatenate([self.W1.ravel(), self.b1, self.W2.ravel(), self.b2])

    def set_flat(self, v):
        v = np.asarray(v, float)
        i = 0
        for arr_name, shape in (("W1", self.W1.shape), ("b1", self.b1.shape),
                                ("W2", self.W2.shape), ("b2", self.b2.shape)):
            n = int(np.prod(shape))
            setattr(self, arr_name, v[i:i + n].reshape(shape))
            i += n
        return self

    def forward(self, raw):
        """raw: length-N_FEAT array in FEATURE_SPEC order. Returns [d_steer, d_throttle, d_brake]."""
        x = (np.asarray(raw, float) - CENTERS) / SCALES
        x = np.clip(x, -4.0, 4.0)
        h = np.tanh(x @ self.W1 + self.b1)
        return np.tanh(h @ self.W2 + self.b2) * self.bounds

    def save(self, path):
        np.savez(path, W1=self.W1, b1=self.b1, W2=self.W2, b2=self.b2, bounds=self.bounds)

    def load(self, path):
        d = np.load(path)
        self.W1, self.b1, self.W2, self.b2 = d["W1"], d["b1"], d["W2"], d["b2"]
        if "bounds" in d:
            self.bounds = d["bounds"]
        self.n_hidden = self.b1.size
        return self


if __name__ == "__main__":
    net = ResidualNet(n_hidden=16)
    print(f"features: {N_FEAT}  params: {net.n_params}")
    z = net.forward(np.zeros(N_FEAT))
    print(f"zero weights -> residual {z} (must be all 0 == no-op)")
    rng = np.random.default_rng(0)
    net.set_flat(rng.normal(0, 0.5, net.n_params))
    out = net.forward(rng.normal(0, 1, N_FEAT))
    print(f"random weights -> residual {np.round(out,4)} (bounded by {net.bounds})")
    flat = net.get_flat(); net2 = ResidualNet(16).set_flat(flat)
    print(f"flat round-trip exact: {np.allclose(net2.get_flat(), flat)}")
