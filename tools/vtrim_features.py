"""Feature-based generalization of the vtrim map (user 07-03: 'instead of vtrim being
indexed by position, it could be something similar to the neural network with its
features'). The converged position map is the TRAINING DATA; a small MLP from
per-station track features extrapolates it.

Features are properties of PLACE, all self-derived (independence-compliant):
  geometry from the plan (curvature windows, grade, vertical curvature, clearance,
  corridor width, the physics model's own speed prediction) + telemetry-measured
  camber proxy (median v^2*kappa_car - a_lat over the bot's own laps: bank assist).

Labels: converged vtrim map. Stations where the cap never binds are excluded
(their map value is meaningless); stations pinned at the bound are censored
(loss is hinge: predict >= bound, not == bound).

Run: python vtrim_features.py <soak_log.csv> [--loso]
Outputs: recordings/vtrim_features.npz (features per station), fit + LOSO report.
"""
import csv, math, sys
import numpy as np

REC = r"C:\Users\talon\FH6-AFK-Farm\recordings"
BOUND_HI, BOUND_LO = 1.55, 0.80
ALAT, ALAT_K = 24.3, 0.0025

d = np.load(REC + r"\refline_plan.npz")
line, elev, grade = d["line"], d["elev"], d["grade"]
left, right = d["left"], d["right"]
n = len(line)
seg = np.hypot(*(np.roll(line, -1, 0) - line).T)
s_of = np.concatenate([[0.0], np.cumsum(seg)])[:-1]


def smooth_closed(a, w):
    out = a.copy()
    for _ in range(w):
        out = (np.roll(out, 1) + out + np.roll(out, -1)) / 3.0
    return out


def win_max(a, dist, back=False):
    out = a.copy()
    for i in range(n):
        dd, j = 0.0, i
        while dd < dist:
            j = (j - 1) % n if back else (j + 1) % n
            dd += seg[j]
            if a[j] > out[i]:
                out[i] = a[j]
    return out


def win_min(a, dist):
    out = a.copy()
    for i in range(n):
        dd, j = 0.0, i
        while dd < dist:
            j = (j + 1) % n
            dd += seg[j]
            if a[j] < out[i]:
                out[i] = a[j]
    return out


# curvature (seam-safe menger, lightly smoothed like the planner's kappa_ref)
a3, b3, c3 = np.roll(line, 1, 0), line, np.roll(line, -1, 0)
ab = b3 - a3; bc = c3 - b3; ac = c3 - a3
cross = ab[:, 0] * bc[:, 1] - ab[:, 1] * bc[:, 0]
la, lb, lc = (np.linalg.norm(v, axis=1) for v in (ab, bc, ac))
kap = np.abs(2.0 * cross / np.maximum(la * lb * lc, 1e-9))
kap = smooth_closed(kap, 3)

kwin18 = win_max(kap, 18.0)
kup20 = win_max(kap, 20.0, back=True)
kdn40 = win_max(kap, 40.0)
dk = smooth_closed(np.abs(np.roll(kap, -3) - np.roll(kap, 3)) / 6.0, 3)
vcurv = smooth_closed(np.gradient(np.gradient(smooth_closed(elev, 5), s_of, edge_order=1), s_of, edge_order=1), 5)
clear = np.minimum(np.hypot(*(line - left).T), np.hypot(*(line - right).T))
clear30 = win_min(clear, 30.0)
width = np.hypot(*(left - right).T)
v_model = np.sqrt(ALAT / np.maximum(kwin18 - ALAT_K, 1e-4))
v_model = np.minimum(v_model, 71.0)

# camber proxy from the bot's own driving: median(v^2*kappa_car - a_lat_meas) [m/s^2].
# positive = bank assists (measured lateral < inertial demand), negative = off-camber.
log_path = sys.argv[1] if len(sys.argv) > 1 else None
camber = np.zeros(n)
if log_path:
    acc = [[] for _ in range(n)]
    for r in csv.DictReader(open(log_path)):
        try:
            i0 = int(float(r["i0"])) % n
            v = float(r["spd_kmh"]) / 3.6
            kc = float(r["kap_car"]); lat = abs(float(r["meas_latg"])) * 9.81   # meas_latg is SIGNED
            dem = abs(kc) * v * v
            # gate to fast, steady cornering: at hairpin speeds kap_car spikes and
            # sideslip pollutes the proxy (read +70 m/s^2 of phantom 'bank' at S5)
            if v > 18.0 and 2.0 < dem < 32.0 and r["on_track"] == "1":
                acc[i0].append(dem - lat)
        except Exception:
            continue
    for i in range(n):
        if len(acc[i]) >= 8:
            camber[i] = np.median(acc[i])
    camber = smooth_closed(camber, 4)

FEAT_NAMES = ["kwin18", "kup20", "kdn40", "dk", "grade", "vcurv", "clear30", "width", "v_model", "camber"]
X = np.stack([kwin18, kup20, kdn40, dk, grade, vcurv, clear30, width, v_model / 71.0, camber], axis=1)

# labels + weights: converged map; weight by how often the cap actually governed
m = np.load(REC + r"\vtrim_map_converged_20260703.npz")["map"]
wgt = np.zeros(n)
if log_path:
    for r in csv.DictReader(open(log_path)):
        try:
            i0 = int(float(r["i0"])) % n
            if float(r["meas_latg"]) > 0.25 and r["on_track"] == "1":
                wgt[i0] += 1.0
        except Exception:
            continue
    wgt = smooth_closed(wgt, 2)
    wgt = wgt / max(wgt.max(), 1e-9)
censored = m > BOUND_HI - 0.01

mu, sd = X.mean(0), X.std(0) + 1e-9
Xn = (X - mu) / sd


def fit_mlp(Xt, yt, wt, ct, seed=0, epochs=3000, h=24):
    rng = np.random.default_rng(seed)
    nf = Xt.shape[1]
    W1 = rng.normal(0, 0.3, (nf, h)); b1 = np.zeros(h)
    W2 = rng.normal(0, 0.3, (h, h)); b2 = np.zeros(h)
    W3 = rng.normal(0, 0.3, (h, 1)); b3v = np.zeros(1)
    params = [W1, b1, W2, b2, W3, b3v]
    mth = [np.zeros_like(p) for p in params]
    vth = [np.zeros_like(p) for p in params]
    lr, be1, be2 = 3e-3, 0.9, 0.999
    for ep in range(1, epochs + 1):
        z1 = Xt @ W1 + b1; a1 = np.tanh(z1)
        z2 = a1 @ W2 + b2; a2 = np.tanh(z2)
        pred = (a2 @ W3 + b3v).ravel() + 1.0
        err = pred - yt
        # censored: only penalize if prediction is BELOW the bound
        err = np.where(ct & (err > 0), 0.0, err)
        g = 2.0 * err * wt / max(wt.sum(), 1e-9)
        gW3 = a2.T @ g[:, None]; gb3 = g.sum(keepdims=True)
        d2 = (g[:, None] @ W3.T) * (1 - a2 ** 2)
        gW2 = a1.T @ d2; gb2 = d2.sum(0)
        d1 = (d2 @ W2.T) * (1 - a1 ** 2)
        gW1 = Xt.T @ d1; gb1 = d1.sum(0)
        grads = [gW1, gb1, gW2, gb2, gW3, gb3]
        for k in range(6):
            grads[k] = grads[k] + 1e-4 * params[k]
            mth[k] = be1 * mth[k] + (1 - be1) * grads[k]
            vth[k] = be2 * vth[k] + (1 - be2) * grads[k] ** 2
            params[k] -= lr * (mth[k] / (1 - be1 ** ep)) / (np.sqrt(vth[k] / (1 - be2 ** ep)) + 1e-8)
        W1, b1, W2, b2, W3, b3v = params
    return params


def predict(params, Xt):
    W1, b1, W2, b2, W3, b3v = params
    return (np.tanh(np.tanh(Xt @ W1 + b1) @ W2 + b2) @ W3 + b3v).ravel() + 1.0


# section assignment (V1-pinned gates)
v1 = np.load(REC + r"\refline_plan_v1_27s.npz")
l1 = v1["line"]; s1 = np.concatenate([[0.0], np.cumsum(np.hypot(*(np.roll(l1, -1, 0) - l1).T))])[:-1]
from scipy.spatial import cKDTree
tree = cKDTree(line)
bidx = []
for bst in [56, 136, 236, 340, 388, 428, 512, 568, 596, 656, 732, 820, 928]:
    _, im = tree.query(l1[bst]); bidx.append(int(im))
sec_of = np.zeros(n, int)
for k in range(13):
    a4, b4 = bidx[k], bidx[(k + 1) % 13]
    i = a4
    while i != b4:
        sec_of[i] = k + 1; i = (i + 1) % n

np.savez(REC + r"\vtrim_features.npz", X=X, names=np.array(FEAT_NAMES), mu=mu, sd=sd,
         label=m, weight=wgt, censored=censored, sec=sec_of, camber=camber)
print(f"features saved. informative stations (w>0.1): {(wgt > 0.1).sum()}, censored among them: {(censored & (wgt > 0.1)).sum()}")
print(f"camber proxy: min {camber.min():+.2f} @ s={s_of[int(np.argmin(camber))]:.0f}, "
      f"max {camber.max():+.2f} @ s={s_of[int(np.argmax(camber))]:.0f} m/s^2")

if "--loso" in sys.argv:
    print("\nLeave-one-section-out (informative stations only):")
    print(f"{'sec':>4} {'n':>4} {'label med':>9} {'pred med':>8} {'wMAE':>6}")
    for k in range(1, 14):
        te = (sec_of == k) & (wgt > 0.1)
        tr = (sec_of != k) & (wgt > 0.1)
        if te.sum() < 5:
            print(f"S{k:<3} {te.sum():>4} (too few informative stations)")
            continue
        p = fit_mlp(Xn[tr], m[tr], wgt[tr], censored[tr], seed=k)
        pr = predict(p, Xn[te])
        lab = m[te]; cw = wgt[te]; ce = censored[te]
        e = np.abs(pr - lab)
        e = np.where(ce & (pr > lab), 0.0, e)
        print(f"S{k:<3} {te.sum():>4} {np.median(lab):9.2f} {np.median(pr):8.2f} {np.average(e, weights=cw):6.3f}")
    pfull = fit_mlp(Xn[wgt > 0.1], m[wgt > 0.1], wgt[wgt > 0.1], censored[wgt > 0.1], seed=99)
    prf = predict(pfull, Xn)
    np.savez(REC + r"\vtrim_model_eval.npz", pred=prf)
    print("\nfull-fit prediction saved to vtrim_model_eval.npz")
