"""Autopsy corner 3 (stations ~880-925): why is the bot 71.8 km/h under its own target?

The tension: raw v_curve there is ~134 km/h, implying radius ~51 m at planner_alat=27 m/s2.
The human carries 199 km/h (55.3 m/s). On a 51 m radius that needs 59.6 m/s2 = 6.1 g, which
the car does not have. So either the human's PATH is much wider, or the grip model is wrong.
Both are measurable offline.

Forza sled axes, as follow.py reads them: ax = lateral, ay = vertical, az = longitudinal.
"""
import numpy as np
import pandas as pd

HUMAN = r'C:\Users\Talon\AppData\Local\FH6 TC\recording_20260802_073646.csv'
LO, HI = 880, 925

d = np.load('recordings/refline_plan.npz')
line, left, right = d['line'], d['left'], d['right']
seg = np.hypot(*(np.roll(line, -1, 0) - line).T)
s_of = np.concatenate([[0.0], np.cumsum(seg)])[:-1]
N = len(line)

# refline curvature from the polyline (Menger, 5-station stencil for stability)
def curv(P, k=5):
    a = np.roll(P, k, 0); b = P; c = np.roll(P, -k, 0)
    ab = np.linalg.norm(b - a, axis=1); bc = np.linalg.norm(c - b, axis=1)
    ca = np.linalg.norm(a - c, axis=1)
    cross = np.abs((b[:, 0]-a[:, 0])*(c[:, 1]-a[:, 1]) - (b[:, 1]-a[:, 1])*(c[:, 0]-a[:, 0]))
    return np.divide(2*cross, ab*bc*ca, out=np.zeros(len(P)), where=(ab*bc*ca) > 1e-9)

kap_ref = curv(line)
span = np.arange(LO, HI + 1)

# unit normal (left-positive) for signed offset
tang = np.roll(line, -1, 0) - np.roll(line, 1, 0)
tang /= np.maximum(np.linalg.norm(tang, axis=1, keepdims=True), 1e-9)
nrm = np.stack([-tang[:, 1], tang[:, 0]], 1)

print("=" * 92)
print(f"CORNER 3  stations {LO}-{HI}   s = {s_of[LO]:.0f}-{s_of[HI]:.0f} m")
w = np.linalg.norm(left - right, axis=1)
print(f"  refline curvature over span: median {np.median(kap_ref[span]):.5f} 1/m "
      f"-> radius {1/max(np.median(kap_ref[span]),1e-9):.0f} m")
print(f"  track width over span: median {np.median(w[span]):.1f} m")
print(f"  implied v_curve at planner_alat=27: "
      f"{3.6*np.sqrt(27.0/max(np.median(kap_ref[span]),1e-9)):.0f} km/h")

# ---- human ------------------------------------------------------------------
cols = ['pos_x', 'pos_z', 'speed_mps', 'ax', 'ay', 'az', 'steer', 'accel', 'brake',
        'lap_no', 'is_race_on', 'combined_slip_fl', 'combined_slip_fr']
h = pd.read_csv(HUMAN, usecols=lambda c: c in cols, on_bad_lines='skip',
                low_memory=False).apply(pd.to_numeric, errors='coerce').dropna()
h = h[(h.get('is_race_on', 1) > 0) & (h['speed_mps'] > 1)]
P = h[['pos_x', 'pos_z']].to_numpy()
st = np.empty(len(P), dtype=int); dmin = np.empty(len(P))
for i in range(0, len(P), 20000):
    d2 = ((P[i:i+20000, None, :] - line[None, :, :]) ** 2).sum(2)
    st[i:i+20000] = d2.argmin(1); dmin[i:i+20000] = np.sqrt(d2.min(1))
off = np.einsum('ij,ij->i', P - line[st], nrm[st])       # signed lateral offset
h = h.assign(st=st, off=off, kmh=h['speed_mps']*3.6,
             latg=h['ax'].abs()/9.81, longg=h['az']/9.81)
hs = h[h['st'].isin(span)]
print(f"\nHUMAN through the corner ({len(hs):,} ticks, {hs['lap_no'].nunique()} laps)")
print(f"  speed         median {hs['kmh'].median():6.1f} km/h   p90 {hs['kmh'].quantile(.9):6.1f}")
print(f"  lateral g     median {hs['latg'].median():6.2f} g      p90 {hs['latg'].quantile(.9):6.2f} "
      f"  (model allows {27.0/9.81:.2f} g)")
print(f"  |offset| from refline  median {hs['off'].abs().median():5.2f} m   p90 "
      f"{hs['off'].abs().quantile(.9):5.2f} m   signed median {hs['off'].median():+5.2f} m")
print(f"  steer |.|     median {hs['steer'].abs().median():6.3f}    throttle median {hs['accel'].median():6.3f}"
      f"   brake median {hs['brake'].median():6.3f}")
# implied radius the human is actually driving
v = hs['speed_mps'].to_numpy(); a = (hs['ax'].abs()).to_numpy()
R = np.divide(v**2, np.maximum(a, 0.5))
print(f"  implied radius from v^2/a_lat: median {np.median(R):.0f} m  "
      f"(refline radius {1/max(np.median(kap_ref[span]),1e-9):.0f} m)")

print(f"\n  per-station human offset (+ = left of refline):")
g = hs.groupby('st').agg(off=('off','median'), kmh=('kmh','median'), latg=('latg','median'))
for s0 in range(LO, HI+1, 5):
    sub = g.reindex(range(s0, min(s0+5, HI+1))).dropna()
    if len(sub):
        print(f"    {s0:3d}-{min(s0+4,HI):3d}  offset {sub['off'].median():+6.2f} m   "
              f"speed {sub['kmh'].median():6.1f}   lat {sub['latg'].median():4.2f} g")

# ---- bot --------------------------------------------------------------------
bn = ['t','race_pos','on_track','i0','spd_kmh','tgt_kmh','vcurve_kmh','steer','cte_m',
      'thr','pad_thr','thr_cap','drive_slip','brk','meas_latg','bind_code']
b = pd.read_csv('recordings/follow_log.csv', usecols=lambda c: c in bn,
                on_bad_lines='skip', low_memory=False).apply(pd.to_numeric, errors='coerce')
b = b.dropna(subset=['i0','spd_kmh','tgt_kmh'])
b = b[(b['race_pos'] >= 1) & (b['on_track'] > 0.5)]
b = b.assign(st=b['i0'].astype(int) % N)
bs = b[b['st'].isin(span)]
print(f"\nBOT through the same span ({len(bs):,} ticks)")
print(f"  {'stn':>7} {'tgt':>7} {'act':>7} {'vcurv':>7} {'|str|':>6} {'lock%':>6} "
      f"{'|cte|':>6} {'thr':>6} {'pad':>6} {'cap':>6} {'slip':>6} {'brk%':>5} {'latg':>5}")
for s0 in range(LO, HI+1, 5):
    sub = bs[(bs['st'] >= s0) & (bs['st'] <= min(s0+4, HI))]
    if len(sub) < 50:
        continue
    print(f"  {s0:3d}-{min(s0+4,HI):3d} {sub['tgt_kmh'].median():7.1f} {sub['spd_kmh'].median():7.1f} "
          f"{sub['vcurve_kmh'].median():7.1f} {sub['steer'].abs().median():6.2f} "
          f"{100*np.mean(sub['steer'].abs()>0.99):5.0f}% {sub['cte_m'].abs().median():6.2f} "
          f"{sub['thr'].median():6.2f} {sub['pad_thr'].median():6.2f} {sub['thr_cap'].median():6.2f} "
          f"{sub['drive_slip'].median():6.2f} {100*np.mean(sub['brk']>0.05):4.0f}% "
          f"{sub['meas_latg'].abs().median():5.2f}")

print(f"\n  bot summary: speed {bs['spd_kmh'].median():.1f} vs target {bs['tgt_kmh'].median():.1f}"
      f"   full-lock {100*np.mean(bs['steer'].abs()>0.99):.0f}% of ticks")
print(f"  bot lateral g median {bs['meas_latg'].abs().median():.2f} g "
      f"(human {hs['latg'].median():.2f} g, model {27.0/9.81:.2f} g)")
print(f"  bot braking on {100*np.mean(bs['brk']>0.05):.0f}% of ticks   "
      f"cap binding {100*np.mean(np.abs(bs['thr']-bs['thr_cap'])<0.01):.0f}%")
