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

## What could make this wrong

The car achieves only 0.59 of the modelled envelope curvature at full lock, which either means
the envelope fit (`kappa_max ~= 3.86 v^-1.294`) is optimistic, or the car is not converting lock
into rotation. The understeer flag is set on just 24.1% of full-lock ticks, so it is not simply
understeer. **This is unresolved**, and if the true envelope is much lower than modelled then
the wheel is nearer a real limit than this proposal assumes and bounding the correction will
cost tracking. Stage 2 should settle it before any live window.
