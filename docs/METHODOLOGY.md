# Experimental Methodology & Engineering Notes

The working rules for testing and changing the controller, plus lessons that constrain future
designs. (The program's hard requirements live in CONSTRAINTS.md; this is *how we work on it*.)
Rules marked **(measured)** were established by a specific experiment.

## A/B testing rules

1. **Never A/B over a live learner.** Freeze vtrim for scored windows (`vtrim_up/dn/cut/netscale=0`
   **with `vtrim_on=1`**; note that `vtrim_on=0` removes the map's boost instead of freezing it), or
   compare long equilibria.
2. **~30 min re-equilibration after any config change.** Short windows measure the transient
   (S11 re-carves after every zone change) **(measured)**.
3. **Calibrate thresholds on the current config before using them as aborts.** Healthy production
   reads 5.3-6.2/s on the steer-reversal metric; an uncalibrated 4.5/s tripwire false-aborted a
   good rung **(measured)**.
4. **Abort monitors must ACT:** they write the rollback key themselves, never just print a verdict
   (a print-only "HARD ABORT" once let a failed arm run 40 minutes).
5. **Compare condition-matched, never aggregate.** Aggregate decel medians "changed -8%" after a
   game update; speed-matched bins showed ±1 m/s² **(measured)**. Match κ/v/load/brake for
   steering probes.
6. **Fresh windows, session-aware scans.** Cumulative windows double-count old bad periods;
   follower restarts reset `t` in the log; watchdog restarts silently disarm hot keys mid-window
   (log effective-state columns; a restarted window is void).
7. **Dedupe event counts** (wedge episodes multi-count within ~60 s).
8. **ABAB discipline.** A washout that beats both arms means session drift, not a win
   **(caught the BC-blend "gains")**.
9. **Frozen-map arms overstate downstream breakage.** The deployed learner absorbs new arrival
   speeds by design; judge frozen arms in-zone, validate downstream with learning on **(measured)**.

10. **Per-station MEDIANS are not additive.** Summing per-station median dwell inflates every
    zone by about 1.6% (+0.479 s of phantom time on this lap) and will not reconcile against the
    real lap-time gap. Use MEAN dwell for any decomposition that has to add up **(measured 07-29;
    earlier work in this project used medians)**.
11. **Judge farm liveness by log GROWTH, not file mtime.** The follower touches follow_log.csv
    periodically while writing no telemetry rows, so a mtime-based staleness check reads healthy
    through a completely dead farm **(measured 07-29: 90 minutes lost, watchdog and a purpose-built
    monitor both fooled)**.
12. **A missing measurement is not a negative measurement.** Recovery treated a dropped telemetry
    frame as evidence against free roam and reset its confirmation counter, making the gate
    unreachable **(measured 07-29)**. Any N-consecutive-confirmations gate must treat "no data" as
    a skip, not a reset.

13. **One long incident can masquerade as a config regression.** A stuck car parked off-track
    contributes thousands of samples at speed 0, which dragged an apparent "median 33 s vs the
    29.7 s baseline" and "on_track 79% vs 99.9%" - while the clean laps either side of it ran
    cte 0.23 m at 100% on-track **(measured 08-01)**. Always split per-lap before believing an
    aggregate got worse.

14. **A carved vtrim pocket damages ~18 m UPSTREAM of itself, not just itself.** `map_w` is a
    window-MIN over the next 18 m, so a handful of stations driven to the 0.80 floor pull the
    target down for every station that can see them. Measured 08-01: stations 300-305 at the
    floor dragged the target at station 294 from 217 to 119 km/h - predicted 118.9, observed
    118.9 - and 37% of the lap ended up >10 km/h down, worth **+3.24 s**. When judging map
    damage, look at the WINDOW-MIN, never the per-station value: at station 294 the map itself
    still read 1.550.

15. **A code bisect cannot exonerate code when learned state persists across the revert.**
    Running the 29.72 s commit's `follow.py` scored 33.00 and I read it as "the regression is
    environmental", which sent the search into game settings and hardware for hours. The damage
    was in `recordings/vtrim_*.npz`, which `git checkout` does not touch **(measured 08-01)**.
    Bisect the *state* alongside the code, or the arm is not what it claims to be.

16. **`git checkout <commit> -- <path>` writes the INDEX too**, so a later
    `git checkout -- <path>` restores the bisect version rather than HEAD. Restore with
    `git checkout HEAD -- <path>` and verify by **content** (`md5sum`, or grep for a line the
    revision does or does not contain). `git log -1 -- <path>` reports the last commit that
    *touched* the file and proves nothing about what is on disk **(cost 1 h of wrong-code
    running, 08-01)**.

17. **Match steady state before comparing plant response.** Yaw-per-steer at matched speed
    appeared 26% down, which reads exactly like an assist change. Restricting to steer held
    within 0.05 and speed within 3 km/h across a 280 ms window, the two eras were identical
    (ratio 1.02 and 1.00 at full lock). The unsettled comparison was measuring the bot's own
    changed behaviour distribution **(measured 08-01)**. Rule 5 applies to the *settling state*,
    not just to κ/v/load.

18. **Never freeze the layer that compensates for the change under test.** `pad_clamp` alters
    how much acceleration the car can actually deliver, so every arrival speed downstream moves.
    Scored over a frozen vtrim it read 33.31 s with 4.25% off-track; the learner had no way to
    re-carve the corners the car now reaches faster **(measured 08-02)**. Rule 9 already said
    frozen arms overstate breakage; the sharper form is that a frozen arm is not merely
    pessimistic but *invalid* when the change moves the plant the frozen layer was fitted to.

19. **Verify the actuator, not just the controller.** Nine percent of ticks commanded
    `throttle > 1.0`, which `vgamepad` wrote into a ctypes `c_ubyte` that wraps mod 256, so a
    commanded 1.002 is delivered as 0.024 and 1.06-1.30 as 0.110 - confirmed from the device
    byte itself (`pad_thr`), not inferred: 20.4% of the average pedal destroyed, worth **-5.87
    m/s2** once lag-aligned. It was invisible in every log because the log recorded only the
    *commanded* value **(measured 08-02, see WRAP_GROUND_TRUTH_0802.md)**. Log commanded and delivered separately, and range-check anything
    crossing an FFI boundary: ctypes does not raise on overflow.

20. **Never derive a quantity the telemetry already carries.** `meas_long` (car-local
    longitudinal acceleration) sat unlogged in the packet for months while every longitudinal
    conclusion was drawn from single-tick `dv/dt`. Because `spd_kmh` is logged rounded to
    0.1 km/h, that estimator moves in ~2 m/s^2 steps at 72 Hz and correlates only **+0.291** with
    the real channel (+0.945 when smoothed over 200 ms). Its *median* snaps between quantisation
    levels, so it manufactures large, clean-looking, wrong deltas **(measured 08-02)**.

21. **Lag-align before relating an input to a response.** Pedal to longitudinal acceleration is
    **111 ms** (corr +0.718 at 8 ticks, +0.492 unaligned). Over-range throttle episodes have a
    median length of 111 ms, exactly the lag, so an unaligned comparison measures the
    acceleration the car is still carrying from *before* the episode and the effect vanishes
    entirely. This caused me to retract a correct finding **(measured 08-02)**. The steering side
    has its own measured lag of 196 ms; neither is optional.

22. **When two solid measurements disagree, instrument the disputed quantity instead of
    generating hypotheses.** Code inspection said the pad byte must wrap; the car said it did
    not. I proposed the wrong interpreter, a different vgamepad version, and lag-smoothed brief
    episodes. Logging `gp.report.bRightTrigger` directly settled it in ten minutes and showed the
    reconstruction was right on 99.6% of ticks **(08-02)**. Read back what the device actually
    received; never assume the write took the value you passed.

23. **Validate the lap detector before trusting a single lap time.** `lap_no` is NOT unique
    within a follower session: the event restarts and numbering begins again, so keying laps by
    `(session, lap_no)` merged ~4 real laps per group and reported `max(lap_t)` across them.
    `ab_arm.py` did this from the beginning, which put **+0.71 s on the median and +0.48 s on
    the best**, and reported 50 laps where 211 existed. Every median in docs/ dated before
    2026-08-06 is on the inflated scale, and the bias varies per log with how often the event
    restarted, so cross-log comparisons on the old scale are unreliable in both directions.
    The check that catches it costs nothing: **ticks per detected lap**. A 30 s lap at 69 Hz is
    ~2070 ticks; the groups held 9153. Any detector whose laps contain several times the
    expected number of samples is merging laps. Segment on `lap_t` resets, require the run to
    begin at `lap_t<0.5` and end at a reset, and print the rejection reasons **(08-06)**.

24. **A stricter filter is not automatically a better one.** Replacing the reset detector with
    a "strict" `lap_no`-keyed one that demanded start-line, rollover and on-track evidence felt
    more rigorous and was measurably worse: it inherited the merge bias its extra conditions
    could not see. The original detector had agreed with truth to 0.01 s. Rank detectors by
    agreement with an independent measurement, never by how many conditions they impose
    **(08-06)**.

## Control-law lessons (constraints on future designs)

- **Compensate latency/braking with ONSET, never GAIN.** Raising `brk_ff` causes branch-chatter
  that halves delivered braking **(measured twice)**. Onset knobs: `bla_tau`, `t_ff`.
- **Never cap a corner EXIT.** Deficits compound down the following straight (-0.5 s/lap)
  **(measured)**.
- **Anticipate the onset, never move the setpoint.** Anticipated error must gate *entry* only,
  or every zone over-brakes by desc·τ **(measured, bla v1/v2)**.
- **Feedforward saturates:** `ffm_w` 0.15 is optimal, 0.30 strictly worse; reactive gains must
  shed as FF grows (`ffm_gsc`) **(measured)**.
- **Check a derate's SIGNAL before its threshold.** Both pedal slip derates gate on COMBINED
  slip (lateral included), so the brake one fires as a steering detector: at full lock it trips
  53% of braking time with no wheel lockup, cutting the pedal from 0.66 to 0.38 for 3.42 s/lap
  **(measured 07-29)**. And both thresholds sit below where this car's tyres make peak force.
- **A long-range profile must use the same window as the short-range cap it feeds.** `v_curve`
  uses `max_kappa_line_ahead(18 m)`; reading curvature per station instead reads +23.7 km/h high
  (p90 error 89 km/h) because the station before a corner is still straight **(measured 07-29,
  cost two arms at 33.5 s)**.
- **Full stick = front tires at their limit** (game speed-sensitive steering); `fc_frac` is
  total grip and stays submaximal in understeer, so "add steering authority" framings are wrong.

## Working prior: the conservative-looking limiters are load-bearing

Five independent relaxations have now been proposed from static analysis and **all five measured
worse in the car** (50 scored laps each, non-overlapping IQRs):

| relaxation | paper argument | measured |
|---|---|---|
| remove the human speed ceiling (`vown_w` 1.0) | it caps below the bot's own model at 418/1000 stations | **+0.90 s** |
| `slip_target` 1.05 -> 1.35 | tyres peak at slip 1.18-1.80 | **0 -> 4 stalls / 15 min** |
| `brk_lock_slip` 2.0 -> 3.0 | delivered decel is flat to slip 3.0 | **+1.12 s** |
| `pad_clamp` 1.0 (deliver the full commanded pedal) | 22.4% of average pedal is destroyed by a `c_ubyte` wrap | **+0.7 s, 8 stalls, off-track 0.20 -> 4.25%** |
| `slip_target` 1.05 -> 1.50 **with** `spin_thr` 1.5 | the derate is a steering detector: it fires on 44.3% of the lap for a 1.58x sideslip-risk lift, and on 83% of full-lock ticks, while the car sits 21 km/h below target | **+4.6 s, off-track 0.74 -> 2.21%, sideslip p99 7.5 -> 17.4** |

**The fifth one is the most instructive, because the analysis behind it was correct and the
conclusion still wrong.** `drive_slip` really is steering-correlated (r = +0.372 vs +0.005 for
the longitudinal-only `drive_spin`), and the shipped threshold really does tax 44% of the lap for
almost no measured safety return. But relaxing it produced **more** wheelspin, not less:
`drive_spin > 1.5` went 2.02% -> 4.82% of ticks. Derating throttle in proportion to *total* tyre
load is friction-circle physics, not a mis-fire: you cannot spend grip laterally and
longitudinally at once. `fc_frac` already does this against the *modelled* grip ellipse; the
combined-slip term does it against the *measured* tyre state and catches what the model misses.
**"Signal X correlates with steering" is not evidence that a throttle limiter is mis-targeted.
For a friction-circle-aware limiter, that correlation is the intended behaviour.**

The tyre-data arguments were not wrong about the tyres; they were wrong about the consequence.
Extra slip goes into rotation rather than drive, deeper brake slip lengthens the stop, and the
human speed field encodes corner knowledge the curvature model does not have. **Treat any
"this limiter is too conservative" finding as a hypothesis with a poor prior until it survives
a scored window.** The remaining lap time is not sitting behind these limits.

Corollary on the lap model: it predicted the `vown` arm would GAIN 0.235 s and it lost 0.90 s -
**wrong in sign**. `tools/line_opt_solver.py` is trustworthy for "what does this constraint set
imply" and not for "what will this control change do"; it has no representation of how the
tracker behaves when targets move.

## Measured artifacts and validity envelopes

| Artifact | What | Envelope / caveats |
|---|---|---|
| `recordings/steer_ff_map.npz` | \|stick\| for (κ,v), fit from bot telemetry | Steady/flat/no-brake fit; runtime-gated off under braking & light load; latency-independent (survived the 07-13 update). Rebuild: git log `3374e97`. |
| `recordings/vtrim_*.npz` | self-learned per-station speed map | Operating rates `0.0002/0.002/0.03`; faster re-earn is a churn-recovery crutch only (erodes learned protection as a standing rate). |
| Grip model (follow.py) | measured a_lat + downforce + load + friction circle | Total-grip; does not resolve front/rear axle. |
| Pedal-decel curve | full pedal ≈ 26-28 m/s² | Speed-matched comparisons only. |
| `tools/line_opt_solver.py` model | offline lap-time simulator | Calibrated within 0.05 s of the bot's real median (07-20); use for what-ifs before burning farm time. |

## Post-game-update checklist

See OPERATIONS.md §5. The one non-obvious probe: **steer→yawrate cross-correlation lag**, the
only test that catches input-pipeline latency changes (07-13: +28 ms with zero physics/settings
changes; every physics probe read clean).
