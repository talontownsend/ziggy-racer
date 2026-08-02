# Pre-registered prediction for joint search plan 1

Written 08-02 ~11:45, **before** any arm reported. Recorded so the outcome is a test rather than
a story told afterwards. Today has already produced four hypotheses of mine that looked good and
were refuted, so the discipline is worth the file.

## What the evidence says

**1. The human genuinely exceeds the bot's grip model, and it is not a banking artifact.**
Gravity correction (`a_lat - g·sin(roll)`) makes the gap *larger*, not smaller:

| | raw p99 | gravity-corrected p99 | p99.9 | \|roll\| p99 |
|---|---|---|---|---|
| human | 4.05 g | **4.14 g** | 4.93 g | 7.6 deg |
| bot | 3.26 g | 3.35 g | | 8.0 deg |

Roll is only ~8 deg, worth ~0.13 g, so banking cannot explain a 0.8 g gap. The human's 4.93 g
p99.9 is consistent with this car's independently measured ~4.7 g peak. The model
(`planner_alat` 27 + 0.0025·v²) allows 3.39 g at 180 km/h, about 3.13 g after `grip_scale`.
**The model under-calls real capability by roughly 30%.**

**2. But the bot never reaches its own model, so raising the model does not directly unlock
lateral grip.** `g_util = |meas_latg| / alat_max_g` over 152k clean-lap ticks:

| p50 | p90 | p99 | p99.9 | max | fraction > 1.0 |
|---|---|---|---|---|---|
| 0.537 | 0.763 | 0.814 | 0.840 | **0.872** | **0.00%** |

and p99 is 0.79-0.83 in *every* curvature band. That flat ceiling is not an active limiter, it is
arithmetic: lateral force scales with v², so a car running 13.4 km/h below a 159 km/h target
reaches (1 - 13.4/159)² ~= 0.84 of the grip its target implies. The number matches.

## The prediction

`planner_alat` 27 -> 30 has two paths, and only one of them is live:

- **via `v_curve` (corner speed target): INERT.** The car already fails to reach the current
  targets by 13.4 km/h. Raising them further changes nothing it can act on.
- **via `fc_frac` (in-corner throttle cap): LIVE but small.** `fc_frac = sqrt(1 - (a_lat/alat_max)²)`,
  so at 2.0 g lateral the cap rises from sqrt(1-(2/3.13)²) = 0.769 to sqrt(1-(2/3.70)²) = 0.841,
  about **+9% throttle in corners** — which is exactly where the earlier decomposition located
  the derate tax.

So: **J1 and J3 should produce a small improvement at most, arriving through the throttle path
rather than through corner speed. I do not predict a large win, and a large win would mean my
mechanism is wrong.** J1 is the cleaner read since J3 confounds it with a tightened combined
ceiling.

**J2 (`planner_alat` 24, `slip_target` 1.25) is the genuine unknown.** Nothing in this project has
ever tested *lowering* the demand. If the bot drives better against a reachable target than
against an impossible one, J2 wins and the whole framing of the last three days changes. If the
speed target is simply a ceiling the car is nowhere near, J2 loses about 0.5 s and the framing
holds.

## Falsification

- If J1 wins by more than ~0.4 s, the fc_frac path is not the mechanism and I have missed
  something.
- If J1 and J3 both lose, `planner_alat` joins the load-bearing list and the grip-model
  under-call is real but **unreachable**, which would mean the constraint is the throttle side
  and nothing else.
- If J2 wins, the "targets are right, delivery is wrong" conclusion from the human comparison is
  incomplete: the targets would be actively harmful rather than merely unreachable.
