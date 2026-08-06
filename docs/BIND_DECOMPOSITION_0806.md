# What actually limits the target, measured

`bind_code` (added 08-05) records which limiter set the speed target on every tick. Over
485,494 on-track racing ticks of the 08-06 baseline:

| binding limiter | share | mean target | mean speed | headroom | mean \|steer\| |
|---|---|---|---|---|---|
| plan | **58.9%** | 156.1 | 136.1 | **+20.0** | 0.563 |
| `v_curve * map_w` | 36.3% | 112.1 | 116.7 | **-4.6** | 0.828 |
| pdg | 2.8% | 176.3 | 176.3 | 0.0 | 0.687 |
| cte governor | 1.7% | 94.1 | 91.7 | +2.4 | 0.950 |

**49.4% of ticks are more than 5 km/h below target, and 81% of those are plan-bound.**

## The two readings

1. **For ~59% of the lap the car is 20 km/h below its own target.** The active cap there is the
   plan, and the car is nowhere near it. Nothing is holding the car back on that part of the
   lap except its own ability to get to the speed already permitted.

2. **Where the vtrim path binds, the car is already 4.6 km/h OVER target.** That is arriving
   too hot, a tracking failure, not a cap limitation.

Both are control problems. Neither is a cap problem.

## What this closes

**Raising the vtrim ceiling is pointless, and this is worth stating because the map looks like
it is begging for it.** 81% of stations sit at the 1.55 clip, and it is tempting to read that
as "the learner wants more speed and is being refused." It is not. The ceiling is reached
because the learner keeps crediting stations where the car never approaches the cap in the
first place, so credit accrues without ever being tested. In the 36.3% of the lap where that
cap actually binds, the car is already exceeding the target it sets.

This also explains the standing `vtrim_health` WARN. A net fitted to a map that is 81% pinned
at 1.55 must output above 1.55 there, so "46% of net outputs out of range" is substantially
structural rather than pure drift. Refitting (08-06) still helped: `|delta|` mean 0.3499 to
0.0255 and 27.5% of stations came off the delta bound where they could no longer move, with
the effective map reproduced exactly (max err 0.0).

## Consistency with the rest

This is the same wall the other arms hit, now quantified rather than inferred. The throttle
side has been closed seven ways, the brake is unreachable by construction, the path is inert
by decomposition, and the car sits at full steering lock 34% of the lap. A car that is 20 km/h
under target for 59% of the lap while saturating its steering is not short of permission. It
is short of the ability to use it.
