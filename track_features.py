#!/usr/bin/env python3
"""Track-geometry preview features for the learned controller (the residual NN's 'vision').

Given the car pose (x, z, world heading) and its station i0 on the plan, sample the LEFT edge,
RIGHT edge, and racing LINE at several distances ahead ALONG THE TRACK, and express each as a
(forward, lateral) offset in the CAR'S LOCAL FRAME. This is global/track-agnostic (purely
relative geometry) and tells the net the actual shape of the track unrolling ahead -- where it
bends, where it pinches -- not just point-curvature. Used BOTH offline (derive from logged pose +
the static plan) and live (the follower computes it each tick to feed the net).

Layout per distance d (6 values): [Lfwd, Llat, Rfwd, Rlat, Cfwd, Clat]
  fwd = longitudinal distance ahead (shrinks as the track bends away);
  lat = lateral offset (+=left of the car's heading). On a straight, L.lat~+halfwidth,
  R.lat~-halfwidth, C.lat~0, and fwd~d. In a corner the points swing to one side.
"""
import numpy as np

DISTS = (15.0, 30.0, 50.0, 80.0)          # meters ahead along the track
N_PREVIEW = len(DISTS) * 6                  # 24 features


def cumlen(line):
    """Cumulative arc length along the closed plan line (len == len(line))."""
    return np.r_[0.0, np.cumsum(np.hypot(np.diff(line[:, 0]), np.diff(line[:, 1])))]


def boundary_preview(x, z, heading, i0, line, left, right, clen, dists=DISTS):
    """Return a flat list of len(dists)*6 car-frame offsets (see module docstring)."""
    n = len(line)
    Ltot = clen[-1]
    ch, sh = np.cos(heading), np.sin(heading)
    base = clen[int(i0) % n]
    out = []
    for d in dists:
        s = int(np.searchsorted(clen, (base + d) % Ltot) % n)
        for arr in (left, right, line):
            dx = arr[s, 0] - x
            dz = arr[s, 1] - z
            out.append(dx * ch + dz * sh)      # forward (along heading)
            out.append(-dx * sh + dz * ch)     # lateral (+ = left)
    return out


# normalization (center, scale) for the 24 preview features, repeated per distance.
# fwd ~ d (0..80 m); lat ~ track half-width (~ +-15 m). Generic, track-agnostic.
def preview_spec():
    spec = []
    for d in DISTS:
        for name in ("L", "R", "C"):
            spec.append((f"{name}{int(d)}_fwd", d, 40.0))     # forward ~ d, scale 40
            spec.append((f"{name}{int(d)}_lat", 0.0, 12.0))   # lateral ~ 0 +- width
    return spec


# ---- 3D PREVIEW (the running corrector's vision) ----
# Per left/right/line point at each distance ahead: CAR-FRAME (forward, lateral, vertical) offset
# + total 3D distance. 4 dists * 3 curves * 4 = 48. Vertical uses the line elevation profile (edges
# approximated at line height, since left/right are stored x,z only). Car-relative -> transferable.
def boundary_preview3d(x, y, z, heading, i0, line, left, right, elev, clen, dists=DISTS):
    n = len(line); Ltot = clen[-1]
    ch, sh = np.cos(heading), np.sin(heading)
    base = clen[int(i0) % n]
    out = []
    for d in dists:
        s = int(np.searchsorted(clen, (base + d) % Ltot) % n)
        ey = float(elev[s])
        for arr in (left, right, line):
            dx = float(arr[s, 0]) - x; dz = float(arr[s, 1]) - z; dy = ey - y
            out.append(dx * ch + dz * sh)                            # forward (along heading)
            out.append(-dx * sh + dz * ch)                           # lateral (+ = left)
            out.append(dy)                                           # vertical (elevation diff)
            out.append(float(np.sqrt(dx * dx + dy * dy + dz * dz)))  # total 3D distance to the point
    return out


def preview3d_spec():
    """(name, center, scale) for the 48 features of boundary_preview3d, in the same order."""
    spec = []
    for d in DISTS:
        for nm in ("L", "R", "C"):
            spec += [(f"{nm}{int(d)}_fwd", float(d), 40.0), (f"{nm}{int(d)}_lat", 0.0, 12.0),
                     (f"{nm}{int(d)}_vert", 0.0, 8.0), (f"{nm}{int(d)}_dist", float(d), 40.0)]
    return spec


# ---- SFT/BC policy: shared feature assembly (follower + dataset MUST use this) + numpy forward ----
SFT_STATE_NAMES = ["speed", "vel_x", "vel_y", "vel_z", "angvel_x", "angvel_y", "angvel_z",
                   "pitch", "roll", "rpm_frac", "gear"]


def sft_features(speed, vel_x, vel_y, vel_z, angvel_x, angvel_y, angvel_z, pitch, roll, rpm, gear,
                 x, z, heading, i0, line, left, right, clen):
    """The 35-vector the SFT policy expects: 11 car-state + 24 boundary preview (line-invariant).
    rpm is RAW (normalized to /8000 here). heading must be the YAW-derived world heading (yaw_sign*yaw
    +yaw_offset) -- the same one build_bc_dataset.py used -- NOT the follower's velocity-derived heading."""
    state = [speed, vel_x, vel_y, vel_z, angvel_x, angvel_y, angvel_z, pitch, roll, rpm / 8000.0, gear]
    return state + boundary_preview(x, z, heading, i0, line, left, right, clen)


def load_bc_policy(path):
    d = np.load(path)
    return {k: d[k] for k in ("W0", "b0", "W1", "b1", "W2", "b2", "mean", "std")}


def bc_forward(p, feats):
    """numpy forward of the SFT MLP (35 -> 256 -> 256 -> 3): ReLU, ReLU, tanh(steer)/sigmoid(thr,brk)."""
    x = (np.asarray(feats, float) - p["mean"]) / p["std"]
    h0 = np.maximum(0.0, x @ p["W0"].T + p["b0"])
    h1 = np.maximum(0.0, h0 @ p["W1"].T + p["b1"])
    o = h1 @ p["W2"].T + p["b2"]
    return float(np.tanh(o[0])), float(1.0 / (1.0 + np.exp(-o[1]))), float(1.0 / (1.0 + np.exp(-o[2])))


if __name__ == "__main__":
    import os
    base = r"C:\Users\talon\FH6-AFK-Farm\recordings"
    d = np.load(os.path.join(base, "refline_plan.npz"))
    line, left, right = d["line"], d["left"], d["right"]
    clen = cumlen(line)
    print(f"plan: {len(line)} stations, lap length {clen[-1]:.0f} m, ~{clen[-1]/len(line):.2f} m/station")

    # pull a few real frames from the log (t,x,z,head_deg,i0): col 0,1,2,5,6
    rows = []
    for ln in open(os.path.join(base, "follow_log.csv")):
        c = ln.split(",")
        if len(c) < 49 or c[0] == "t":
            continue
        try:
            rows.append((float(c[1]), float(c[2]), float(c[5]), int(float(c[6])), float(c[3])))
        except ValueError:
            continue
    rows = rows[-4000::1500]   # a few spread-out frames
    for (x, z, hdeg, i0, spd) in rows:
        fv = boundary_preview(x, z, np.radians(hdeg), i0, line, left, right, clen)
        # show left/right/line LAT at each distance + fwd at 15 & 80
        lat = [round(fv[k*6+1], 1) for k in range(4)], [round(fv[k*6+3], 1) for k in range(4)], [round(fv[k*6+5], 1) for k in range(4)]
        print(f"\ni0={i0} spd={spd:.0f} hdg={hdeg:.0f}")
        print(f"  L.lat @15/30/50/80: {lat[0]}   R.lat: {lat[1]}   C.lat: {lat[2]}")
        print(f"  fwd @15: L={fv[0]:.1f} R={fv[2]:.1f}  | @80: L={fv[18]:.1f} R={fv[20]:.1f}  (straight->fwd~d, lat~+-width; corner->fwd<d, lat swings)")
