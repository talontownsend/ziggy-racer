# Closed questions

Every hypothesis tested to a conclusion, so none of them is re-derived. Each row is backed by a
scored window or a structural argument, not an opinion. **Read this before proposing any change.**

Baseline through all of it: bot **29.84-30.48 s** median. Human **26.818 s** median / 26.207 best,
same car, same track, same morning (08-02, 48 clean laps). Gap **~3.25 s**.

## The one thing that worked

| change | result | why it was different |
|---|---|---|
| vtrim net clip + `vtrim_dmax = hi-lo` | **33.28 -> 29.88 s** | a broken component restored to spec, not a parameter improved |

The net had drifted so far outside its own output range (87.3% outside [0.80, 1.55]) that a
newly-bounded delta could no longer lift stations off the floor. Floor occupancy 3.5% -> 32.1%,
and via the 18 m window-MIN that suppressed targets across most of the lap.

## Closed by measurement: 24 arms, no lap-time gain

| axis | arms | outcome |
|---|---|---|
| limiter relaxations | 6 | all worse. Every guard is load-bearing |
| joint multi-axis tuning | 3 | all worse |
| feedforward throttle (`ff_thr`) | 3 | neutral at best; `ff_itrim` bound is load-bearing |
| throttle delivery, 3 mechanisms | 7 | all worse. Real delivery gain, larger stability cost |
| cte governor threshold (`cte_soft`) | 2 | worse; slowing earlier RAISED off-track 0.05 -> 2.24% |
| cross-track integrator leak | 2 | `\|cte\|` p90 improved 4.14 -> 2.99 m, lap time -0.02 s |

**The generalisation: every individual mechanism metric is improvable and none of them sets the
lap time.** Delivered pedal, speed-vs-target, derate footprint, over-range commands, cross-track
error and integrator staleness have each been moved in the intended direction under a targeted
change, verified per-tick, with the median lap unmoved.

## Closed without spending a window

| question | why it is closed |
|---|---|
| **The brake side** | `follow.py:1913` is `err >= 0 and (err_b >= 0 or err > 1.0)`, so the brake branch is reachable only at `err <= 1.0 m/s`. Max `err` on any of 59,205 brake ticks: **1.000000 m/s = 3.6 km/h**. The delivery-limited slice (>10 km/h, 2.223 s/lap, 67% of the gap) has **0.00%** of ticks braking. Structurally unreachable |
| **The path / reference line** | All five corners holding 51% of the gap are delivery-limited, so raising `v_curve` there is inert. A min-curvature solve in the corridor gains 6% and is worse at 22-27% of stations, and would invalidate the station-indexed learned map |
| **Front-driven throttle derate** | Looks wrong (front sets `drive_slip` on 89.1% of full-lock ticks; rear-only would allow 1.46x more pedal) but the car is **AWD**. Adding drive to a front tyre at combined slip 1.5 removes the lateral grip it is steering with. **Do not "fix" this** |
| **Per-axle grip model** | Front load predicts capability, but `corr(alat_max_g, susp_f) = +0.703` already; the front/rear SPLIT does not (unloaded 2.86 g vs loaded 2.80 g, and MORE understeer when loaded). The split measures braking, not grip |
| **Loop-timing regression** | Real (p999 17 -> 24 ms) but does NOT cost lap time: hitch-free laps median 30.300 s vs 30.280 s with hitches |

## Instrument defects found (four in one week)

| defect | consequence |
|---|---|
| `meas_long` never logged | every longitudinal conclusion came from single-tick `dv/dt`, which correlates **+0.291** with truth because `spd_kmh` is rounded to 0.1 km/h |
| `pad_thr` never read back | the `c_ubyte` throttle wrap was inferred, retracted, then re-confirmed from the device byte: **20.4% of mean pedal destroyed** |
| pedal-to-acceleration lag unmeasured | **111 ms**. Over-range episodes are also 111 ms, so unaligned comparison erases the effect entirely. This caused a correct finding to be retracted |
| per-corner channels never parsed | suspension travel (offset 68) and wheel speed (offset 100) unread; load inferred from one vertical accelerometer |

Only the first led anywhere, and even that produced no lap time once its consequences were tested
across seven arms.

## Gates that now exist

- `tools/vtrim_health.py`, stranded learned state (the 3.3 s defect's signature)
- `tools/loop_health.py`, control-loop tail latency
- `tools/joint_search.py`, multi-axis A/B with mechanism metrics, auto-revert, learner restore
- `tools/vtrim_refit_net.py`, refit the net to the CURRENT map, never the stored 07-03 labels

## What remains

The steering saturates for **34.4% of the lap**, and it is the cross-track PID doing it, not
curvature: `|ff|` exceeds 0.97 on **0.00%** of ticks, and **71%** of full-lock time is
PID-dominated at `|cte|` 2.53 m. The car is out of steering ANGLE (`kappa_max ~= 3.86 v^-1.294`),
not grip (`g_util` 0.685 while saturated). It has no authority in reserve when a slide starts,
which is why extra pedal escalates slides (p90 peak sideslip 8.7 -> 25.0 deg) without starting
more of them (1.28 -> 1.37 per 1000 ticks).

Every local remedy for that has been tried and lost. What has NOT been tried is a lateral law that
knows its own authority limit and stops commanding lock it cannot deliver. That is a redesign,
not an arm.
