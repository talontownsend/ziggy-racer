# The excursion, the governor, and the recovery-allowance design

The governor is the symptom. This maps every episode, finds where the disease starts, and
designs the change behind its own key. Offline only; farm down. Tools:
`governor_episodes.py`, `tv_trace.py`.

## One excursion owns 70% of all governed ticks

440 episodes (>=10 ticks) across 359 lap segments, binned by start station:

| zone | s_m | episodes | laps | ticks | entry \|cte\| | target | ungoverned | denied |
|---|---|---|---|---|---|---|---|---|
| **750-774** | 803 | 138 | 138 | **9,729** | 5.03 | 116.2 | 151.5 | 35.2 |
| **775-799** | 830 | 106 | 106 | **5,141** | 5.02 | 125.2 | 151.2 | 26.0 |
| 75-99 | 80 | 66 | 66 | 1,914 | 5.01 | 105.8 | 135.6 | 29.8 |
| 850-874 | 911 | 17 | 17 | 1,581 | 5.06 | 58.6 | 194.4 | **135.8** |
| 825-849 | 885 | 63 | 63 | 1,323 | 5.04 | 117.2 | 173.7 | 56.5 |

The top two zones are contiguous: **one excursion spanning stations 750-799 is 70% of all
governed ticks**, in 138/359 laps. Corner 1's entry is the dominant episode, not one of several.

## It is born in the same place every lap, at full lock

| stn | s_m | \|cte\| | d\|cte\| | spd | steer | brk% | thr |
|---|---|---|---|---|---|---|---|
| 742 | 794 | 0.28 | −0.17 | 157.0 | **+1.00** | 100% | 0.00 |
| 748 | 800 | 0.75 | +0.31 | 147.4 | **+1.00** | 100% | 0.00 |
| 754 | 807 | 1.84 | +0.38 | 134.5 | **+1.00** | 100% | 0.00 |
| 760 | 814 | 2.96 | +0.41 | 121.7 | **+1.00** | 9% | 0.30 |
| 768 | 823 | 4.20 | +0.25 | 126.6 | +0.90 | 1% | 0.70 |
| 776 | 832 | 5.07 | +0.25 | 129.7 | +0.86 | 54% | 0.00 |

**The car sits at full steering lock from station 740 to 774 while braking 100%, and washes wide
regardless.** `|cte|` grows +0.3 to +0.4 m every two stations across 30+ stations of pinned lock.
That is trail-braking at the steering limit: combined slip consumes the lateral grip needed to
make the corner.

**248 of 359 laps cross 5.0 m here; station median 774, p10 770, p90 778, sd 3.0.** The same
place every lap.

**So the disease is the corner at s~794-814, not corner 1.** The candidate fixes there are entry
speed and brake/steer separation. The governor work below is symptom relief on the dominant
episode, worth doing, but it is not the cure.

## Design pass: a recovery ALLOWANCE, not a floor

**First design, evaluated and rejected.** Floor the target at a fraction of the ungoverned
target. At the dominant episode it does nothing: `|cte|` is 5.68 against `cte_soft` 5.0, so
`g = 0.966` and the shipped floor is already ~`spd + 1`; the car sits at 79% of the ungoverned
target, so `gov_floor * g * target` does not bind until ~0.82.

| gov_floor (fraction form) | 0.6 | 0.7 | 0.8 |
|---|---|---|---|
| target at the dominant episode | 120.9 (+0.0) | 120.9 (+0.0) | 122.1 (+1.2) |

**And "the car cannot accelerate" was too strong.** The shipped floor gives `spd + 1.0 m/s`, a
standing +3.6 km/h allowance, and the car does climb out (121.7 -> 130.1 km/h over 14 stations).
**The defect is the RATE**: the throttle controller sees `err = 1 m/s` instead of the true ~30 m/s
deficit, so it creeps at `kp_thr * 1`.

**Shipped:**
```python
_c = max(spd * (0.5 + 0.5 * g) + 1.0, 4.0)
```
**Proposed** (`gov_floor`, default 0.0 = OFF):
```python
_c = max(spd * (0.5 + 0.5 * g) + 1.0 + gov_floor * (g ** 3), 4.0)
_c = min(_c, target_v)          # never exceeds the ungoverned target
```

`gov_floor = 0` is **bit-identical by construction** (`+ 0 * g**3` is `+ 0`), and the branch is
inside `if acte > cte_soft`, so only governed ticks are reachable.

**Why `g**3`.** The linear form relaxed the guard too far off-line: +10.6 km/h at `|cte|` 10 m.
Cubing collapses it there while leaving the mild band, where 96% of governed ticks live, nearly
untouched.

| | ALL governed | DOMINANT 750-799 | FAR \|cte\|>10 m |
|---|---|---|---|
| \|cte\| median | 5.63 (g 0.969) | 5.68 (g 0.966) | 10.30 (g 0.735) |
| shipped target | 115.5 | 120.9 | 52.8 |
| `gov_floor=2` | 121.9 (+6.5) | 127.4 (+6.5) | 55.6 (**+2.9**) |
| `gov_floor=4` | 128.4 (+13.0) | 133.8 (+12.9) | 58.3 (**+5.7**) |
| `gov_floor=6` | 134.9 (+19.0) | 140.2 (+18.7) | 61.2 (+8.6) |

Ungoverned target at the dominant episode is 151.4 km/h, so even `gov_floor=6` leaves 11 km/h of
governing in place there.

**Suggested first rung `gov_floor = 2.0`**: +6.5 km/h of target at the dominant episode, +2.9 far
off-line. `4.0` is the natural second rung.

## Status

Implemented, `gov_floor` defaults to 0.0. **Not queued** — the queue stays as written
(`ileak_rep2`, then `ksp_025`). Note `cte_ileak` and `gov_floor` act on the same mechanism from
opposite ends: ileak reduces `|cte|` so the governor trips less; `gov_floor` softens the governor
when it does trip. They must not be armed together until each is scored alone.
