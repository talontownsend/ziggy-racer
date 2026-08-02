# Night log, 08-01 into 08-02

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

RESULT_PLACEHOLDER

## Notes

- The two-PID follower (myenv launcher plus Python312 child, same parentage) is normal. Check
  `ParentProcessId` before concluding there are duplicate followers.
- `Adobe Desktop Service.exe` is still spinning at 85% of one core, left alone at the user's
  instruction. It is measurably not the cause of anything here: loop period 14.00 ms median with
  0.00% of ticks over 20 ms in both eras.
