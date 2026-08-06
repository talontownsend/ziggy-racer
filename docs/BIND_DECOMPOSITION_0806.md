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

## Why the car is under target: the decomposition

Of the on-track ticks that are plan-bound AND more than 5 km/h under target (39.8% of the
lap, mean deficit **29.1 km/h**):

| state | share | mean a_long | mean deficit |
|---|---|---|---|
| **pedal held down by the `thr_cap` derate** | **66.2%** | 0.83 | 29.1 |
| throttle commanded below cap voluntarily | 29.6% | 0.82 | 28.8 |
| full pedal delivered, accelerating | 2.4% | 1.40 | 30.3 |
| full pedal delivered, NOT accelerating | 1.8% | 0.29 | 31.2 |

On the derate-held ticks: `thr_cap` 0.681, delivered pedal 0.618, mean `|steer|` 0.614,
full-lock 20.8%. On the full-pedal non-accelerating ticks: rpm/max 0.713, gear 3.75,
160 km/h, a_long +0.29.

**Only 1.8% of the deficit is the car running out of engine.** Two thirds of it is the
throttle derate, and it is active under moderate-to-heavy steering.

## Why every relaxation lost, finally consistent

`thr_cap = max_throttle * fc_frac * slip_frac * grip_scale`, and `slip_frac` derives from
`drive_slip`, the max combined slip over four wheels. Combined slip includes the lateral
component, so it rises with steering: this project already established it functions largely as
a **steering detector**.

So the derate is the proximate cause of the speed deficit AND it is load-bearing. It is what
keeps the car on the road while the steering is already saturated 34% of the lap with no
authority in reserve. Remove it and the measured result is the spin arm: identical pace,
**15x the off-track rate**. Six other relaxations lost the same way.

This is why the throttle side cannot be opened from the throttle side. The derate is
compensating for a lateral controller that has run out of authority. **Restore the steering
authority and the derate becomes relaxable; until then it is holding the car together.**

## One thing left unexplained

29.6% of the deficit ticks have the throttle commanded **below** a cap that is not binding, and
are not braking. The speed controller is voluntarily asking for less than it is allowed while
the car is 28.8 km/h under target. That is not explained by the derate and has not been
investigated. It is the one throttle-side question this decomposition opens rather than closes.

## The 29.6%, resolved: the demand law is wrong and a byte overflow is hiding it

The unexplained ticks are the pad wrap, still live (`pad_clamp` defaults to 0.0). Measured over
485,494 on-track ticks:

- `thr_cap > 1.0` on **18.3%** of ticks (max 1.854), because
  `thr_cap = max_throttle * fc_frac * slip_frac * grip_scale` and `grip_scale = load_factor^0.705`
  exceeds 1 under load. A grip multiplier above 1 is meaningful for `alat_max`. For a **pedal**
  it is meaningless.
- commanded throttle exceeds 1.0 on **9.4%** of ticks, and `vgamepad` writes it into a
  `c_ubyte` that wraps mod 256.

The sawtooth is unambiguous:

| commanded | n | delivered | a correct pad |
|---|---|---|---|
| 1.0-1.2 | 31697 | 0.098 | 1.000 |
| 1.2-1.4 | 7019 | 0.264 | 1.000 |
| 1.4-1.6 | 2275 | 0.490 | 1.000 |
| 1.6-1.8 | 4682 | 0.690 | 1.000 |
| 1.8-2.0 | 462 | 0.816 | 1.000 |

Delivered is exactly `commanded - 1.0`. This destroys **23.9% of all on-track pedal**.

### Why fixing it keeps losing

The wrap is **not** uniformly distributed. The understeer flag is set on **48.6%** of over-range
ticks against 31.5% overall. So the overflow acts as a throttle cut that fires preferentially
when the car is understeering, which is exactly when a throttle cut is correct. Delivering the
commanded value instead (`pad_clamp`) measured worse six times, and pairing it with a stability
compensation (`slip_target` 1.05 -> 0.85) did not rescue it.

`gs_max=1.0` is **not** an independent fix: capping `grip_scale` for `thr_cap` makes the demand
<= 1.0, and on exactly those ticks the controller wanted "as much as possible", so it delivers
1.0 just as `pad_clamp` does. The two are equivalent where it matters.

### What that actually means

The controller asks for full throttle while the car is understeering, on ~9% of the lap, and the
only reason the car stays on the road is an integer overflow. **The defect is the demand law,
not the pad.** Clamping cannot help, because clamping faithfully delivers a wrong demand.

The fix is for the demand law not to ask for full throttle under understeer in the first place.
`understeer_gain` and the `under` flag already exist and are evidently not doing enough. That is
a throttle-side redesign, distinct from every `pad_clamp` arm tried so far, all of which changed
delivery while leaving the demand untouched.

**Do not "fix the wrap" without fixing the demand first.** The wrap is currently load-bearing,
and removing a load-bearing accident before replacing its function is how this gets slower.
