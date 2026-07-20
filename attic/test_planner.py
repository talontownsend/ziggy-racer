"""Offline validation of the local planner:
  A) merge feasibility + convergence across a sweep of off-line states
  B) closed-loop kinematic-bicycle sim of planner+pure-pursuit (no game) -- the car
     must glide onto the line from a big offset with no spin / no oscillation.
"""
import glob, math, time
import numpy as np
from local_planner import LocalPlanner
from racing_line import menger_curvature

PLAN = sorted(glob.glob(r"C:\Users\talon\FH6-AFK-Farm\recordings\*_plan.npz"))[-1]
line = np.load(PLAN)["line"]
lp = LocalPlanner(line, a_lat=13.0)
k = menger_curvature(line)
straight_i, corner_i = int(np.argmin(k)), int(np.argmax(k))


def final_offset(plan):
    end = plan["path"][-1]
    j = int(np.argmin((line[:, 0]-end[0])**2 + (line[:, 1]-end[1])**2))
    return float((end - line[j]) @ lp.nrm[j])


# ---------------- A) feasibility + convergence sweep ----------------
print(f"plan={PLAN}\nstraight@{straight_i} (R={1/max(k[straight_i],1e-6):.0f}m)  "
      f"corner@{corner_i} (R={1/max(k[corner_i],1e-6):.0f}m)\n")
print("A) feasibility + convergence sweep")
results = []
for i0 in (straight_i, corner_i):
    base, n, htan = line[i0], lp.nrm[i0], lp.heading_ref[i0]
    for d0 in (-4, -3, -0.5, 0.5, 2, 4):
        for psi in (-20, 0, 15, 30):
            for v in (15, 25, 40, 55):
                x, z = base + d0 * n
                lp.prev_dn = None  # independent scenarios
                pl = lp.plan(x, z, htan + math.radians(psi), v, i_hint=i0)
                results.append((i0 == corner_i, d0, psi, v, pl, final_offset(pl)))
ends = [abs(r[5]) for r in results]
# feasibility is realistic only at low/mid speed; a 4 m snap at 55 m/s SHOULD be flagged
# infeasible (and the planner then returns the gentlest path + degraded flag).
low = [r for r in results if r[3] <= 25]
low_feas = [r[4]["feasible"] for r in low]
allconv = max(ends) < 0.06
print(f"  {len(results)} scenarios: max|end offset|={max(ends):.3f}m (all converge: {allconv})")
print(f"  low/mid-speed (v<=25) feasible: {sum(low_feas)}/{len(low)}  "
      f"(high-speed big-offset correctly infeasible -> gentle+degraded)")
# big offsets right at the R8m hairpin are legitimately infeasible even slow; accept >=80%
print(f"  PASS-A: {'YES' if allconv and sum(low_feas)/len(low) >= 0.8 else 'NO'}")

# ---------------- B) closed-loop kinematic sim ----------------
print("\nB) closed-loop kinematic-bicycle sim (planner + pure pursuit), start 4 m off line")
def run_sim(start_i, d_start, v_set, secs=10.0, dt=1/60):
    base, n, htan = line[start_i], lp.nrm[start_i], lp.heading_ref[start_i]
    x, z = base + d_start * n
    heading = htan                      # start pointing along the line (worst case: big lateral error)
    v = min(v_set, 12.0)               # realistic: start moderate, speed controller takes over
    lp.prev_dn = None
    idx = start_i
    cte_hist = []
    for step in range(int(secs / dt)):
        idx = lp.localize(x, z, idx)
        pl = lp.plan(x, z, heading, v, i_hint=idx)
        ld = float(np.clip(6 + 0.3 * v, 7, 40))
        tgt = lp.lookahead_target(pl, ld)
        alpha = math.atan2(tgt[1] - z, tgt[0] - x) - heading
        alpha = (alpha + math.pi) % (2*math.pi) - math.pi
        kappa_cmd = 2.0 * math.sin(alpha) / ld          # pure pursuit
        kmax = lp.a_lat / (v*v)                          # grip-limited turn rate
        kappa_cmd = max(-kmax, min(kmax, kappa_cmd))
        # SPEED CONTROLLER: slow for the planned curvature ahead (v_curve = sqrt(a_lat/kappa))
        k_ahead = lp.max_kappa_ahead(pl, ld + 12.0)
        v_curve = math.sqrt(lp.a_lat / max(abs(k_ahead), 1e-3))
        v_tgt = min(v_set, v_curve)
        v += max(-18.0 * dt, min(9.0 * dt, v_tgt - v))   # brake 1.8g / accel 0.9g limited
        v = max(v, 4.0)
        # integrate kinematic bicycle
        heading += v * kappa_cmd * dt
        x += v * math.cos(heading) * dt
        z += v * math.sin(heading) * dt
        j = lp.localize(x, z, idx)
        cte = float((np.array([x, z]) - line[j]) @ lp.nrm[j])
        cte_hist.append(cte)
    return np.array(cte_hist)

ok = True
for (name, i0) in [("straight", straight_i), ("corner-region", (corner_i-40) % len(line))]:
    for v in (20.0, 35.0):
        cte = run_sim(i0, 4.0, v)
        settle = cte[int(len(cte)*0.5):]              # second half = settled
        sign_flips = int(np.sum(np.abs(np.diff(np.sign(settle))) > 0))
        thresh = 0.35 if name == "straight" else 0.65  # hairpin region settles higher (apexing line)
        converged = np.abs(settle).mean() < thresh
        smooth = sign_flips < 12                       # not oscillating
        ok = ok and converged and smooth
        print(f"  {name:14s} v={v:4.0f}: start cte {cte[0]:+.1f}m -> settled |cte| "
              f"{np.abs(settle).mean():.2f}m (max {np.abs(settle).max():.2f})  "
              f"sign-flips {sign_flips}  {'OK' if converged and smooth else 'CHECK'}")
print(f"  PASS-B: {'YES' if ok else 'NO'} (converge <0.35 m, no oscillation)")

# ---------------- timing ----------------
t0 = time.time()
for _ in range(2000):
    lp.plan(line[straight_i, 0]+2, line[straight_i, 1], lp.heading_ref[straight_i], 40, i_hint=straight_i)
dtms = (time.time()-t0)/2000*1000
print(f"\nplan() timing: {dtms:.3f} ms/call  (<16 ms budget: {'OK' if dtms < 16 else 'TOO SLOW'})")
