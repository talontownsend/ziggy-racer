# Night log, 2026-07-29/30

Farm resumed after a 9-day pause. Goal: close the gap to the human PB of 25.679 on the
current reference line, without breaking any CONSTRAINTS.md invariant.

## 21:26 Startup

- Reorganization regression found and fixed: `follow.py` imports `racing_line`
  (menger_curvature), which the cleanup had moved to `attic/`. The move-time check grepped a
  fixed module list instead of every local import. Full import-graph check is now clean, and
  `cand_grad.py` (a real dependency of `build_corridor*.py`) moved back to `tools/`.
- Health checks after the 9-day pause: steer to yawrate lag 196 ms tonight vs 196 ms on 07-20,
  so no silent game-update latency shift. Baseline lap times match the 07-20 record.

## Baseline A (shipped config, 28 laps)

    med 29.715   best 29.26   p25 29.52   p75 30.01   stalls 0   complex 11.60/11.47

Best baseline in project history, and it confirms the 07-20 record config survived the pause.

## FINDING: the human's lap speed was a hard ceiling on the bot

`vplan` (the reference lap's speed at each station) entered the target chain as

    tv       = braking-anticipated min over vplan
    target_v = min(tv * safety_eff, ...)      with safety = 1.0, so no derating at all

so the human's 27.28 s lap capped the bot's target everywhere. Measured on live telemetry:

- the human-plan branch was the **binding limiter 44% of ticks**, across 15 of 20 track blocks
- at **5 of 8 corner minima** it was the limiter *while the bot's own model allowed more*
  (+5 to +13 km/h; at the s432 hairpin the bot sat exactly on 55.9 km/h with its own model
  saying 65.3)
- when it bound, the bot's own `v_curve` was higher on 89% of those ticks, median +15.6 km/h

This violates CONSTRAINTS.md rule 3 (no human-derived operating bounds). The calibrated lap
model prices it at **+0.539 s/lap** (30.129 s free vs 30.668 s with the ceiling applied),
concentrated in the s412-443 hairpin complex, which matches the per-corner measurement.

### Fix: `v_own`, a self-derived speed profile

`v_own = sqrt(alat0 / (k - alat_k))` evaluated on the reference line's own curvature: the
identical closed form the live `v_curve` already uses, just precomputed over the whole lap so
it can serve the long-range braking anticipation too. The line stays the human's (the one
allowed exception in the register); the speeds become the bot's own. Validated against logged
`v_curve` at six corner minima, agreeing within ~1 km/h.

Two new hot keys, both defaulting to the old behaviour:
- `vown_w` 0..1, blend weight (0 = human plan, 1 = the bot's own model)
- `vown_raise` 1 = relaxation only, never target below the human plan

Not in the watchdog `$addKeys`, so any restart disarms them (dead-man switch, as intended).

## RULED OUT (cheaply, before spending farm time): the "model disagreement" theory

Where the human plan sits *above* the bot's own model, I expected late panic braking. Tested
on the baseline: corr(disagreement, speed-over-target) = **-0.045**, corr(disagreement, peak
brake) = **-0.085**, and at high-disagreement stations the car runs 8.6 km/h *below* target,
not above. Theory dead.

It also caught a trap worth more than the theory: at s285 the human drove **202 km/h** where
the bot's line-curvature model says only **130**. So on fast sections `v_own` is badly
conservative (line curvature noise), and a full blend (`vown_raise=0`) would have *slowed* the
car by 70 km/h in places. Raise-only is not just the safe choice, it is the correct one, and
the full-blend arm is cancelled rather than tested.
