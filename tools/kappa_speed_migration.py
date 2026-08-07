"""Migration table for the speed-path kappa change.

The learned vtrim map was trained against the OLD caps. At corners where the cap rises, the
existing map_w (learned to compensate for a cap that was too low, 1.35-1.45 at corners 1 and 3)
multiplies the NEW cap and produces effective targets far above anything ever driven. That is a
crash, not a test.

Reports, per station:
  old_eff = old_cap * map_w      (today's effective target)
  new_eff = new_cap * map_w      (what arming ksp_on alone would produce)
  jump    = new_eff - old_eff

Then evaluates the proposed migration: pre-scale the map by old_cap/new_cap where the cap moved
more than PCT, which preserves day-one effective targets exactly. Checks the [0.80, 1.55] bounds
and the window-min health metric.

NOTE map_w is a WINDOW-MIN over the next 18 stations, not the map at the station, so per-station
rescaling does not exactly preserve the window-min. That error is quantified rather than assumed.
"""
import numpy as np
import sys

sys.path.insert(0, '.')
from local_planner import LocalPlanner

ALAT, AK, W = 27.0, 0.0025, 18
LO_B, HI_B = 0.80, 1.55
PCT = 0.05

line = np.load('recordings/refline_plan.npz')['line']
N = len(line)
seg = np.hypot(*(np.roll(line, -1, 0) - line).T)
cum = np.concatenate([[0.0], np.cumsum(seg)])
tot = float(cum[-1])

pa = LocalPlanner(line, a_lat=ALAT)
pb = LocalPlanner(line, a_lat=ALAT); pb.use_speed_kappa = True


def caps(p):
    out = np.empty(N)
    for i in range(N):
        ss = np.mod(np.linspace(cum[i], cum[i] + 18.0, 16), tot)
        idx = np.clip(np.searchsorted(cum, ss, side='right') - 1, 0, N - 1)
        src = p.kappa_speed if p.use_speed_kappa else p.kappa_ref
        k = np.percentile(np.abs(src[idx]), p.kappa_pct)
        out[i] = 3.6 * np.sqrt(ALAT / max(k - AK, 1e-4))
    return out


old_cap, new_cap = caps(pa), caps(pb)
ratio = new_cap / np.maximum(old_cap, 1e-9)
mp = np.load('recordings/vtrim_map.npz')['map'].astype(float)
idxw = (np.arange(N)[:, None] + np.arange(W)[None, :]) % N
mapw = mp[idxw].min(axis=1)

old_eff = old_cap * mapw
new_eff = new_cap * mapw
jump = new_eff - old_eff

print(f"CAP CHANGE: median {100*(np.median(ratio)-1):+.1f}%   "
      f"stations up >5%: {100*np.mean(ratio > 1+PCT):.0f}%   down >5%: {100*np.mean(ratio < 1-PCT):.0f}%")
print(f"  cap  old median {np.median(old_cap):.1f} -> new {np.median(new_cap):.1f} km/h")
print(f"  map_w (window-min) median {np.median(mapw):.3f}  max {mapw.max():.3f}")

print(f"\nLARGEST EFFECTIVE-TARGET JUMPS (new_cap * current map_w vs today)")
print(f"  {'stn':>5} {'old_cap':>8} {'new_cap':>8} {'map_w':>6} {'old_eff':>8} {'new_eff':>8} {'jump':>7}")
for i in np.argsort(-jump)[:12]:
    print(f"  {i:5d} {old_cap[i]:8.1f} {new_cap[i]:8.1f} {mapw[i]:6.3f} "
          f"{old_eff[i]:8.1f} {new_eff[i]:8.1f} {jump[i]:+7.1f}")
print(f"\n  max effective target today {old_eff.max():.0f} km/h -> with ksp_on alone "
      f"{new_eff.max():.0f} km/h")
print(f"  stations whose effective target would exceed 250 km/h: "
      f"{int(np.sum(new_eff > 250))} (today {int(np.sum(old_eff > 250))})")

# ---- proposed migration: pre-scale where the cap moved > PCT ----------------
scale = np.where(np.abs(ratio - 1) > PCT, old_cap / np.maximum(new_cap, 1e-9), 1.0)
mig = mp * scale
clipped = np.clip(mig, LO_B, HI_B)
n_lo = int(np.sum(mig < LO_B)); n_hi = int(np.sum(mig > HI_B))
mig_w = clipped[idxw].min(axis=1)
mig_eff = new_cap * mig_w

print(f"\nPROPOSED MIGRATION: map *= old_cap/new_cap where |ratio-1| > {PCT:.0%}")
print(f"  stations rescaled: {int(np.sum(scale != 1.0))} ({100*np.mean(scale != 1.0):.0f}%)")
print(f"  scale factor: min {scale.min():.3f}  median {np.median(scale[scale!=1]):.3f}  max {scale.max():.3f}")
print(f"  map after rescale: min {mig.min():.3f}  max {mig.max():.3f}")
print(f"  BOUND VIOLATIONS: below {LO_B}: {n_lo} stations   above {HI_B}: {n_hi} stations")
if n_lo:
    bad = np.where(mig < LO_B)[0]
    print(f"    worst below-floor: station {bad[np.argmin(mig[bad])]} -> {mig.min():.3f} "
          f"(clipped to {LO_B}); cap there {old_cap[bad[np.argmin(mig[bad])]]:.0f} -> "
          f"{new_cap[bad[np.argmin(mig[bad])]]:.0f}")
print(f"\n  EFFECTIVE TARGET after migration vs today:")
err = mig_eff - old_eff
print(f"    identical within 1 km/h: {100*np.mean(np.abs(err) < 1.0):.1f}% of stations")
print(f"    median error {np.median(err):+.2f} km/h   p95 |err| {np.percentile(np.abs(err),95):.1f}   "
      f"max {err.max():+.1f} / {err.min():+.1f}")
print(f"    (nonzero because map_w is a WINDOW-MIN; per-station rescaling cannot preserve it exactly)")

print(f"\n  WINDOW-MIN HEALTH:")
print(f"    today     {mapw.mean():.4f}")
print(f"    migrated  {mig_w.mean():.4f}   ({mig_w.mean()-mapw.mean():+.4f})")
print(f"    floor occupancy {100*np.mean(mp<=LO_B+1e-3):.1f}% -> {100*np.mean(clipped<=LO_B+1e-3):.1f}%")
print(f"    ceiling         {100*np.mean(mp>=HI_B-1e-3):.1f}% -> {100*np.mean(clipped>=HI_B-1e-3):.1f}%")
verdict = (n_hi == 0 and n_lo <= 5 and np.percentile(np.abs(err), 95) < 8.0)
print(f"\n  MIGRATION {'VIABLE' if verdict else 'NEEDS WORK'}")
