# Proposal: reserve steering authority for the path

**Status: proposal, not implemented. Needs a go/no-go.**

## The measurement that motivates it

485,494 on-track racing ticks, 08-06 baseline:

| | value |
|---|---|
| at full lock (\|steer\| > 0.99) | **31.9%** of the lap |
| plan demands more curvature than the envelope allows | **0.3%** of ticks |
| `\|ff\| > 0.97` (curvature feedforward alone saturating) | **0.00%** |
| full-lock ticks that are PID-dominated | **97.9%** |
| median \|cte\| at full lock | **1.62 m** |
| lateral g used / `alat_max` at full lock | **0.683** |

**The path never requires full lock.** The feedforward, which encodes the corner, never once
saturates the wheel across half a million ticks. The wheel is pinned for a third of the lap by
the cross-track correction, for a median error of 1.62 m, while 32% of the grip is unused.

Correcting an earlier framing of mine: this is not "the car is out of steering angle" in the
sense of a physical limit the corner imposes. The corner fits. The controller is spending the
whole actuator range on correction and has nothing left for the corner it is in.

## What that costs

When the wheel is already at the stop, the loop has no authority to answer a disturbance. The
`thr_cap` derate is what covers that gap, and it is the largest single contributor to the speed
deficit: 66.2% of under-target ticks have the pedal held down by it, against 1.8% that are
actually out of engine. Six attempts to relax the derate lost, because the derate is
compensating for exactly this.

## The change

**Bound the correction so total steering cannot saturate.** The feedforward gets first claim on
the actuator; the PID gets what is left.

    ff      = curvature feedforward           (never exceeds 0.97 today)
    avail   = steer_limit - |ff|              (authority not already committed to the path)
    corr    = clip(p_t + i_t + d_t, -avail*k_reserve, +avail*k_reserve)
    steer   = ff + corr

with `k_reserve` in (0, 1] as the single hot key, `k_reserve = 1.0` reproducing today's
behaviour minus the saturation. Plus honest anti-windup: the integrator must stop accumulating
whenever `corr` is clipped, not only when it agrees in sign with the error (`aw_on`'s current
condition).

## Why this is not one of the relaxations that lost

Every one of those raised a limit. This lowers one. The derate, the wrap and the governor are
all downstream compensations for a saturated wheel; this removes the saturation instead of
loosening the things that exist because of it. If it works, the derate becomes relaxable and the
pad-clamp ordering already on record (fix corner-exit authority, then clamp) becomes reachable.

## Prediction, to be recorded before the window is scored

1. Full-lock share falls from 31.9% to under 15%.
2. `|cte|` p90 does **not** worsen by more than 0.5 m. Correction is bounded, not removed, and
   the current unbounded version is not achieving lower error anyway.
3. Lap time is **unchanged or slightly worse** on the first pass, because the derate still binds.
   The prize only appears when the derate is relaxed afterwards.

Prediction 3 matters: **judging this arm on lap time alone will reject it.** Score it on
full-lock share and `|cte|` first, then relax the derate as a second stage.

## Staging

1. Implement behind `k_reserve`, default 1.0 (no behaviour change), with anti-windup on clip.
2. Verify offline on a replayed log that `k_reserve=1.0` reproduces the current steer trace.
3. Ladder `k_reserve` 0.8 / 0.6 / 0.4, 30 min equilibration and 45 min scoring each, one
   `tune_hash` per window, learner live (never frozen: METHODOLOGY rule 18).
4. Only if full-lock share drops and `|cte|` holds, ladder the derate back.

Roughly 4 hours for stage 3, 3 more for stage 4.

## The open risk, resolved (it was real, and the proposal survives)

The concern was that the car reaches only 0.59 of the modelled curvature envelope at full lock,
so the wheel might be nearer a genuine limit than this assumes. Measured on **steady** full lock
only (saturated >=200 ms, no brake, 54,756 ticks), p95 achieved curvature per speed bin:

| speed km/h | achieved p95 | model `3.86 v^-1.294` | ratio |
|---|---|---|---|
| 80-100 | 0.03772 | 0.05518 | 0.68 |
| 100-120 | 0.03393 | 0.04709 | 0.72 |
| 120-140 | 0.02607 | 0.03735 | 0.70 |
| 140-160 | 0.02145 | 0.03148 | 0.68 |
| 160-190 | 0.01665 | 0.02611 | 0.64 |

**The envelope in the notes is optimistic by 30-35% at every speed.** Refit on steady full-lock
p95: `kappa_max = 4.273 * v^-1.429`. At steady full lock the understeer flag is set on just
**3.3%** of ticks, sideslip is 1.2 deg and grip util 0.745, so the car is not sliding or pushing.
It is simply at maximum steering angle: **when saturated, the wheel is at a real limit.**

That formula is used **nowhere in `follow.py`** (only in a `tools/` docstring), so it is a
descriptive fit for analysis and being wrong by 30% has no runtime consequence. It does mean the
"0.3% infeasible" figure was measured against an envelope that does not exist.

Recomputed against the measured envelope:

| | assumed | measured |
|---|---|---|
| plan demands infeasible curvature | 0.3% | **1.0%** |
| among full-lock ticks | 0.4% | **1.4%** |
| median demand/limit at full lock | - | **0.57** |
| share of lap with demand > 0.8 x limit | - | **4.0%** |

**The premise holds and is stronger than first stated.** Even against the real, lower envelope,
at the moments the wheel is pinned the path is asking for 57% of the curvature available. And
the decisive pair does not depend on the envelope at all:

    at full lock:   mean |ff| = 0.206     mean PID sum = 0.965

The corner needs a fifth of the wheel. The correction demands all of it.

## Remaining uncertainty

The envelope refit is a p95 over steady full-lock samples, which is a lower bound on capability:
the car only reaches those states where the controller took it. If some speeds are never driven
at genuine maximum lock the fit understates them there. This does not affect the proposal, whose
argument rests on the `ff` vs PID split, but it does mean `4.273 * v^-1.429` should be treated
as measured-behaviour, not proven-capability.

## Design correction (08-06, before any window was spent)

An open-loop replay attempt caught two things.

**1. `k < 1.0` removes full lock entirely, by construction.** The clip gives
`|steer| <= |ff| + (1-|ff|)*k`, which for `k < 1` is strictly below 1.0 at every value of `ff`.
So the proposed ladder 0.8 / 0.6 / 0.4 does not reserve headroom, it caps peak steering at
roughly 0.84 / 0.68 / 0.52 of lock and the car can never command the top of its range. The plan
demands infeasible curvature on 1.4% of full-lock ticks, so that capability is occasionally real.

The parameter therefore conflates two separate ideas:

- `k = 1.0` : the PID cannot push the total past full lock, but full lock remains reachable when
  the feedforward asks for it. **This is the "no saturation" change actually argued for above.**
- `k < 1.0` : additionally reserves headroom and caps peak steering below the mechanical limit.
  A stronger intervention, and one that removes capability the car sometimes needs.

**Revised ladder: 1.0 first.** Only if 1.0 shows the predicted effect should `k < 1` be tried,
and then it should be understood as a peak-steering cap, not as reserving margin.

**2. The offline replay in stage 2 is not possible with the current log schema.** `h_t` (the
pursuit term) is not logged separately, and `steer` is recorded after the slew limiter, clamp and
BC blend, so the correction cannot be reconstructed: `steer - ff` correlates **-0.013** with the
logged `p_t + i_t + d_t`. Logging `h_t` and a pre-slew `steer_raw` would make the replay possible.

The part of stage 2 that mattered was already settled analytically: `k_reserve = 0.0` is inert to
zero counts after pad quantisation. What is lost is the ability to predict the ON behaviour
offline, which means the first rung has to be measured live.
