# Night log, 2026-07-29/30

**Bottom line:** no lap-time win was banked. The 50-lap race ended at ~22:03, and the
auto-restart came back with **the wrong car**, so there was no valid platform to measure on for
most of the night. What the night produced instead is a corrected and reconciled map of where
the 3.36 s actually lives, **seven shipped fixes** (three of them bugs that were silently
costing lap time, four protecting future unattended runs), and a car-gated ladder that runs
itself as soon as the Tacoma is back.

**What you need to do (about 60 seconds):** put the Tacoma back on, start the 50-lap
Shimanoyama event, then run:

```bash
bash tools/morning_ladder.sh
```

It starts the watchdog, refuses to proceed unless the car fingerprint matches, freezes the
learner, snapshots the map, and runs four arms back to back with self-executing aborts. Nothing
is armed right now; the farm is stopped and the config is the known-good 07-20 record stack.

---

## Baseline A - the best baseline in project history

    med 29.715   best 29.26   p25 29.52   p75 30.01   stalls 0   (28 laps)

Health checks after the 9-day pause were clean: steer-to-yawrate lag 196 ms tonight vs 196 ms on
07-20, so no silent game-update latency shift.

---

## Where the 3.36 s actually is

This decomposition reconciles exactly (sum of per-station dwell deltas = 3.3625 s against a
measured 3.362 s gap), which none of the project's earlier decompositions did.

| Phase | Seconds | Share | Bot vs human |
|---|---|---|---|
| APEX | 1.220 | 36% | 110.0 vs 122.8 km/h |
| EXIT | 1.141 | 34% | 158.0 vs 183.7 km/h |
| BRAKING | 0.602 | 18% | |
| ENTRY | 0.236 | 7% | |
| STRAIGHT | 0.164 | 5% | only 54 m of a 1071 m lap |

- **The bot drives a longer lap:** 1094.6 m vs 1072.8 m (+21.8 m, +2.0%), worth ~0.72 s,
  confirmed two independent ways. It runs a mean 1.37 m outside the line in corners.
- **Grip is not the problem.** Bot corner utilisation 0.642 of its own modelled ceiling vs the
  human's 0.661. The human does *not* exceed the bot's grip model. Stop chasing grip.
- **Methodological trap:** per-station *medians* are not additive and inflate every zone by
  ~1.6% (+0.479 s of phantom time). Earlier work here used them. Use mean dwell.

---

## The three bugs that were costing lap time

### 1. `plan_degraded` was braking on straights with 93% of grip unused (real, but small)

When no feasible merge exists, `target_v` was clamped to exactly `spd`. That makes `err == 0`,
which drives the brake-onset anticipation negative and drops the controller into a brake branch
whose own braking lowers the target further and self-sustains.

Verified on 60,780 racing ticks: fires **4.30% of the time (~90 ticks/lap)**, applies brake on
**88%** of those ticks at a median **175 km/h** (p90 204) - with median `fc_frac` **0.930**, so
the car has nearly all its longitudinal grip in hand. The trigger is a merge-*curvature*
feasibility test (`klim ~ a_lat/v²`, so a 1-2 m offset reads "infeasible" above 200 km/h), not a
grip test. That makes it a speed cap on corner exits and straights, which METHODOLOGY forbids
outright. One-line fix using the cure already proven for the rejoin coast-lock. Key `pdg_gain`.

**Sizing correction.** The analysis that surfaced this priced it at +0.65 s and I nearly made it
arm 1 on that basis. My own direct measurement disagrees: 5.2 episodes/lap, median 0.17 s each,
median in-episode speed drop 4.6 km/h, first-order cost **0.027 s/lap** (excluding re-accel, so a
lower bound - call it 0.05-0.15 s realistically). That is **at or below the 0.09 s resolution** of
a 40-minute scored window, so it can never be cleanly measured on its own. It is a correctness fix
worth shipping, not a headline win, and it rides along in the combined arm rather than burning a
window. Left default-off (`pdg_gain = 0.0`) pending that.

### 2. Both pedals are muted below the tyres' own peak

The same bug twice: a derate gating on **combined** slip (lateral included) with a threshold
below where this car's tyres actually make peak force.

- **Throttle** (`slip_target = 1.05`): the bot's own tyres peak at slip **1.18-1.80**; p90 total
  g peaks at **3.25 g** in the 1.60-2.00 bin vs **2.85 g** at 1.05-1.30 (+14%). Worth 0.44-1.04 s.
  Two analyses found this independently. The code's own comment already sanctions the retry
  ("derate from ~1.5 instead of 1.05"), and there is a 07-03 power-oversteer precedent, so the
  armed test is 1.05 -> **1.35**, never removal, with a tight abort.
- **Brake** (`LOCK_SLIP = 2.0`): worse, because it is not measuring what it claims. Over 19.6k
  braking ticks, when it fires `|steer|` is **1.00** median vs 0.76 when it does not; it fires
  **53%** of full-lock braking time vs **14%** at low steer. It is a **steering detector, not a
  lockup detector**, active **3.42 s/lap**, cutting the pedal from ~0.66 commanded to ~0.38.
  And the threshold has no physical basis: the bot's own delivered deceleration is **flat
  (19.8-21.8 m/s²) from slip 0.5 through 3.0**. Keys `brk_lock_slip`, `brk_lock_mode`.

This chain explains the shape of the gap: weak braking means the car arrives at turn-in +45 to
+49 km/h over target, washes wide, and spends the +21.8 m of extra path.

### 3. The human's lap speed was a hard ceiling (and is load-bearing)

`vplan` entered the target chain with `safety = 1.0`, so it capped the bot everywhere: binding
limiter on **44% of ticks**, at **5 of 8 corner minima**, and below the bot's own cap at
**418/1000 stations** (median shortfall 19.7 km/h). That is a CONSTRAINTS rule-3 violation and
it is now in the exceptions register with an exit path.

**Provenance corrected** (the project's memory had this wrong, and it misled me): the reference
is **not** a 27.28 s lap. It is the per-station **median of 48 flying laps** with the speed field
scaled 1.043x, written 07-03. Also settled: **no faster lap exists to rebuild from** - the
fastest on disk is 26.096 s and it is already one of the 48.

**My own bug, and the correction.** I shipped `v_own` reading curvature *per station*, but the
live `v_curve` uses `max_kappa_line_ahead(18 m)`. The station before a corner is still straight,
so my profile read **+23.7 km/h high** (p90 error 89 km/h) and claimed 162 km/h in the crest
hazards where the real cap is 131. Two arms ran at **33.5** and **33.99 s** against a 29.72 s
baseline before I stopped them. The 18 m window-min reproduces logged `v_curve` to **-1.5 km/h**
(corr 0.905) and agrees with the human plan exactly where the hazards are. Model: **-0.235 s**.

The honest reading: the human speed field has been doing the bot's corner-speed *safety* job,
not merely bounding it. Removing it is right in principle, but only once the self-model is
trustworthy per station.

---

## The self-learned map was largely decorative

**833 of 1000 stations sit at exactly the 1.55 ceiling**, and the persisted delta had wound to
**+6.575** against that bound. 94% of stations were never the active limiter, because the human
ceiling capped below them - so the credit rule ran open-loop and recorded nothing.

The existing pinned-station guard is necessary but not sufficient: `vnet.step()` generalizes
every bump to similar stations, so net drift repeatedly un-pins a saturated station and the
delta ratchets. **Shipped:** a true anti-windup clamp on the integrator state (`vtrim_dmax`),
behaviour-neutral today but the ratchet cannot recur.

**Ruled out cheaply, before spending farm time:** the "model disagreement causes late panic
braking" theory (corr -0.045; the car runs 8.6 km/h *below* target there). It also caught that a
full blend would have *slowed* the car by 70 km/h in places.

**Do not chase:** `STEER_CAP` removal scores -3.889 s in the simulator but is largely modelling
fiction - the human's own laps violate that cap at **287/1000 stations** (ratio 1.19x p50). And
do not trust candidate-vs-candidate line deltas under ~1.5 s in that model; it is extremely
sensitive to curvature noise.

---

## What went wrong operationally, and the four fixes

1. **Wrong car, undetected.** The EventLab auto-restart came back with a **Nissan Skyline**
   (max_rpm 11000) instead of the Tacoma (8000), and vtrim learned on it for ~7 minutes, moving
   **645 stations by up to 0.75** before I caught it by eye in a screenshot. The map was restored
   from a 21:52 snapshot; the contaminated copy is kept as
   `snapshots/vtrim_map_WRONGCAR_contaminated.npz`. **Shipped:** a car-identity guard - on a
   max_rpm mismatch it freezes learning and shouts, but keeps driving (an AFK farm still earns,
   and the map is the irreplaceable asset). Unit-tested against tonight's real values.
2. **Liveness judged by mtime, which lies.** At 22:08 the log's `LastWriteTime` read 91 s old
   while its rows had been frozen since 22:03: the follower touches the file without writing
   rows. **Shipped:** the watchdog now tracks file **growth**. Verified firing correctly at 22:11
   and 22:20. *(An earlier draft of this log said this cost 90 minutes. It did not - I was
   mis-tracking wall-clock time across long waits. The weakness is real; it was not the expensive
   part of the night.)*
3. **Recovery could never confirm free roam.** The path needs 4 consecutive confirmations, but a
   missing telemetry frame (recovery races the follower for UDP 7777) was treated as evidence
   *against* free roam and reset the counter - so with free roam confirmed on ~1 read in 4, the
   gate was unreachable. **Shipped:** a missing frame is no information; skip, keep the count.
   Verified live: recovery walked 1/4 -> 4/4 and opened EventLab for the first time.
4. **Two reorganization regressions.** `follow.py` imports `racing_line`, which the cleanup had
   moved to `attic/` (the follower would not start). And every tool importing a root module broke,
   because Python puts the *script's* directory on `sys.path`, not the cwd - both project
   self-tests were casualties. Both fixed; all tools compile and both self-tests pass.

**I deliberately did not hand-navigate the game menus** to put the Tacoma back. This codebase
carries a hard guard because a mis-tab into the Store has opened a Steam purchase overlay before,
and that is not a risk worth taking unsupervised on your machine.

---

## Backlog, ranked by risk-adjusted value

Armed in `tools/morning_ladder.sh` (in order): **slip_target 1.35**, **brk_lock_slip 3.0**,
**vown_w 1.0**, then a combined arm carrying whatever won plus `pdg_gain`. Ordered by expected
value *relative to the 0.09 s measurement floor*, not by raw estimate.

Next best, not yet built: self-calibrated peak-grip slip table replacing the `slip_target`
literal (+0.44); decouple speed-path curvature from steering-FF curvature (+0.39); shorten the
shift lift (+0.40); brake-release onset to front-load the car at turn-in (+0.35); rebuild the
reference line as a curvature-continuous spline (+0.27).

Explicit negatives worth remembering: do **not** raise `planner_alat`, `vtrim_hi`, or the load
exponent; do **not** swap the reference line; do **not** add steering gain or feedforward; and do
not pursue grip, power, or braking capability increases at the current operating point.
