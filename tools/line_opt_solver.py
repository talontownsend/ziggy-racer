#!/usr/bin/env python3
"""line_opt_solver.py -- min-lap-time racing line for Shimanoyama under MEASURED maps.

Reads (read-only):
  recordings/refline_plan.npz   line/left/right/speed/elev/grade (human 27.28s lap = 'line')
  recordings/surface_cap.npz    bank, zpp (surface grip modulation, build_surface_cap physics)
  recordings/steer_ff_map.npz   M[v_bin,kappa_bin] = |stick| to hold kappa at v (1.0 = saturated)
  recordings/tune.json          planner_alat / planner_alat_k / speed_cap (runtime grip model)

Writes (new file only):
  recordings/refline_plan_opt_candidate.npz  (same schema as refline_plan.npz)

Model: lateral offset e(s) on the 1000-station corridor axis; signed Menger curvature
smoothed w=5 (EXACTLY the runtime LocalPlanner kappa_ref recipe); velocity profile =
min(lat-grip cap w/ bank+crest load^0.705, steering-feasibility cap from steer_ff_map,
speed_cap) then forward (measured accel envelope, friction-circle & grade coupled) /
backward (24 m/s^2 brake, friction-circle & grade coupled) passes over the closed lap.

Optimizer: e = e_human + Fourier(c); Adam on finite-difference gradient, stage-wise
harmonics (coarse->fine), penalties for wall margin (<1.0 m) and curvature-rate above
the human line's own 99th percentile (follower kink tolerance).
"""
import json
import os
import sys
import time

import numpy as np

REC = r"C:\Users\talon\FH6-AFK-Farm\recordings"
G = 9.81
EXP = 0.705          # load sensitivity exponent (build_surface_cap.py)
A_BRK = 24.0         # conservative full-pedal decel m/s^2 (measured 25.6-27.8)
WALL_MARGIN = 1.0    # required clearance, m
HARD_CLIP = 0.55     # geometry hard clip inside the wall, m (penalty pushes to 1.0)
STRAIGHT_K = 0.004   # |kappa| below this = straight (acceptance metric b)

# ---------------------------------------------------------------- data loading
plan = np.load(os.path.join(REC, "refline_plan.npz"))
LINE_H = plan["line"]; LEFT = plan["left"]; RIGHT = plan["right"]
SPEED_H = plan["speed"]; ELEV = plan["elev"]; GRADE = plan["grade"]
N = len(LINE_H)

surf = np.load(os.path.join(REC, "surface_cap.npz"))
BANK = surf["bank"]; ZPP = surf["zpp"]

tune = json.load(open(os.path.join(REC, "tune.json")))
A0 = float(tune.get("planner_alat", 27.0))          # 27.0 live
AK = float(tune.get("planner_alat_k", 0.0025))      # 0.0025 live
VMAX = float(tune.get("speed_cap", 71.0))           # 71 m/s live

def smooth_closed(a, w=5):
    k = np.ones(w) / w
    return np.convolve(np.r_[a[-w:], a, a[:w]], k, "same")[w:-w]


# frame: offsets are measured from the HUMAN LINE along its left normal (the corridor
# center has zero-length duplicate stations -- reconstructing through it corrupts kappa)
_tan = np.roll(LINE_H, -1, 0) - np.roll(LINE_H, 1, 0)
_tan /= np.hypot(_tan[:, 0], _tan[:, 1])[:, None]
NRM = np.column_stack([-_tan[:, 1], _tan[:, 0]])         # left normal (planner convention)
D_L = ((LEFT - LINE_H) * NRM).sum(1)                     # wall offsets from human line
D_R = ((RIGHT - LINE_H) * NRM).sum(1)                    # (D_L > 0 > D_R)
# conservative smoothing of noisy wall projections: never widen the corridor
D_L = np.minimum(D_L, smooth_closed(D_L, 5))
D_R = np.maximum(D_R, smooth_closed(D_R, 5))
E_H = np.zeros(N)                                        # human line = e 0
CENTER_OFF = 0.5 * (D_L + D_R)                           # corridor center in e-coords
HALFW = 0.5 * (D_L - D_R)

SEG_H = np.hypot(*(np.roll(LINE_H, -1, 0) - LINE_H).T)   # station spacing (human line)
S_OF = np.concatenate([[0.0], np.cumsum(SEG_H)])[:-1]
TRACK_LEN = SEG_H.sum()


# ---------------------------------------------------- steering feasibility map
sfm = np.load(os.path.join(REC, "steer_ff_map.npz"))
M_MAP, N_MAP, VC_KMH, KC = sfm["M"], sfm["n"], sfm["vc"], sfm["kc"]


def build_steer_cap():
    """kappa_max(v): last kappa bin with real samples (n>0) and M<1.0 per speed row,
    median-3 smoothed across rows, then running-min => monotone non-increasing in v.
    Returns v_steer_cap(kappa) as a fine inverse lookup (m/s)."""
    K_OPEN = 0.30    # rows unsaturated through the whole map domain impose no limit
    kmax_raw = np.empty(len(VC_KMH))
    for r in range(len(VC_KMH)):
        ok = np.where((N_MAP[r] > 0) & (M_MAP[r] < 0.999))[0]
        sat = np.where((N_MAP[r] > 0) & (M_MAP[r] >= 0.999))[0]
        if len(sat) == 0:
            # never saturated where sampled: the map's KB ceiling, not the car,
            # ends the data -- no steering limit observable at this speed
            kmax_raw[r] = K_OPEN
        else:
            kmax_raw[r] = KC[ok[-1]] if len(ok) else KC[0]
    kmed = kmax_raw.copy()
    for r in range(1, len(kmax_raw) - 1):
        kmed[r] = np.median(kmax_raw[r - 1:r + 2])
    kmono = np.minimum.accumulate(kmed)
    v_ms = VC_KMH / 3.6
    # fine grid inversion: v_cap(kappa) = max v with kmono(v) >= kappa
    vg = np.linspace(v_ms[0], VMAX + 5.0, 600)
    kg = np.interp(vg, v_ms, kmono)          # non-increasing
    def cap(kappa):
        kappa = np.abs(kappa)
        # searchsorted on -kg (ascending): first grid idx where kg < kappa
        idx = np.searchsorted(-kg, -kappa, side="left")
        out = np.where(idx == 0, v_ms[0], vg[np.clip(idx - 1, 0, len(vg) - 1)])
        return np.where(kappa <= kg[-1], vg[-1], out)
    return cap, v_ms, kmono


STEER_CAP, _SC_V, _SC_K = build_steer_cap()


# ------------------------------------------------------- accel envelope (measured)
def build_accel_envelope():
    """Engine accel a(v) from the human lap: a_meas = v dv/ds on the SMOOTHED speed
    trace, engine = a_meas + g*grade. Envelope = 80th pct per 4 m/s bin, capped at a
    physical ceiling (raw 1 m derivative noise fabricates 2g+ 'accel')."""
    sp = smooth_closed(SPEED_H, 9)
    dv = 0.5 * (np.roll(sp, -1) - np.roll(sp, 1))
    ds = 0.5 * (SEG_H + np.roll(SEG_H, 1))
    a_meas = sp * dv / np.maximum(ds, 1e-6)
    a_eng = a_meas + G * GRADE
    bins = np.arange(12.0, VMAX + 4.0, 4.0)
    bv, ba = [], []
    for lo in bins[:-1]:
        mk = (sp >= lo) & (sp < lo + 4.0) & (a_eng > 0.2)
        if mk.sum() >= 4:
            bv.append(lo + 2.0)
            ba.append(min(np.percentile(a_eng[mk], 90), 20.0))
    bv, ba = np.array(bv), np.array(ba)
    if len(ba) >= 3:
        ba = np.convolve(np.r_[ba[0], ba, ba[-1]], np.ones(3) / 3, "same")[1:-1]
    def env(v):
        return np.interp(v, bv, ba, left=ba[0], right=max(ba[-1], 0.5))
    return env, bv, ba


ACC_ENV, _AE_V, _AE_A = build_accel_envelope()
_vg_lut = np.arange(0.0, (VMAX + 8.0) * 4.0) / 4.0
ACC_LUT = ACC_ENV(_vg_lut)                       # 0.25 m/s lookup for the hot loop


# ------------------------------------------------------------- geometry & kappa
def line_from_e(e):
    return LINE_H + e[:, None] * NRM


def kappa_of(pts):
    """Signed Menger curvature smoothed w=5 -- byte-for-byte the LocalPlanner recipe."""
    p0 = np.roll(pts, 1, 0); p2 = np.roll(pts, -1, 0)
    a = np.hypot(*(pts - p0).T); b = np.hypot(*(p2 - pts).T); c = np.hypot(*(p2 - p0).T)
    cross = (pts[:, 0] - p0[:, 0]) * (p2[:, 1] - p0[:, 1]) - \
            (pts[:, 1] - p0[:, 1]) * (p2[:, 0] - p0[:, 0])
    area = 0.5 * np.abs(cross)
    denom = a * b * c
    kmag = np.where(denom > 1e-9, 4 * area / denom, 0.0)
    return smooth_closed(kmag * np.sign(cross), 5)


def seg_of(pts):
    return np.hypot(*(np.roll(pts, -1, 0) - pts).T)


def krate_of(kap, seg):
    """|dkappa/ds| central difference on the closed lap (gradient(S_OF) NaNs on dup s)."""
    ds = seg + np.roll(seg, 1)
    return np.abs((np.roll(kap, -1) - np.roll(kap, 1)) / np.maximum(ds, 1e-6))


# ------------------------------------------------------------ velocity profile
def vcap_lateral(kap):
    """Fixed point of  v^2 k cos(t) - g sin(t) = (A0 + AK v^2) load^EXP  per station
    (build_surface_cap.py physics; bank assists, crest unloads). Vectorized."""
    k = np.abs(kap)
    t = BANK
    v = np.minimum(np.sqrt(A0 / np.maximum(k - AK, 1e-5)), VMAX)
    tiny = k < 1e-4
    for _ in range(20):
        load = np.cos(t) + ZPP * v * v / G + (v * v * k / G) * np.sin(t)
        load = np.clip(load, 0.35, 1.6)
        avail = (A0 + AK * v * v) * load ** EXP
        rhs = avail + G * np.sin(t)
        need = np.maximum(k * np.cos(t), 1e-6)
        v_new = np.minimum(np.sqrt(np.maximum(rhs, 1e-3) / need), VMAX)
        v = 0.5 * v + 0.5 * v_new
    # +-25% sanity clamp vs flat-world (build_surface_cap discipline)
    flat = np.minimum(np.sqrt(A0 / np.maximum(k - AK, 1e-5)), VMAX)
    v = np.clip(v, 0.75 * flat, 1.25 * flat)
    v[tiny] = VMAX
    return v


def profile(kap, seg):
    """Forward-backward velocity profile on the closed lap. Returns (T, v)."""
    k = np.abs(kap)
    vcap = np.minimum(np.minimum(vcap_lateral(kap), STEER_CAP(k)), VMAX)
    alat_max = A0 + AK * vcap * vcap
    v = vcap.copy()
    for _ in range(2):                        # closed lap: two wraps to converge
        # forward: accel limited (friction-circle share, u clipped so the apex
        # station itself doesn't zero out drive/brake authority)
        for i in range(2 * N):
            j = i % N; jn = (j + 1) % N
            vj = v[j]
            u = min(vj * vj * k[j] / (A0 + AK * vj * vj), 0.95)
            fc = np.sqrt(1.0 - u * u)
            ax = ACC_LUT[int(vj * 4.0)] * fc - G * GRADE[j]
            if ax < 1.0:
                ax = 1.0
            vn = np.sqrt(vj * vj + 2.0 * ax * seg[j])
            if vn < v[jn]:
                v[jn] = vn
        # backward: braking limited
        for i in range(2 * N, 0, -1):
            j = i % N; jp = (j - 1) % N
            vj = v[j]
            u = min(vj * vj * k[j] / (A0 + AK * vj * vj), 0.95)
            fc = np.sqrt(1.0 - u * u)
            ab = A_BRK * fc + G * GRADE[j]
            if ab < 6.0:
                ab = 6.0
            vp = np.sqrt(vj * vj + 2.0 * ab * seg[jp])
            if vp < v[jp]:
                v[jp] = vp
    T = float((seg * 2.0 / (v + np.roll(v, -1))).sum())
    return T, v


def evaluate(e):
    pts = line_from_e(e)
    kap = kappa_of(pts)
    seg = seg_of(pts)
    T, v = profile(kap, seg)
    return T, v, kap, seg, pts


# ------------------------------------------------------------------- objective
KRATE_REF = None      # set in main from the human line


def objective(e, full=False):
    T, v, kap, seg, _ = evaluate(e)
    # wall margin penalty (hinge at 1.0 m clearance from BOTH walls, e vs D_L/D_R)
    viol = np.maximum(0.0, e - (D_L - WALL_MARGIN)) + \
           np.maximum(0.0, (D_R + WALL_MARGIN) - e)
    p_wall = 60.0 * float((viol ** 2).sum())
    # curvature-rate penalty above the human line's own 99th pct
    kr = krate_of(kap, seg)
    kv = np.maximum(0.0, kr - KRATE_REF)
    p_kr = 1e5 * float((kv ** 2 * seg).sum())
    if full:
        return T + p_wall + p_kr, T, float(viol.max()), float(np.percentile(kr, 99))
    return T + p_wall + p_kr, T


def fourier_basis(H):
    t = np.arange(N) / N
    cols = [np.ones(N)]
    for h in range(1, H + 1):
        cols.append(np.cos(2 * np.pi * h * t))
        cols.append(np.sin(2 * np.pi * h * t))
    return np.column_stack(cols)               # N x (2H+1)


def clip_e(e):
    return np.clip(e, D_R + HARD_CLIP, D_L - HARD_CLIP)


def make_seed(w=13):
    """Noise-smoothed human line, iteratively pushed inside the 1.0 m margins with
    softened clip kinks. Removes phantom curvature spikes the recorded lap carries."""
    lo = D_R + WALL_MARGIN; hi = D_L - WALL_MARGIN
    mid = 0.5 * (lo + hi)
    sm = np.column_stack([smooth_closed(LINE_H[:, 0], w), smooth_closed(LINE_H[:, 1], w)])
    e = ((sm - LINE_H) * NRM).sum(1)
    for _ in range(4):
        e = np.where(lo < hi, np.clip(e, lo, hi), mid)
        e = smooth_closed(e, 5)
    return np.where(lo < hi, np.clip(e, lo + 0.01, hi - 0.01), mid)


def optimize(stages=((12, 60, 0.020, 0.06), (28, 80, 0.015, 0.04),
                     (48, 80, 0.010, 0.02)), log=print):
    """Stage-wise central-difference Adam from the smoothed seed.
    stages = (harmonics, steps, fd_step_m, lr). Tracks best-J and best
    acceptance-feasible-T (clearance ok AND krate_p99 <= human ref)."""
    base = make_seed()
    J_best, T_best, mv, k99 = objective(clip_e(base), full=True)
    e_best = clip_e(base)
    e_acc, T_acc = None, np.inf
    if mv <= 1e-9 and k99 <= KRATE_REF:
        e_acc, T_acc = e_best.copy(), T_best
    log(f"seed: J={J_best:.3f} T={T_best:.3f} viol={mv:.2f} krate99={k99:.2e}")
    pert = np.zeros(N)
    for H, steps, fd, lr0 in stages:
        B = fourier_basis(H)
        nc = B.shape[1]
        c = np.zeros(nc)
        bp = pert.copy()
        m = np.zeros(nc); vv = np.zeros(nc)
        lr = lr0
        J_stage = np.inf; c_stage = c.copy()
        for it in range(steps):
            g = np.zeros(nc)
            for j in range(nc):
                cp = c.copy(); cp[j] += fd
                cm = c.copy(); cm[j] -= fd
                Jp, _ = objective(clip_e(base + bp + B @ cp))
                Jm, _ = objective(clip_e(base + bp + B @ cm))
                g[j] = (Jp - Jm) / (2 * fd)
            m = 0.9 * m + 0.1 * g
            vv = 0.999 * vv + 0.001 * g * g
            mh = m / (1 - 0.9 ** (it + 1)); vh = vv / (1 - 0.999 ** (it + 1))
            c -= lr * mh / (np.sqrt(vh) + 1e-8)
            Jn, Tn, mv, k99 = objective(clip_e(base + bp + B @ c), full=True)
            if Jn < J_stage:
                J_stage, c_stage = Jn, c.copy()
            if mv <= 1e-9 and k99 <= KRATE_REF and Tn < T_acc:
                e_acc, T_acc = clip_e(base + bp + B @ c), Tn
            if (it + 1) % 10 == 0:
                log(f"  H={H} it={it+1:3d} J={Jn:.3f} T={Tn:.3f} viol={mv:.2f} "
                    f"kr99={k99:.2e} bestT_acc={T_acc:.3f}")
                if Jn > J_stage + 0.3:
                    lr *= 0.5              # diverging: cool down
        pert = bp + B @ c_stage
        Jn, Tn, mv, k99 = objective(clip_e(base + pert), full=True)
        log(f"stage H={H} done: J={Jn:.3f} T={Tn:.3f}")
        if Jn < J_best:
            J_best, T_best, e_best = Jn, Tn, clip_e(base + pert)
    if e_acc is not None:
        log(f"best acceptance-feasible T={T_acc:.3f} (using it)")
        return e_acc, T_acc, T_acc
    return e_best, J_best, T_best


# ------------------------------------------------------------------ acceptance
def report(e_opt):
    T_h, v_h, k_h, seg_h, _ = evaluate(E_H)
    T_o, v_o, k_o, seg_o, pts_o = evaluate(e_opt)
    stra = np.abs(k_h) < STRAIGHT_K
    frac_h = (np.abs(E_H - CENTER_OFF) / HALFW)[stra].mean()
    stra_o = np.abs(k_o) < STRAIGHT_K
    frac_o = (np.abs(e_opt - CENTER_OFF) / HALFW)[stra_o].mean()
    kr_h = krate_of(k_h, seg_h)
    kr_o = krate_of(k_o, seg_o)
    clear = float(np.minimum(D_L - e_opt, e_opt - D_R).min())
    print("=" * 64)
    print(f"(a) predicted lap time  human {T_h:.3f}s  opt {T_o:.3f}s  "
          f"delta {T_h - T_o:+.3f}s  (need > +0.15)")
    print(f"(b) straights mean|frac|  human {frac_h:.2f}  opt {frac_o:.2f}  (need > 0.5)")
    print(f"(c) curvature-rate p50/p90/p99  human "
          f"{np.percentile(kr_h,50):.2e}/{np.percentile(kr_h,90):.2e}/{np.percentile(kr_h,99):.2e}"
          f"  opt {np.percentile(kr_o,50):.2e}/{np.percentile(kr_o,90):.2e}/{np.percentile(kr_o,99):.2e}")
    print(f"(d) min wall clearance  {clear:.2f} m  (need >= 1.0; human line was "
          f"{float(np.minimum(D_L, -D_R).min()):.2f})")
    print("=" * 64)
    return T_h, T_o, v_o, pts_o


def validate():
    """Model sanity: predict the human line's lap time."""
    T_h, v_h, k_h, _, _ = evaluate(E_H)
    t_plan = float((SEG_H * 2.0 / (SPEED_H + np.roll(SPEED_H, -1))).sum())
    print(f"track length {TRACK_LEN:.1f} m, stations {N}")
    print(f"human plan speed integrates to {t_plan:.2f} s (actual lap 27.28 s)")
    print(f"MODEL prediction for the human line: {T_h:.2f} s")
    err = v_h - SPEED_H
    print(f"model-v minus plan-v: mean {err.mean():+.2f} p10 {np.percentile(err,10):+.2f} "
          f"p90 {np.percentile(err,90):+.2f} m/s")
    # which constraint binds
    k = np.abs(k_h)
    vlat = vcap_lateral(k_h); vst = STEER_CAP(k)
    bind_st = (vst < vlat - 0.2) & (v_h > vst - 0.3)
    print(f"steer-cap binding at {bind_st.sum()} stations; "
          f"lat-cap active at {int(((v_h > vlat - 0.3) & (k > 0.004)).sum())} stations")
    return T_h


def main():
    global KRATE_REF
    k_h = kappa_of(LINE_H)
    KRATE_REF = float(np.percentile(krate_of(k_h, seg_of(LINE_H)), 99))
    print(f"curvature-rate bound (human p99): {KRATE_REF:.2e} 1/m^2")
    validate()
    if "--validate-only" in sys.argv:
        return
    t0 = time.time()
    e_opt, J, T = optimize()
    print(f"optimize done in {time.time() - t0:.0f}s: J={J:.3f} T={T:.3f}")
    T_h, T_o, v_o, pts_o = report(e_opt)
    out = os.path.join(REC, "refline_plan_opt_candidate.npz")
    np.savez(out, line=pts_o, left=LEFT, right=RIGHT, speed=v_o,
             elev=ELEV, grade=GRADE)
    print(f"saved {out}")


if __name__ == "__main__":
    main()
