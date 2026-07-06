#!/usr/bin/env python3
"""
Receding-horizon LOCAL PLANNER for the FH6 follower (Frenet quintic merge).

Each tick we generate a short, smooth MERGE TRAJECTORY from the car's current state
back onto the racing line and the tracker follows THAT path -- so the follower stops
chasing the global line exactly and instead always follows a fresh, grip-feasible path
that converges onto it. This is the Frenet-frame local planner (Werling et al.) used in
Apollo/Autoware/Waymo-lineage stacks, with the racing refinements from the design pass:

  - Frenet coords vs the reference line: s = arc length, d = signed lateral offset (left+).
    The car's lateral state is (d0, d0', d0'') with d0 = cross-track offset and
    d0' = dd/ds = tan(heading_err) * (1 - kappa_ref*d0)  (Werling high-speed relation).
  - QUINTIC lateral blend d(Δs): (d0, d0', 0) -> (0, 0, 0) over a horizon L. Continuous
    position/heading/curvature => smooth, low-jerk, no kinks. If on the line, d≡0.
  - Sample several horizons L (speed- & offset-adaptive); score by cost; pick the best.
  - FEASIBILITY on the MERGE-ADDED curvature only (kappa_merge = d''/(1+d'^2)^1.5), NOT
    the line's own curvature (that's the speed controller's job to slow for). This is the
    key fix: it lets the planner corner instead of rejecting every corner as "too tight".
  - TEMPORAL CONSISTENCY (critical at 60 Hz): a previous-plan-divergence cost term + a
    horizon-hysteresis so the choice doesn't chatter tick-to-tick.

Returns a world path beginning AT the car, plus per-point total curvature (for the speed
clamp and steer feedforward), and feasible/degraded flags. numpy only, <<1 ms.
"""
from __future__ import annotations

import numpy as np


def _quintic(p0, v0, a0, p1, v1, a1, T):
    """Coefficients c0..c5 of the quintic meeting (p0,v0,a0)@0 and (p1,v1,a1)@T."""
    T = max(T, 1e-3)
    c0, c1, c2 = p0, v0, 0.5 * a0
    T2, T3, T4, T5 = T * T, T**3, T**4, T**5
    c3 = (20 * (p1 - p0) - (8 * v1 + 12 * v0) * T - (3 * a0 - a1) * T2) / (2 * T3)
    c4 = (30 * (p0 - p1) + (14 * v1 + 16 * v0) * T + (3 * a0 - 2 * a1) * T2) / (2 * T4)
    c5 = (12 * (p1 - p0) - (6 * v1 + 6 * v0) * T + (a1 - a0) * T2) / (2 * T5)
    return np.array([c0, c1, c2, c3, c4, c5])


def _wrap(a):
    return (a + np.pi) % (2 * np.pi) - np.pi


def _smooth_closed(a, w=5):
    if w <= 1:
        return a
    k = np.ones(w) / w
    return np.convolve(np.r_[a[-w:], a, a[:w]], k, "same")[w:-w]


class LocalPlanner:
    def __init__(self, line, *, a_lat=13.0, delta_max=0.6, L_eff=3.0,
                 T_h=1.4, S_min=10.0, S_max=55.0, S_hardmax=80.0,
                 k_d=3.0, k_th=0.5, horizon_mults=(0.7, 1.0, 1.4, 1.9, 2.6),
                 n_pts=24, kappa_margin=0.85, d_max=8.0,
                 w_jerk=0.4, w_len=0.015, w_merge=6.0, w_dev=0.3, w_prev=2.0,
                 big=100.0, hysteresis=0.92, w_speed=0.0, kappa_pct=100.0, w_hyst=0.0,
                 d0p_max=2.6):
        """line: (N,2) closed reference (world x,z). a_lat: lateral grip m/s^2."""
        self.line = np.asarray(line, float)
        self.N = len(self.line)
        self.a_lat = a_lat
        self.delta_max = delta_max
        self.L_eff = L_eff
        self.T_h, self.S_min, self.S_max, self.S_hardmax = T_h, S_min, S_max, S_hardmax
        self.k_d, self.k_th = k_d, k_th
        self.horizon_mults = tuple(horizon_mults)
        self.n_pts = n_pts
        self.kappa_margin = kappa_margin
        self.d_max = d_max
        self.w_jerk, self.w_len, self.w_merge = w_jerk, w_len, w_merge
        self.w_dev, self.w_prev, self.big = w_dev, w_prev, big
        self.hysteresis = hysteresis
        # MOMENTUM term: cost -= w_speed * (predicted corner speed this path forces). Lets the
        # planner trade distance-to-line against carried speed (off by default -> enable live).
        self.w_speed = w_speed
        # v_curve curvature clamp uses this PERCENTILE (not raw max) so a single noise kink in
        # the next 18 m can't bind the whole corner-speed cap. 85 ~= true corner, rejects kinks.
        self.kappa_pct = kappa_pct
        # PLAN-AMPLIFICATION CLAMP: the quintic must match the car's lateral drift slope
        # d0' = dd/ds at its start, so with a big heading error the plan BULGES PAST the car
        # (measured: target -8.2 m when the car was -6.7) and then overshoots the line on the
        # way back -- the planner rings WITH the car instead of damping it (the hairpin limit
        # cycle). Clamping d0' caps how much of the car's runaway heading is projected into
        # the plan: the path still starts at the car but immediately leads back toward the
        # line, restoring a damping reference. ~0.3 (17 deg drift slope) is generous for
        # healthy driving; the pathological hairpin entries hit tan(1.2)=2.57. Live-tunable.
        self.d0p_max = d0p_max
        # HORIZON HYSTERESIS: penalize changing the merge horizon vs last tick. Without it the
        # planner re-picks among the 5 near-equal-cost candidates every tick -> horizon chatters
        # (12<->60 m) -> the merge-path curvature (kappa_ff) jumps -> steer FEEDFORWARD jumps ->
        # steering HUNTS (turn-in/straighten), worst in slow tight corners. Quadratic in the
        # relative horizon change: cheap for gradual drift (so A can still lengthen merges),
        # expensive for tick-to-tick flips. (replaces the dead `hysteresis` field.)
        self.w_hyst = w_hyst
        # arc length + frames
        d = np.roll(self.line, -1, axis=0) - self.line
        self.seg = np.hypot(d[:, 0], d[:, 1])
        self.cum_s = np.concatenate([[0.0], np.cumsum(self.seg)])
        self.total_s = float(self.cum_s[-1])
        tang = np.roll(self.line, -1, 0) - np.roll(self.line, 1, 0)
        tang /= np.maximum(np.hypot(tang[:, 0], tang[:, 1]), 1e-9)[:, None]
        self.tang = tang
        self.nrm = np.column_stack([-tang[:, 1], tang[:, 0]])       # left normal
        self.heading_ref = np.arctan2(tang[:, 1], tang[:, 0])
        # signed reference curvature (menger magnitude * turn sign), smoothed
        p0 = np.roll(self.line, 1, 0); p2 = np.roll(self.line, -1, 0)
        a = np.hypot(*(self.line - p0).T); b = np.hypot(*(p2 - self.line).T); c = np.hypot(*(p2 - p0).T)
        area = 0.5 * np.abs((self.line[:, 0]-p0[:, 0])*(p2[:, 1]-p0[:, 1]) -
                            (self.line[:, 1]-p0[:, 1])*(p2[:, 0]-p0[:, 0]))
        denom = a * b * c
        kmag = np.where(denom > 1e-9, 4 * area / denom, 0.0)
        sign = np.sign((self.line[:, 0]-p0[:, 0])*(p2[:, 1]-p0[:, 1]) -
                       (self.line[:, 1]-p0[:, 1])*(p2[:, 0]-p0[:, 0]))
        # NOTE: kappa_ref is DUAL-USE -- it feeds BOTH the v_curve speed clamp AND the steer
        # feedforward (kappa_ff via kappa_at). Widening this smoothing to de-kink the speed clamp
        # also weakened turn-in -> understeer wide -> off-track. So keep it tight (w=5 ~= 2.5 m);
        # de-kink the SPEED path separately (kappa_pct) if needed, NOT by smoothing the FF source.
        self.kappa_ref = _smooth_closed(kmag * sign, 5)
        # temporal-consistency memory
        self.prev_dn = None      # chosen lateral profile on a normalized [0,1] grid
        self.prev_L = None

    # ---- reference samples at arbitrary arc length ----
    def _ref_at(self, s):
        s = np.mod(s, self.total_s)
        i = np.clip(np.searchsorted(self.cum_s, s, side="right") - 1, 0, self.N - 1)
        frac = (s - self.cum_s[i]) / np.maximum(self.seg[i], 1e-9)
        p = self.line[i] + frac[:, None] * (self.line[(i + 1) % self.N] - self.line[i])
        h0 = self.heading_ref[i]; h1 = self.heading_ref[(i + 1) % self.N]
        h = h0 + _wrap(h1 - h0) * frac
        nrm = np.column_stack([-np.sin(h), np.cos(h)])
        kr = self.kappa_ref[i] + (self.kappa_ref[(i + 1) % self.N] - self.kappa_ref[i]) * frac
        return p, nrm, kr

    def localize(self, x, z, i_hint=None):
        if i_hint is None:
            return int(np.argmin((self.line[:, 0]-x)**2 + (self.line[:, 1]-z)**2))
        win = [(i_hint + k) % self.N for k in range(-5, 30)]
        wd = [(self.line[j, 0]-x)**2 + (self.line[j, 1]-z)**2 for j in win]
        i = win[int(np.argmin(wd))]
        if min(wd) > 900.0:
            i = int(np.argmin((self.line[:, 0]-x)**2 + (self.line[:, 1]-z)**2))
        return i

    def plan(self, x, z, heading, speed, i_hint=None):
        i0 = self.localize(x, z, i_hint)
        n0 = self.nrm[i0]
        d0 = float((np.array([x, z]) - self.line[i0]) @ n0)
        d0 = float(np.clip(d0, -self.d_max, self.d_max))
        psi = float(_wrap(heading - self.heading_ref[i0]))
        s0 = float(self.cum_s[i0]); kr0 = float(self.kappa_ref[i0])
        d0p = float(np.tan(np.clip(psi, -1.2, 1.2)) * (1.0 - kr0 * d0))  # dd/ds
        d0p = float(np.clip(d0p, -self.d0p_max, self.d0p_max))  # cap plan amplification (see init)
        v = max(speed, 3.0)
        klim = self.kappa_margin * self.a_lat / (v * v)            # merge curvature budget
        kgeom = np.tan(self.delta_max) / self.L_eff                # geometric steer cap

        # Merge length scales with HOW FAR OFF we are (+ heading error), so on the line ->
        # short horizon -> tight tracking; far off -> long, gentle merge. Speed enters only
        # weakly (k_th*psi*v) and via the feasibility sampling below -- NOT as a big base.
        # (A large speed base, T_h*v, left a steady ~1 m offset: it always planned a very
        # gentle merge that never closed the last bit even when nearly on the line.)
        S_ref = self.S_min + self.k_d * abs(d0) + self.k_th * abs(psi) * v
        S_ref = float(np.clip(S_ref, self.S_min, self.S_max))  # cap (S_max, live-tunable): keeps a
                                                          # big offset from running away to an
                                                          # over-gentle merge (loose loop). Raise
                                                          # S_max for gentler rejoins.

        best = None; best_feas = None
        for m in self.horizon_mults:
            L = float(np.clip(S_ref * m, self.S_min, self.S_hardmax))
            c = _quintic(d0, d0p, 0.0, 0.0, 0.0, 0.0, L)
            ds = np.linspace(0.0, L, self.n_pts)
            dd = c[0] + c[1]*ds + c[2]*ds**2 + c[3]*ds**3 + c[4]*ds**4 + c[5]*ds**5
            dp = c[1] + 2*c[2]*ds + 3*c[3]*ds**2 + 4*c[4]*ds**3 + 5*c[5]*ds**4
            dpp = 2*c[2] + 6*c[3]*ds + 12*c[4]*ds**2 + 20*c[5]*ds**3
            d3 = 6*c[3] + 24*c[4]*ds + 60*c[5]*ds**2
            p, nrm, kr = self._ref_at(s0 + ds)
            path = p + dd[:, None] * nrm
            kappa_merge = dpp / np.maximum((1.0 + dp**2)**1.5, 1e-9)   # curvature the merge ADDS
            kappa_path = kr + kappa_merge                              # total (for speed/FF)
            km_max = float(np.max(np.abs(kappa_merge)))
            # MOMENTUM: the corner-speed THIS candidate would force on the v_curve clamp.
            # v_curve downstream = sqrt(a_lat / |kappa_total|) over the next ~18 m, so a short
            # tight merge self-inflicts a low v_curve (its own curvature bulge), and chasing a
            # kink does too. Reward candidates that keep that predicted speed high, using the
            # SAME robust percentile the clamp uses, so the planner optimizes what the speed
            # controller will actually do. On a true straight all candidates share a high
            # v_cand -> term is flat -> no wandering. (a_lat is live downforce grip, set/tick.)
            kc = np.abs(kappa_path)[ds <= 18.0]
            k_eff = float(np.percentile(kc, self.kappa_pct)) if kc.size else float(np.max(np.abs(kappa_path)))
            v_cand = float(np.sqrt(self.a_lat / max(k_eff, 1e-4)))
            feasible = (km_max <= klim) and (km_max <= kgeom)
            # normalized lateral profile for the previous-plan consistency term
            dn = dd / max(abs(d0), 1e-3)
            prevdiff = float(np.mean((dn - self.prev_dn)**2)) if self.prev_dn is not None else 0.0
            j2 = d3**2
            jerk = float(np.sum(0.5 * (j2[:-1] + j2[1:]) * np.diff(ds)))
            hyst = 0.0
            if self.prev_L is not None and self.w_hyst > 0.0:
                hyst = self.w_hyst * ((L - self.prev_L) / max(self.prev_L, 5.0)) ** 2
            cost = (self.w_jerk * jerk + self.w_len * L + self.w_merge * km_max +
                    self.w_dev * float(np.mean(dd**2)) + self.w_prev * prevdiff +
                    self.big * max(0.0, km_max - klim)
                    - self.w_speed * v_cand                # reward carried speed (momentum)
                    + hyst)                                # resist tick-to-tick horizon flipping
            cand = dict(path=path, kappa_path=kappa_path, kappa_merge_max=km_max,
                        i0=i0, s0=s0, d0=d0, psi=psi, horizon=L, feasible=feasible,
                        cost=cost, dn=dn)
            if best is None or cost < best["cost"]:
                best = cand
            if feasible and (best_feas is None or cost < best_feas["cost"]):
                best_feas = cand

        chosen = best_feas if best_feas is not None else best
        chosen = dict(chosen)
        chosen["degraded"] = best_feas is None
        # horizon hysteresis: keep last horizon if it's still (near-)best, to avoid chatter
        self.prev_dn = chosen["dn"]
        self.prev_L = chosen["horizon"]
        return chosen

    def lookahead_target(self, plan, ld):
        """point on the merge path ~ld meters ahead of its start (for pure pursuit)."""
        path = plan["path"]
        seg = np.hypot(*np.diff(path, axis=0).T)
        cum = np.concatenate([[0.0], np.cumsum(seg)])
        if ld >= cum[-1]:
            return path[-1]
        j = min(max(int(np.searchsorted(cum, ld)), 1), len(path) - 1)
        f = (ld - cum[j - 1]) / max(seg[j - 1], 1e-9)
        return path[j - 1] + f * (path[j] - path[j - 1])

    def kappa_at(self, plan, ld):
        """planned TOTAL curvature ~ld meters ahead (steer feedforward / speed clamp)."""
        path = plan["path"]; kp = plan["kappa_path"]
        seg = np.hypot(*np.diff(path, axis=0).T)
        cum = np.concatenate([[0.0], np.cumsum(seg)])
        j = min(max(int(np.searchsorted(cum, ld)), 1), len(path) - 1)
        return float(kp[j])

    def kappa_line_ahead(self, plan, ld):
        """Curvature of the REFERENCE LINE ~ld m ahead of the car (STABLE corner anticipation
        for the steer feedforward). Unlike kappa_at -- which returns the per-tick MERGE-path
        curvature that wobbles with the car's instantaneous d0/psi and so feeds the
        planner<->tracker steering limit cycle -- this reads the fixed, smoothed line curvature.
        Use it for the FF so the feedforward anticipates the CORNER, not the car's own wobble."""
        s = float(plan["s0"]) + float(ld)
        return float(self._ref_at(np.array([s]))[2][0])

    def max_kappa_line_ahead(self, plan, dist, pct=None):
        """Robust |LINE curvature| within `dist` ahead of the car (STABLE corner-speed cap).
        The merge-path curvature (max_kappa_ahead) re-plans every tick and BREATHES with the
        car's state -- measured spiking v_curve 110->190->86 km/h inside one braking zone,
        releasing the brake mid-corner-approach. The line's curvature is ground truth for the
        corner itself and cannot spike; use min(v_line, v_merge) downstream so merge curvature
        can still SLOW for rejoin arcs but can never spike the cap upward."""
        if pct is None:
            pct = self.kappa_pct
        s0 = float(plan["s0"])
        ss = np.mod(np.linspace(s0, s0 + max(dist, 1.0), 16), self.total_s)
        i = np.clip(np.searchsorted(self.cum_s, ss, side="right") - 1, 0, self.N - 1)
        a = np.abs(self.kappa_ref[i])
        return float(np.percentile(a, pct)) if a.size else 0.0

    def max_kappa_ahead(self, plan, dist, pct=None):
        """Robust |total curvature| within `dist` along the merge path (speed clamp).
        Uses a high PERCENTILE (self.kappa_pct), not the raw max, so a single noise-kink
        station can't bind the whole corner-speed cap. A real corner has many high stations
        in a row (>= the percentile, unaffected); an isolated kink is a small minority and
        sits above the percentile -> rejected. This is what stops braking for straight kinks."""
        if pct is None:
            pct = self.kappa_pct
        path = plan["path"]; kp = plan["kappa_path"]
        seg = np.hypot(*np.diff(path, axis=0).T)
        cum = np.concatenate([[0.0], np.cumsum(seg)])
        m = cum[:len(kp)] <= dist
        a = np.abs(kp[m]) if m.any() else np.abs(kp)
        return float(np.percentile(a, pct)) if a.size else 0.0
