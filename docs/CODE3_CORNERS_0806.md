# Splitting code 3 per corner: the fork resolves to tracking

`bind_code` 3 (`v_curve * map_w`) is the only limiter with material share of the speed deficit
(18.5%, BIND_DECOMP_0806.md). But the mean deficit AT code-3 ticks is ~18 km/h: the car runs well
below the curvature-capped target even while that cap is binding. If that holds per corner,
raising the target is inert.

Three speeds at matched stations, top five corners by code-3 deficit. Station mapping is
nearest-point on the refline, **validated against the bot's own logged `i0`**: median error 0
stations, 100% within 2, mean point distance 1.76 m (human 1.61 m). Human = 50 laps, 08-02.
Run: `python tools/code3_corners.py`.

| # | stations | s_m | km/h-s | ticks | bot TGT | bot ACT | human | human−tgt | tgt−act | map_w |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 810-844 | 869-905 | 6106 | 14,511 | 145.4 | 112.2 | 162.3 | **+16.9** | **33.2** | 1.05 |
| 2 | 614-626 | 657-669 | 3839 | 12,747 | 124.0 | 98.0 | 131.5 | +7.5 | 26.0 | **0.95** |
| 3 | 890-915 | 954-981 | 3412 | 3,384 | 180.9 | 109.1 | 199.1 | **+18.2** | **71.8** | 1.35 |
| 4 | 301-308 | 322-330 | 2387 | 4,348 | 219.9 | 181.2 | 216.3 | **−3.6** | 38.7 | 1.36 |
| 5 | 259-267 | 278-286 | 1790 | 4,952 | 190.3 | 164.3 | 187.9 | **−2.4** | 26.0 | 1.45 |

**Mean: human beats the bot's target by +7.3 km/h; the bot misses its own target by 39.1 km/h.**

## The fork

The tracking gap dominates the target gap **more than 5:1**, in every corner. In corners 4 and 5
the human is *slower* than the speed the bot is already permitted. So:

- **Raising the target is inert.** Confirms the old "path is inert" arms with a per-corner
  mechanism rather than an aggregate.
- **A refline rebuild from the 08-02 laps is NOT the move.** It would force a learner reset for
  at most ~7 km/h of headroom the car cannot use, in corners where it is already 26-72 km/h short
  of the target it has.
- **The corner problem is tracking**, and the structural work goes to the lateral controller.

## What sets the cap

`map_w = tgt / vcurve` where `vcurve_kmh` is logged as raw `v_curve * 3.6` (pre-map). Above 1
means the learned map is **boosting** past the raw curvature limit, not cutting.

Only corner 2 has `map_w < 1`, and only by 5%. Corners 3-5 are boosting **35-45%**, with corner
5 at 1.45 against the 1.55 ceiling. **The map is not restraining the car anywhere except corner
2.** Both halves of the target hypothesis therefore fail: raw curvature is not the limit because
the map already lifts past it, and the map is not the limit because it is boosting.

Corner 3 is the extreme case and the clearest single target: the bot is permitted 180.9 and
drives 109.1, a **71.8 km/h** shortfall, while the map is already boosting 35%.

## Consistent with the ileak

The `cte_ileak 0.5` arm cut code-3 deficit **14.8%** — its largest limiter reduction — while
improving `|cte|` p90 from 3.34 to 3.06 m. A tracking improvement reducing the code-3 deficit is
exactly what this decomposition predicts, and is independent support for reading the corner
problem as tracking. That arm remains a single unreplicated A-B-A.
