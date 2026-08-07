"""Per-station: how much corner speed the cap denies relative to demonstrated human pace.

Corner medians hid this. Corner 2's median cap (130.5) averages the R=23 m spike zone, where
the cap is ~92 and the human runs ~135, together with the fast exit. Integrate the shortfall
per station instead.

denial = integral of max(human - cap, 0) over distance, in km/h*m, plus the peak and its location.

Estimator variants are then re-evaluated AT THE BINDING STATIONS, not as span medians. The bar:
land within ~10 km/h of human at the binding zone of all three corners WITHOUT overshooting
elsewhere -- the per-station vtrim map can trim a mildly optimistic cap back down, but it can
never recover speed a too-low cap never offered.
"""
import numpy as np
import pandas as pd

HUMAN = r'C:\Users\Talon\AppData\Local\FH6 TC\recording_20260802_073646.csv'
ALAT, AK, DIST, NS = 27.0, 0.0025, 18.0, 16
line = np.load('recordings/refline_plan.npz')['line']
N = len(line)
dd = np.roll(line, -1, 0) - line
seg = np.hypot(dd[:, 0], dd[:, 1])
cum = np.concatenate([[0.0], np.cumsum(seg)])
tot = float(cum[-1])


def sm(a, w):
    if w <= 1:
        return a
    k = np.ones(w) / w
    return np.convolve(np.r_[a[-w:], a, a[:w]], k, 'same')[w:-w]


def menger(P, st):
    p0 = np.roll(P, st, 0); p2 = np.roll(P, -st, 0)
    a = np.hypot(*(P - p0).T); b = np.hypot(*(p2 - P).T); c = np.hypot(*(p2 - p0).T)
    ar = 0.5 * np.abs((P[:, 0]-p0[:, 0])*(p2[:, 1]-p0[:, 1]) - (P[:, 1]-p0[:, 1])*(p2[:, 0]-p0[:, 0]))
    den = a * b * c
    return np.where(den > 1e-9, 4 * ar / den, 0.0)


def vline_of(kap, pct):
    out = np.empty(N)
    for i in range(N):
        ss = np.mod(np.linspace(cum[i], cum[i] + DIST, NS), tot)
        idx = np.clip(np.searchsorted(cum, ss, side='right') - 1, 0, N - 1)
        out[i] = np.percentile(np.abs(kap[idx]), pct)
    return 3.6 * np.sqrt(ALAT / np.maximum(out - AK, 1e-4))


# --- human, per station -------------------------------------------------------
h = pd.read_csv(HUMAN, usecols=['pos_x', 'pos_z', 'speed_mps', 'ax', 'is_race_on'],
                on_bad_lines='skip', low_memory=False).apply(pd.to_numeric, errors='coerce').dropna()
h = h[(h['is_race_on'] > 0) & (h['speed_mps'] > 1)]
P = h[['pos_x', 'pos_z']].to_numpy()
st = np.empty(len(P), dtype=int)
for i in range(0, len(P), 20000):
    st[i:i+20000] = ((P[i:i+20000, None, :] - line[None, :, :]) ** 2).sum(2).argmin(1)
h = h.assign(st=st, kmh=h['speed_mps'] * 3.6, latg=h['ax'].abs() / 9.81)
hum = h.groupby('st')['kmh'].median()
humg = h.groupby('st')['latg'].quantile(.9)

# --- bot, per station ---------------------------------------------------------
b = pd.read_csv('recordings/follow_log.csv',
                usecols=['race_pos', 'on_track', 'i0', 'vcurve_kmh', 'tgt_kmh', 'spd_kmh'],
                on_bad_lines='skip', low_memory=False).apply(pd.to_numeric, errors='coerce').dropna()
b = b[(b['race_pos'] >= 1) & (b['on_track'] > 0.5)].assign(st=lambda x: x['i0'].astype(int) % N)
cap = b.groupby('st')['vcurve_kmh'].median()
tgt = b.groupby('st')['tgt_kmh'].median()
bot = b.groupby('st')['spd_kmh'].median()

base = sm(menger(line, 1), 5)
ZONES = {'corner 2': np.arange(595, 641), 'corner 1': np.arange(795, 846),
         'corner 3': np.arange(880, 926)}

print("=" * 100)
print("PER-STATION: shipped cap vs demonstrated human pace")
for lab, z in ZONES.items():
    c = cap.reindex(z); t = tgt.reindex(z); u = hum.reindex(z); bo = bot.reindex(z)
    ok = c.notna() & u.notna()
    zz = z[ok.to_numpy()]
    exc = np.maximum(u[ok].to_numpy() - c[ok].to_numpy(), 0.0)
    excT = np.maximum(u[ok].to_numpy() - t[ok].to_numpy(), 0.0)
    L = seg[zz]
    print(f"\n{lab}  stations {z[0]}-{z[-1]}  ({L.sum():.0f} m)")
    print(f"  denial vs CAP    : integral {np.sum(exc*L):8.0f} km/h*m   mean {np.sum(exc*L)/L.sum():6.1f} km/h"
          f"   peak {exc.max():6.1f} @ station {zz[np.argmax(exc)]}")
    print(f"  denial vs TARGET : integral {np.sum(excT*L):8.0f} km/h*m   mean {np.sum(excT*L)/L.sum():6.1f} km/h"
          f"   peak {excT.max():6.1f} @ station {zz[np.argmax(excT)]}")
    print(f"  stations where human > cap: {100*np.mean(exc>0):.0f}%   > cap by >20 km/h: {100*np.mean(exc>20):.0f}%")
    # the binding zone = contiguous stations with the largest shortfall
    thr = max(np.percentile(exc, 75), 5.0)
    m = exc > thr
    if m.any():
        bz = zz[m]
        print(f"  BINDING ZONE (excess>{thr:.0f}): stations {bz.min()}-{bz.max()}  "
              f"cap {c[ok][m].median():.1f}  human {u[ok][m].median():.1f}  bot {bo.reindex(bz).median():.1f}"
              f"  human lat-g p90 {humg.reindex(bz).median():.2f}")
        ZONES[lab] = bz    # narrow to the binding zone for the estimator test

print("\n" + "=" * 100)
print("ESTIMATOR VARIANTS AT THE BINDING STATIONS (km/h; human in brackets)")
cfgs = [('SHIPPED 3pt w5 max', base, 100.0), ('3pt w5 pct95', base, 95.0),
        ('3pt w5 pct90', base, 90.0), ('3pt w11 max', sm(menger(line, 1), 11), 100.0),
        ('5pt w5 max', sm(menger(line, 5), 5), 100.0),
        ('5pt w11 max', sm(menger(line, 5), 11), 100.0),
        ('9pt w5 max', sm(menger(line, 9), 5), 100.0)]
V = {lab: vline_of(k, p) for lab, k, p in cfgs}
hdr = "  {:>20}".format('estimator')
for lab in ZONES:
    hdr += f" {lab+' bind':>16}"
print(hdr + f" {'worst |err|':>12}")
for lab, _, _ in cfgs:
    v = V[lab]; row = f"  {lab:>20}"; errs = []
    for cl, z in ZONES.items():
        m = np.median(v[z]); hh = hum.reindex(z).median()
        errs.append(m - hh)
        row += f" {m:8.1f} [{hh:5.1f}]"
    row += f" {max(abs(e) for e in errs):12.1f}"
    print(row)
print("\n  bar: within ~10 km/h of human at ALL THREE binding zones, without licensing")
print("  speeds far above it (vtrim can trim down; it cannot recover a cap never offered).")
