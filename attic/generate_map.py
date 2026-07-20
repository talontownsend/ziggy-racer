"""Render the follower's last complete lap as an SVG map: track walls, the ideal
racing line, and the actual driven path (dirt excursions flagged red)."""
import csv
import numpy as np

LOG = r"C:\Users\talon\FH6-AFK-Farm\recordings\follow_log.csv"
PLAN = r"C:\Users\talon\FH6-AFK-Farm\recordings\session_20260621_093038_plan.npz"
OUT = r"C:\Users\talon\FH6-AFK-Farm\recordings\map_lastlap.svg"

rows = list(csv.DictReader(open(LOG)))
i0 = np.array([float(r["i0"]) for r in rows])
wraps = [k for k in range(1, len(rows)) if i0[k - 1] > 350 and i0[k] < 50]
a, b = wraps[-2], wraps[-1]                      # last COMPLETE lap
lap = rows[a:b]
dx = np.array([float(r["x"]) for r in lap])
dz = np.array([float(r["z"]) for r in lap])
ot = np.array([int(float(r["on_track"])) for r in lap])
spd = np.array([float(r["spd_kmh"]) for r in lap])
lap_t = float(lap[-1]["t"]) - float(lap[0]["t"])
ontrack_pct = 100 * ot.mean()

d = np.load(PLAN)
line, left, right = d["line"], d["left"], d["right"]

# ---- world -> SVG transform (frame on the walls; flip z so north is up) ----
allx = np.concatenate([left[:, 0], right[:, 0], dx])
allz = np.concatenate([left[:, 1], right[:, 1], dz])
minx, maxx, minz, maxz = allx.min(), allx.max(), allz.min(), allz.max()
pad = 40.0
W = 1000.0
span_x = (maxx - minx) or 1.0
span_z = (maxz - minz) or 1.0
sc = (W - 2 * pad) / span_x
H = span_z * sc + 2 * pad


def X(x):
    return pad + (x - minx) * sc


def Y(z):
    return H - pad - (z - minz) * sc            # flip


def pts(arr_x, arr_z, step=1):
    return " ".join(f"{X(x):.1f},{Y(z):.1f}" for x, z in zip(arr_x[::step], arr_z[::step]))


# closed wall loops
left_pts = pts(left[:, 0], left[:, 1]) + f" {X(left[0,0]):.1f},{Y(left[0,1]):.1f}"
right_pts = pts(right[:, 0], right[:, 1]) + f" {X(right[0,0]):.1f},{Y(right[0,1]):.1f}"
line_pts = pts(line[:, 0], line[:, 1]) + f" {X(line[0,0]):.1f},{Y(line[0,1]):.1f}"
drive_pts = pts(dx, dz, step=2)

# dirt excursion markers
dirt = [(X(x), Y(z)) for x, z, o in zip(dx, dz, ot) if o == 0]
# thin them so we don't draw thousands
dirt = dirt[::2]
dirt_circles = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.2"/>' for x, y in dirt)

# start/finish marker (line index 0) + a small heading tick
sf_x, sf_z = X(line[0, 0]), Y(line[0, 1])

WALL = "#888780"     # gray 400  — both-mode safe
IDEAL = "#378ADD"    # blue 400
DRIVE = "#1D9E75"    # teal 400
DIRTC = "#E24B4A"    # red 400
TXT = "var(--color-text-primary)"
SUB = "var(--color-text-secondary)"

svg = f'''<svg viewBox="0 0 {W:.0f} {H:.0f}" xmlns="http://www.w3.org/2000/svg" role="img" font-family="var(--font-sans, system-ui, sans-serif)">
  <title>Follower's last full lap of the test circuit</title>
  <desc>Track walls in gray, the ideal racing line dashed blue, the actual driven path in teal, and dirt excursions marked as red dots. {ontrack_pct:.0f} percent of the lap was on track.</desc>
  <polyline points="{left_pts}" fill="none" stroke="{WALL}" stroke-width="2.2" opacity="0.7"/>
  <polyline points="{right_pts}" fill="none" stroke="{WALL}" stroke-width="2.2" opacity="0.7"/>
  <polyline points="{line_pts}" fill="none" stroke="{IDEAL}" stroke-width="2.4" stroke-dasharray="7 6" opacity="0.9"/>
  <polyline points="{drive_pts}" fill="none" stroke="{DRIVE}" stroke-width="3.4" stroke-linejoin="round" stroke-linecap="round"/>
  <g fill="{DIRTC}">{dirt_circles}</g>
  <circle cx="{sf_x:.1f}" cy="{sf_z:.1f}" r="6" fill="{TXT}"/>
  <text x="{sf_x+10:.1f}" y="{sf_z-8:.1f}" font-size="20" font-weight="500" fill="{TXT}">S/F</text>
  <g transform="translate(28,30)">
    <text font-size="24" font-weight="500" fill="{TXT}">Last lap — {ontrack_pct:.0f}% on track</text>
    <text y="26" font-size="16" fill="{SUB}">{lap_t:.0f}s &#183; avg {spd.mean():.0f} / max {spd.max():.0f} km/h &#183; {int(ot.sum()==0 and 0 or (ot==0).sum())} dirt samples</text>
    <g transform="translate(0,52)" font-size="15">
      <line x1="0" y1="-5" x2="34" y2="-5" stroke="{DRIVE}" stroke-width="3.4"/><text x="42" fill="{SUB}">driven path</text>
      <line x1="150" y1="-5" x2="184" y2="-5" stroke="{IDEAL}" stroke-width="2.4" stroke-dasharray="7 6"/><text x="192" fill="{SUB}">ideal line</text>
      <circle cx="305" cy="-5" r="4" fill="{DIRTC}"/><text x="316" fill="{SUB}">in the dirt</text>
    </g>
  </g>
</svg>'''

open(OUT, "w", encoding="utf-8").write(svg)
print(f"last full lap rows {a}-{b}  {len(lap)} samples  {lap_t:.0f}s  {ontrack_pct:.0f}% on-track")
print(f"viewBox 0 0 {W:.0f} {H:.0f}  dirt markers {len(dirt)}")
print(f"wrote {OUT}  ({len(svg)} bytes)")
