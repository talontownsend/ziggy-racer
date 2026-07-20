#!/usr/bin/env python3
"""Train the residual corrector net on LAP TIME, by an antithetic evolution strategy (ES).

Black-box / derivative-free: no sim, no gradients -- just "write weights, watch laps, score."
The trainer and the (already running) follower share two files:
  - recordings/residual_net.npz   -- the WEIGHTS. Trainer writes a candidate; follower hot-loads
                                     it (~2x/s) and drives with it.
  - recordings/follow_log.csv     -- per-tick log. Trainer reads lap times + off-track back.

Each candidate is scored = median lap time over a few measured laps + an OFF-TRACK PENALTY
(so it can't "win" by cutting corners and crashing -- we saw exactly that with the smoothed
line). The base follower is stable and the residual is bounded, so a bad candidate can't wreck
the farm -- training runs unattended. The mean weights are saved continuously to residual_net.npz
(what the follower runs); residual_best.npz keeps the best-scoring snapshot.

Run: the follower must already be running with resid integration (it is after the residual
relaunch); this script sets resid_on=1 in tune.json, then loops. Ctrl-C to stop; rerun to resume
(pass --resume). Progress -> train_log.csv.
"""
import argparse, csv, json, os, time
import numpy as np
from residual_net import ResidualNet

DIR = r"C:\Users\talon\FH6-AFK-Farm\recordings"
RESID = os.path.join(DIR, "residual_net.npz")
BEST = os.path.join(DIR, "residual_best.npz")
MEAN_CKPT = os.path.join(DIR, "residual_mean.npz")
LOG = os.path.join(DIR, "follow_log.csv")
TUNE = os.path.join(DIR, "tune.json")
TRAINLOG = r"C:\Users\talon\FH6-AFK-Farm\train_log.csv"
STATE = os.path.join(DIR, "es_state.json")   # complete ES state -> crash-safe, lossless resume


def atomic_save_net(net, path):
    """Save the net npz ATOMICALLY (temp + os.replace) so a crash mid-write can never leave a
    truncated file for the follower to hot-load or the trainer to resume from. Retries os.replace
    a few times in case the follower has the file briefly open for reading."""
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        np.savez(fh, W1=net.W1, b1=net.b1, W2=net.W2, b2=net.b2, bounds=net.bounds)
    for _ in range(5):
        try:
            os.replace(tmp, path); return
        except PermissionError:
            time.sleep(0.05)
    os.replace(tmp, path)


def atomic_write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh)
    os.replace(tmp, path)


def set_resid_on(val=1.0):
    try:
        t = json.load(open(TUNE)); t["resid_on"] = val
        json.dump(t, open(TUNE, "w"), indent=2)
    except Exception as e:
        print(f"  (could not set resid_on: {e})")


# ---- follow_log.csv column indices ----
C_T, C_X, C_Z, C_SPD, C_CTE, C_ON, C_LT, C_SS, C_RP = 0, 1, 2, 3, 10, 17, 28, 29, 48
NCOL = 49

# incident thresholds (overridden from argv in main); calibrated on the real 71 Hz log
CRASH_G = 6.0      # decel above this g = an impact (braking tops out ~4.25 g at p99.9)
OVER_DEG = 8.0     # |sideslip| above this deg = a real slide (only 3.4% of clean frames)
CTE_OK = 2.5       # |cte| (m) below this is fine; excess penalized -- cte is the #1 lap-time predictor


def read_tail(nbytes=32_000_000):
    # 32 MB covers ~25 min of 71 Hz log (~265 B/row) -- 2x headroom over the 680 s measure
    # window. Too small would SILENTLY truncate the window (wrong metrics, no error).
    """Parse only the last nbytes of follow_log. It grows at ~71 Hz (millions of rows over a
    night), so reading the whole file every candidate would get ruinously slow; the tail still
    covers far more than one settle+measure window. Returns a dict of np arrays, or None."""
    try:
        sz = os.path.getsize(LOG)
        with open(LOG, "rb") as fh:
            if sz > nbytes:
                fh.seek(sz - nbytes)
                fh.readline()                          # drop the partial first line
            raw = fh.read().decode("utf-8", "replace")
    except OSError:
        return None
    keys = ("t", "x", "z", "spd", "cte", "on", "lt", "ss", "rp")
    idx = (C_T, C_X, C_Z, C_SPD, C_CTE, C_ON, C_LT, C_SS, C_RP)
    cols = {k: [] for k in keys}
    for line in raw.splitlines():
        p = line.split(",")
        if len(p) < NCOL or p[0] == "t":
            continue
        try:
            vals = [float(p[j]) for j in idx]
        except (ValueError, IndexError):
            continue
        for k, v in zip(keys, vals):
            cols[k].append(v)
    if len(cols["t"]) < 50:
        return None
    return {k: np.array(v) for k, v in cols.items()}


def now_logt():
    d = read_tail(2_000_000)
    return float(d["t"][-1]) if d is not None else None


def _m(m, k, nd=0):
    """Format a candidate metric, or '-' if it DNF'd (no metrics)."""
    if not m or m.get(k) is None:
        return "-"
    return f"{m[k]:.{nd}f}"


def window_metrics(t_lo, t_hi):
    """Incident-aware metrics over (t_lo, t_hi]: clean-lap times + reset/crash/oversteer/off-track.
    Glitch-robust for the 71 Hz log -- teleport and time-gap frames are excluded from the decel
    so a reset_car jump can't masquerade as a 430 g 'crash'."""
    d = read_tail()
    if d is None:
        return None
    t, x, z, spd, cte, on, lt, ss, rp = (d[k] for k in ("t", "x", "z", "spd", "cte", "on", "lt", "ss", "rp"))
    win = (t > t_lo) & (t <= t_hi)
    if int(win.sum()) < 50:
        return None
    wmid = win[1:]                                       # aligns with the np.diff arrays below

    # clean laps finishing in-window (lap_t drops to ~0 when a lap completes; >25 s skips glitches)
    laps = [lt[i-1] for i in range(1, len(t))
            if lt[i] < lt[i-1] - 5.0 and 25.0 < lt[i-1] < 90.0 and t_lo < t[i] <= t_hi]

    dt = np.diff(t)
    dpos = np.hypot(np.diff(x), np.diff(z))
    teleport = dpos > 15.0                               # impossible at racing speed -> reset_car
    gap = (dt > 0.30) | (dt <= 0.0)
    inrace = (rp[1:] >= 1) & (rp[:-1] >= 1)              # a race RESTART drops rp to 0 -> excluded

    n_reset = int(np.sum(teleport & inrace & wmid))

    dv = np.diff(spd) / 3.6                              # m/s
    safe = (~teleport) & (~gap)
    decel = np.where(safe, -dv / np.where(dt > 0, dt, 1.0), 0.0)
    g = np.clip(decel / 9.81, 0.0, 15.0)
    over_g = np.maximum(0.0, g - CRASH_G)
    crash_int = float(np.sum((over_g * np.minimum(dt, 0.1))[wmid]))   # g*seconds above threshold
    n_crash = int(np.sum((g > CRASH_G) & wmid))                      # frames over threshold (diag)

    over_slip = float(np.mean(np.maximum(0.0, np.abs(ss[win]) - OVER_DEG)))
    off = float(np.mean(on[win] < 0.5))
    acte = np.abs(cte[win]); acte = acte[acte < 100.0]      # drop garbage-localization spikes
    cte_excess = float(np.mean(np.maximum(0.0, acte - CTE_OK))) if acte.size else 0.0

    return dict(laps=laps, n_reset=n_reset, crash_int=crash_int, n_crash=n_crash,
                over_slip=over_slip, off=off, cte=cte_excess)


def evaluate(net, flat, a):
    """Write weights, let them settle, measure -> composite fitness (lower=better) + the metrics.

    fitness = median clean-lap time
            + w_reset * (# reset_car teleports)        <- VERY high: a reset means it gave up
            + w_crash * (g*s of decel above crash_g)   <- high, scales with impact severity
            + w_over  * (mean sideslip-excess deg)     <- moderate: discourage big slides
            + off_pen * off_track_fraction
    Clean candidates land ~33; crashy ones 50-70 -- a >15 s gap that swamps the ~0.3 s lap noise,
    so the ES finds the stable basin first, then refines speed inside it."""
    net.set_flat(flat); atomic_save_net(net, RESID)
    time.sleep(a.settle)                                 # follower hot-loads + clears the mixed lap
    t0 = now_logt()
    if t0 is None:
        time.sleep(a.measure); return a.dnf, None
    time.sleep(a.measure)
    m = window_metrics(t0, t0 + a.measure + 5.0)
    if m is None or not m["laps"]:
        return a.dnf, m                                  # no clean lap finished -> heavy penalty
    fit = (float(np.median(m["laps"]))
           + a.w_reset * m["n_reset"]
           + a.w_crash * m["crash_int"]
           + a.w_over * m["over_slip"]
           + a.w_cte * m["cte"]
           + a.off_pen * m["off"])
    return fit, m


def ensure_lap_med_column():
    """Non-destructive migration: add the 'lap_med' column (median CLEAN-lap time, pooled across
    the gen's candidates, independent of the incident penalties folded into fitness) without
    rewriting history. Historical gens (before this column existed) get a blank -- we don't have
    their raw lap times, only the composite fitness -- so old rows stay honest, not backfilled."""
    if not os.path.exists(TRAINLOG):
        return
    with open(TRAINLOG, newline="") as fh:
        rows = list(csv.reader(fh))
    if not rows or "lap_med" in rows[0]:
        return
    rows[0].insert(3, "lap_med")             # right after median_fit, before the incident columns
    for r in rows[1:]:
        r.insert(3, "")
    tmp = TRAINLOG + ".tmp"
    with open(tmp, "w", newline="") as fh:
        csv.writer(fh).writerows(rows)
    os.replace(tmp, TRAINLOG)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hidden", type=int, default=16)
    ap.add_argument("--pop", type=int, default=12, help="population (uses pop//2 antithetic pairs)")
    ap.add_argument("--sigma", type=float, default=0.08, help="exploration noise std")
    ap.add_argument("--lr", type=float, default=0.06)
    ap.add_argument("--settle", type=float, default=33.0, help="s to let new weights take over (~1 lap)")
    ap.add_argument("--measure", type=float, default=66.0, help="s to measure (~2 laps)")
    ap.add_argument("--off-pen", type=float, default=40.0, help="penalty per off-track fraction")
    ap.add_argument("--w-reset", type=float, default=10.0, help="penalty per reset_car teleport (very high)")
    ap.add_argument("--w-crash", type=float, default=10.0, help="penalty per g*s of decel above --crash-g")
    ap.add_argument("--w-over", type=float, default=2.0, help="penalty per deg of mean sideslip-excess")
    ap.add_argument("--crash-g", type=float, default=6.0, help="decel threshold (g) counted as an impact")
    ap.add_argument("--over-deg", type=float, default=8.0, help="sideslip threshold (deg) counted as a slide")
    ap.add_argument("--w-cte", type=float, default=5.0, help="penalty per m of mean |cte|-excess (line adherence)")
    ap.add_argument("--cte-ok", type=float, default=2.5, help="|cte| (m) below this is free; cte is the #1 lap-time predictor")
    ap.add_argument("--dnf", type=float, default=90.0, help="fitness when no clean lap finishes")
    ap.add_argument("--gens", type=int, default=10000)
    ap.add_argument("--resume", action="store_true")
    a = ap.parse_args()
    global CRASH_G, OVER_DEG, CTE_OK
    CRASH_G, OVER_DEG, CTE_OK = a.crash_g, a.over_deg, a.cte_ok

    net = ResidualNet(n_hidden=a.hidden)
    n = net.n_params
    rng = np.random.default_rng(1234)
    half = max(1, a.pop // 2)
    mean = np.zeros(n)
    best_fit = 1e9
    best_med, best_mean = 1e9, mean.copy()       # elitist guard: never drift far below the best gen
    REVERT_MARGIN = 12.0                          # gen median this much worse than best -> snap mean back
    gen_start = 0
    if a.resume and os.path.exists(STATE):        # crash-safe resume: restore the COMPLETE ES state
        try:
            st = json.load(open(STATE))
            if int(st.get("n", -1)) != n:
                print(f"  es_state n={st.get('n')} != {n} (feature count changed) -> starting FRESH")
            else:
                mean = np.array(st["mean"], float)
                best_mean = np.array(st["best_mean"], float)
                best_fit = float(st["best_fit"]); best_med = float(st["best_med"])
                gen_start = int(st["gen"]) + 1
                rng.bit_generator.state = st["rng"]      # restore the exact perturbation stream
                print(f"resumed FULL ES state from {STATE}: next gen {gen_start}, "
                      f"best_fit {best_fit:.2f}, best_med {best_med:.2f}")
        except Exception as e:
            print(f"  could not load es_state ({e}); falling back")
    elif a.resume and os.path.exists(MEAN_CKPT):  # older checkpoint: mean only
        mean = ResidualNet(a.hidden).load(MEAN_CKPT).get_flat()
        best_mean = mean.copy()
        print(f"resumed mean only from {MEAN_CKPT} (no es_state; gen/best reset)")
    print(f"residual ES: {n} params, pop {2*half} (antithetic), sigma {a.sigma}, lr {a.lr}")
    print(f"per-candidate ~{a.settle+a.measure:.0f}s -> ~{(a.settle+a.measure)*2*half/60:.0f} min/gen. Ctrl-C to stop.")
    print(f"fitness = lap + {a.w_reset:g}*reset + {a.w_crash:g}*crash(g*s>{a.crash_g:g}g)"
          f" + {a.w_over:g}*slip(>{a.over_deg:g}deg) + {a.w_cte:g}*cte(>{a.cte_ok:g}m) + {a.off_pen:g}*off")
    set_resid_on(1.0)
    ensure_lap_med_column()                    # non-destructive: adds the column if missing, no rewrite of history
    if not os.path.exists(TRAINLOG):
        csv.writer(open(TRAINLOG, "w", newline="")).writerow(
            ["gen", "best_fit", "median_fit", "lap_med", "avg_reset", "avg_crash", "avg_over", "avg_cte", "avg_off", "sigma", "elapsed_s"])
    t_start = time.time()

    for gen in range(gen_start, a.gens):
        set_resid_on(1.0)              # re-assert each gen: self-heals if a follower restart wiped tune.json
        eps = rng.standard_normal((half, n))
        fits = np.empty(2 * half)
        ms = []
        for i in range(half):
            fits[i],        mp = evaluate(net, mean + a.sigma * eps[i], a)
            fits[half + i], mm = evaluate(net, mean - a.sigma * eps[i], a)
            ms += [mp, mm]
            print(f"  gen {gen} pair {i+1}/{half}: fit+ {fits[i]:6.2f}  fit- {fits[half+i]:6.2f}"
                  f"   (+ rst {_m(mp,'n_reset')} crash {_m(mp,'crash_int',1)} "
                  f"slip {_m(mp,'over_slip',2)} cte {_m(mp,'cte',2)} off {_m(mp,'off',2)})", flush=True)
        med = float(np.median(fits))
        if med < best_med:                       # this mean's neighborhood is the best so far -> remember it
            best_med, best_mean = med, mean.copy()
        # rank shaping: lower fitness (faster + cleaner) -> higher utility, centered
        order = np.argsort(fits)
        util = np.empty(2 * half); util[order] = np.linspace(0.5, -0.5, 2 * half)
        up, um = util[:half], util[half:]
        grad = ((up - um)[:, None] * eps).sum(0) / half          # toward higher utility = better fitness
        mean = mean + a.lr * grad
        reverted = ""
        if med > best_med + REVERT_MARGIN:        # ELITIST: drifted well worse than best -> snap mean back
            mean = best_mean.copy(); reverted = " [REVERTED]"
        # the follower runs the MEAN weights; checkpoint + track best candidate (all atomic)
        net.set_flat(mean); atomic_save_net(net, RESID); atomic_save_net(net, MEAN_CKPT)
        gbest = float(fits.min())
        if gbest < best_fit:
            best_fit = gbest
            best_idx = int(order[0])
            bflat = (mean + a.sigma * eps[best_idx]) if best_idx < half else (mean - a.sigma * eps[best_idx - half])
            atomic_save_net(ResidualNet(a.hidden).set_flat(bflat), BEST)
        el = time.time() - t_start
        good = [m for m in ms if m]
        avg = lambda k: (float(np.mean([m[k] for m in good])) if good else float("nan"))
        # lap_med: median CLEAN-lap time pooled across every candidate's laps this gen, kept
        # SEPARATE from the composite fitness -- fitness mixes lap time + incident penalties, so a
        # falling fitness alone can't tell us whether it's getting FASTER or just CLEANER. This can.
        all_laps = [t for m in good for t in m.get("laps", [])]
        lap_med = float(np.median(all_laps)) if all_laps else float("nan")
        print(f"gen {gen:3d} | best {gbest:6.2f} (overall {best_fit:6.2f}) | median {med:6.2f}{reverted} "
              f"| lap {lap_med:.2f} | reset {avg('n_reset'):.1f} crash {avg('crash_int'):.1f} "
              f"slip {avg('over_slip'):.2f} cte {avg('cte'):.2f} off {avg('off'):.2f} | {el/60:.0f} min")
        csv.writer(open(TRAINLOG, "a", newline="")).writerow(
            [gen, round(gbest, 2), round(med, 2), round(lap_med, 2) if all_laps else "",
             round(avg('n_reset'), 2), round(avg('crash_int'), 2), round(avg('over_slip'), 3),
             round(avg('cte'), 3), round(avg('off'), 3), a.sigma, round(el)])
        # crash-safe checkpoint of the COMPLETE ES state -> a --resume continues exactly here,
        # losing at most the current in-flight gen and never clobbering residual_best / the anchor
        atomic_write_json(STATE, {"n": n, "gen": gen, "sigma": a.sigma, "lr": a.lr,
                                  "best_fit": best_fit, "best_med": best_med,
                                  "mean": mean.tolist(), "best_mean": best_mean.tolist(),
                                  "rng": rng.bit_generator.state})


if __name__ == "__main__":
    main()
