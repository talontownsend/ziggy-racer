# The lost pedal cannot be returned: seven arms, three mechanisms, one answer

## The defect is real, confirmed from the device byte

`vgamepad` writes `round(v*255)` into a ctypes `c_ubyte` that wraps mod 256. Read back from
`gp.report.bRightTrigger`: commanded 1.00-1.06 arrives as **0.0235**, 1.06-1.30 as **0.1098**.
Overall **0.3922 commanded, 0.3120 delivered: 20.4% destroyed**, worth **-5.87 m/s²** once
lag-aligned by the measured 111 ms.

It fires exactly where the car needs it. On the 36.9% of the lap that is plan-bound, more than
10 km/h below target and not braking, **22% of ticks are wrapped** (commanded 1.080 → delivered
0.082) and the mean pedal lost there is **25.2% of commanded**.

And the cause is understood: `thr_cap = max_throttle · fc_frac · slip_frac · grip_scale` exceeds
1.0 only when `grip_scale ≈ 1.4`, i.e. `load_factor ≈ 1.65`. **The command runs past full pedal
only under heavy transient compression.**

## Three different ways to return it. Same answer every time.

| mechanism | what it delivers | median | stalls | off% | sideslip p99 | spd-tgt |
|---|---|---|---|---|---|---|
| baseline (wrap active) | wrapped near-zero | **30.01** | 2 | 0.85 | **7.50** | -10.09 |
| `pad_clamp` (deliver in full) | 1.000 | 31.10 | 11 | 3.54 | 22.00 | -9.26 |
| `pad_clamp` + `spin_thr` 2.5 | 1.000, guarded | 30.14 | 5 | 2.58 | 15.50 | -7.78 |
| `pad_clamp` + `spin_thr` 1.5 / 1.0 | 1.000, guarded harder | 31.02 / 30.69 | 7 / 6 | 2.60 / 2.50 | 15.40 / 14.90 | -8.80 / -8.44 |
| `gs_max` at source | cap + shrunken lateral model | 32.41 | 3 | 1.92 | 15.70 | -9.32 |
| **`gs_max` on `thr_cap` only** | **capped at fc_frac, lateral model intact** | **30.75** | **9** | **3.60** | **19.40** | **-8.77** |

The last row is the clean test, and its mechanism metrics are perfect: over-range commands
**6.11% → 0.01%**, mean delivered pedal **0.3234 → 0.3336**, speed-vs-target **-10.09 → -8.77**.
Everything the design predicted happened. The car destabilised anyway.

**The delivery gain is consistently real and consistently smaller than the stability cost.** The
best speed-vs-target ever measured on this bot (-7.78) came from an arm that lost 0.30 s.

## What that means

The wrap is not why the bot is slow. It is closer to the reverse: a chaotic 20% throttle cut is
currently holding the car inside its stability envelope, and every principled replacement for it
— full delivery, guarded delivery, friction-circle-capped delivery — puts the car outside that
envelope faster than it gains speed.

So the binding constraint is **not longitudinal authority**. The car already commands more
throttle than it can hold. The constraint is whatever fails when that throttle is delivered:
sideslip p99 goes 7.5 → 15-22 in every arm, and no longitudinal guard reaches it (`spin_thr`
plateaus at ~15 across 2.5/1.5/1.0).

That is a **lateral/stability control** problem, and it is the one major subsystem this project
has never attacked. The steering law has a feedforward map (`ffm`) and a PID on cross-track, but
nothing that manages the car's stability margin as a function of delivered power.

## Standing count

**Twenty arms, no lap-time gain.** Five single-axis relaxations, three joint-axis, three
feedforward, seven throttle-restoration, plus the path route (inert by decomposition) and the
brake side (unreachable by construction). Relaxation prior: 0 for 6.

The bot sits at 29.84-30.29 against a human 26.82 on the same car, track and morning.
