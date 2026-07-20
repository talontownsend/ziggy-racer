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

## Control-law lessons (constraints on future designs)

- **Compensate latency/braking with ONSET, never GAIN.** Raising `brk_ff` causes branch-chatter
  that halves delivered braking **(measured twice)**. Onset knobs: `bla_tau`, `t_ff`.
- **Never cap a corner EXIT.** Deficits compound down the following straight (-0.5 s/lap)
  **(measured)**.
- **Anticipate the onset, never move the setpoint.** Anticipated error must gate *entry* only,
  or every zone over-brakes by desc·τ **(measured, bla v1/v2)**.
- **Feedforward saturates:** `ffm_w` 0.15 is optimal, 0.30 strictly worse; reactive gains must
  shed as FF grows (`ffm_gsc`) **(measured)**.
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
