"""Per-section time comparison: base controller vs the user's recorded laps.

Method: project every telemetry frame onto the refline (nearest station + tangent
refinement -> continuous arc-length s), unwrap s across laps, interpolate the exact
crossing time of each section boundary, and difference crossings -> per-lap
per-section times. Same pipeline for both sources so methodology noise cancels.
"""
import csv as csvmod
import json
import sys

import numpy as np

ROOT = r"C:\Users\talon\FH6-AFK-Farm"
REC = ROOT + r"\recordings"

# Section gates are defined on the V1 refline's stations (what the user clicked on the map).
# Pin the projection geometry to V1 PERMANENTLY so section times stay comparable across line
# changes -- the live refline_plan.npz now carries the rebuilt (26.10s-lap) line.
d = np.load(REC + r"\refline_plan_v1_27s.npz")
line = d["line"]
N = len(line)
clen = np.r_[0.0, np.cumsum(np.hypot(np.diff(line[:, 0]), np.diff(line[:, 1])))]
LAP = float(clen[-1])
seg = np.diff(np.r_[line, line[:1]], axis=0)                  # station i -> i+1
seglen = np.hypot(seg[:, 0], seg[:, 1])
tang = seg / seglen[:, None]

B = json.load(open(REC + r"\sections.json"))["boundaries"]    # 13 stations
NSEC = len(B)
b_s = np.array([clen[b] for b in B])                          # arc-length of each boundary


def s_of_xy(x, z):
    """Continuous arc-length position of each (x,z): nearest station + projection."""
    s_out = np.empty(len(x))
    for i0 in range(0, len(x), 20000):                        # chunk the 1000-wide argmin
        xs = x[i0:i0 + 20000, None]; zs = z[i0:i0 + 20000, None]
        d2 = (xs - line[None, :, 0]) ** 2 + (zs - line[None, :, 1]) ** 2
        ni = np.argmin(d2, axis=1)
        dx = xs[:, 0] - line[ni, 0]; dz = zs[:, 0] - line[ni, 1]
        proj = np.clip(dx * tang[ni, 0] + dz * tang[ni, 1], -seglen[ni], seglen[ni])
        s_out[i0:i0 + 20000] = (clen[ni] + proj) % LAP
    return s_out


def section_laps(t, s, vk):
    """Find boundary crossings LOCALLY on the modular s (never a global unwrap -- an
    unwrap accumulates a permanent offset at every zeroed teleport, shifting every later
    section window off the track). A frame pair crosses boundary k iff the short forward
    modular step from s[i] passes b_s[k]. Events are then grouped in TIME order into full
    13-section laps. Returns list of laps; each = dict(times=[13], vmin=[13], vent=[13])."""
    keep = np.r_[True, np.diff(t) > 1e-4]                      # drop same-timestamp dupes
    t, s, vk = t[keep], s[keep], vk[keep]
    ds = (np.diff(s) + LAP / 2) % LAP - LAP / 2                # signed short modular step
    dt = np.diff(t)
    good = (ds > 0) & (ds < 15.0) & (dt > 0) & (dt <= 0.5)     # forward, no teleport/pause

    events = []                                                # (t_cross, k)
    for k in range(NSEC):
        delta = (b_s[k] - s[:-1]) % LAP                        # forward distance to boundary k
        hit = np.where(good & (delta < ds))[0]
        for i in hit:
            f = delta[i] / ds[i]
            events.append((t[i] + f * (t[i + 1] - t[i]), k))
    events.sort()

    laps = []
    i = 0
    while i < len(events):
        if events[i][1] != 0:
            i += 1; continue
        chunk = events[i:i + NSEC + 1]                         # k=0,1,...,12, then next k=0
        ks = [c[1] for c in chunk]
        if len(chunk) < NSEC + 1 or ks != list(range(NSEC)) + [0]:
            i += 1; continue
        times, vmins, vents, ok = [], [], [], True
        for j in range(NSEC):
            tc, tc2 = chunk[j][0], chunk[j + 1][0]
            dtk = tc2 - tc
            win = (t >= tc) & (t <= tc2)
            if not (0.3 < dtk < 30.0) or win.sum() < 2:
                ok = False; break
            times.append(dtk)
            vmins.append(float(vk[win].min()))
            vents.append(float(vk[win][0]))
        if ok:
            laps.append(dict(times=times, vmin=vmins, vent=vents))
            i += NSEC
        else:
            i += 1
    return laps


def load_named_csv(path):
    """Human recorder format (named header)."""
    with open(path, newline="") as fh:
        r = csvmod.reader(fh)
        hdr = next(r)
        ix = {c: hdr.index(c) for c in ("timestamp_ms", "pos_x", "pos_z", "speed_mps", "is_race_on")}
        rows = []
        for p in r:
            try:
                if p[ix["is_race_on"]] in ("1", "1.0"):
                    rows.append((float(p[ix["timestamp_ms"]]) / 1000.0, float(p[ix["pos_x"]]),
                                 float(p[ix["pos_z"]]), float(p[ix["speed_mps"]]) * 3.6))
            except (ValueError, IndexError):
                continue
    a = np.array(rows)
    return a[:, 0], a[:, 1], a[:, 2], a[:, 3]


def load_follow_log(path):
    """follow_log.csv: t=0,x=1,z=2,spd_kmh=3,race_pos=48."""
    rows = []
    for ln in open(path):
        p = ln.split(",")
        if len(p) < 49 or p[0] == "t":
            continue
        try:
            if float(p[48]) >= 1:
                rows.append((float(p[0]), float(p[1]), float(p[2]), float(p[3])))
        except ValueError:
            continue
    a = np.array(rows)
    return a[:, 0], a[:, 1], a[:, 2], a[:, 3]


def analyze(name, t, x, z, vk):
    s = s_of_xy(x, z)
    laps = section_laps(t, s, vk)
    tot = [sum(l["times"]) for l in laps]
    keep = [l for l, T in zip(laps, tot) if 24.0 < T < 45.0]   # sane full laps only
    print(f"{name}: {len(laps)} stitched laps, {len(keep)} kept "
          f"(best {min((sum(l['times']) for l in keep), default=float('nan')):.2f}s)")
    return keep


def summarize(laps):
    times = np.array([l["times"] for l in laps])               # laps x 13
    vmin = np.array([l["vmin"] for l in laps])
    vent = np.array([l["vent"] for l in laps])
    return dict(
        n=len(laps),
        med=[round(float(v), 3) for v in np.median(times, 0)],
        best=[round(float(v), 3) for v in times.min(0)],
        vmin_med=[round(float(v), 1) for v in np.median(vmin, 0)],
        vent_med=[round(float(v), 1) for v in np.median(vent, 0)],
        lap_med=round(float(np.median(times.sum(1))), 2),
        lap_best=round(float(times.sum(1).min()), 2),
    )


if __name__ == "__main__":
    out = {"boundaries": B, "sec_len": [round(float((b_s[(k + 1) % NSEC] - b_s[k]) % LAP), 1) or round(LAP, 1) for k in range(NSEC)]}
    human_laps = []
    for f in ("run_20260625_120907.csv", "run_20260625_120122.csv", "session_20260621_093038.csv"):
        t, x, z, vk = load_named_csv(REC + "\\" + f)
        human_laps += analyze(f, t, x, z, vk)
    out["human"] = summarize(human_laps)
    if len(sys.argv) > 1 and sys.argv[1] != "human-only":
        t, x, z, vk = load_follow_log(sys.argv[1])
        ctl = analyze("controller(base)", t, x, z, vk)
        out["controller"] = summarize(ctl)
    json.dump(out, open(sys.argv[2] if len(sys.argv) > 2 else
                        r"C:\Users\Talon\AppData\Local\Temp\claude\C--\0fe7484c-638c-408b-a34d-de8e5d737bf0\scratchpad\section_compare.json", "w"), indent=1)
    print("done")
