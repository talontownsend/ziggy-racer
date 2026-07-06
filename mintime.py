"""TRUE minimum-LAP-TIME racing line -> the real out-in-out.
Project-gradient on the actual lap time (velocity_profile), warm-started from the
smooth min-curvature line. Min-time rewards the wide entry / late apex (faster exit),
so the line swings to the OUTSIDE before corners instead of riding the inside wall."""
import numpy as np, sys, time
sys.path.insert(0, r"C:\Users\talon\FH6-AFK-Farm")
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from build_corridor_edges import corridor_from_edges, line_metrics, save_plan, smooth_closed
from racing_line import velocity_profile, grade_adjust, menger_curvature, segment_lengths

LEFT = r"recordings/limits_left/session_20260626_103954.csv"
RIGHT = r"recordings/limits_right/session_20260626_104413.csv"


def D2(a):
    return np.roll(a, 1, 0) + np.roll(a, -1, 0) - 2.0 * a


def _runs(mask):
    N = len(mask)
    if not mask.any():
        return []
    sh = int(np.argmin(mask)); m = np.roll(mask, -sh); out = []; i = 0
    while i < N:
        if m[i]:
            j = i
            while j < N and m[j]:
                j += 1
            out.append([(x + sh) % N for x in range(i, j)]); i = j
        else:
            i += 1
    return out


def out_in_out(corr, line):
    left, right = corr["left"], corr["right"]
    cen = 0.5 * (left + right); half = 0.5 * np.linalg.norm(left - right, axis=1)
    nrm = right - cen; nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
    frac = np.sum((line - cen) * nrm, axis=1) / np.maximum(half, 1e-6)
    t = np.roll(line, -1, 0) - line; t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-9)
    cr = t[:, 0] * np.roll(t, -1, 0)[:, 1] - t[:, 1] * np.roll(t, -1, 0)[:, 0]
    kap = smooth_closed(cr, 7); N = len(line)
    iscorner = np.abs(kap) > np.percentile(np.abs(kap), 72)
    good = bad = 0
    for run in _runs(iscorner):
        run = np.array(run)
        apex_frac = frac[run][np.argmax(np.abs(kap[run]))]
        ent_frac = frac[(run[0] - 12) % N]
        if np.sign(ent_frac) == -np.sign(apex_frac) and abs(ent_frac) > 0.25:
            good += 1
        else:
            bad += 1
    return good, bad, frac, iscorner


corr = corridor_from_edges(LEFT, RIGHT, lap=1, a_lat_g=2.45)
veh, grade = corr["veh"], corr["grade"]
aacc, abrk = grade_adjust(veh["a_acc"], veh["a_brake"], grade)
WALL_W, INSET = 11, 1.5
left = smooth_closed(corr["left"], WALL_W); right = smooth_closed(corr["right"], WALL_W)
center = 0.5 * (left + right)
tang = np.roll(center, -1, 0) - np.roll(center, 1, 0)
tang /= np.maximum(np.linalg.norm(tang, axis=1, keepdims=True), 1e-9)
nrm = np.column_stack([-tang[:, 1], tang[:, 0]])
amax = np.sum((left - center) * nrm, axis=1); amin = np.sum((right - center) * nrm, axis=1)
lo = np.minimum(amin, amax) + INSET; hi = np.maximum(amin, amax) - INSET
bad = hi < lo; mid = 0.5 * (amin + amax); lo = np.where(bad, mid, lo); hi = np.where(bad, mid, hi)
N = len(center)


def laptime(alpha):
    line = center + alpha[:, None] * nrm
    v, _, ds = velocity_profile(line, veh["a_lat"], aacc, abrk, veh["v_max"], a_lat_k=veh["a_lat_k"])
    return float(np.sum(ds / np.maximum(v, 0.5))), line


# warm start: smooth min-curvature (FFT) clipped to box
c = np.sum(D2(center) * nrm, axis=1); k = np.arange(N); lam = -4.0 * np.sin(np.pi * k / N) ** 2
ah = np.where(k == 0, 0.0, -np.fft.fft(c) / np.where(k == 0, 1.0, lam))
alpha = np.clip(np.real(np.fft.ifft(ah)), lo, hi)
for _ in range(1500):
    alpha = np.clip(alpha - 0.04 * 2.0 * D2(D2(alpha) + c), lo, hi)

T0, _ = laptime(alpha)
print(f"warm-start (min-curv) lap_est {T0:.2f}s", flush=True)
best_alpha = alpha.copy(); best_T = T0
h = 0.25
t_start = time.time()
for it in range(50):
    base, _ = laptime(alpha)
    g = np.zeros(N)
    for i in range(N):                       # forward finite-diff lap-time gradient
        ai = alpha.copy(); ai[i] = min(ai[i] + h, hi[i])
        Ti, _ = laptime(ai); g[i] = (Ti - base) / h
    g = smooth_closed(g, 5)                  # denoise the gradient
    gmax = np.max(np.abs(g))
    if gmax < 1e-9:
        break
    alpha = np.clip(alpha - (0.35 / gmax) * g, lo, hi)   # move worst station <=0.35 m
    alpha = (1 - 0.15) * alpha + 0.15 * smooth_closed(alpha, 3)  # keep followable
    alpha = np.clip(alpha, lo, hi)
    T, _ = laptime(alpha)
    if T < best_T:
        best_T, best_alpha = T, alpha.copy()
    if it % 5 == 0:
        print(f"  it {it}: lap_est {T:.2f}s ({time.time()-t_start:.0f}s elapsed)", flush=True)

alpha = best_alpha
line = center + alpha[:, None] * nrm
line = smooth_closed(line, 5)
a2 = np.clip(np.sum((line - center) * nrm, axis=1), lo, hi); line = center + a2[:, None] * nrm
V, _, ds = velocity_profile(line, veh["a_lat"], aacc, abrk, veh["v_max"], a_lat_k=veh["a_lat_k"])
m = line_metrics(corr["left"], corr["right"], line, V)
good, bad_, frac, iscorner = out_in_out(corr, line)
print(f"\nMIN-TIME line: out-in-out {good} good / {bad_} inside | apex {m['apex_corner']:.2f} "
      f"p99turn {m['max_turn']:.1f} clear {m['min_clear']:.2f} lap_est {m['lap_time']:.1f}s (was {T0:.1f})", flush=True)

s = np.cumsum(segment_lengths(line))
fig, ax = plt.subplots(2, 1, figsize=(15, 8))
ax[0].fill_between(s, -1, 1, where=iscorner, color="0.9")
ax[0].plot(s, frac, "b-", lw=1.2); ax[0].axhline(0, color="k", lw=0.5); ax[0].set_ylim(-1.2, 1.2)
ax[0].set_title("MIN-TIME line: out-in-out? (gray=corner)")
sc = ax[1].scatter(line[:, 0], line[:, 1], c=V * 3.6, s=10, cmap="turbo")
ax[1].plot(corr["left"][:, 0], corr["left"][:, 1], "k-", lw=0.5)
ax[1].plot(corr["right"][:, 0], corr["right"][:, 1], "k-", lw=0.5)
ax[1].axis("equal"); fig.colorbar(sc, ax=ax[1]); plt.tight_layout()
plt.savefig(r"C:\Users\talon\FH6-AFK-Farm\recordings\mintime.png", dpi=95)
save_plan(corr, line, V, out=r"C:\Users\talon\FH6-AFK-Farm\recordings\limits_edges_v4")
print("saved recordings/limits_edges_v4_plan.npz + mintime.png", flush=True)
