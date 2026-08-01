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
