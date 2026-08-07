# Speed-path kappa split (`ksp_on`): built, tested, migration solved

Splits the curvature source so the `v_curve` clamp reads a line-smoothed array while the
steering feedforward keeps the existing one. Offline only; farm was down throughout.

## The change

`local_planner.py` builds a second array `kappa_speed`: smooth the LINE geometry (w=9) **before**
differentiating, then the same 3-point Menger + `_smooth_closed(5)` as `kappa_ref`. Only
`max_kappa_line_ahead` (the `v_curve` clamp) reads it. `kappa_at` and `kappa_line_ahead` — both
steering-FF sources — still read `kappa_ref`. The 18 m lookahead and `kappa_pct=100` are untouched.

Smoothing the line at source is what post-smoothing the curvature cannot do: a 5-point stencil and
w=11 kappa smoothing both fall short (see CAP_VS_HUMAN_0806.md).

**It is a BLEND, not a switch.** `ksp_on` in tune.json sets `planner.ksp` in [0,1]:
`kappa = kappa_ref + ksp*(kappa_speed - kappa_ref)`. `ksp=0` reproduces today's cap exactly
(verified: max |diff| 0.00e+00 km/h).

## Acceptance tests — both PASS

`python tools/test_kappa_speed.py`, replaying 2,159 logged states through the real planner.

| test | result |
|---|---|
| `kappa_line_ahead` (ff_use_line source) bit-identical | **PASS**, max \|diff\| 0.000e+00 |
| `kappa_at` (merge FF source) bit-identical | **PASS**, max \|diff\| 0.000e+00 |
| replayed `v_curve` at corner 2 / 1 / 3 binding zones | **112.2 / 173.4 / 206.9**, err ±0.0 |

`kappa_speed` differs from `kappa_ref` at 100% of stations (max |diff| 0.01733), so the FF
identity is a real invariance, not a no-op.

## Why the proposed map migration does NOT work

Pre-scaling the map by `old_cap/new_cap` at stations that moved >5% was the natural idea. Measured,
it fails:

| | result |
|---|---|
| effective-target error vs today | median +0.00, **p95 19.9 km/h**, max +13.0 / −47.3 |
| stations within 2 km/h of today | **39%** |
| bound violations | **15** below 0.80, **3** above 1.55 |
| window-min health | 1.4129 -> **1.2882** (−0.125), ceiling 79% -> 59% |

**The cause is structural: `map_w` is a window-MIN over 18 stations.** Rescaling per station changes
*which* station is the minimum, so the product is not preserved. No per-station rescaling can fix
this; it is an inverse problem over overlapping windows.

## The migration that does work: ramp the blend

No learner surgery, no bound violations, no window-min damage, exactly reversible. Day-one
behaviour is preserved by construction at `ksp=0`, and the learner adapts continuously as the
blend rises rather than being forced through a discrete jump.

Effective-target jump at the 341 binding stations (`speed_cap` = 256 km/h applied):

| `ksp` | median | p95 | max | >20 km/h | >40 | corner-2 cap |
|---|---|---|---|---|---|---|
| 0.00 | 0.0 | 0.0 | 0.0 | 0 | 0 | 91.9 |
| **0.15** | 1.9 | 8.2 | **14.9** | 0 | 0 | 94.3 |
| **0.25** | 3.1 | 14.2 | **26.9** | 12 | 0 | 96.0 |
| 0.40 | 5.1 | 18.2 | 48.3 | 12 | 2 | 98.7 |
| 0.60 | 7.4 | 26.8 | 51.8 | 23 | 12 | 102.7 |
| 1.00 | 11.6 | 32.2 | 51.8 | 116 | 12 | 112.2 |

Human at corner 2's binding zone: **135.4** km/h. Shipped cap: 91.9.

**Suggested first rung `ksp = 0.15`** (worst jump 14.9 km/h, nothing over 20) rather than 0.25 —
the jump distribution has a long tail and 0.25 already puts 12 stations over 20 km/h.

## Note on the raw numbers

`speed_cap` (71 m/s = 256 km/h) is applied to `target_v` **before** the `v_curve` clamp, so it
bounds every effective target. Without it the analysis shows jumps of +2231 km/h at stations where
curvature is ~0 and the cap hits its `1e-4` floor; those are straights where `v_curve` never binds.
Any future analysis of this chain must apply `speed_cap` and restrict to stations where the cap
actually binds, or it will report nonsense.

## Status

Code written, acceptance tests passing, `ksp_on` defaults to **0.0** (inert). Live A-B-A design,
snapshot budget, and sequencing against the pending ileak replication are deferred until the farm
is back.
