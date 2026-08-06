
---

# Stage 4: relax the throttle derate against an unpinned wheel

`k_reserve = 1.0` deployed (code default + dead-man + live config). Stage 4 asked the question
the whole week pointed at: with the wheel no longer saturated a third of the lap, is the
`thr_cap` derate still load-bearing?

Knob: `slip_target`, 1.05 -> 1.25. `slip_frac = 1 - (drive_slip - slip_target)/slip_target`.

## Result: NULL. The arm worked; the lap time did not move.

| | slip 1.05 | slip 1.25 |
|---|---|---|
| laps | 142 | 116 |
| **lap median** | **30.41** | **30.40** |
| cap binding (`thr == thr_cap`) | 54.6% | 49.0% |
| cap binding at full lock | 45.4% | 36.0% |
| commanded throttle at full lock | 0.368 | 0.404 |
| `thr_cap` at full lock | 0.437 | 0.589 |

The mechanism moved substantially: the cap rose 35% at full lock, binding fell 9.4 points there,
and the car commanded 10% more throttle. The median moved 0.01 s.

**Eighth independent instance of the same pattern**: throttle delivery improves, lap time does
not. The difference this time is that it ran with steering saturation fixed, which was the
stated reason to expect a different answer. It was not different.

## Two measurement errors of mine, both caught here

**1. The apparent 0.27 s gain was drift.** The first read compared the arm (30.33) against only
the first 45 min of baseline (30.60), which was measured immediately after a restart while the
map re-equilibrates. Including the post-revert baseline laps gives 30.41 vs 30.40. Lap times
declined monotonically across the whole three hours (30.60 -> 30.33 -> 30.25 -> 30.11)
independent of config. **Never baseline a window against a post-restart transient.**

**2. "The derate is not binding at full lock" was brake-contaminated.** Delivered pedal at full
lock reads 0.020, which looks like the controller wanting nothing. Filtering brake ticks, the
commanded throttle is 0.368 against a cap of 0.609: it binds on 45.4% of full-lock ticks. Always
exclude braking before reasoning about throttle.

Related: the bind decomposition's "66.2% of under-target ticks held by the derate" tested
`thr_cap < 0.97`, which shows the cap is below full, not that it binds. The binding test gives
**48.9%** of ticks cap-binding *and* >5 km/h under target.

## What this closes

The derate binds, relaxing it delivers more throttle, and the car is no faster. That holds with
the wheel unpinned, which was the last remaining reason to think the throttle side was
recoverable. **The throttle side is closed on its own terms**, not merely blocked by steering.

`k_reserve = 1.0` stays deployed: it improves saturation and tracking measurably and costs
nothing, but it is not a lap-time change and should not be recorded as one.
