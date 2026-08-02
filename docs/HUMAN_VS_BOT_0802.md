# Human vs bot, 08-02: where the 3.25 s actually is

Source: 50 human laps recorded 08-02 07:36 via the FH6-TC plugin recorder (48 clean, two
outliers dropped), against the bot's final 198 clean laps from the same morning. Same car
(`max_rpm` 8000, Tacoma), same track, same day.

| | human | bot |
|---|---|---|
| median | **26.818** | 29.950 |
| best | **26.207** | 29.290 |
| p25 / p75 | 26.547 / 27.036 | 29.76 / 30.11 |
| IQR | 0.49 | **0.35** |

The gap is **3.25 s**, not the 4.28 s previously quoted against the one-off 25.679 PB. Note the
bot is already the *more consistent* driver: its IQR is smaller. Consistency is not the problem.

## The plan is not the problem

| | mean speed |
|---|---|
| human | 159.19 km/h |
| bot's own commanded **target** | 155.43 |
| bot **achieves** | 142.03 |
| reference plan field | 163.43 |

- The bot's target already equals or exceeds human speed at **54.6% of stations**.
- The bot actually reaches human speed at **12.6%**.
- Mean shortfall against its own target: **13.40 km/h** (median 11.55).

Every previous framing of the remaining gap as "the target chain is too conservative" is wrong.
The targets are approximately right. The car does not deliver them.

## The loss is diffuse, and it is where the throttle is

Cumulative time loss grows smoothly around the whole lap. The top 50 stations hold only 17% of
the gap and the top 150 hold 41%; the bot is actually faster than the human at 152 stations.
There is no single corner to fix.

Splitting the deficit by what the bot is doing at the time:

| bot state | stations | shortfall vs its OWN target | vs human |
|---|---|---|---|
| **on throttle > 0.5** | 436 | **26.76 km/h** | 21.36 |
| part throttle 0.05-0.5 | 260 | 16.45 | 17.69 |
| braking | 295 | -8.71 (above target, as expected) | 10.61 |

The shortfall lives almost entirely where the car is trying to accelerate.

## Two deficits, and they must be fixed together

**1. Longitudinal: 22.4% of the average pedal is destroyed before it reaches the game.**
In this exact session the bot commanded `thr > 1.0` on **9.19%** of ticks, and the `c_ubyte`
wrap turns those into near-zero pedal. Mean commanded pedal 0.407, mean **delivered** 0.316.
On **6.97%** of all ticks the controller asked for full power and the game received under 0.25.

Corroborating from the other side: the human is on full throttle at **20.9%** of stations, the
bot commands it at 13.7% and delivers far less.

**2. Lateral: the bot uses about 20% less cornering grip than the human.**

> ## RETRACTED, same day. This deficit is not real.
>
> Twelve independent verifications across five analysis lenses, each with its own pipeline,
> converged on refuting it. The lateral gap is the **speed deficit restated through
> `a_lat = v² · κ`**, not unused grip:
>
> - At matched station, the bot's lateral g **predicted from its own speed on the human's
>   geometry** is 1.395 g against 1.456 g actually measured. Speed alone explains **120%** of the
>   0.302 g gap; the residual is **+0.061 g in the bot's favour**.
> - Independent of any accelerometer: total heading change over the 13 corner segments is
>   **651.8 deg for the bot against 646.9 for the human** (ratio 1.0076), and geometric path
>   curvature from world positions is bot/human >= 1.0 in every curvature band. **The bot drives
>   the same or a tighter line, at 89% of the speed.**
> - Scored against the bot's own grip model, the human tops out at `g_util` p99 0.854 / p99.9
>   0.883 versus the bot's 0.813 / 0.842. **The same ceiling.**
>
> The corroborating evidence below (lateral utilisation 0.31 in fast sections vs 0.64 in
> hairpins) is real but says the opposite of what I read into it: utilisation is lowest exactly
> where the speed deficit is largest, because a slower car needs less lateral force at the same
> radius. Keep the numbers, discard the conclusion.
>
> **The coast hypothesis below is closed too.** At matched curvature and speed the effect is
> +0.010, -0.012, -0.030 and -0.091 g across four independent designs, every confidence interval
> spanning zero. And the 13.7%-vs-0.9% figure is largely an artifact: **48.9% of the bot's coast
> ticks are gearshift lifts** (`follow.py` forces throttle to 0 through every shift), leaving
> 0.80% genuine neutral. The mechanism is also analytically negative: a 0.25 s neutral window
> buys +0.127 g of lateral capability and costs 8.8 km/h. What cannot be concluded is that a
> *designed* coast phase would fail, since the bot has never driven a settled one (median neutral
> episode is 3 ticks). It is untested, not refuted, and still not worth a window.

| | mean | p90 | p99 |
|---|---|---|---|
| human lateral g | 1.82 | 3.02 | **4.06** |
| bot lateral g | 1.55 | 2.64 | **3.25** |

The car demonstrably has that grip (measured envelope is ~3 g median, 4.7 g peak). The bot is
leaving roughly a quarter of the cornering force unused, which is consistent with the standing
finding that it is understeer-limited rather than steering-authority-limited.

**Why `pad_clamp` actually fails** (the lateral story above being retracted, this is the
evidenced version). Decomposing `thr_cap = max_throttle * fc_frac * slip_frac * grip_scale` into
its factors shows **two disjoint defects that live in different parts of the corner**:

| defect | where it lives | footprint | mean pedal destroyed |
|---|---|---|---|
| `c_ubyte` wrap | **straights**: lateral g median 0.53, steer median 0.36, 153 km/h | 9.20% of ticks | 0.0914 |
| combined-slip derate | **corner exit**: 87.7% at >1.5 g lateral, 55.4% at full lock, 1.1% on straights | 20.69% of ticks binding | 0.0574 |

**Overlap between the two populations: 0.1%.** They are disjoint and additive. `pad_clamp`
restores drive on the *straights*, which raises corner **arrival** speed, while the corner
**exit** stays taxed by a derate the car cannot escape. Arriving faster with no more exit drive
is precisely the measured failure: off-tracks concentrated at corner entries (s894-905, 2% to
86%), plus a vtrim carving spiral.

So the ordering stands but with the correct prerequisite substituted: **fix corner-exit throttle
authority first, then `pad_clamp`.** Not lateral grip.

## A mechanism worth chasing for the lateral deficit

The single sharpest behavioural difference in the data:

| | coasts (no throttle, no brake) |
|---|---|
| human | **13.7% of stations** |
| bot | **0.9%** |

The human regularly goes neutral, lets the car settle and rotate, then reapplies power. The bot
is on throttle or brake essentially always, because it is a controller nulling a speed error it
can never null. Being permanently on a pedal loads the tyres in a way that costs front grip
exactly when it is needed for turn-in. This is a control-law hypothesis, it is testable from the
bot's own telemetry, and it does not require any human-derived operating bound.

## Constraint note

All of the above uses human laps as an *evaluation target*, which `CONSTRAINTS.md` #3 permits.
None of it proposes a human-derived operating bound. A behavioural-cloning policy fitted to
this recording would violate #3 and is not proposed here; the recording tells us **what** is
wrong, and the fixes must come from the bot's own measurements.

---

# Follow-up, 08-02 10:00: the corner-exit derate is not a defect either

The "fix corner-exit throttle authority first" conclusion above was tested and is **wrong**.

The reasoning behind it reproduced independently and held up: `drive_slip` is
`max|combined_slip|`, it correlates with steering (r = +0.372 here, +0.005 for the
longitudinal-only `drive_spin`), its mean climbs 0.601 -> 1.707 across steering bands while
`drive_spin` stays flat, and the shipped threshold fires on **44.3% of the lap for a 1.58x lift**
in the probability of exceeding 7 deg of sideslip within 0.35 s, measured from a settled car.
Every one of those numbers is right.

The arm that followed from them was not. `slip_target` 1.05 -> 1.50 with `spin_thr` 1.5 (raise
the combined ceiling, add the longitudinal signal to carry the wheelspin duty) against a
same-session 29.94 s baseline:

| | baseline | arm |
|---|---|---|
| median | 29.94 | **34.50, aborted** |
| \|sideslip\| p99 | 7.50 deg | **17.40** |
| off-track | 0.74% | **2.21%** |
| **`drive_spin` > 1.5** | **2.02%** | **4.82%** |

It produced **more genuine wheelspin**, which is the opposite of what a better-targeted wheelspin
guard should do. So the combined-slip derate is not a mis-fired wheelspin detector at all; it is
doing friction-circle work against the *measured* tyre state, where `fc_frac` only does it
against the *modelled* grip ellipse. Detecting steering is the intended behaviour for a limiter
whose job is to stop the car spending grip laterally and longitudinally at the same time.

## Where that leaves the 3.25 s

Both throttle-side defects are now measured and both are load-bearing:

- the `c_ubyte` wrap destroys 22.4% of average pedal, and removing it costs 0.7 s and 8 stalls
- the combined-slip derate taxes 44% of the lap, and relaxing it costs 4.6 s

Every guard between the bot and its own commanded target has now been tested and each one is
holding the car together rather than holding it back. Five relaxations, five losses.

The human reaches those same speeds in the same car with the same grip, so the speed is
physically available. What differs is not a limit value but the **coordination**: how throttle,
brake and steering are sequenced through a corner so that grip is spent in the right order. That
is a controller-architecture question, not a tuning question, and no knob in the current
structure addresses it. It should be treated as the next real project rather than the next arm.

---

# Follow-up 2, 08-02 11:00: coordination is not the answer either

If the gap were about *sequencing* grip through a corner (brake, release, rotate, power) rather
than about limit values, it would show as a thinner friction-circle usage: one axis at a time
instead of combined loading. It does not. Over 48 clean human laps and 71 clean bot laps,
lateral from the same telemetry channel and longitudinal from dv/dt for both:

| | human | bot |
|---|---|---|
| combined loading (both axes > 0.5 g) | 57.4% | **58.8%** |
| lateral only | 27.3% | 22.6% |
| longitudinal only | 15.0% | 13.6% |
| trail-braking (lat > 1 g and decel > 1 g) | 11.57% | **16.11%** |
| power-on (lat > 1 g and accel > 1 g) | 14.59% | 12.69% |

And the g-g envelope, the honest test of whether a driver can hold longitudinal force while
already loaded laterally:

| lateral load | human \|long\| p95 | bot \|long\| p95 |
|---|---|---|
| 0.5-1.0 g | 2.41 | 2.40 |
| 1.0-1.5 g | 2.07 | **2.22** |
| 1.5-2.0 g | 1.91 | **2.02** |
| 2.0-2.5 g | 1.66 | **1.82** |
| 2.5-3.0 g | 1.45 | **1.74** |
| 3.0+ g | 1.45 | 1.21 |

**The bot combines grip as well as or better than the human at every lateral load below 3 g, and
trail-brakes more.** The coordination hypothesis in its "spends grip in the wrong order" form is
refuted. Task #15's option (A) should be closed; option (B), joint rather than single-axis
tuning, is what remains.

## The two residuals that survive

**1. Peak grip.** Total \|a\| p99 is 4.13 g for the human against 3.48 g for the bot, and lateral
p99 4.05 vs 3.26. The bot's own grip model allows only about 3.2 g at these speeds
(`planner_alat` 27 plus `planner_alat_k` 0.0025·v², which rises just 3% across the speed
difference), so the human is exceeding the model, not just the bot. Whether the model is
under-calling the high end, or the peaks come from banked sections where the lateral channel
carries a gravity component, is **not established here** and should not be assumed either way.

**2. Dead time.** The bot spends 4.98% of on-track ticks (**1.48 s/lap**) with both axes under
0.5 g, against the human's 0.3%. It is not recovery artifact: 84.6% of it is above 120 km/h, at
163.5 km/h against a 178.9 km/h target. But it is also **not a throttle cap**: commanded throttle
there is 0.420 while `thr_cap` allows 1.016, `fc_frac` is 1.000 and `drive_slip` is 0.10. At those
same stations across all ticks the throttle sits at 0.996. So it is a transient, and the throttle
is zeroed 49.3 times per lap (94.2% by the brake branch, 61% of those lasting under 56 ms) with a
~264 ms rate-limited ramp back each time.

That looks like a prize and probably is not one: the speed deficit across all below-cap ticks is
only +1.3 km/h, and an earlier adversarial pass priced brake-branch chatter at 0.03 s/lap with a
hard upper bound of 0.07. Recorded so it is not rediscovered and chased a third time.
