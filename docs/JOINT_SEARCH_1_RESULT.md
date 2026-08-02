# Joint search plan 1: all three arms lost, and the pattern finally explains itself

Run 08-02 11:32 to 15:04. Learner ON throughout (rule 18), each arm snapshotted, auto-revert,
auto-restore when worse, auto-abort on median.

| arm | keys | median | delta | stalls | off% | sideslip p99 | mean thr | spd-tgt |
|---|---|---|---|---|---|---|---|---|
| BASELINE | | **29.98** | | 0 | 0.06 | 7.30 | 0.407 | -11.13 |
| J1 grip up | `planner_alat` 30, `spin_thr` 2.5 | 30.50 | +0.52 | 1 | 0.72 | **14.30** | 0.399 | -13.53 |
| J2 demand down | `planner_alat` 24, `slip_target` 1.25 | 31.64 | +1.66 | 2 | 0.36 | 7.60 | 0.398 | -10.55 |
| J3 grip up guarded | `planner_alat` 30, `slip_target` 0.90, `spin_thr` 2.5 | 30.18 | +0.20 | 0 | 0.38 | 10.60 | 0.387 | -12.01 |

J3's +0.20 s is inside the ~0.30 s measurement floor and should be read as a wash, not a loss.
J1 and J2 are real losses.

## Scoring the pre-registered prediction

[`PREDICTION_joint_plan_1.md`](PREDICTION_joint_plan_1.md), written before any arm reported:

- **"No large win."** CORRECT. Nothing gained; best case was a wash.
- **"`planner_alat` is inert via the corner-speed path."** **WRONG, and this is the finding.**
- **"`planner_alat` gives about +9% throttle in corners via `fc_frac`."** **WRONG in sign.** Mean
  commanded throttle *fell*: 0.407 -> 0.399 (J1) -> 0.387 (J3).
- **"J2 is the genuine unknown."** It was, and it lost 1.66 s. Lowering the demand made the car
  track better (`spd-tgt` improved to -10.55, the best of any arm) and simply slower
  (`lat_p99` 2.88, the lowest of any arm). The target is a ceiling the car is nowhere near, but
  lowering it still costs, so the current value is near-optimal on that axis.

## Why raising the grip model produced LESS throttle: a positive feedback loop

| arm | target error | spin > 1.5 | derate rate | `thr_cap` | delivered thr | sideslip p99 |
|---|---|---|---|---|---|---|
| BASELINE | -11.13 | 1.85% | 51.6% | 0.697 | 0.407 | 7.30 |
| J1 | **-13.53** | **2.39%** | **54.9%** | **0.679** | **0.399** | **14.30** |

Monotonic along the whole chain, and it closes on itself:

> raise the target -> the error grows -> `kp_thr · err` demands more throttle -> more throttle
> makes more slip -> more slip deepens the combined-slip derate -> the derate cuts delivered
> throttle -> **the error grows further**

This is a genuine destabilising loop in the control law, and it explains the entire record of
**eight consecutive failed relaxations**. The guards are not individually magic. The loop is
self-limiting: any extra demand or permission injected anywhere gets converted into slip and
then into derating, and comes back out as *less* delivered throttle plus more sliding. That is
why single-axis moves fail, and it is why joint moves fail too. The system is not sitting in a
local optimum that a cleverer search direction escapes. It is sitting at the fixed point of a
feedback loop.

## What this rules in

The throttle law is pure feedback with no feedforward:

```
desired = kp_thr * err + thr_i          # err = target_v - spd
desired = min(desired, thr_cap)
throttle = min(desired, throttle + thr_rate)
```

With a 13.4 km/h standing deficit, `kp_thr · err = 0.4 * 3.7 = 1.49` before the integral, so
`desired` is saturated essentially always and the pedal is shaped entirely by `thr_cap`. The
controller is not asking for the acceleration the tyres can deliver; it is asking for whatever
the error implies, which is always "everything", and then a stack of caps argues it back down.

The structural fix follows directly and matches a lesson this project already learned on the
brake side: **compensate with feedforward and onset, never with gain.** A throttle law of the
form "command the longitudinal acceleration the grip budget currently allows, then trim with a
small feedback term" cannot enter this loop, because its demand does not scale with the error.

That is the next project. It is a controller-architecture change, not a tuning arm, and no
further knob-turning should be attempted before it. Tuning is exhausted: 8 for 8.
