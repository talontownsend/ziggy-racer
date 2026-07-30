# Night log, 2026-07-29/30

Farm resumed after a 9-day pause. Goal: close the gap to the human PB of 25.679 on the
current reference line, without breaking any CONSTRAINTS.md invariant.

**Outcome in one line:** no lap-time win was banked, because the 50-lap race ended at 22:03
and the event cannot be restarted without a human. What the night produced instead is a
corrected map of where the 3.36 s actually lives, three shipped bug fixes, and an armed
ladder that runs itself the moment the race is running again.

---

## 21:26 Startup and health checks

- **Reorganization regression, fixed.** `follow.py` imports `racing_line` (menger_curvature),
  which the cleanup had moved to `attic/`. The move-time check grepped a fixed module list
  instead of every local import. Full import-graph check is now clean; `cand_grad.py` (a real
  dependency of `build_corridor*.py`) also moved back to `tools/`.
- **No silent game change over the 9-day pause:** steer-to-yawrate lag 196 ms tonight vs
  196 ms on 07-20, and baseline lap times match the 07-20 record.

### Baseline A (shipped config, 28 laps) - best baseline in project history

    med 29.715   best 29.26   p25 29.52   p75 30.01   stalls 0   complex 11.60/11.47

---

## Where the 3.36 s actually is

Six independent analyses (plus my own) decomposed the gap. The decomposition below reconciles
exactly: bot mean 29.881 s vs the mean of the human's five fastest 26.526 s = 3.362 s, and the
sum of per-station dwell deltas = 3.3625 s.

| Phase | Seconds | Share | Bot vs human |
|---|---|---|---|
| APEX | 1.220 | 36% | 110.0 vs 122.8 km/h |
| EXIT | 1.141 | 34% | 158.0 vs 183.7 km/h |
| BRAKING | 0.602 | 18% | |
| ENTRY | 0.236 | 7% | |
| STRAIGHT | 0.164 | 5% | only 54 m of a 1071 m lap |

Two cross-cutting facts:
- **The bot drives a longer lap.** 1094.6 m vs the human's 1072.8 m (+21.8 m, +2.0%), worth
  ~0.72 s, confirmed two independent ways. It runs a mean 1.37 m outside the line in corners.
- **Grip is not the problem.** Bot corner utilisation 0.642 median of its own modelled ceiling
  vs the human's 0.661: a 1.9-point gap. The human does *not* exceed the bot's grip model.

**Methodological trap worth keeping:** per-station medians are not additive and inflate every
zone by ~1.6% (+0.479 s of phantom time). Earlier work in this project used them. Use mean dwell.

---

## THE THEME OF THE NIGHT: both pedals are muted below the tyres' own peak

Two derates, one on each pedal, both gate on **combined** slip (lateral included) with a
threshold set below where this car's tyres actually make peak force. They were found
independently, by different routes, and they are the same bug twice.

### Throttle: `slip_target = 1.05`

Found by two lenses that did not know of each other. The bot's own tyres peak at slip
**1.18-1.80**; p90 total g peaks in the 1.60-2.00 bin at **3.25 g** against **2.85 g** in the
1.05-1.30 bin (+14%). Estimated 0.44-1.04 s, central **0.6 s**. The code's own comment already
sanctions the retry: *"Any retry must keep a combined ceiling, just softer, e.g. derate from
~1.5 instead of 1.05."* There is a 07-03 precedent (full release caused power-oversteer), so
the armed test is 1.05 -> **1.35**, not a removal, with a tight abort.

### Brake: `LOCK_SLIP = 2.0`

This one is worse, because it is not measuring what it claims. `drive_slip` is combined slip,
so it fires as a **steering detector, not a lockup detector**. Measured over 19.6k braking ticks:

- when the derate fires, `|steer|` is **1.00** median, vs 0.76 when it does not
- it fires **53%** of full-lock braking time vs **14%** at low steer; corr(|steer|, slip) +0.48
- it is active **3.42 s of every lap** and cuts the pedal from a commanded ~0.66 to ~0.38

And the threshold has no physical basis: the bot's **own delivered deceleration is flat
(19.8-21.8 m/s²) from slip 0.5 through 3.0** - there is no lockup cliff anywhere near 2.0.
Cornering-load coupling is already handled separately by `brake_cap = max(fc_frac, 0.2)`, so
the combined term is redundant here.

Consequence chain, measured: weak delivered braking means the car arrives at turn-in far above
its own target (S11 +48.8 km/h, S9 +45.4 km/h), then pins the wheel and washes wide - which is
exactly the +21.8 m of extra path and the 1.22 s of apex loss.

Shipped: `brk_lock_slip` (threshold, default 2.0 = unchanged) and `brk_lock_mode` (0 = legacy
combined, 1 = the physically correct longitudinal lockup signal), plus a new `brake_lock` log
column so the longitudinal threshold can be calibrated from the bot's own data rather than guessed.

---

## The human speed ceiling: real, quantified, and load-bearing

`vplan` (the plan's speed field) entered the target chain as `target_v = min(tv * safety_eff, ...)`
with `safety = 1.0`, so it capped the bot everywhere. Measured:

- binding limiter on **44% of ticks**, and at **5 of 8 corner minima** while the bot's own model
  allowed +5 to +13 km/h more
- below the bot's own cap at **418/1000 stations**, median shortfall 19.7 km/h
- forces a decel demand on 10.03% of the lap, 0.73 s of which the bot's own cap would not ask for

**Provenance corrected** (I had this wrong, and so did the project's memory): the reference is
**not** a 27.28 s lap. It is the per-station **median of 48 flying laps** from the 06-25
recordings with the speed field scaled 1.043x, written 07-03. The 27.28 s artifact is the
retired `snapshots/refline_plan_v1_27s.npz`. Also settled: **no faster lap exists to rebuild
from** - the fastest lap on disk is 26.096 s and it is already one of the 48. The 25.679 PB was
never recorded.

### My fix, my bug, and the correction

`v_own` replaces the human speeds with the same closed form the live `v_curve` already uses,
evaluated on the reference line's curvature. I shipped it reading curvature **per station**,
but the live `v_curve` uses `max_kappa_line_ahead(18 m)` - the worst curvature in the next 18 m.
The station just before a corner is still straight, so my profile read **+23.7 km/h high**
(median; p90 error 89 km/h, corr 0.722). In the crest hazard spans it claimed 162 km/h where
the real cap is 131. Two arms ran at median **33.5** and **33.99 s** against a 29.72 s baseline
before I stopped them.

The 18 m window-min reproduces logged `v_curve` to **-1.5 km/h** median (corr 0.905) and agrees
with the human plan exactly where the hazards are, lifting only where there is real headroom
(40% of stations, median +18.8 km/h). Calibrated model: **-0.235 s/lap**, against -0.539 s for
removing the ceiling outright. Shipped default-off as `vown_w` / `vown_raise`.

**The honest reading:** the human speed field has been functioning as the bot's primary corner-
speed safety system, not merely as a bound. Removing it is correct in principle but only pays
once the self-model is trustworthy per station.

---

## The self-learned map was largely decorative

- **833 of 1000 stations sit at exactly the 1.55 ceiling** (p50 = p90 = max = 1.55); 32 at the floor.
- The persisted delta had wound to **+6.575** against that 1.55 bound.
- 94% of stations were never the active limiter, because the human ceiling capped below them -
  so the credit rule ran open-loop and the "learned" value there recorded nothing.

The pinned-station guard in `_vt_bump` is necessary but not sufficient: `vnet.step()`
generalizes every bump to similar stations, so net drift repeatedly un-pins a saturated station
and the delta ratchets. **Shipped:** a true anti-windup clamp on the integrator state
(`vtrim_dmax`, default 0.80). Behaviour-neutral today (1.0 + 0.8 still clips to 1.55) but the
delta becomes an honest record and the ratchet cannot recur.

**Ruled out cheaply:** the "model disagreement causes late panic braking" theory. corr = -0.045;
at high-disagreement stations the car runs 8.6 km/h *below* target, not above. Killed before it
cost farm time - and it caught that a full blend would have *slowed* the car by 70 km/h in places.

**Also worth knowing:** the simulator says removing `STEER_CAP` is worth -3.889 s, but that cap
is largely modelling fiction - the human's own recorded laps violate it at **287/1000 stations**
(ratio 1.19x p50, 1.45x p90). Do not chase it as if it were free time, and do not trust
candidate-vs-candidate line deltas under ~1.5 s in that model: it is extremely sensitive to
curvature noise.

---

## Infrastructure: two bugs that cost the night

**1. The watchdog could not see a dead farm.** The 50-lap race ended at 22:03 and the farm sat
dead for 90 minutes. The watchdog's staleness check used the log's `LastWriteTime`, and the
follower *touches* `follow_log.csv` periodically even while writing no telemetry rows - so the
timestamp kept resetting below the threshold and the check never fired. My own health monitor
used the same signal and was fooled identically. **Fixed:** the watchdog now tracks file
**growth**; if the log has not grown, the driver is not driving, whatever the timestamp says.

**2. Recovery could never confirm free roam.** The free-roam path needs 4 consecutive
confirmations, but `in_world` depends on `get_frame()`, and the follower owns UDP 7777 so
recovery's frame reads race against it. A missing frame was treated as evidence *against* free
roam and reset the counter - so with free roam confirmed on roughly 1 read in 4, the gate was
unreachable. **Fixed:** a missing frame is now no information; skip the tick, keep the count.
Verified live - recovery walked 1/4 -> 4/4 and opened EventLab for the first time tonight.

The EventLab **button-sequence** navigation still does not land the blueprint, so the race did
not restart. I deliberately did not improvise menu navigation: the code carries a hard guard
because a mis-tab into the Store opens a Steam purchase overlay, and that is not a thing to
gamble on unattended.

---

## What is armed for the morning

The moment the race is running, an armed background ladder detects it and runs itself, with
vtrim learning frozen (cuts left armed), state snapshotted, and the map restored between arms:

1. **`slip_target` 1.05 -> 1.35** - throttle mute, central estimate +0.6 s, zero code
2. **`brk_lock_slip` 2.0 -> 3.0** - brake mute, supported by the bot's own flat decel curve
3. **`vown_w` 1.0 raise-only** - corrected self-derived speed profile, model says +0.235 s

Every arm reverts itself, aborts on its own numeric trigger, and voids its window if the
follower restarts. All three keys default to today's exact behaviour, so a restart fails closed.
