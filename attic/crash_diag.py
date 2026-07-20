"""Diagnose the crash: wheelspin (high rpm / low gear / flat speed under throttle)
and spin-outs (big heading rate / speed collapse) in the follower log."""
import numpy as np
LOG = r"C:\Users\talon\FH6-AFK-Farm\recordings\follow_log.csv"
# cols: 0t 1x 2z 3spd 4yaw 5head 6i0 7tx 8tz 9alpha 10cte 11steer 12thr 13brk
#       14tgt 15gear 16rpm 17ontrk 18maxrpm 19shift ... 27kappa 28lap 29lapt
rows = []
for ln in open(LOG):
    ln = ln.strip()
    if not ln or ln[0].isalpha():
        continue
    p = ln.split(",")
    if len(p) < 18:
        continue
    try:
        rows.append([float(p[i]) for i in range(18)])
    except ValueError:
        continue
D = np.array(rows)
if len(D) < 5:
    print("not enough rows", len(D)); raise SystemExit
t, spd, head, thr, brk, tgt, gear, rpm, ontrk = (D[:,0], D[:,3], D[:,5], D[:,12],
    D[:,13], D[:,14], D[:,15], D[:,16], D[:,17])
dt = np.gradient(t)
dspd = np.gradient(spd) / np.maximum(dt, 1e-3)        # km/h per s
hrate = np.abs(np.gradient(np.unwrap(np.radians(head))) / np.maximum(dt, 1e-3))  # rad/s
print(f"rows={len(D)}  dur={t[-1]-t[0]:.1f}s  spd {spd.min():.0f}-{spd.max():.0f} km/h")
print(f"on-track fraction: {100*ontrk.mean():.0f}%   gears seen: {sorted(set(gear.astype(int)))}")

# wheelspin: high throttle, low gear, high rpm, but speed NOT climbing (or falling)
ws = (thr > 0.4) & (gear <= 2) & (rpm > 5500) & (dspd < 3)
print(f"\nwheelspin-suspect frames (thr>0.4 & gear<=2 & rpm>5500 & dspd<3): {ws.sum()} "
      f"({100*ws.mean():.0f}%)")
# spin-out: very high heading rate
spin = hrate > np.radians(120)     # >120 deg/s yaw of travel = sliding/spinning
print(f"high heading-rate frames (>120 deg/s): {spin.sum()}  max={np.degrees(hrate.max()):.0f} deg/s")
# big speed collapses (crash impacts / spins scrub speed)
drop = dspd < -60
print(f"hard speed-drop frames (<-60 km/h/s): {drop.sum()}  worst={dspd.min():.0f} km/h/s")

steer = D[:, 11]; cte = D[:, 10]
# top-3 spin onsets (local maxima of heading rate), with throttle context
order = np.argsort(hrate)[::-1]
picked = []
for k in order:
    if all(abs(k - q) > 25 for q in picked):
        picked.append(k)
    if len(picked) == 3:
        break
for k in sorted(picked):
    print(f"\n--- spin event @ t={t[k]:.1f}s  peak {np.degrees(hrate[k]):.0f} deg/s ---")
    print(f"{'t':>6} {'spd':>5} {'tgt':>5} {'thr':>4} {'brk':>4} {'gr':>3} {'rpm':>5} {'steer':>6} {'cte':>5} {'dspd':>6} {'h°/s':>6} {'on':>2}")
    for i in range(max(0, k-6), min(len(D), k+6)):
        print(f"{t[i]:6.1f} {spd[i]:5.0f} {tgt[i]:5.0f} {thr[i]:4.2f} {brk[i]:4.2f} "
              f"{int(gear[i]):3d} {rpm[i]:5.0f} {steer[i]:6.2f} {cte[i]:5.1f} {dspd[i]:6.0f} "
              f"{np.degrees(hrate[i]):6.0f} {int(ontrk[i]):2d}")

# throttle just before each spin onset (wheelspin test)
pre = np.clip(order[:60] - 2, 0, len(D)-1)
print(f"\nthrottle 2 frames before the 60 biggest spins: mean={thr[pre].mean():.2f} "
      f"max={thr[pre].max():.2f}  (high => wheelspin-induced; low => entry/trail)")

# show the first off-track transition with context
off = np.where((ontrk[:-1] == 1) & (ontrk[1:] == 0))[0]
if len(off):
    k = off[0]
    print(f"\nfirst OFF-TRACK at t={t[k]:.1f}s (row {k}); context:")
    print(f"{'t':>6} {'spd':>5} {'tgt':>5} {'thr':>4} {'brk':>4} {'gear':>4} {'rpm':>5} {'dspd':>6} {'hrate°/s':>8} {'on':>2}")
    for i in range(max(0, k-8), min(len(D), k+10)):
        print(f"{t[i]:6.1f} {spd[i]:5.0f} {tgt[i]:5.0f} {thr[i]:4.2f} {brk[i]:4.2f} "
              f"{int(gear[i]):4d} {rpm[i]:5.0f} {dspd[i]:6.0f} {np.degrees(hrate[i]):8.0f} {int(ontrk[i]):2d}")
