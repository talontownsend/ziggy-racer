# State of knowledge, 2026-08-06

What we believe about the gap, why, and which claims this supersedes. Written after a session
that corrected a lot -- including several of my own numbers, some more than once.

**Read this before trusting any pre-08-06 document.** Every median written before today is on an
inflated scale (see Superseded, item 1), and four load-bearing conclusions were wrong.

---

## 1. The measurement floor, first

Nothing below means anything without this:

| | value |
|---|---|
| bot lap (fixed detector) | **29.85 s** median |
| human lap (08-02, 50 laps) | **26.53 s** median |
| **gap** | **3.32 s** |
| measurement floor, 40-min window | **~0.30 s** |

`ab_arm` keyed laps by `lap_no`, which repeats within a follower session, and reported
`max(lap_t)` over ~4 merged laps: **+0.71 s on the median**, 211 laps counted as 50. Fixed
08-06. Any median in a document dated earlier is inflated, and the bias varies per log with how
often the event restarted, so old cross-log comparisons are unreliable in both directions.

---

## 2. Where the 3.32 s actually lives

Median per-lap **section time**, bot vs human, 222 bot laps and 50 human laps.
Run: `python tools/time_budget.py`.

| section | m | bot s | human s | lost | % of gap | governor% |
|---|---|---|---|---|---|---|
| **stations 470-610** (s 501-652) | 152 | 4.83 | 4.09 | **+0.75** | **23%** | 0.0% |
| **stations 610-700** (s 652-748) | 96 | 2.74 | 2.28 | **+0.45** | **14%** | 0.2% |
| start / T1 (0-120) | 128 | 3.26 | 2.81 | +0.44 | 13% | 4.3% |
| **excursion born + governed** (745-800) | 61 | 1.82 | 1.44 | **+0.38** | **11%** | 10.4% |
| corner 3, inherits (850-930) | 85 | 1.86 | 1.59 | +0.27 | 8% | 1.5% |
| fast 260-340 | 85 | 1.76 | 1.52 | +0.25 | 7% | 0.2% |
| corner 1, inherits (800-850) | 54 | 1.42 | 1.20 | +0.21 | 6% | 0.0% |
| main straight (930-1000) | 74 | 1.30 | 1.09 | +0.21 | 6% | 1.3% |
| S2 (120-260) | 151 | 4.46 | 4.31 | +0.15 | 4% | 0.3% |
| approach to the excursion (700-745) | 49 | 1.03 | 0.91 | +0.12 | 4% | 0.3% |
| S4-S5 (340-470) | 137 | 5.38 | 5.29 | +0.09 | 3% | 0.5% |
| **TOTAL** | 1071 | **29.85** | **26.53** | **+3.32** | | |

**CORRECTION (added after the span-A study).** The section labels above are STATION indices, and
I originally mislabelled two of them as the MBC spans. They are not. MBC span A is s=470-608 m =
**stations 442-567**, and the row labelled "470-610" is stations 470-610 = s 501-652 -- overlapping
but different. Measured directly per lap, **the real span A costs +0.56 s**, not 0.75. The section
rows remain correct as station ranges; only the MBC labels were wrong.

Method note: this is per-lap section timing, NOT integrated median speed. The speed method is
destroyed by sparse stations -- station 714 has a bot median of 3.9 km/h from a handful of stall
samples and single-handedly produced a bogus 1.11 s for the 700-745 section, which is really
0.12 s. **Never budget time from per-station median speeds.**

---

## 2b. The survey is NOT complete -- full section allocation

Non-overlapping partition aligned to the REAL structure boundaries (span A = stations 442-567,
span B = 596-656), launch and stall laps excluded on both sides. Sums to +3.37 s.

| section | stations | m | bot s | hum s | lost | coverage |
|---|---|---|---|---|---|---|
| start / T1 | 0-120 | 128 | 3.25 | 2.81 | +0.44 | **CLOSED** `T1_SECTION_0806` |
| S2 | 120-260 | 151 | 4.46 | 4.31 | +0.15 | **untouched** |
| fast 260-340 | 260-340 | 85 | 1.78 | 1.52 | **+0.26** | **untouched** |
| S4 -> span A entry | 340-442 | 107 | 4.51 | 4.47 | +0.04 | untouched |
| MBC SPAN A | 442-568 | 138 | 4.26 | 3.70 | +0.56 | **CLOSED** `MBC_SPAN_B_0806` |
| between the spans | 568-596 | 30 | 0.95 | 0.80 | +0.15 | **untouched** |
| MBC SPAN B | 596-657 | 64 | 2.12 | 1.70 | +0.43 | ARM `mbc_rzc_115` |
| span B exit -> excursion | 657-745 | 95 | 2.10 | 1.84 | **+0.26** | **untouched** |
| EXCURSION | 745-800 | 61 | 1.82 | 1.44 | +0.38 | ARM `abrake_k_075` / `ileak_rep2` |
| corner 1 (inherits) | 800-850 | 54 | 1.42 | 1.20 | +0.21 | inherits -> `abrake_k_075` |
| corner 3 (inherits) | 850-930 | 85 | 1.86 | 1.59 | +0.27 | inherits -> `abrake_k_075` |
| main straight | 930-1000 | 74 | 1.30 | 1.09 | +0.21 | **untouched** |
| **TOTAL** | | 1071 | **29.84** | **26.47** | **+3.37** | |

**Allocation: closed 1.00 s (30%), queued arms 0.81 s (24%), inherits 0.48 s (14%),
UNTOUCHED 1.08 s (32%).**

**The budget is NOT fully allocated. State this plainly rather than implying completeness.**

### Untouched sections at or above 0.15 s, by loss density

| section | lost | m | s per 100 m | stations |
|---|---|---|---|---|
| **between the spans** | +0.15 | 30 | **0.500** | 568-596 |
| main straight | +0.21 | 74 | 0.284 | 930-1000 |
| fast 260-340 | +0.26 | 85 | 0.306 | 260-340 |
| span B exit -> excursion | +0.26 | 95 | 0.274 | 657-745 |
| S2 | +0.15 | 151 | 0.099 | 120-260 |

For scale, the two armed sections run 0.62-0.67 s per 100 m, so nothing untouched is as dense as
what is already targeted.

**Next depth treatment: `between the spans` (stations 568-596)** -- highest loss density of
anything untouched, only 30 m, and it sits directly between two clamped spans, which makes it
the most likely place for a boundary or hand-off artifact. `fast 260-340` and `main straight`
follow; both are high-speed sections where the cause is more likely gearing or power than a
control decision, and neither has been examined at all.

---

## 3. The causal model

### 3a. The excursion (measured, high confidence)

The car reaches **full steering lock at station 740 and holds it to 774 while braking 100%**,
and washes wide regardless: `|cte|` grows +0.3 to +0.4 m every two stations across 30+ stations
of pinned lock. **248 of 359 laps cross 5.0 m of cross-track error here, station median 774,
sd 3.0** -- the same place, every lap.

**Cause: `A_BRAKE` is optimistic.** The braking pass back-propagates at a flat 25.0 m/s^2
regardless of steering. Achieved, by band (human reference, 15,301 braking ticks):

| \|steer\| | achieved m/s^2 | vs assumed |
|---|---|---|
| straight <0.15 | 21.4 | −14% |
| partial | 20.0 | −20% |
| heavy | 19.5 | −22% |
| **full lock** | **16.1** | **−36%** |

To shed 157 → 121 km/h the planner budgets **15.4 m** and needs **27.4 m** at lock, so it brakes
**~12 m too late** into every corner requiring steering while braking. The human brakes **18 m
earlier**, peaks lower (2.03 vs 2.66 g) and tapers; the bot brakes late, harder, and holds full
brake at full lock 25 m deeper.

Calibrate to the human, not the bot: the bot's own 14.1 m/s^2 at lock is partly self-inflicted
(front `cs_front` p50 2.42 with a slip **angle** of only 1.04 deg -- the fronts are locked
longitudinally on 90% of ticks). But the human also runs `cs_front` 3.13 at lock, so front
saturation is characteristic of the car, not purely behavioural.

### 3b. The governor cascade (measured, but smaller than it looks)

`|cte|` crosses `cte_soft` = 5.0 at station ~776 and the cross-track governor (`bind_code` 6)
fires, collapsing the target to `spd*(0.5+0.5g) + 1.0` -- roughly **current speed + 3.6 km/h**.
Formula reproduced exactly: predicted 115.6 vs logged 115.6.

One excursion spanning stations 750-799 owns **70% of all governed ticks** in 138/359 laps, and
where it binds it denies **37.8 km/h** of target (115.7 vs 153.5 ungoverned).

**But it costs only ~0.38 s, 11% of the gap.** Governed stations are slow and short, so a large
speed denial buys little time. *I over-weighted this for most of the session on tick share; time
is the correct currency.*

The car is not unable to accelerate out -- it gets `spd + 1 m/s` and does climb 121.7 → 130.1
km/h. The defect is the **rate**: `kp_thr` sees `err = 1 m/s` instead of the real ~30.

### 3c. What corners inherit (measured)

Corner 3's 71.8 km/h shortfall is **not generated there**. The car is already 42 km/h down at
station 800, before the corner exists, and accelerates at +0.9 to +1.2 g the whole way through
without closing. Corner 1 is likewise downstream. **Ranking corners independently is invalid**;
they are one chain.

### 3d. What is NOT the cause (each closed with evidence)

- **The reference line.** The human runs within **0.99-1.37 m** of it through every corner
  examined, on a 9.6-16.1 m track. A rebuild buys nothing.
- **The grip model.** The human pulls 2.20-2.35 g where the model allows 2.75. Not wrong.
- **The throttle side.** Relaxing the derate is null at `slip_target` 1.25 (cap binding at full
  lock 45.4% → 36.0%, throttle +10%, lap time 30.41 → 30.40) and unstable at 1.45 (aborted at
  23 min, stalls 1 → 6). Closed **on its own terms**, not blocked by steering.
- **The brake.** See Superseded item 2 -- the old closure was tautological, but the corrected
  picture still does not make the brake a lever.
- **Curvature-estimator noise.** `kappa_ref` is genuinely spiky (R=703 m to R=23 m over metres,
  3-point Menger at 1.06 m spacing) but the 18 m max-window absorbs it into a cap that lands
  within 3-7 km/h of demonstrated human speed *on the corner median*. See Superseded item 3 for
  the per-station correction.

### 3e. Rough budget of the 3.32 s -- **HYPOTHESIS**

Everything above is measured. This attribution is not; it is the best current reading and is
where a future session should push hardest.

| component | s | basis | confidence |
|---|---|---|---|
| MBC clamps (spans A+B) suppressing corner targets | ~1.2 | section timing; both spans clamp `map_w` to 1.0 and neither boundary sits on its geometry | **medium** -- the section cost is measured, the attribution to MBC specifically is not |
| Late braking → excursion → governor chain | ~0.5 | 0.38 s in the governed section + part of corners 1/3 inheritance | medium |
| Corner-entry speed generally (not MBC, not governor) | ~0.8 | residual across T1, S2, fast sections | **low** |
| Straight-line and top-end | ~0.4 | main straight 0.21 + fast 260-340 0.25, partly gearing/power | low |
| Unattributed | ~0.4 | | -- |

**Sections investigated to full depth and CLOSED as targets** (each with a doc a future session
can trust): MBC span A (+0.56 s, `MBC_SPAN_B_0806.md`) -- diffuse, 68% genuine crest, the one real
boundary error worth 0.05-0.13 s, under the floor. start/T1 (+0.44 s, `T1_SECTION_0806.md`) --
real, not launch contamination, but cap-limited at a FLOORED map with the car at full lock, so the
low cap is the learner's earned answer and there is nothing to release.

Both share a root with the excursion: **the car runs out of steering authority and the learner
cuts the map in response.** That makes `abrake_k_075` the arm with the widest reach -- braking
earlier means less speed at turn-in, less lock demanded, and it should improve T1 and the
inherited corners without touching them.

---

## 4. The queued arms, mapped onto the model

Each arm tests one component. **Score tomorrow against the stated signature, not ad hoc.**

| arm | model component | predicted mechanism signature | not expected |
|---|---|---|---|
| **`ileak_rep2`** (`cte_ileak` 0.5) | 3b, governor cascade | `|cte|` p90 falls (3.34 → ~3.06 m); governor tick share falls (3.44% → ~2.42%); `|cte|` >5.0 m ticks fall 3.4% → 2.4%; **at stations 786-800 governor engagement 67% → ~53%** | **0.38 s of any gain has a named mechanism (the governed section); the rest would need one.** Do not read a larger result as impossible: the measured effects are lap-wide, not confined to the governed stations -- `|cte|` p90 fell 0.28 m, code-3 deficit 14.8%, under-target deficit 1.6 km/h. Better tracking pays wherever the car is near its target. The A-B-A decides |
| **`abrake_k_075`** | 3a, late braking | brake onset moves **s=780 → 769 m** (11 m earlier, human 761); entry speed into the corner DROPS while the minimum through it RISES; `|cte|` at 750-799 falls; governor share falls | lap time -- predicted gain is below the 0.30 s floor |
| **`mbc_rzc_115`** (`mbc_b_lo` 646 + `rzc` 1.15) | 3e, MBC span B | effective target at stations 596-603 rises **+13.2 km/h**, and **nowhere else changes at all** (verified: 0.0000 km/h delta upstream, across the crest, and elsewhere) | lap time at rung 1; this is a bounded first step of three |
| **`ksp_025`** | curvature source | effective target at binding stations +1.7 median, +4.5 max on the 700-780 approach | lap time; the predicted gain is far below the floor. **Watch `|cte|` at 750-799**: it adds +1.6-1.9 km/h exactly where the excursion is born |
| **`gov_floor_2`** *(conditional)* | 3b, governor recovery rate | governed target at 750-799 rises ~+6.5 km/h and speed through the span rises | re-justify only if the excursion survives `abrake_k` -- it treats a symptom of a symptom |

**No arm currently targets MBC span A (0.75 s, the largest section).** That is the clearest gap
in the plan.

---

## 5. Superseded claims

Every one of these is wrong in an existing document. **Fix the reading, not just the number.**

**1. Every median dated before 2026-08-06 is inflated by ~0.71 s.**
`ab_arm` keyed laps by `(session, lap_no)`; `lap_no` repeats within a session because the event
restarts, so it merged ~4 laps and reported the slowest. Measured on one 211-lap window: 50 laps
/ 30.89 median reported, versus 211 laps / 30.18 true. The bias tracks **incident rate**, not
speed, so a "worse" verdict may reflect restart frequency. *Evidence: ticks per detected lap --
a 30 s lap at 69 Hz is ~2070 ticks; the merged groups held 9153.*

**2. "The brake cannot reach the deficit" (BRAKE_SIDE_CLOSED_0803) is true but tautological.**
The brake branch fires whenever `err < 0` (car over target) with **no magnitude bound**; the
`err <= 1.0` ceiling applies only to the anticipatory `err >= 0` case. The closure tested ticks
with `tgt − v > 10 km/h` and found 0.00% braking -- which the predicate *guarantees*, since
`err > 1.0` forces the throttle branch. At the excursion 18.9% of ticks brake, and 34.5% of
those run to **−68.2 km/h** of error. *Replacement: the closure is scoped to under-target ticks
only and says nothing about corner entry.*

**3. "The corner-speed cap is within 3-7 km/h of the human" was a corner-median artifact.**
Per station the cap denies **13-18 km/h mean and 33-45 km/h at the peak**, and the human exceeds
it at 61-80% of stations. The median averaged the binding zone together with the fast exit.
*Evidence: integrated `max(human − cap, 0)` = 886 / 724 / 666 km/h·m at corners 2 / 1 / 3.*

**4. "The lookahead denies 23-69 km/h" compared against an unachievable reference.**
`v_phys` uses curvature *at* the station, which no one can drive because you must already be
slowing for what is 18 m ahead. Benchmark against the human instead.

**5. "The corner-1 dip is set by the plan's `tv`" -- wrong, twice.**
`tv` there is 153.5 while the log says 119.7. It is `bind_code` 6, the **cross-track governor**,
binding on 55-70% of ticks. And the follow-on hypothesis that the same kappa spikes drive `tv`
by a second path is also dead: `vown_w = 0`, so `_kl` and `v_own` are **dead code** in the live
config. *Evidence: `tv` reproduced to +0.00 km/h median across 584 stations; governor formula
predicted 115.6 vs logged 115.6.*

**6. "Map window-min predicts lap time, r = −0.992."** Fabricated by my own labelling -- I had
assigned session medians to snapshots by name. Objectively paired, **r = −0.139**. *A
correlation built on guessed labels is not evidence.*

**7. "k_reserve = 1.0 gained 0.20 s."** The washout read 29.94 against the arm's 29.92. The
mechanism is real and reverts with the key (full-lock 32.6% → 27.1% → 32.0%); the lap time is
**not attributable**. Deployed as a better-behaved controller, not a faster one.

**8. "Stage 4 gained 0.27 s."** Baselined against the first 45 min after a restart, during which
lap times fell 30.60 → 30.33 → 30.25 → 30.11 monotonically *regardless of config*. Full-baseline
comparison: 30.41 vs 30.40. **Never baseline against a post-restart transient.**

**9. "The derate is not binding at full lock."** Brake-contaminated. Excluding brake ticks it
binds on **45.4%** of full-lock ticks (commanded 0.368 against a cap of 0.609).

**10. "The excursion approach costs 1.11 s."** One station (714) with a 3.9 km/h median from
stall samples produced 0.99 s of that. The section is **0.12 s**. *Never budget time from
per-station median speeds; use per-lap section times.*

**11. "The MBC span-B stored map can be reset to 1.0 to make day one neutral."** It cannot at the
storage level: `map_w` is a window-MIN over 18 stations, so writing 1.0 at 596-603 drags 17
upstream stations down 47-62 km/h. *Replacement: cap at USE time (`rzc`), exactly as MBC itself
does -- verified bit-identical at default and zero-leak at every rung.*

---

## 6. Open questions, ranked

1. **What is MBC span A's 0.75 s made of?** Largest section, no arm, boundaries known wrong
   (misses 30 m of crest at entry, clamps 12 m of non-crest at exit).
2. **Does `abrake_k` actually remove the excursion?** If it does, `gov_floor` is unnecessary and
   corners 1 and 3 should improve without being touched.
3. **Is the ileak result real?** Cycle 1's −0.51 s exceeds what the governor mechanism can
   explain (0.38 s section total). Replication decides.
4. **Front lock under braking.** Both bot and human run `cs_front` ~3 at lock; a brake taper as
   a function of `|steer|` is unexplored.
5. **`mbc_a_lo` misses 30 m of real crest.** Zero incidents there today, but it is unguarded
   crest -- re-check after any arm that raises entry speed.
