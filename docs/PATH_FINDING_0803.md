# The reference line's curvature peaks are sharper than any lap actually driven

First result from attacking the path rather than the speed. It is the best lead in three days.

## Five corners hold half the gap

Splitting the 3.25 s human-bot gap by corner (60-station windows around each geometric apex):

| corner | bot min speed | its own target there | human min | bot below own target | dwell cost |
|---|---|---|---|---|---|
| s571 | 98.2 | 105.5 | 112.9 | +7.3 | +0.270 s |
| s611 | 89.6 | 100.7 | **130.4** | +11.1 | +0.407 s |
| s660 | 103.7 | 130.4 | 132.9 | **+26.7** | +0.237 s |
| s773 | 114.5 | 131.9 | 144.9 | +17.4 | +0.426 s |
| s794 | 116.2 | 144.1 | 144.9 | +27.9 | +0.320 s |

**Together +1.659 s, or 51% of the entire gap.**

## What binds there is `v_curve`, not the learned map

At s596-616 the bot's target collapses to 85-90 km/h while the plan field still reads 129-134.
`vtrim` is at its 1.55 maximum, so the learned map is not the limiter. `v_curve` reads **91.9**.
The bot brakes to 94.7 km/h; the human does not brake at all there and holds 132-136 km/h.

`v_curve = sqrt(alat_max / max_kappa_line_ahead(18 m))`, so it is set by the **reference line's
geometry**.

## And the reference line is tighter than anyone drives

The line is the per-station **median of 48 human laps**. Averaging laps whose apexes fall in
slightly different places produces a path with sharper local curvature than any of them. Measured
against the 48 laps recorded 08-02, resampling each lap's own path curvature onto the stations:

| station | line radius | typical human-lap radius | ratio | `v_curve` gain |
|---|---|---|---|---|
| s571 | 31.5 m | 47.2 m | 1.50 | **1.22x** |
| s611 | 34.7 m | 50.5 m | 1.45 | **1.21x** |
| s606 | 42.2 m | 49.5 m | 1.17 | 1.08x |
| s601 | 76.0 m | 50.1 m | 0.66 | 0.81x |

Globally the two agree (median radius 62.3 m vs 60.0 m, ratio 1.05). The defect is **local and
peaked**: the human spreads each turn over a longer arc, lower peak curvature with more curvature
in the approach and exit. Because `v_curve` takes the **maximum** over an 18 m window, one sharp
peak suppresses speed for that whole stretch.

## The bot tracks the line too well

At s611 the corridor is **8.44 m** of half-width. The human sits **1.05 m** off the line and
gets a 50.5 m radius; the bot sits **0.57 m** off and inherits the line's 34.7 m. About a metre
of deviation is worth 45% of radius, and radius enters speed as its square root.

So this is not "the human takes a better line". The human takes *almost the same line*, slightly
less precisely, exactly where precision is expensive.

## What this implies, and what it does not

It does **not** imply re-solving the racing line. Six computed-line solvers have already failed
on this track (they hug the inside), and globally the line is fine.

It suggests two narrower changes, both testable:

1. **Curvature source.** `v_curve` should be driven by a curvature profile that a car can
   actually drive within the corridor, not by the median line's local peaks. A minimum-curvature
   path solved *within the surveyed corridor* would give that, and it is derived from survey
   geometry alone, so it is CONSTRAINTS #1 and #3 clean.
2. **Outward bias where curvature peaks.** `lb_on` already exists but is hardcoded to
   `636 <= s <= 680`, a track-specific literal and a standing #1 exception. A generalised form,
   biasing outward in proportion to local curvature and bounded by measured corridor width,
   would open the radius exactly where the peak is.

Caution on both: `kappa_pct` (percentile instead of max over the window) and wider `kappa_ref`
smoothing have each been tried and measured worse, for corner anticipation and turn-in
respectively. This finding does not overturn those; it says the **line artifact**, not the
planner's use of it, is where the sharpness comes from.
