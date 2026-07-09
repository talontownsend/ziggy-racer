"""Build a compact per-station diagnostic table over the S5->S11 span (s400-810) from the
vtrim2 soak log + surface geometry + the learned map2. One row per 3 m bin: median car
behaviour (line offset, steering, understeer/oversteer, slip, attitude, grip headroom,
speed vs the physics curve, throttle/brake) alongside the surface (bank, crest zpp, grade,
line curvature) and the map2 ask. This is the shared substrate for the section investigation.
Writes scratchpad/diag_table.csv and prints a per-section summary."""
import csv
import numpy as np

REC = r"C:\Users\talon\FH6-AFK-Farm\recordings"
OUT = r"C:\Users\Talon\AppData\Local\Temp\claude\C--\8d5243b5-eb41-4b0e-8aa8-68e5f24fdcdc\scratchpad\diag_table.csv"
LOG = REC + r"\follow_log.csv"

d = np.load(REC + r"\refline_plan.npz"); line = d["line"]; elev = d["elev"]; grade = d["grade"]; n = len(line)
seg = np.hypot(*(np.roll(line, -1, 0) - line).T)
s_of = np.concatenate([[0.0], np.cumsum(seg)])[:-1]
sc = np.load(REC + r"\surface_cap.npz"); bank = sc["bank"]; zpp = sc["zpp"]
# line curvature (menger) signed
def curv(p):
    a = np.roll(p, 1, 0); b = p; c = np.roll(p, -1, 0)
    ab = np.hypot(*(b - a).T); bc = np.hypot(*(c - b).T); ca = np.hypot(*(a - c).T)
    area = 0.5 * np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (c[:, 0] - a[:, 0]) * (b[:, 1] - a[:, 1]))
    k = 4 * area / (ab * bc * ca + 1e-9)
    cross = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])
    return k * np.sign(cross)
kappa = curv(line)
# verified inside/wide geometry
_t = np.roll(line, -1, 0) - line; _t = _t / (np.hypot(_t[:, 0], _t[:, 1])[:, None] + 1e-9)
lnorm = np.stack([-_t[:, 1], _t[:, 0]], 1); _tn = np.roll(_t, -3, 0)
tsign = np.sign(_t[:, 0] * _tn[:, 1] - _t[:, 1] * _tn[:, 0])
# map2 snapshot
v2 = np.load(REC + r"\vtrim2_snap_investig.npz"); map2 = v2["map"]
s_lo = float(v2["s_lo"]); cell_m = float(v2["cell_m"])
def map2_at(s):
    c = int((s - s_lo) / cell_m)
    return float(map2[c]) if 0 <= c < len(map2) else 1.0

S_LO, S_HI, BIN = 400.0, 810.0, 3.0
nb = int((S_HI - S_LO) / BIN)
acc = [{k: [] for k in ("ins", "steer", "und", "ovr", "ss", "pit", "rol", "fc", "latg",
                        "amax", "spd", "vc", "thr", "brk", "cte", "er")} for _ in range(nb)]
for r in csv.DictReader(open(LOG)):
    try:
        if float(r["race_pos"]) < 1:
            continue
        i0 = int(float(r["i0"])) % n; sm = s_of[i0]
        b = int((sm - S_LO) / BIN)
        if not (0 <= b < nb):
            continue
        a = acc[b]
        a["ins"].append(float(r["vt2_inside"])); a["steer"].append(abs(float(r["steer"])))
        a["und"].append(int(float(r["under"]))); a["ovr"].append(int(float(r["over"])))
        a["ss"].append(abs(float(r["sideslip"]))); a["pit"].append(float(r["pitch_deg"]))
        a["rol"].append(float(r["roll_deg"])); a["fc"].append(float(r["fc_frac"]))
        a["latg"].append(float(r["meas_latg"])); a["amax"].append(float(r["alat_max_g"]))
        a["spd"].append(float(r["spd_kmh"])); a["vc"].append(float(r["vcurve_kmh"]))
        a["thr"].append(float(r["thr"])); a["brk"].append(float(r["brk"]))
        a["cte"].append(float(r["cte_m"])); a["er"].append(float(r["e_r"]))
    except Exception:
        continue

def med(x): return float(np.median(x)) if x else float("nan")
def p90(x): return float(np.percentile(x, 90)) if x else float("nan")
def frac(x): return float(np.mean(x)) if x else float("nan")

cols = ["s", "n", "map2", "spd", "vcurve", "spd_over_vc", "inside_med", "inside_p10",
        "steer_abs", "steer_sat", "under_f", "over_f", "sslip_med", "sslip_p90",
        "pitch", "roll", "bank_deg", "zpp", "grade", "elev", "line_kappa",
        "fc_frac", "meas_latg", "alat_max_g", "thr", "brk_f", "cte_med", "e_r"]
rows_out = []
for b in range(nb):
    a = acc[b]
    if len(a["ins"]) < 5:
        continue
    sc_s = S_LO + (b + 0.5) * BIN
    i = int(np.argmin(np.abs(s_of - sc_s)))
    rows_out.append([round(sc_s, 1), len(a["ins"]), round(map2_at(sc_s), 3),
        round(med(a["spd"]), 1), round(med(a["vc"]), 1),
        round(med(a["spd"]) / max(med(a["vc"]), 1), 3),
        round(med(a["ins"]), 2), round(np.percentile(a["ins"], 10), 2),
        round(med(a["steer"]), 3), round(frac([s > 0.9 for s in a["steer"]]), 2),
        round(frac(a["und"]), 2), round(frac(a["ovr"]), 2),
        round(med(a["ss"]), 1), round(p90(a["ss"]), 1),
        round(med(a["pit"]), 2), round(med(a["rol"]), 2),
        round(float(bank[i]), 2), round(float(zpp[i]), 4), round(float(grade[i]), 4),
        round(float(elev[i]), 2), round(float(kappa[i]), 4),
        round(med(a["fc"]), 2), round(med(a["latg"]), 2), round(med(a["amax"]), 2),
        round(med(a["thr"]), 2), round(frac([x > 0 for x in a["brk"]]), 2),
        round(med(a["cte"]), 2), round(med(a["er"]), 3)])

with open(OUT, "w", newline="") as f:
    w = csv.writer(f); w.writerow(cols); w.writerows(rows_out)
print(f"wrote {OUT}  ({len(rows_out)} bins, s{S_LO:.0f}-{S_HI:.0f})")

# per-section summary
BND = {"S5": (413, 455), "S6": (455, 547), "S7": (547, 608), "S8": (608, 638),
       "S9": (638, 702), "S10": (702, 783), "S11": (783, 810)}
arr = np.array([r for r in rows_out]); sv = arr[:, 0]
ci = {c: k for k, c in enumerate(cols)}
print(f"\n{'sec':>4} {'map2 med/min':>12} {'ins med/p10':>12} {'steerSat':>8} {'under':>6} "
      f"{'sslip90':>7} {'bank':>6} {'zpp':>7} {'grade':>6} {'roll':>6} {'spd/vc':>6}")
for sec, (a, b) in BND.items():
    m = (sv >= a) & (sv < b)
    if not m.any():
        continue
    sub = arr[m]
    g = lambda c: sub[:, ci[c]]
    print(f"{sec:>4} {np.median(g('map2')):.2f}/{g('map2').min():.2f}      "
          f"{np.median(g('inside_med')):+.2f}/{np.median(g('inside_p10')):+.2f}   "
          f"{np.median(g('steer_sat')):.2f}    {np.median(g('under_f')):.2f}   "
          f"{np.median(g('sslip_p90')):.1f}  {np.median(g('bank_deg')):+.1f}  "
          f"{np.median(g('zpp')):+.4f} {np.median(g('grade')):+.3f} {np.median(g('roll')):+.1f}  {np.median(g('spd_over_vc')):.2f}")
