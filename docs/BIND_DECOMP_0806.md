# Where the speed deficit actually comes from

First clean `bind_code` decomposition. `bind_code` is **logged, not reconstructed**: it names
the last term that lowered `target_v`, so it is the binding constraint. Every prior
reconstruction of this chain needed correcting, which is why it is logged.

Method: racing, on-track, **brake excluded**, ticks where `tgt_kmh > spd_kmh`. Weight is
`(tgt - spd) * dt` in km/h-seconds, the integral of the deficit over time, so shares sum to
100%. Tick counts alone cannot distinguish a code that binds constantly by 1 km/h from one that
binds rarely by 100. Run: `python tools/bind_decomp.py`.

Brake ticks are excluded because a braking car is under target *by design*. Including them once
already produced a wrong conclusion (KRESERVE_LADDER_0806.md).

## cte_ileak 0.0 (baseline, pooled) — 206,001 ticks, 204,270 under target (99.2%), 52.8 min

| code | constraint | ticks | %ticks | km/h-s | share | mean |
|---|---|---|---|---|---|---|
| 1 | plan / tv | 162,034 | 79.3% | 56,231 | **79.6%** | 23.3 |
| 3 | `v_curve * map_w` | 39,181 | 19.2% | 13,059 | **18.5%** | 18.5 |
| 5 | launch cap | 1,331 | 0.7% | 971 | 1.4% | 51.8 |
| 7 | understeer | 179 | 0.1% | 265 | 0.4% | 102.5 |
| 6 | cte governor | 1,545 | 0.8% | 75 | 0.1% | 2.7 |

## cte_ileak 0.5 (armed) — 318,276 ticks, 316,048 under target (99.3%), 82.2 min

| code | constraint | ticks | %ticks | km/h-s | share | mean |
|---|---|---|---|---|---|---|
| 1 | plan / tv | 259,410 | 82.1% | 82,193 | **82.1%** | 21.2 |
| 3 | `v_curve * map_w` | 54,092 | 17.1% | 17,331 | **17.3%** | 17.2 |
| 5 | launch cap | 672 | 0.2% | 346 | 0.3% | 35.7 |
| 7 | understeer | 72 | 0.0% | 103 | 0.1% | 103.0 |
| 6 | cte governor | 1,802 | 0.6% | 93 | 0.1% | 2.6 |

Codes 2 (`speed_cap`), 4 (`pdg`) and 8 (zone) **never bind**. `safety = 1.0`, so `safety_eff` is
identically 1.0 and contributes no derate: code 1 is the raw plan target.

## The largest code is 1, and it is not actionable

Code 1 means `tv` was the minimum and **nothing downstream bound at all**. Under it:

- **87.4% of ticks are accelerating**, mean `+0.724 g`
- only **2.2%** have the pedal wide open; commanded throttle p90 is **1.081** (demand exceeds
  full throttle), so neither demand nor engine is the shortfall
- `thr_cap` binds on **57.4%**
- mean target 154 km/h, mean actual 131 km/h

**99.2% of non-braking on-track ticks are "under target".** A car that has just slowed for a
corner is below its straight-line target for the whole straight. So most of code 1 measures *the
car accelerating normally*, not something restraining it. **The deficit metric is much weaker as
a diagnostic than previously assumed**, and any past claim of the form "X% of the deficit is
caused by Y" inherits that weakness.

## The largest genuine limiter is code 3

`v_curve * map_w * v_curve_trim * sfac` — curvature crossed with the learned vtrim map — owns
**18.5% / 17.3%** of the deficit on ~19% of ticks. Every other real limiter is under 1.5%.

That is corner speed, which is where lap time normally lives, and it is the only place a limiter
materially binds. **Structural work goes here**, not into the throttle chain (closed on its own
terms, stage 4) and not into the governor/understeer/zone terms, which are rounding errors.

## What the ileak changed

Rate = km/h-s per minute under target, so the segments compare despite different lengths.

| code | constraint | 0.0 | 0.5 | delta | %chg |
|---|---|---|---|---|---|
| 1 | plan / tv | 1066 | 1000 | -66 | -6.2% |
| 3 | `v_curve * map_w` | 248 | 211 | **-37** | **-14.8%** |
| 5 | launch cap | 18 | 4 | -14 | -77.1% |
| 7 | understeer | 5 | 1 | -4 | -75.1% |
| 6 | cte governor | 1 | 1 | -0 | -19.9% |
| | **TOTAL** | **1338** | **1217** | **-121** | **-9.0%** |

The -0.51 s came with a 9% cut in integrated deficit, and its largest limiter reduction was code
3 at -14.8% — the same code this decomposition identifies as the only material one. Coherent,
not coincidental. Understeer events also fell 179 -> 72 ticks, consistent with better cross-track
tracking. **The ileak result is still a single unreplicated A-B-A** and is not yet a finding.
