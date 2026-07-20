"""TRUE minimum-curvature racing line (out-in-out), not the inside-hugging taut string.

Minimize the line's perpendicular curvature |D2(line)|^2 = |D2 alpha + c|^2 (c = the
corridor center's perp curvature). The global optimum flattens each corner into the
largest possible arc -> the line MUST use the OUTSIDE on entry/exit and the inside at
the apex. We solve the unconstrained optimum exactly via FFT (D2 is circulant), then
project into the corridor box. Verifies the out-in-out pattern explicitly per corner.
"""
import numpy as np, sys
sys.path.insert(0, r"C:\Users\talon\FH6-AFK-Farm")
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from build_corridor_edges import corridor_from_edges, line_metrics, save_plan, smooth_closed
from racing_line import velocity_profile, grade_adjust, menger_curvature, segment_lengths

LEFT = r"recordings/limits_left/session_20260626_103954.csv"
RIGHT = r"recordings/limits_right/session_20260626_104413.csv"


def D2(a):
    return np.roll(a, 1, 0) + np.roll(a, -1, 0) - 2.0 * a


def mincurv(corr, inset_base=1.3, wall_w=11, box_iters=2500, step=0.03, final_smooth=5,
            p=8.0, irls=14):
    """min-MAX curvature (out-in-out racing line) via iteratively-reweighted least sq:
    minimize sum(w_i (D2 alpha + c)_i^2) with w = |curvature|^(p-2) updated each round ->
    converges to minimizing the L^p norm of curvature; large p -> min-max -> the line
    uses the OUTSIDE on entry to make each corner one gentle constant-radius arc."""
    left = smooth_closed(corr["left"], wall_w)
    right = smooth_closed(corr["right"], wall_w)
    center = 0.5 * (left + right)
    tang = np.roll(center, -1, 0) - np.roll(center, 1, 0)
    tang /= np.maximum(np.linalg.norm(tang, axis=1, keepdims=True), 1e-9)
    nrm = np.column_stack([-tang[:, 1], tang[:, 0]])
    amax = np.sum((left - center) * nrm, axis=1)
    amin = np.sum((right - center) * nrm, axis=1)
    lo = np.minimum(amin, amax) + inset_base
    hi = np.maximum(amin, amax) - inset_base
    bad = hi < lo; mid = 0.5 * (amin + amax)
    lo = np.where(bad, mid, lo); hi = np.where(bad, mid, hi)
    N = len(center)
    c = np.sum(D2(center) * nrm, axis=1)                    # perp curvature of the centerline
    # FFT warm-start: exact unconstrained min |D2 alpha + c|^2 (uniform weight)
    k = np.arange(N); lam = -4.0 * np.sin(np.pi * k / N) ** 2
    ch = np.fft.fft(c); ah = np.where(k == 0, 0.0, -ch / np.where(k == 0, 1.0, lam))
    alpha = np.clip(np.real(np.fft.ifft(ah)), lo, hi)
    w = np.ones(N)
    for _outer in range(irls):
        for _ in range(box_iters):
            r = w * (D2(alpha) + c)                         # weighted residual
            alpha = np.clip(alpha - step * 2.0 * D2(r), lo, hi)
        kap = np.abs(D2(alpha) + c)                         # current perp curvature
        w = (kap + 0.02 * kap.max() + 1e-6) ** ((p - 2.0) / 2.0)
        w = w / w.mean()                                    # normalize so step stays valid
    line = center + alpha[:, None] * nrm
    if final_smooth > 1:
        line = smooth_closed(line, final_smooth)
        a2 = np.clip(np.sum((line - center) * nrm, axis=1), lo, hi)
        line = center + a2[:, None] * nrm
    return line, center, nrm, lo, hi


def out_in_out_report(corr, line):
    """For each corner, is the line OUTSIDE on entry (good) or inside (bad)?"""
    left, right = corr["left"], corr["right"]
    cen = 0.5 * (left + right); half = 0.5 * np.linalg.norm(left - right, axis=1)
    nrm = right - cen; nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
    frac = np.sum((line - cen) * nrm, axis=1) / np.maximum(half, 1e-6)
    # signed curvature of the line -> corner direction (left/right)
    t = np.roll(line, -1, 0) - line; t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-9)
    dthe = np.arctan2(np.cross(t, np.roll(t, -1, 0)), np.sum(t * np.roll(t, -1, 0), 1))
    kap = smooth_closed(dthe, 7)
    N = len(line); inside_sign = -np.sign(kap)   # apex is toward the inside of the bend
    # corners = high |kap| runs
    iscorner = np.abs(kap) > np.percentile(np.abs(kap), 75)
    good = bad = 0
    for sid in _runs(iscorner):
        i0, i1 = sid[0], sid[-1]
        entry = (i0 - 12) % N
        apex_frac = frac[sid][np.argmax(np.abs(kap[sid]))]
        ent_frac = frac[entry]
        # out-in-out: entry on OUTSIDE = frac sign opposite to apex (inside) sign
        if np.sign(ent_frac) == -np.sign(apex_frac) and abs(ent_frac) > 0.25:
            good += 1
        else:
            bad += 1
    return good, bad, frac, kap, iscorner


def _runs(mask):
    N = len(mask); out = []; i = 0
    # rotate so we don't split a run across the seam
    sh = int(np.argmin(mask)) if mask.any() else 0
    m = np.roll(mask, -sh)
    i = 0
    while i < N:
        if m[i]:
            j = i
            while j < N and m[j]:
                j += 1
            out.append([(x + sh) % N for x in range(i, j)])
            i = j
        else:
            i += 1
    return out


corr = corridor_from_edges(LEFT, RIGHT, lap=1, a_lat_g=2.45)
veh, grade = corr["veh"], corr["grade"]
aacc, abrk = grade_adjust(veh["a_acc"], veh["a_brake"], grade)
print()
for inset in (1.2, 1.6):
    line, center, nrm, lo, hi = mincurv(corr, inset_base=inset, wall_w=11, p=2.0, irls=1)
    V, _, ds = velocity_profile(line, veh["a_lat"], aacc, abrk, veh["v_max"], a_lat_k=veh["a_lat_k"])
    m = line_metrics(corr["left"], corr["right"], line, V)
    good, bad, frac, kap, iscorner = out_in_out_report(corr, line)
    print(f"inset {inset}: out-in-out corners {good} good / {bad} inside-hugging | "
          f"apex {m['apex_corner']:.2f} p99turn {m['max_turn']:.1f} clear {m['min_clear']:.2f} lap {m['lap_time']:.1f}s")
    if inset == 1.6:
        bestL, bestV, bestm, bestfrac, bestkap, bestcorner = line, V, m, frac, kap, iscorner

# visualize the chosen line: offset profile + line on track
s = np.cumsum(segment_lengths(bestL))
fig, ax = plt.subplots(2, 1, figsize=(15, 8))
ax[0].fill_between(s, -1, 1, where=bestcorner, color="0.9")
ax[0].plot(s, bestfrac, "b-", lw=1.2)
ax[0].axhline(0, color="k", lw=0.5); ax[0].set_ylim(-1.2, 1.2)
ax[0].set_ylabel("offset/half (+right/-left wall)"); ax[0].set_title("min-curv v3: out-in-out? (gray=corner)")
sc = ax[1].scatter(bestL[:, 0], bestL[:, 1], c=bestV * 3.6, s=10, cmap="turbo")
ax[1].plot(corr["left"][:, 0], corr["left"][:, 1], "k-", lw=0.5)
ax[1].plot(corr["right"][:, 0], corr["right"][:, 1], "k-", lw=0.5)
ax[1].axis("equal"); fig.colorbar(sc, ax=ax[1]); plt.tight_layout()
plt.savefig(r"C:\Users\talon\FH6-AFK-Farm\recordings\mincurv_v3.png", dpi=95)
save_plan(corr, bestL, bestV, out=r"C:\Users\talon\FH6-AFK-Farm\recordings\limits_edges_v3")
print("saved recordings/limits_edges_v3_plan.npz + mincurv_v3.png")
