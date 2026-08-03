# Feedforward throttle: structurally sound, lap-time neutral, and it falsifies my loop diagnosis

Run 08-02 19:34 to 23:35. Learner ON, each arm snapshotted, auto-revert.

| arm | median | delta | stalls | off% | sideslip p99 | derate rate | mean thr | spd-tgt |
|---|---|---|---|---|---|---|---|---|
| BASELINE | 29.86 | | 0 | 0.15 | 7.40 | 51.9% | 0.406 | -10.31 |
| **FF_030** (`ff_thr` 0.30) | **29.84** | **-0.02** | 0 | **0.09** | **7.30** | **48.3%** | 0.392 | -10.21 |
| FF_060 (`ff_thr` 0.60) | 30.14 | +0.29 | 0 | 0.08 | 7.40 | 49.0% | 0.347 | -10.96 |
| FF_030 + `ff_itrim` 0.60 | 29.89 | +0.04 | **3** | **0.63** | 7.50 | 50.9% | 0.402 | -10.52 |

## What the prediction got right and wrong

I predicted FF_030 would show **lower slip and HIGHER delivered throttle**, that combination being
the signature no tuning arm had produced. It delivered lower slip (`spin>1.5` 1.77% to 1.66%),
lower off-track (0.15% to 0.09%), less derating (51.9% to 48.3%) and a marginally smaller speed
deficit — with **lower** throttle (0.406 to 0.392) at identical lap time.

So the law does what it was designed to do mechanically. It just does not make the car faster.

## Why: the loop's weakest link, measured

The diagnosis was: bigger error -> more demand -> more slip -> deeper derate -> less throttle.
The middle arrow is nearly absent.

```
corr(drive_slip, pedal)       = -0.126
corr(drive_slip, |lateral g|) = +0.501
```

`drive_slip` is combined slip, so it tracks **cornering**, not throttle. Cutting throttle demand
therefore barely moves the derate: a 38% cut in demand (1.489 -> 0.850) bought only 3.6
percentage points of derate relief. The J1 chain that suggested the loop was monotonic and real,
but its throttle->slip gain is too small for the loop to be the binding constraint. **My
"one loop explains all eight failures" claim was too strong**; the loop exists and is weak.

## What the control arm proved

`ff_itrim` 0.25 -> 0.60 produced **3 stalls and 4x the off-track** at the same `ff_thr`. So the
integral bound is doing real work, and letting the integral re-supply the demand re-creates the
instability. That is the one clean positive result here: the bound is necessary, not cosmetic.

## Disposition

`ff_thr` stays **OFF**. -0.02 s is a wash, well inside the ~0.30 s floor, and the project rule is
that a wash does not ship. It is recorded as measured-neutral and available: same lap time, less
throttle, less derating, fewer excursions, no saturation. If the throttle path is ever revisited,
start from `ff_thr = 0.30, ff_itrim = 0.25` rather than from the legacy law.

## The standing count

**Eleven arms, no lap-time gain**: 5 single-axis relaxations, 3 joint-axis, 3 feedforward. The
bot sits at 29.84-29.98 through all of them, against a human 26.82 on the same car and track.

The throttle/limit/demand axis is exhausted. Nothing on it moves lap time, and the reasons are
now individually measured rather than assumed. What has never been tested is the **path**: every
arm so far changed how fast the car tries to go, none changed where it goes. The bot's realised
line, its corner entry geometry and its braking points remain untouched, and the earlier
finding that the bot drives the same-or-tighter line at 89% of the human's speed
(`HUMAN_VS_BOT_0802.md`) says the geometry is at least as good — which makes the entry/exit
*sequencing* of that geometry the remaining candidate.
