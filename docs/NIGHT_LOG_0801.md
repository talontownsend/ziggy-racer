# Night log, 08-01 into 08-02

## Bottom line

**The 3.3 s regression is fixed and the cause is understood.** It was not the game, the car, the
drivers or the settings. The vtrim net had drifted outside the range its own output can occupy,
and the anti-windup bound I added on 07-29 then stopped the correction term from lifting stations
off the floor, producing a downward-only ratchet. Floor occupancy had gone 3.5% to 32.1%, and
because `map_w` is an 18 m window-MIN that suppressed targets across most of the lap.

| window | median | best | stalls |
|---|---|---|---|
| where the night started | 33.28 | 32.78 | 0 |
| after the net-clip fix | 30.27 | 29.29 | 1 |
| after the map settled | 30.12 | 29.35 | 1 |
| **frozen baseline (current state)** | **29.88** | **29.39** | **0** |
| 07-29 reference | 29.72 | | 0 |

**A second, larger defect was found and is NOT fixed, deliberately.** `vgamepad` writes throttle
into a ctypes `c_ubyte` with no bound check, and ctypes wraps mod 256 in silence. The controller
commands `throttle > 1.0` on 9.04% of ticks, so a commanded 1.002 was delivered as **0.000**
pedal. That is about 10 m/s2 of missing drive on a tenth of every lap. Repairing it made the car
*slower and much less stable* (30.62 s and 8 stalls after 70 minutes of adaptation, against
29.88 s and 0 stalls), because every limit and the whole learned map are calibrated to the
weakened plant. It is left off, with the analysis and a staged plan for using it properly.

**Nothing has been pushed.** All work is in local commits for review.

---

Two things were settled tonight. The focus diagnosis from 07-31 was wrong, and the ~3.3 s
regression that had survived nine straight exoneration tests was found. Both corrections came
from tests that could have gone the other way, which is the only reason to trust them.

## 1. The focus diagnosis was wrong (user was right)

07-31 concluded that `TextInputHost.exe` was stealing the foreground and pausing the game, and
shipped a kill for it into the watchdog. The user pushed back: *"you haven't considered what
happens when computer use is turned on/off."*

The controlled test (`tools/focus_watch.ps1`, foreground owner sampled every 5 s):

| window | computer use in session | result |
|---|---|---|
| 35 min hands-off, 08-01 21:31 to 22:06 | never activated | 146,727 rows, 50 laps, 0 stalls, FH6 held foreground throughout, TextInputHost took it **zero** times |
| same hands-off test, 07-31 | had been activated | 0 laps |

The only foreground steal the instrument ever caught was `fg=claude`, the Claude desktop app,
at the moment tool calls were being issued. TextInputHost is resident from ~24 s after boot and
is otherwise idle (17.7 s CPU across 11 hours).

The kill has been removed from the watchdog. The refocus and pad re-plug behaviour stays.

**Method lesson:** the original claim was generalised from one observation made *inside* a
computer-use session, and the no-computer-use case was never run. Any claim of the form
"process X is doing Y to the game" needs a window where the suspected observer is absent.

## 2. Root cause of the regression: the vtrim net drifted out of range

Baseline 07-29 was 29.72 s median. Every window since has sat at 33.0 to 33.4 s. Nine causes
had already been ruled out by measurement (route, car, gearing, engine, config, cte governor,
`plan_degraded`, learner rate, CPU contention, loop timing, latency).

### Two of my own findings retracted first

**Code bisect, retracted as inconclusive.** Running `follow.py` from `2aeed06` (the 29.72 s
commit) scored 33.00 against HEAD's 33.28, and I read that as exonerating the code. Two errors:
the restore step used `git checkout <commit> -- follow.py`, which writes the **index** as well
as the worktree, so the follow-up `git checkout -- follow.py` restored the bisect version, not
HEAD. The verification line printed `git log -1 -- follow.py`, which reports the last commit
that *touched* the file and says nothing about its contents. The farm then ran the wrong code
for over an hour. More importantly, a code bisect cannot exonerate anything here, because
reverting code does not revert **learned state**, and the state was already damaged.

**"Steering gain fell 26%", retracted.** Yaw response per unit steering at matched speed looked
down sharply at moderate inputs and normal at full lock, which reads like an assist or linearity
change. It is an artifact. Restricting to genuinely steady state (steer held within 0.05 and
speed within 3 km/h across a 280 ms window) the two eras are identical:

| band | steady yaw @ full lock, 07-29 | tonight | ratio |
|---|---|---|---|
| 80 to 110 km/h | 0.8045 rad/s | 0.8230 | 1.023 |
| 110 to 140 km/h | 0.7610 rad/s | 0.7640 | 1.004 |

The unsettled comparison was measuring the bot's own changed behaviour distribution, not the
car. The plant did not change. Wheelspin distributions at >90% throttle are likewise identical
(p50 0.40 vs 0.39, p90 0.99 vs 1.03, max 1.3 both), so traction control is not intervening
either, and an earlier "drive_slip 0.39 vs 0.77" reading was taken under a different filter and
is not a TCS signature.

### The actual cause

`vtrim` is `map = clip(vt_base + delta, 0.80, 1.55)` where `vt_base = VtrimNet.forward(features)`.

`forward()` returns `tanh(...) @ W2 + b2 + 1.0` with no bound, and `step()` nudges the shared
weights on every credit and debit event. Over weeks the net drifts far outside any range a
speed *multiplier* can occupy. Measured on the live net:

```
net RAW output   : mean +0.727  min -2.810  max +4.778
  outside [0.80, 1.55] : 87.3%   (below floor 49.4%, above ceiling 37.9%)
```

87.3% of the net's outputs are outside the range its own output is supposed to live in.

This was invisible for as long as `delta` was unbounded, because delta had wound up to **+6.57**
to hold the map in place. The 07-29 anti-windup commit (`f1c0390`) bounded the delta state and
claimed to be "behaviour-neutral today". It was neutral on the day and not neutral afterwards:
once the net drifted further, the bounded delta could no longer lift stations off the floor.

| | 07-29 (29.72 s) | 08-01 (33.3 s) |
|---|---|---|
| map mean | 1.4587 | 1.2553 |
| stations at the 0.80 floor | **3.5%** | **32.1%** |
| delta at the stations now floored | +4.62 mean | +1.04 mean, still floored |

Those floored stations have a **positive** delta and are pinned at the floor anyway, which is
the signature: the correction term is pushing up as hard as it is allowed to and the drifted
base is still winning. And because `map_w` is a window-MIN over the next 18 m, floored stations
suppress the target well upstream of themselves, so 32% floored is a near-global speed cut.

### Fix

Two lines, both mechanism-level rather than track-specific:

1. `vtrim_base()` now clips the net into the map range: `np.clip(vnet.forward(vXf), 0.80, 1.55)`.
2. `vtrim_dmax` is `0.75`, exactly `vtrim_hi - vtrim_lo`. With the base clipped into `[lo, hi]`
   and the correction bounded at `hi - lo`, every value in the map range is reachable from any
   base, so the delta can always correct the net. Any larger bound is windup; any smaller bound
   silently strands stations at a limit, which is precisely what happened.

The delta table was then rebuilt as `delta = map_0729 - clip(base)` so the effective map
reproduces the 07-29 operating point exactly (max reconstruction error 0.00000, mean 1.4587,
3.5% floored). The net was left untouched. Previous state is snapshotted to
`recordings/snapshots/*_preNetClip_0801.npz`.

This is now invariant 8 in `CONSTRAINTS.md`.

### Result

50 scored laps, hands-off, 23:52 to 00:32:

| window | median | best | p25 | p75 | stalls |
|---|---|---|---|---|---|
| HEAD, earlier tonight | 33.28 | 32.78 | 33.15 | 33.37 | 0 |
| bisect to `2aeed06` | 33.00 | 32.51 | | | 0 |
| **net clip + restore** | **30.27** | **29.29** | 29.89 | 30.58 | 1 |
| 07-29 reference | 29.72 | | | | 0 |

**-3.01 s** against tonight's HEAD, and the best lap beats the 07-29 baseline median. The
remaining 0.55 s to 29.72 is within the range the map re-earns as it settles.

The confirming detail is not the lap time, it is what the map did during the window: floor
occupancy fell **3.5% to 1.2%** and mean rose 1.4587 to 1.4706. Under the old bound the map
only ever went down, because debits could always reach the floor while credits could no longer
lift off it. That asymmetry was the ratchet, and it is gone: the learner is now climbing.

Known-good state snapshotted to `recordings/snapshots/*_GOOD_3027_0802.npz`.

One stall in 50 laps against 0 at baseline. Worth watching, not worth acting on yet.

A second 45 minute window with no config change, letting the map keep learning, settled at
**30.12 median / 29.35 best / p25 29.84 / p75 30.29 / 1 stall (n=50)**. Another 0.15 s came back
on its own and the spread tightened. That is the baseline any arm tonight has to beat.

The map is now saturating upward instead: floor 1.7%, **ceiling 78.2%** (was 68.6% an hour
earlier), 0 stranded, window-min 1.3925. Two-thirds to three-quarters of the track sitting at
the learned ceiling means the map has lost most of its ability to discriminate between stations,
which is a generalisation problem as much as a speed one. Whether it is also costing lap time
depends on whether the map is the binding term at those stations, which is being measured
rather than assumed.

## 3. The bot has been driving on an integer overflow

A six-lens analysis over the 76 clean laps, each finding put through adversarial verification,
refuted 21 of 26 target-chain and limiter findings to zero. The three that survived were all
**I/O correctness defects**, and one of them is large.

### The defect

`vgamepad` writes the throttle as `self.report.bRightTrigger = round(value_float * 255)` with no
bound check. `bRightTrigger` is a ctypes `c_ubyte`, and ctypes **wraps mod 256 in silence**:

| commanded throttle | delivered pedal |
|---|---|
| 1.000 | 1.000 |
| **1.002** | **0.000** |
| **1.076** (median of the over-range population) | **0.071** |
| 1.200 | 0.196 |
| 1.854 (max seen) | 0.851 |

The controller emits `throttle > 1.0` on **9.04% of ticks**, because
`thr_cap = max_throttle * fc_frac * slip_frac * grip_scale` exceeds 1.0 whenever `grip_scale`
is above unity. `follow.py` does contain a clamp, but it sits inside the
`if resid_on > 0.5:` residual-corrector block, and `resid_on` defaults to 0.0, so it never runs.
Steering and brake never exceed 1.0, so throttle is the only exposure. (Steering would have been
worse: `sThumbLX` is a `c_short`, so an over-range steer would wrap to full *opposite* lock.)

Measured cost, matched on gear, speed and lateral load, brake off, no shift, below the limiter:

| gear / speed | thr 0.90-1.00 | thr 1.002-1.20 | delta |
|---|---|---|---|
| g3 140-180 | +15.87 m/s2 | +2.31 | **-13.56** |
| g4 140-180 | +12.96 | +2.14 | **-10.83** |
| g4 100-140 | +14.81 | +6.41 | -8.40 |
| g3 100-140 | +6.94 | +3.97 | -2.98 |

Clamping at the pad write (`pad_clamp`, hot key, logged values stay pre-clamp) removes the
deficit entirely: the same cells read **+1.06** and **+0.61** afterwards.

### And it is load-bearing

Scored against the 29.88 s frozen baseline, `pad_clamp = 1.0` **aborted**:

| metric | baseline (wrap active) | pad_clamp |
|---|---|---|
| median | 29.88, 0 stalls | **33.31, 3 stalls** |
| off-track | 0.29% | **4.25%** |
| \|sideslip\| p99 | 7.40 deg | **21.90 deg** |
| drive_slip p99 | 3.53 | 5.73 |
| stopped | 0.14% | 2.83% |

Off-tracks concentrate at s894-905 (2% to 86%) and s404, i.e. corner entries.

This is the fourth data point for the load-bearing-limiter prior, and the most striking, because
**this limiter was an accident**. Every downstream calibration, and the entire learned speed map,
was fitted to a plant that quietly lost about 10 m/s2 of drive on a tenth of every lap.

### The test design was wrong, though

`thr_cap` does bind properly under wheelspin (p50 0.541 at drive_slip 1.05-2.0, 0.126 at
2.0-3.5). The over-range commands happen at **low** slip, 54.7% of them below drive_slip 0.5.
So the off-tracks are not traction loss. The car simply accelerates harder down the straights
and **arrives at corners faster than the speed plan expects** - and I had frozen the learner,
which is the one layer that absorbs new arrival speeds. That is METHODOLOGY rule 9 exactly:
frozen-map arms overstate downstream breakage. The frozen number is not a verdict on the fix.

### Re-run with learning on: still worse, and the reason is the interesting part

70 minutes of adaptation from the known-good map, then 40 minutes scored:

| | median | best | p25 | p75 | stalls |
|---|---|---|---|---|---|
| baseline, frozen, wrap active | **29.88** | 29.39 | 29.66 | 30.25 | **0** |
| `pad_clamp`, frozen | 33.31 (aborted) | | | | 3 |
| `pad_clamp`, 70 min adapted | 30.62 | 29.82 | 30.10 | **33.21** | **8** |

Adaptation recovered most of the frozen arm's loss (33.31 to 30.62) and the early instability
did clear: stalls ran 2, 1, 0, 0, 0, 0, 0 across the first 35 minutes. Then they came back and
kept climbing: 3, 3, 4, 2, 4, 4, 4. Over the same period the learner carved the map from
1.4665 down to 1.4198, and the window-min (what the cap actually reads) from 1.3925 to 1.3058.

That is a spiral, not a convergence. The learner's only tool for "the car arrived too fast" is
to cut the map, a cut is a window-MIN over 18 m so it suppresses a whole approach, the deeper
cut costs corner speed, and the resulting incidents trigger further cuts. It never reaches a
stable operating point, and the p75 of 33.21 against a 30.25 baseline is where that shows.

**Verdict: `pad_clamp` stays OFF (default 0.0, watchdog dead-man 0.0).** Reverted, known-good
learned state restored, confirmed by a scored window.

### What this actually means

`throttle > 1.0` only ever occurs when the car is well *below* its commanded target, because
`desired = kp_thr * err + thr_i`. So the over-range commands are the controller asking for speed
it is not getting - and the independent budget decomposition found exactly that: **1.524 s/lap
of pure delivery shortfall**, the car failing to reach its own commanded target on its own path.

The speed plan is therefore systematically un-achievable, and every downstream calibration - the
limits, the derates, and the whole learned vtrim map - has been fitted to a plant that quietly
loses about 10 m/s2 of drive on 9% of ticks. Repair the actuator and the targets become
reachable, at which point they turn out to be too aggressive for the corners that follow.

This is not an overnight tune. Using that acceleration requires rebuilding the speed plan
against the true plant, in this order:

1. Fix the actuator (`pad_clamp = 1.0`) and hold it fixed.
2. Rebuild the braking/arrival model against measured acceleration **with the clamp on**, since
   the current one was identified on the weakened plant.
3. Reset the vtrim map and re-learn from a neutral prior rather than letting the existing map
   carve down into it. The carving spiral above is the direct evidence that incremental
   adaptation from a plant-mismatched map does not get there.

The prize is real: roughly 10 m/s2 of drive on a tenth of every lap, against a measured
delivery shortfall of 1.524 s. That is far larger than every tuning candidate found tonight
combined (~0.25 s, all below the detection floor of a 40-minute window).

## Notes

- The two-PID follower (myenv launcher plus Python312 child, same parentage) is normal. Check
  `ParentProcessId` before concluding there are duplicate followers.
- `Adobe Desktop Service.exe` is still spinning at 85% of one core, left alone at the user's
  instruction. It is measurably not the cause of anything here: loop period 14.00 ms median with
  0.00% of ticks over 20 ms in both eras.
