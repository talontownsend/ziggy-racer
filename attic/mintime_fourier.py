"""Min-LAP-TIME racing line over a LOW-DIM smooth Fourier basis.
alpha(s) = B @ theta  (M closed-loop Fourier modes -> smooth by construction).
Optimize the ~50 coefficients for minimum lap time with scipy L-BFGS-B; a soft box
penalty keeps the line in the corridor. Low-dim + smooth => well-conditioned, fast,
and free to form the out-in-out shape that min-time wants."""
import numpy as np, sys, time
sys.path.insert(0, r"C:\Users\talon\FH6-AFK-Farm")
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from scipy.optimize import minimize
from build_corridor_edges import corridor_from_edges, line_metrics, save_plan, smooth_closed
from racing_line import velocity_profile, grade_adjust, segment_lengths

LEFT = r"recordings/limits_left/session_20260626_103954.csv"
RIGHT = r"recordings/limits_right/session_20260626_104413.csv"
D2 = lambda a: np.roll(a, 1, 0) + np.roll(a, -1, 0) - 2.0 * a


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
            out.append(np.array([(x + sh) % N for x in range(i, j)])); i = j
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
left = smooth_closed(corr["left"], 11); right = smooth_closed(corr["right"], 11)
center = 0.5 * (left + right)
tang = np.roll(center, -1, 0) - np.roll(center, 1, 0)
tang /= np.maximum(np.linalg.norm(tang, axis=1, keepdims=True), 1e-9)
nrm = np.column_stack([-tang[:, 1], tang[:, 0]])
amax = np.sum((left - center) * nrm, axis=1); amin = np.sum((right - center) * nrm, axis=1)
INSET = 1.4
lo = np.minimum(amin, amax) + INSET; hi = np.maximum(amin, amax) - INSET
bad = hi < lo; mid = 0.5 * (amin + amax); lo = np.where(bad, mid, lo); hi = np.where(bad, mid, hi)
N = len(center)

# Fourier design matrix (closed loop), M modes
M = 26
k = np.arange(N)
cols = [np.ones(N)]
for mwave in range(1, M + 1):
    cols.append(np.cos(2 * np.pi * mwave * k / N))
    cols.append(np.sin(2 * np.pi * mwave * k / N))
Bmat = np.column_stack(cols)            # N x (2M+1)


def lap_of(alpha):
    line = center + alpha[:, None] * nrm
    v, _, ds = velocity_profile(line, veh["a_lat"], aacc, abrk, veh["v_max"], a_lat_k=veh["a_lat_k"])
    return float(np.sum(ds / np.maximum(v, 0.5)))


PEN = 80.0
def obj(theta):
    alpha = Bmat @ theta
    over = np.maximum(alpha - hi, 0.0); under = np.maximum(lo - alpha, 0.0)
    return lap_of(np.clip(alpha, lo, hi)) + PEN * float(np.sum(over ** 2 + under ** 2))


# warm start: fit Fourier to the min-curvature alpha
c = np.sum(D2(center) * nrm, axis=1); lam = -4.0 * np.sin(np.pi * k / N) ** 2
ah = np.where(k == 0, 0.0, -np.fft.fft(c) / np.where(k == 0, 1.0, lam))
alpha_mc = np.clip(np.real(np.fft.ifft(ah)), lo, hi)
theta0 = np.linalg.lstsq(Bmat, alpha_mc, rcond=None)[0]
print(f"warm-start min-curv lap {lap_of(np.clip(Bmat@theta0, lo, hi)):.2f}s  ({2*M+1} coeffs)", flush=True)

t0 = time.time()
res = minimize(obj, theta0, method="L-BFGS-B", options=dict(maxiter=300, maxfun=8000))
alpha = np.clip(Bmat @ res.x, lo, hi)
line = center + alpha[:, None] * nrm
V, _, ds = velocity_profile(line, veh["a_lat"], aacc, abrk, veh["v_max"], a_lat_k=veh["a_lat_k"])
m = line_metrics(corr["left"], corr["right"], line, V)
good, bad_, frac, iscorner = out_in_out(corr, line)
print(f"MIN-TIME(Fourier) lap_est {m['lap_time']:.2f}s  out-in-out {good} good / {bad_} inside | "
      f"apex {m['apex_corner']:.2f} p99turn {m['max_turn']:.1f} clear {m['min_clear']:.2f}  ({time.time()-t0:.0f}s)", flush=True)

s = np.cumsum(segment_lengths(line))
fig, ax = plt.subplots(2, 1, figsize=(15, 8))
ax[0].fill_between(s, -1, 1, where=iscorner, color="0.9")
ax[0].plot(s, frac, "b-", lw=1.2); ax[0].axhline(0, color="k", lw=0.5); ax[0].set_ylim(-1.2, 1.2)
ax[0].set_title(f"MIN-TIME Fourier line: out-in-out {good}/{good+bad_} corners (gray=corner)")
sc = ax[1].scatter(line[:, 0], line[:, 1], c=V * 3.6, s=10, cmap="turbo")
ax[1].plot(corr["left"][:, 0], corr["left"][:, 1], "k-", lw=0.5)
ax[1].plot(corr["right"][:, 0], corr["right"][:, 1], "k-", lw=0.5)
ax[1].axis("equal"); fig.colorbar(sc, ax=ax[1]); plt.tight_layout()
plt.savefig(r"C:\Users\talon\FH6-AFK-Farm\recordings\mintime_fourier.png", dpi=95)
save_plan(corr, line, V, out=r"C:\Users\talon\FH6-AFK-Farm\recordings\limits_edges_v4")
print("saved recordings/limits_edges_v4_plan.npz + mintime_fourier.png", flush=True)
