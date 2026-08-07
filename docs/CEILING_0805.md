# Twenty-four arms: the mechanism metrics are all improvable, the lap time is not

> **MEDIANS INFLATED ~0.71 s (see docs/STATE_OF_KNOWLEDGE_0806.md, item 1).** The lap detector merged ~4 laps per group until 08-06. Conclusions resting on a scored median need re-reading.

## The integrator leak: the defect was real, the fix worked, the clock did not move

The cross-track integrator has a clamp and no leak. Measured over 398k ticks: at/near its 3.0
clamp on 45.0% of ticks, 4.9 sign flips per lap, failing to unwind below half-clamp within 2.1 s
on 65.2% of releases, and **opposing the current error on 32.0% of ticks with |i_t| 0.208 against
|p_t| 0.208 — a 1.00x ratio, cancelling the proportional correction outright.** The shipped
`aw_on` cannot help: it decays the integral only when it AGREES with the error.

Adding a first-order leak did exactly what it should:

| | baseline | leak 0.5 | leak 1.0 |
|---|---|---|---|
| integral opposing the error | 27.8% | 19.8% | **16.1%** |
| at/near clamp | 38.9% | 13.3% | **3.3%** |
| `\|cte_int\|` p50 | 2.526 | 1.674 | **1.148** |
| **`\|cte\|` p90** | 4.14 m | 3.68 | **2.99 m** |
| full-lock fraction | 37.5% | 36.8% | 33.9% |

| | median | delta | stalls | off% | sideslip p99 |
|---|---|---|---|---|---|
| baseline | **30.27** | | **0** | **0.13** | **7.40** |
| leak 0.5 | 30.26 | -0.02 | 1 | 1.41 | 22.20 |
| leak 1.0 | 30.62 | +0.35 | 7 | 0.87 | 8.30 |

Cross-track tracking improved by **a full metre at p90** and lap time did not move. Stability got
worse.

## The pattern, stated plainly

**Twenty-four arms, no lap-time gain.** Every subsystem attacked with measurement:

| axis | arms | outcome |
|---|---|---|
| limiter relaxations | 6 | all worse |
| joint multi-axis tuning | 3 | all worse |
| throttle demand law (feedforward) | 3 | neutral at best |
| throttle delivery (3 mechanisms) | 7 | all worse; delivery gain real, stability cost larger |
| the path / reference line | 0 | inert by decomposition: the worst corners are delivery-limited |
| the brake | 0 | unreachable by construction: `err > 1.0` bounds brake ticks to 3.6 km/h of error |
| steering governor threshold | 2 | worse; slowing earlier RAISED off-track |
| cross-track integrator windup | 2 | mechanism fixed, clock unmoved |

The generalisation is now well supported: **every individual mechanism metric on this car is
improvable, and none of them is what sets the lap time.** Delivered pedal, speed-versus-target,
derate footprint, over-range commands, cross-track error, integrator staleness — each has been
moved in the intended direction by a targeted change, and the median lap has stayed at
29.84-30.62 throughout.

The one thing that ever moved the clock was not a tuning arm: repairing the vtrim net drift and
the delta ratchet, worth 3.3 s of the 3.4 s recovered this week. That was a broken component
restored to spec, not a parameter improved.

## What that implies

The bot is at 29.9 against a human 26.82 on the same car, track and morning. The remaining 3.1 s
is not sitting behind any single term that has been examined, and the terms have now been
examined exhaustively.

Two honest readings remain, and they are distinguishable only by work larger than an arm:

1. **The architecture is at its ceiling.** A speed-error PID under a stack of independent
   multiplicative caps, with a separate cross-track PID, cannot express what the remaining time
   requires: coordinated, anticipatory use of a shared grip budget. Each loop is individually
   near-optimal, which is exactly why every local change loses.
2. **Something structural remains unmeasured.** Three separate instrument defects were found this
   week (`meas_long` never logged, `pad_thr` never read back, single-tick `dv/dt` correlating
   +0.291 with truth). A fourth is not impossible.

I would not spend another window on a twenty-fifth arm of the same shape.
