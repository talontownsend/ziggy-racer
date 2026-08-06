# Rescoring the archived arms after the lap-detector fix

`ab_arm.py` keyed laps by `(session, lap_no)`. `lap_no` repeats within a follower session
because the event restarts and numbering begins again, so it merged ~4 real laps per group
and reported `max(lap_t)`: **+0.71 s median, +0.48 s best**, 211 laps counted as 50.

The bias tracks incident rate, not speed. An arm that causes more restarts merges more laps
and reads slower. So every arm was rescored from its archived log, on two axes instead of one.

## Why two axes

A clean-lap median alone can exonerate an arm that is wrecking the car, because dirty laps are
*excluded* rather than counted. The old keying folded incidents into the median by accident.
Splitting that apart gives an honest pace number and an honest stability number:

- **pace**: median of clean laps (>97% on-track, no telemetry gap >2 s, started at the line)
- **stability**: share of lap attempts that were not clean, laps/hour, stalls/hour

## Results

| arm | pace | off-track | laps/h | stalls/h | verdict |
|---|---|---|---|---|---|
| spin substitution | +0.12 (noise) | 1.4% -> **20.5%** | 110 -> 80 | 3.1 -> 8.1 | reject, **unstable, not slow** |
| pad clamp (TC) | **+0.97** | unchanged | unchanged | unchanged | reject, genuinely slower |
| pad clamp (arm) | +0.59 (n=16) | 2.5% -> 26.9% | 111 -> 61 | 1.2 -> 15.2 | reject, both axes |
| throttle wrap off | -0.13 (noise) | unchanged | unchanged | unchanged | **no gain** (looked like +0.47 s) |
| net refit | +0.06 (noise) | unchanged | unchanged | unchanged | neutral, as recorded |

## What changed

No verdict flips from bad to good. Two records were wrong about **why**:

1. **Spin substitution was not slow.** It was recorded as 4.0 s slower; it holds baseline pace
   and goes off-track 15x more often. That matters because it is the arm that replaces the
   combined-slip derate (which is really a steering detector) with true longitudinal spin. A
   mechanism that is 4 s slower is dead. A mechanism that is fast but unstable is a stability
   problem, and worth another attempt with the instability addressed rather than the idea
   discarded.

2. **The throttle-wrap fix gained nothing.** It read +0.47 s better under the old detector and
   is neutral. Consistent with the standing conclusion that the fix is load-bearing (the pad
   byte really did wrap) without being a lap-time win.

Run it with `python tools/rescore_arms.py`. Score every future arm on both axes.
