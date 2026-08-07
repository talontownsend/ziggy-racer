# start/T1 (+0.44 s): real, not contamination -- and it closes as a target

Third-largest section with no explanation and no arm. Same treatment as MBC spans A and B.
`python tools/t1_section.py`. Farm down throughout.

## 1. Contamination ruled out first

That section is uniquely exposed: a follower restart or stall recovery puts a STANDING LAUNCH at
exactly that part of the track, and the human's recording opens from a standstill.

| | bot s | n | human s | n | gap |
|---|---|---|---|---|---|
| all laps (as budgeted) | 3.26 | 222 | 2.82 | 50 | **+0.44** |
| launch/stall laps excluded | 3.25 | 211 | 2.81 | 48 | **+0.44** |

16 bot laps excluded (1 session-first, 8 containing a near-stop, plus the lap after each) and the
human's opening standing lap. **101% of the gap survives.** It is real.

**Loose end closed: the launch cap fires on 0 ticks across the entire lap on clean laps.** Its
"51.8 km/h mean deficit when it binds", recorded in the bind decomposition, came entirely from
launch laps -- exactly the contamination class excluded here. `bind_code` 5 is a non-event on
racing laps and needs no further attention.

## 2. Where it accumulates

| stations | s_m | lost | code1 | code3 | bot km/h | human km/h |
|---|---|---|---|---|---|---|
| 0-19 | 0-20 | +0.04 | 99% | 0% | 214.0 | 248.8 |
| 20-39 | 21-41 | +0.02 | 100% | 0% | 205.3 | 215.2 |
| 40-59 | 42-63 | +0.01 | 85% | 15% | 171.6 | 178.0 |
| 60-79 | 64-84 | +0.07 | 0% | 100% | 134.8 | 148.5 |
| **80-99** | 85-106 | **+0.19** | 0% | **95%** | 109.6 | 132.1 |
| 100-119 | 107-127 | +0.11 | 75% | 3% | 111.7 | 129.6 |

**+0.30 s of the 0.44 is in the T1 corner itself (stations 60-119)**, and it is `bind_code` 3
limited -- the curvature x vtrim cap. This is **outside both MBC spans**, so nothing is clamping
`map_w`.

## 3. Why the cap is low -- and it is EARNED, not an artifact

| stn | map | window-min | v_curve | eff cap | logTGT | bot | human |
|---|---|---|---|---|---|---|---|
| 75 | 0.800 | **0.800** | 125.4 | 105.0 | 105.0 | 123.7 | 143.0 |
| 87 | 0.857 | **0.800** | 125.4 | 111.9 | 111.9 | 108.7 | 132.3 |
| 93 | 0.800 | **0.800** | 129.6 | 120.2 | 120.2 | 109.2 | 130.4 |
| 102 | 1.550 | 1.550 | 122.7 | 218.5 | **135.6** | 110.9 | 128.3 |

**The learned map sits at its 0.800 FLOOR through the corner entry** -- the exact opposite of the
MBC spans, where it was pinned at the 1.55 ceiling with no feedback. A floor is *earned*: the
learner tried more speed there and was punished. And from station 99 the cap rises to 159-233
while the logged target stays 114-141, so **`bind_code` 1 (the plan) binds, not the cap**.

Through stations 80-119 the bot is at **full steering lock (|steer| = 1.00)**, braking on 27% of
ticks, with `|cte|` p90 **5.13 m** -- brushing the 5.0 governor threshold, which is why this
section shows 4.3% governor engagement in the budget.

And the human pulls **3.07 g p90 here against a model allowance of 2.75** -- the only corner
examined where the human exceeds the grip model. Elsewhere they sit at 2.20-2.35.

## Verdict: NO ARM. Same root as the excursion.

1. the loss is **cap-limited at a floored map**, so it is not a clamp or boundary problem --
   there is nothing to release, and the low value is the learner's own earned answer
2. the bot is at **full lock** through the corner and already at `|cte|` 5.13; it cannot use more
   speed at the current level of steering authority, which is precisely what the floor encodes
3. the grip model is **under-calibrated here specifically** (human 3.07 g vs allowance 2.75), but
   raising `planner_alat` globally was already tested and lost (J1: +0.52 s, and it produces LESS
   delivered throttle through the slip-derate feedback loop)

**T1 shares its root with the excursion corner: the car runs out of steering, cannot hold the
line, and the learner correctly responds by cutting the map.** It should improve for free if
`abrake_k_075` works -- braking earlier means less speed at turn-in, which means less lock
demanded -- and it is a natural place to re-measure after that window.

Recorded so a future session does not re-derive it: **T1 was investigated to span A/B depth and
produced no arm.** The one genuinely new fact is the grip-model shortfall at 3.07 vs 2.75, which
is a *per-station* observation and therefore vtrim's job, not `planner_alat`'s.
