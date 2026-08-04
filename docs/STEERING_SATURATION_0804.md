# The car is steering-saturated for a third of every lap, and relieving it makes things worse

## The finding

Over 398,001 on-track ticks:

| | |
|---|---|
| ticks at full steering lock (`\|steer\|>0.97`) | **34.4%** |
| ...in the 0-120 km/h bands | **~50%** |
| radius achieved while saturated | 43.7 m |
| radius the path demands there | 38.6 m |
| **ratio** | **1.16 (it cannot turn tight enough)** |
| `g_util` while saturated | **0.685** |

It is not grip-limited. It is out of **steering angle**: FH6 applies speed-sensitive steering and
the measured envelope is `kappa_max ~= 3.86 * v^-1.294`.

## And the saturation is not the corner's fault

| at full lock | |
|---|---|
| `\|ff\|` (curvature feedforward) | median **0.187**, exceeds 0.97 on **0.00%** of ticks |
| full-lock ticks with `\|ff\| < 0.5` | **96.8%** |
| **PID-dominated** full-lock ticks | **71%**, `\|cte\|` median **2.53 m** |
| ff-dominated | 29%, `\|cte\|` median 0.68 m |

**The steering saturates chasing cross-track error, not curvature.** That is a lateral positive
feedback with the same shape as the throttle one: error grows, the PID demands more lock, the
command saturates, no authority remains to correct, the error persists.

It also explains why every throttle arm escalated. Slide ONSET barely changed with extra pedal
(1.28 -> 1.37 episodes per 1000 ticks); severity exploded (p90 peak sideslip 8.7 -> 25.0 deg,
max 44 -> 82). The car is already at full lock with zero reserve when a slide begins, so it
cannot catch it.

## Two sub-hypotheses killed on the way

**Sideslip rate as an early trigger: useless.** A `rate > 20 deg/s` trigger fires 62-90 ms
earlier than the `level > 7 deg` trigger, but `\|steer\|` at that moment is 1.000 with **73-75%
already saturated**, *more* saturated than at the level trigger. Earlier detection is worthless
without authority to spend.

**The reference line is not steering-limited.** Comparing the measured envelope against the
line's curvature at every key corner: s611 needs 129.7 km/h and steering allows 158.8; s660 needs
161.0 and allows 280.3. Only s403 is close (59.0 vs 61.7). The line is achievable; the car
demands *more* curvature than the line because it is off-line and trying to rejoin.

## The arm, and why it failed

Authority is gone at `\|cte\| ~= 2.5 m`, but the cte governor arms at `cte_soft = 5.0 m` and
binds on 1.3% of ticks. Slowing raises achievable curvature (`v^-1.294`), so moving the threshold
to where authority is actually lost looked like the fix.

| arm | median | delta | stalls | off% | sideslip p99 | spd-tgt |
|---|---|---|---|---|---|---|
| baseline | **30.28** | | 0 | **0.05** | 7.40 | -10.31 |
| `cte_soft` 2.5 | 32.73 | +2.45 (aborted) | 2 | **2.24** | 11.80 | -14.62 |
| `cte_soft` 3.5 | 31.00 | +0.71 | 2 | 0.47 | 7.49 | -12.97 |

Off-track went **up**, 0.05% -> 2.24%. Slowing earlier when off-line made excursions more common,
not less. The diagnosis of *where* authority is lost stands; the diagnosis of *what to do about
it* does not. The governor slows by braking, and braking while off-line and at full lock upsets
the car further, so its response is wrong even where its trigger would be right.

## Standing count

**Twenty-two arms, no lap-time gain.** Every subsystem has now been attacked with measurement:
limiters (0/6), joint tuning (0/3), the demand law (0/3), throttle delivery (0/7), the path
(inert by decomposition), the brake (unreachable by construction), and now the steering governor
(0/2). The bot sits at 29.84-30.28 against a human 26.82 on the same car, track and morning.

The one change that ever worked this week was not a tuning arm: repairing the vtrim net drift and
the delta ratchet, worth 3.3 s, and that was a defect repair.
