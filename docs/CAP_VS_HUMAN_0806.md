# Per-station: what the corner-speed cap actually denies

Supersedes the "cap is within 3-7 km/h of human" claim in VCURVE_RECONCILED_0806.md, which was
a **corner-median artifact**: it averaged the R=23 m spike zone together with the fast exit.
Per station, integrating `max(human - cap, 0)` over distance. Run: `python tools/cap_vs_human.py`.

## The denial is real and concentrated

| corner | binding zone | cap | human | bot | integral | mean | peak |
|---|---|---|---|---|---|---|---|
| 2 | 595-607 | **91.9** | 135.4 | 121.2 | 886 km/h·m | 18.4 | **44.9** @ 596 |
| 1 | 815-845 | 134.4 | 159.7 | 112.2 | 724 km/h·m | 13.2 | 33.1 @ 818 |
| 3 | 900-914 | 168.6 | 202.3 | 164.2 | 666 km/h·m | 13.6 | 38.5 @ 914 |

The human exceeds the cap at **67% / 80% / 61%** of stations, by >20 km/h at 43% / 35% / 37%.

**The corner-2 spike is not geometry.** At R=23 m the human's 135 km/h would need **6.1 g**,
against a car measuring 2.7-3.0 g peak. (In that zone the human pulls **3.06 g** p90, itself
above the 2.75 g model.) A 3-point Menger stencil at ~1.06 m spacing on noisy points inflates
curvature, and `kappa_pct=100` makes the 18 m window a raw max, which harvests exactly those
spikes. The docstring says the percentile exists so "a single noise-kink station can't bind the
whole corner-speed cap" -- that protection is disabled by configuration.

## No estimator variant meets the bar

Bar: within ~10 km/h of human at the binding zone of **all three** corners.

| variant | corner 2 [135.2] | corner 1 [163.1] | corner 3 [201.7] | worst |
|---|---|---|---|---|
| **SHIPPED** 3pt w5 max | 91.9 | 151.0 | 168.6 | 43.3 |
| pct 95 / 90 | 93.3 / 94.3 | 153.2 / 155.5 | 175.7 / 185.1 | 42.2 / 41.1 |
| kappa-smooth w11 | 110.8 | 164.5 | 202.0 | 24.6 |
| 5-pt stencil | 103.8 | 166.4 | 196.7 | 31.7 |
| **line-smooth w=9** | 112.2 | 173.4 | 206.9 | **23.0** |
| line-smooth w=15 / 21 | 116.7 / 134.1 | 174.4 / 168.9 | 238.8 / **277.9** | 37.1 / 76.2 |
| w=9 + lookahead 5 m | 132.0 | 179.8 | 215.1 | 16.7 |

Smoothing enough to reach corner 2 (w=21 -> 134.1) destroys corner 3 (277.9 vs 201.7): it stops
resolving the corner. Shortening the lookahead to 5 m scores best on worst-error but is not an
estimator fix -- it removes braking anticipation.

**By the stated criterion the do-not-touch flag stays on.**

## But the error DIRECTION changes, and that is not symmetric

| | corner 2 | corner 1 | corner 3 |
|---|---|---|---|
| SHIPPED | **−43.3** | **−12.1** | **−33.1** |
| line-smooth w=9 | −23.0 | **+10.3** | **+5.2** |

The per-station `vtrim` map can trim an optimistic cap **down**; it can never recover speed a
too-low cap never offered. Shipped undershoots all three (all unrecoverable). Line-smoothing at
w=9 converts two to recoverable overshoot and halves the third. Note `map_w` is currently
trimming **down** at corner 2 (0.93) on top of a cap already 43 km/h low.

## The blocker

`kappa_ref` is **dual-use**: it feeds the `v_curve` clamp *and* the steering feedforward through
`kappa_at`. The source comment records that widening its smoothing weakened turn-in into
understeer and off-tracks, and prescribes the fix: de-kink the **speed path separately, not the
FF source**. So this is a code change (a second kappa array used only by `v_curve`), never a tune
key. Any live test must confirm the steering FF column is bit-identical.

## Corrections to my own earlier reports

1. "Cap within 3-7 km/h of human" — corner-median artifact. Per station it is 13-18 km/h mean,
   33-45 peak.
2. "The lookahead costs 23-69 km/h" — that compared against `v_phys` (station-local curvature),
   which is not achievable. The right benchmark is the human, and the denial is 13-18 km/h.
3. "Every estimator fix licenses speeds above human" — true for kappa-smoothing and 5-pt stencil,
   **false** for line-smoothing at w<=9, which stays at or below human on two corners.
