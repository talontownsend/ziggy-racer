# The brake closure is true, tautological, and irrelevant

Rechecked at the origin of the corner-3 cascade, stations 795-845. Logs + 08-02 recording.

## The verdict: measured only on ticks where braking is structurally impossible

```python
err_b = err - desc_f*bla_tau  if (bla_tau>0 and desc_f>3) else err
if err >= 0 and (err_b >= 0 or err > 1.0):   # throttle
else:                                        # brake
```

`err = target - speed`. The brake branch is taken whenever **`err < 0`** (car OVER target) with
**no bound on magnitude**. The `err <= 1.0` ceiling applies only to the second case, `err >= 0`,
where anticipation fires.

At 795-845: **18.9% of ticks are braking** (7,868 of 41,726).

| condition | ticks | share | err |
|---|---|---|---|
| `err < 0` — car over target, **unbounded** | 2,712 | 34.5% | median −5.9 km/h, **min −68.2** |
| `err >= 0` — anticipatory, needs `err<=1.0` | 5,156 | 65.5% | — |

**Reproducing the closure's own test:** ticks with `tgt − v > 10 km/h` are 64.3% of the span, and
brake is applied on **0.00%** of them. Max `err` over all brake ticks is **1.000000 m/s**, exactly
the doc's figure.

Both numbers are correct **and guaranteed by the predicate**: `err > 1.0` forces the throttle
branch, so a test restricted to `err > 2.78 m/s` can only ever return 0%. The closure measured
the one region where braking is structurally impossible and concluded braking is structurally
impossible.

**It bounds brake ticks from above; nothing bounds them from below.** Corner entry runs to
−68.2 km/h of error at 24-29% of ticks. The closure is true, tautological, and says nothing
about the place lap time is lost. **BRAKE_SIDE_CLOSED_0803.md should be read as scoped to
delivery-limited (under-target) ticks only.**

## Entry profile: not overshoot

| stn | botSPD | humSPD | botTGT | vcurv | botBRK% | humBRK% | a_long | thr | cap | slip |
|---|---|---|---|---|---|---|---|---|---|---|
| 790-794 | 117.7 | 147.8 | 120.5 | 143.1 | **55%** | 0% | −0.38 | 0.00 | **0.09** | 2.99 |
| 795-799 | 113.1 | 149.0 | 153.5 | 143.1 | 46% | 0% | −0.40 | 0.09 | 0.24 | 1.67 |
| 800-804 | 110.0 | 150.9 | 157.8 | 180.1 | 7% | 0% | +0.32 | 0.29 | **0.30** | 1.59 |
| 805-809 | 109.3 | 152.9 | 161.0 | 176.9 | 1% | 0% | +0.54 | 0.39 | **0.39** | 1.48 |
| 815-819 | 109.9 | 158.1 | 129.3 | 126.8 | 34% | 0% | +0.03 | 0.06 | 0.91 | 0.93 |

bot min **109.0** @ 806, human min **148.2** @ 795, bot TARGET min **119.7** @ 795.

The target dips to 119.7 at 795; the bot brakes to it; the target then rises to 161 while the bot
is **still decelerating** (`a_long` −0.40 through 795-799), bottoming at 109 only at 806. It then
reaccelerates at +0.32 to +0.54 g with `thr_cap` at **0.30-0.39** and `thr` sitting exactly on it.

**Diagnosis: a momentary target dip, then derate-limited reacceleration.** Not brake overshoot
(the bot ends only 10.7 km/h under its own *minimum* target, and the loss accrues after the
brake releases). At 790-794 `drive_slip` is 2.99 and the cap is crushed to 0.09.

## It is NOT a general mechanism: corner 2 fails differently

| stn | botSPD | humSPD | botTGT | vcurv | brk% | a_long | cap | slip |
|---|---|---|---|---|---|---|---|---|
| 605-609 | 104.3 | 134.5 | 88.1 | 91.9 | 100% | −1.67 | 0.14 | 2.77 |
| 615-619 | 93.5 | 132.0 | 119.1 | 130.5 | 2% | +0.43 | 0.80 | 0.92 |

bot min 90.3 @ 614, **target** min 85.2 @ 598, human min 130.5 @ 625.
Undershoot vs its own min target: **−5.1 km/h — the bot stays ABOVE it.**

Corner 2's bot tracks its target correctly. The target is simply far too low: **85-90 km/h where
the human drives 131-136**. Reaccel is also healthier (cap binding 44%, `a_long` +1.17 g) than
corner 1 (60%, +0.65 g).

**Corner 1 = tracking + derate-limited reaccel. Corner 2 = the target is wrong.** Different
fixes. Ranking corners by a single deficit number hides this.

## v_curve sits below the refline's own geometric limit

`v_curve = min(v_line, v_rejoin)`, where `v_rejoin` comes from `kappa_merge_max`, the arc needed
to get back to the line. Reconstructing `v_line` from the refline's max-curvature-ahead(18 m):

| corner | kappa@stn | kmax 18 m | v_pred | v_logged | diff |
|---|---|---|---|---|---|
| 2 | 0.01670 | 0.02036 | 140.0 | 130.5 | **−9.5** |
| 1 | 0.01169 | 0.01638 | 158.8 | 145.5 | **−13.3** |
| 3 | 0.00774 | 0.00961 | 221.8 | 199.1 | **−22.8** |

Whole lap: corr +0.746, median |diff| 8.9 km/h, **v_logged consistently below**.

**A hypothesis I tested and could not confirm.** The obvious explanation is a loop: off-line ->
tighter rejoin arc -> lower `v_curve` -> slower. Within-station `corr(|cte|, v_curve)` is
**mean −0.093, median −0.062**; 58% negative but only 26% below −0.3 and 6% positive, and
high-`|cte|` shows lower `v_curve` in only **18%** of stations. The −62 km/h mean gap between
`|cte|` quartiles is an aggregation artifact across stations of different scale.

**So the loop is unsupported.** The ileak arm's `v_curve` gain (155.4 -> 161.2 with `|cte|`
1.77 -> 1.69) is real but not explained by it. Whatever depresses `v_curve` below the line's own
limit is still unidentified, and it is worth 9-23 km/h in the corners that matter.

## The human, for reference

At both corners the human is **on the reference line** (offset median 1.06 m at corner 2, 1.37 m
at corner 1) pulling grip the model already allows: 2.35 g required at corner 2, 2.26 g at corner
1, against `planner_alat` = 2.75 g. **Geometry is not the problem and the grip model is not
wrong.** What the human does is carry speed the bot's `v_curve` never offers it.
