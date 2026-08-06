# Instrument audit: a real gap, but no control defect behind it

Reading 2 of the ceiling question was "a fourth instrument defect is still hiding", chosen
because it is far cheaper to check than reading 1 is to act on. It found a real gap and then
refuted the hypothesis the gap enabled. Both halves are worth recording.

## The gap is real

The Forza sled block carries per-corner measurements the parser never read:

| offset | field | what the bot used instead |
|---|---|---|
| **68** | NormalizedSuspensionTravel FL/FR/RL/RR | `load_factor = 1 + ay/9.81`, one whole-car scalar |
| **100** | WheelRotationSpeed FL/FR/RL/RR | `TireCombinedSlip`, which includes lateral slip |
| 196 | SuspensionTravelMeters | (unused) |
| 116/132/148 | rumble strip / puddle depth / surface rumble | (unused) |

`grip_scale = load_factor^0.705` scales **both** `alat_max` and `thr_cap` from that single
vertical-accelerometer scalar, which cannot see load transfer between axles.

Verified against physics before use, on 69,133 on-track ticks:

| check | result |
|---|---|
| corr(roll transfer, lateral g) | **+0.824** |
| corr(front minus rear load, longitudinal g) | **-0.632** (braking loads the front) |
| corr(rear wheel speed, road speed) | **+0.986** |
| implied rolling radius | **0.378 m** (light truck: 0.35-0.42) |

And with true longitudinal slip available for the first time, at full lock `drive_slip` reads
**1.510** while the rear wheels turn **slower** than the road: no wheelspin at all.
`corr(drive_slip, |steer|) = +0.497` against `corr(true slip, |steer|) = -0.200`.

## The hypothesis it enabled is refuted

`drive_slip` is a max over all four wheels. At full lock the **front** sets it on **89.1%** of
ticks (front combined slip 1.504, rear 0.752), and deriving `slip_frac` from the rear axle alone
would allow **1.46x more pedal**. That looked like the throttle being cut for lateral saturation
on wheels that were not driving.

**The car is AWD** (drivetrain = 2 on 100% of race ticks, from the owner's own recording of the
same car). The front wheels are driven, so adding drive to a front tyre already at combined slip
1.5 removes the lateral grip it is using to steer. **Cutting the throttle there is correct
friction-circle physics**, and using the rear axle alone would have pushed drive into precisely
the tyres that cannot take it -- a plausible explanation for why every throttle-restoration arm
produced understeer and off-tracks.

## A correction

I reported front slip angle as **65.41 deg** at full lock. That was wrong: I applied a
radians-to-degrees conversion to a value the game already reports in degrees. The true figure is
**1.14 deg**, against the human's p50 0.76 and p90 1.27. The bot's front tyres are in a normal
slip-angle range. `sa_front` is now annotated in the log line.

## Where this leaves the ceiling question

Reading 2 is answered: the instrumentation gap was real, it is now closed, and it does **not**
hide a lap-time defect. Four instrument defects were found this week (`meas_long` unlogged,
`pad_thr` never read back, single-tick `dv/dt` correlating +0.291 with truth, and these
per-corner channels), and none of the last three moved the clock.

That leaves reading 1, the architectural ceiling, with the evidence now substantially stronger
for it. The per-corner load channels remain available and unused by the control law; if anything
is ever built on them it should be a grip model that resolves load transfer per axle, which is
the one thing the current single scalar structurally cannot do.

## Follow-up: the per-axle grip model is not supported either

The audit left one candidate: the per-corner load channels exist and the control law still uses a
single scalar, so a grip model resolving load transfer per axle looked like the one well-founded
remaining build. Measured on 45,218 on-track ticks, it is not.

**Front load does predict achievable lateral grip.** At 80-120 km/h, `|lat g|` p95 across
front-load quintiles: 2.42, 2.53, 2.58, 2.85, **3.11**. At 120-160: 2.55, 2.63, 3.00, 3.21, 3.16.
Roughly 28% more lateral capability at high front load.

**But the existing scalar already captures it.** `corr(alat_max_g, susp_f) = +0.703`. The
whole-car term tracks front load strongly. What it lacks is the front/rear SPLIT, and
`corr(alat_max_g, front share) = -0.016`.

**And the split does not predict capability:**

| | \|lat g\| p95 | understeer rate | model `alat_max` |
|---|---|---|---|
| front unloaded + cornering (n=6053) | **2.86** | **16.0%** | 3.22 |
| front loaded + cornering (n=8541) | 2.80 | **37.7%** | 3.19 |

Same lateral capability, and MORE understeer when the front is loaded -- the opposite of the
hypothesis. The confound is longitudinal: `corr(susp_f, meas_long) = -0.299`, so "front loaded"
largely means "braking", and braking while cornering is where the front tyres do double duty. The
front/rear split is measuring longitudinal state, not grip availability.

Building a per-axle grip model on this evidence would not be justified.

## Reading 2 is closed

The instrumentation gap was real and is now closed: four unread channels parsed, verified against
physics, and logged. Neither hypothesis it enabled survives. The front-driven throttle derate is
correct because the car is AWD; the per-axle grip model is unsupported because the split does not
predict capability.

Four instrument defects were found this week and only the first (`meas_long`, which exposed the
throttle wrap) led anywhere, and even that one produced no lap time once its consequences were
tested. That is now strong evidence for reading 1: **the architecture is at its ceiling**, and
the remaining 3.1 s is not reachable by fixing any single term.
