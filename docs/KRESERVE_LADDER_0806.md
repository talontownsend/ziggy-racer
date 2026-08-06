# k_reserve ladder

Bound the cross-track correction to the authority the feedforward is not using:
`|corr| <= (1 - |ff|) * k_reserve`, with `cte_int` frozen whenever the clip binds.
Design and pre-registered predictions: docs/PROPOSAL_lateral_authority.md.

## Rung 1: k_reserve = 1.0 -- PASSES

At 1.0 the clip allows `|steer| <= 1.0`, which `follow.py:1629` already enforced, so the
**steering output at saturation is unchanged**. What changes is anti-windup: `cte_int` stops
accumulating while clipped, so `i_t` decays and the car leaves saturation instead of grinding
against the stop. Rung 1 is therefore a classic anti-windup fix, not a capability change.

| | baseline | k_reserve 1.0 |
|---|---|---|
| laps | 451 | 142 (82 in the scored window) |
| full-lock share | 32.7% | **27.1%** |
| \|cte\| p90 | 3.06 m | **2.98 m** |
| lap median | 30.12 | **29.92** |
| stalls (scored window) | ~4 | **1** |
| clip fired | - | 38.92% of ticks |

Pre-registered criteria: **1 PASS** (saturation falls), **2 PASS** (tracking not worse by
>0.5 m; it improved). Criterion 3 was "lap time unchanged or slightly worse"; it improved by
0.20 s, which is **below the ~0.30 s measurement floor** and is therefore reported as
"did not cost time", not as a win. It held direction across every 15-min trailing slice
(29.80-30.03).

**The prediction was wrong in the favourable direction, which is still a wrong prediction.**
The mechanism argument said the derate would keep binding and cap any gain. It did not cap it
as hard as expected.

## Notes for whoever runs the next rung

`k < 1.0` is a **different kind of change**. It makes `|steer| <= |ff| + (1-|ff|)*k`, strictly
below full lock, so the car can no longer command its mechanical maximum at all. The plan
demands curvature beyond the envelope on 1.4% of full-lock ticks, so that capability is
occasionally real. Judge lower rungs on off-track rate and stalls, not only on `|cte|`.

The watchdog dead-man must track the armed value for the duration and be restored afterwards.
`ab_arm` reverts `tune.json` on exit but **cannot** revert `watchdog.ps1`, so the two go out of
sync at the end of every window and the next restart would silently re-arm. That is the
`pad_clamp` failure mode already on record.
