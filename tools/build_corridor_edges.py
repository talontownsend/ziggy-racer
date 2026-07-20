"""Build the corridor from two EXPLICIT edge runs (left-limit lap + right-limit lap).

Usage: python build_corridor_edges.py <left.csv> <right.csv> [lap] [a_lat_g]

Refactored into reusable pieces so a sweep can build the corridor ONCE and only
vary the line-solve knobs:
  corridor_from_edges(left_csv, right_csv, lap, a_lat_g) -> corridor dict
  solve_line(corr, iters2, build_extra_cap, solver_extra_cap, ...) -> line result + metrics

Pipeline: align the two edge loops by progression, pair them perpendicular into a
corridor, straighten the start/finish seam, despike, inset for car-body clearance,
solve the min-time line (cand_grad), grade-aware speed profile.
"""
import csv, json, sys
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
sys.path.insert(0, r"C:\Users\talon\FH6-AFK-Farm")
from racing_line import (resample_closed, plan_racing_line, velocity_profile,
                         menger_curvature, segment_lengths, grade_adjust)
from cand_grad import min_time_line

N = 1000
HUMAN_BEST = 26.85
OUT = r"C:\Users\talon\FH6-AFK-Farm\recordings\limits_edges"
V_MAX = 70.0   # m/s (~252 km/h): the edge runs are slow boundary traces, so fix top speed


def smooth_closed(a, w=7):
    k = np.ones(w) / w
    if a.ndim == 1:
        return np.convolve(np.r_[a[-w:], a, a[:w]], k, "same")[w:-w]
    return np.column_stack([smooth_closed(a[:, 0], w), smooth_closed(a[:, 1], w)])


def straighten_gap(wall, bad, margin=6):
    n = len(wall); m = bad.copy()
    for _ in range(margin):
        m = m | np.roll(m, 1) | np.roll(m, -1)
    if not m.any() or m.all():
        return wall
    ang = 2 * np.pi * np.where(m)[0] / n
    center = int(round((np.angle(np.mean(np.exp(1j * ang))) % (2 * np.pi)) / (2 * np.pi) * n)) % n
    sh = (center - n // 2) % n
    w = np.roll(wall, -sh, axis=0).copy(); mm = np.roll(m, -sh)
    idx = np.where(mm)[0]
    for run in np.split(idx, np.where(np.diff(idx) > 1)[0] + 1):
        a, b = max(run[0] - 1, 0), min(run[-1] + 1, n - 1)
        if b <= a:
            continue
        for k in run:
            t = (k - a) / (b - a); w[k] = (1 - t) * w[a] + t * w[b]
    return np.roll(w, sh, axis=0)


def load_edge(path, lap):
    """Extract one lap's moving, in-race (x,z) loop + its (x,z,y) frames for elevation."""
    rows = list(csv.DictReader(open(path)))
    pts, frames = [], []
    for r in rows:
        if r.get("is_race_on") != "1":
            continue
        try:
            ln = int(r["lap_no"]); spd = float(r["speed_mps"]); x = float(r["pos_x"])
            z = float(r["pos_z"]); y = float(r["pos_y"])
        except (KeyError, ValueError):
            continue
        if (x == 0 and z == 0) or spd * 3.6 <= 3:
            continue
        frames.append((x, z, y))
        if ln == lap:
            pts.append((x, z))
    if len(pts) < 50:                       # fall back to all moving frames if that lap is sparse
        pts = [(x, z) for x, z, _ in frames]
    return np.array(pts), np.array(frames)


def _wall_turn(w):
    a = w - np.roll(w, 1, 0); b = np.roll(w, -1, 0) - w
    return np.degrees(np.abs(np.angle(np.exp(1j * (np.arctan2(b[:, 1], b[:, 0]) -
                                                   np.arctan2(a[:, 1], a[:, 0]))))))


def corridor_from_edges(left_csv, right_csv, lap=1, a_lat_g=2.45, verbose=True):
    """Load both edge runs and build the aligned, paired, despiked corridor +
    elevation/grade + vehicle limits. Returns everything the line-solve needs."""
    loopA, framesL = load_edge(left_csv, lap)
    loopB, framesR = load_edge(right_csv, lap)
    if verbose:
        print(f"left edge lap{lap}: {len(loopA)} pts | right edge lap{lap}: {len(loopB)} pts")
    loopA = resample_closed(loopA, N)
    loopB = resample_closed(loopB, N)

    # align loop B to loop A by progression (direction + start phase), pair by index
    best = None
    for rev in (False, True):
        Bb = loopB[::-1] if rev else loopB
        for s in range(N):
            cost = np.sum((loopA - np.roll(Bb, s, axis=0)) ** 2)
            if best is None or cost < best[0]:
                best = (cost, rev, s)
    _, rev, shift = best
    loopB = np.roll(loopB[::-1] if rev else loopB, shift, axis=0)
    left = smooth_closed(loopA, 3)
    rightR = smooth_closed(loopB, 3)

    # perpendicular pairing (monotonic window)
    tanL = np.roll(left, -1, 0) - np.roll(left, 1, 0)
    tanL /= np.maximum(np.linalg.norm(tanL, axis=1, keepdims=True), 1e-9)
    right = np.zeros_like(left); j = 0
    for i in range(N):
        best_k, best_t = j, 1e18
        for dj in range(-3, 22):
            k = (j + dj) % N
            vx, vz = rightR[k, 0] - left[i, 0], rightR[k, 1] - left[i, 1]
            if vx * vx + vz * vz > 40.0 ** 2:
                continue
            tcomp = abs(vx * tanL[i, 0] + vz * tanL[i, 1])
            if tcomp < best_t:
                best_t, best_k = tcomp, k
        j = best_k
        right[i] = rightR[best_k]
    width = np.linalg.norm(left - right, axis=1)
    if verbose:
        print(f"perpendicular-paired width m: mean {width.mean():.1f}  min {width.min():.1f}  max {width.max():.1f}")

    # straighten the start/finish seam (where the loops were cut)
    Cc = smooth_closed(0.5 * (left + right), 5)
    tc2 = np.roll(Cc, -1, 0) - np.roll(Cc, 1, 0)
    tc2 /= np.maximum(np.linalg.norm(tc2, axis=1, keepdims=True), 1e-9)
    ncc = np.column_stack([-tc2[:, 1], tc2[:, 0]])
    crossed = np.sum((left - Cc) * ncc, 1) <= np.sum((right - Cc) * ncc, 1)
    seam = crossed | (width < 0.55 * np.median(width))
    left = straighten_gap(left, seam, margin=4)
    right = straighten_gap(right, seam, margin=4)

    lspike = _wall_turn(left) > 45.0; rspike = _wall_turn(right) > 45.0
    if lspike.any(): left = straighten_gap(left, lspike, margin=2)
    if rspike.any(): right = straighten_gap(right, rspike, margin=2)
    if verbose:
        print(f"despike: {int(lspike.sum())} left + {int(rspike.sum())} right folds")

    veh = dict(a_lat=a_lat_g * 9.81, a_lat_k=0.00383, a_acc=11.0, a_brake=17.0, v_max=V_MAX)
    cen = 0.5 * (left + right)
    half = 0.5 * np.linalg.norm(left - right, axis=1)
    ul = cen - left; ul /= np.maximum(np.linalg.norm(ul, axis=1, keepdims=True), 1e-9)
    ur = cen - right; ur /= np.maximum(np.linalg.norm(ur, axis=1, keepdims=True), 1e-9)

    allf = np.vstack([framesL, framesR]) if len(framesR) else framesL
    elev = np.array([allf[np.argmin((allf[:, 0] - cx) ** 2 + (allf[:, 1] - cz) ** 2), 2] for cx, cz in cen])
    elev = smooth_closed(elev, 7)
    ds_c = segment_lengths(cen)
    grade = (np.roll(elev, -1) - np.roll(elev, 1)) / np.maximum(np.roll(ds_c, 1) + ds_c, 1e-6)
    grade = np.clip(smooth_closed(grade, 5), -0.35, 0.35)

    return dict(left=left, right=right, cen=cen, half=half, ul=ul, ur=ur,
                veh=veh, elev=elev, grade=grade)


def line_metrics(left, right, line, V):
    """How much track width does the line use (apex), how followable, how safe."""
    cen = 0.5 * (left + right)
    half = 0.5 * np.linalg.norm(left - right, axis=1)
    nrm = right - cen; nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
    off = np.sum((line - cen) * nrm, axis=1)
    frac = np.clip(off / np.maximum(half, 1e-6), -1.3, 1.3)
    kap = menger_curvature(line)
    straight = kap < (1.0 / 120.0)
    corner = ~straight
    turn = _wall_turn(line)                              # deg of heading change per station
    # clearance: signed distance from line to each wall along the local normal
    dl = np.sum((line - left) * nrm, axis=1)             # +toward right from left wall
    dr = np.sum((right - line) * nrm, axis=1)
    clr = np.minimum(np.abs(dl), np.abs(dr))
    ds = segment_lengths(line)
    return dict(
        apex_corner=float(np.abs(frac[corner]).mean()) if corner.any() else 0.0,
        central_straight=float((straight & (np.abs(frac) < 0.3)).sum() / max(straight.sum(), 1)),
        width_used=float(off.max() - off.min()), half_mean=float(half.mean()),
        max_turn=float(np.percentile(turn, 99.5)), worst_turn=float(turn.max()),
        min_clear=float(clr.min()), lap_time=float(np.sum(ds / np.maximum(V, 0.5))),
        top_kmh=float(V.max() * 3.6),
    )


def solve_line(corr, *, iters2=160, build_extra_cap=0.3, build_extra_gain=40.0,
               solver_extra_cap=0.4, solver_extra_gain=150.0, base_margin=1.1):
    """Inset the corridor (car-body clearance + small curvature spread) and solve the
    min-time line. build_extra_* control the builder's curvature inset; solver_extra_*
    are forwarded to cand_grad's internal corner inset; iters2 = diffusion smoothing."""
    cen, half, ul, ur = corr["cen"], corr["half"], corr["ul"], corr["ur"]
    left, right, veh, grade = corr["left"], corr["right"], corr["veh"], corr["grade"]
    kcen = smooth_closed(menger_curvature(cen), 5)
    extra = np.clip((kcen - 1.0 / 25.0) * build_extra_gain, 0.0, build_extra_cap)
    MARGIN = base_margin + extra
    inset = np.minimum(MARGIN, np.maximum(half - 0.75, 0.0))[:, None]
    aacc, abrk = grade_adjust(veh["a_acc"], veh["a_brake"], grade)
    plan = min_time_line(left + inset * ul, right + inset * ur, veh, n=N, grade=grade,
                         clear=0.02, safety=0.0, iters2=iters2,
                         extra_cap=solver_extra_cap, extra_gain=solver_extra_gain)
    L = np.asarray(plan["line"], float)
    V, _, ds = velocity_profile(L, veh["a_lat"], aacc, abrk, veh["v_max"],
                                a_lat_k=veh.get("a_lat_k", 0.0))
    m = line_metrics(left, right, L, V)
    m["T_solve"] = float(plan["lap_time_est"])
    return L, V, m


def save_plan(corr, L, V, out=OUT, veh=None):
    left, right, elev, grade = corr["left"], corr["right"], corr["elev"], corr["grade"]
    veh = veh or corr["veh"]
    cen = 0.5 * (left + right)
    fig, ax = plt.subplots(1, 2, figsize=(18, 8))
    ax[0].plot(left[:, 0], left[:, 1], "b-", lw=1, label="left edge")
    ax[0].plot(right[:, 0], right[:, 1], "r-", lw=1, label="right edge")
    for i in range(0, N, 12):
        ax[0].plot([left[i, 0], right[i, 0]], [left[i, 1], right[i, 1]], "0.7", lw=0.4)
    ax[0].set_title("corridor from edge runs"); ax[0].axis("equal"); ax[0].legend()
    ax[1].plot(left[:, 0], left[:, 1], "k-", lw=0.6); ax[1].plot(right[:, 0], right[:, 1], "k-", lw=0.6)
    sc = ax[1].scatter(L[:, 0], L[:, 1], c=V * 3.6, s=8, cmap="turbo")
    ax[1].set_title("optimized line (km/h)"); ax[1].axis("equal"); fig.colorbar(sc, ax=ax[1])
    plt.tight_layout(); plt.savefig(out + "_corridor.png", dpi=90)
    ds = segment_lengths(L)
    np.savez(out + "_plan.npz", left=left, right=right, line=L, speed=V, elev=elev, grade=grade)
    json.dump({**veh, "lap_distance": float(ds.sum())}, open(out + "_plan.json", "w"), indent=2)


if __name__ == "__main__":
    left_csv, right_csv = sys.argv[1], sys.argv[2]
    LAP = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    a_lat_g = float(sys.argv[4]) if len(sys.argv) > 4 else 2.45
    corr = corridor_from_edges(left_csv, right_csv, LAP, a_lat_g)
    # improved defaults: small insets + light diffusion so the line APEXES (uses the width)
    L, V, m = solve_line(corr, iters2=160, build_extra_cap=0.3, solver_extra_cap=0.4)
    print(f"line: apex_corner={m['apex_corner']:.2f} central_straight={m['central_straight']*100:.0f}% "
          f"width_used={m['width_used']:.1f}/{2*m['half_mean']:.1f}m")
    print(f"  followability: p99 turn={m['max_turn']:.1f}deg worst={m['worst_turn']:.1f}deg "
          f"min_clear={m['min_clear']:.2f}m")
    print(f"  est lap {m['lap_time']:.1f}s  top {m['top_kmh']:.0f} km/h  (human best {HUMAN_BEST:.1f}s)")
    save_plan(corr, L, V)
    print(f"saved {OUT}_plan.npz (+ .png, .json)")
