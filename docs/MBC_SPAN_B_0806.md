# MBC span B guards a crest that starts 8 m after the span does

Span B caps the learned map's boost at 1.0 across s=638-702. It is the largest per-station
denial found 08-06: at corner 2's binding zone the effective target is 88.1 km/h, and even a
full `ksp` blend only reaches 107.5 because the clamp is binding, not the curvature.
Run: `python tools/mbc_span_b.py`. Logs + the 08-02 recording. Farm down throughout.

## What it memorialises

Introduced 07-08 (`b929dc8`), replacing the retired `s7m`/`acm` crest margins. The adjacent
`cg_on` key documents s600-680 as a "crest grip-margin" zone, so span B guards a **crest**:
reduced vertical load over a rise, where the map would otherwise learn a speed the car only
survives on a good lap. That is a real and sound reason for the mechanism to exist.

## The hazard does not bite where the boundary sits

| | ticks | off-track | \|sideslip\| p99 | \|cte\| p90 |
|---|---|---|---|---|
| **inside B** | 52,479 | **0.01%** | 3.80 | 1.54 |
| outside | 726,961 | 0.56% | 9.40 | 3.42 |

The car is **56x cleaner** inside the span than outside it, and **zero** of the 12 worst
off-track stations on the lap are inside it -- every one is at s=956-975 (corner 3).

**Span A is genuinely clean too** (0.00% off-track, sideslip p99 3.80) and is NOT touched below.

## Neither does the human

| | speed | lat g p90 | brake% | \|offset\| |
|---|---|---|---|---|
| inside B | 136.1 | **2.93** | **4%** | 1.00 |
| outside | 141.9 | 3.04 | 25% | 1.15 |

The human brakes on 4% of span-B ticks against 25% elsewhere, and pulls *less* lateral g inside
than out. They lift (throttle < 0.2) on 32% of ticks. They do not tread carefully here.

## But lifting the span is wrong

| config | eff target at B's binding stations | vs human 135.4 |
|---|---|---|
| clamped (shipped) | 124.3 | −11.1 |
| **fully lifted** | **192.7** | **+57.3** |

Releasing the whole span licenses ~57 km/h beyond anything demonstrated. **The fault is the
span's BOUNDARY, not its value.**

## The boundary is 8 m too early, and geometry says so

The span exists to guard convex (crest) geometry. `d2z/ds2` through the span's opening:

| stn | s_m | d2z/ds2 | |
|---|---|---|---|
| 596 | 638 | **+0.00218** | concave — shipped `mbc_b_lo` starts here |
| 600 | 642 | +0.00149 | concave |
| 603 | 645 | +0.00003 | concave |
| **604** | **646** | **−0.00020** | **convex — the crest actually begins** |
| 612 | 654 | −0.00180 | convex |

**The shipped span clamps 8 m of concave track before the crest starts.**

## Proposal: `mbc_b_lo` 638 -> 646

`mbc_b_lo` is **already a tune key** -- no code change, and nothing else in the chain moves.

| zone | shipped | proposed | delta | human | vs human |
|---|---|---|---|---|---|
| RELEASED (8 stations, all concave) | 88.1 | **136.5** | **+48.4** | 135.8 | +0.7 |
| KEPT (the convex crest) | 130.2 | 130.2 | +0.0 | 134.5 | −4.4 |

- exactly **8 stations change** (596-603); every one has `d2z/ds2 >= 0`
- the first station still clamped is **604**, the first convex one
- **span A untouched**; lap-wide max change outside those 8 stations is **0.000 km/h**

**The boundary is set by where `d2z/ds2` crosses zero -- geometry, not the human's speed.** That
matters for CONSTRAINTS #3: human laps are evaluation targets, never operating bounds. The human
column above is the *check* that the result is sane, not the basis for it. I first picked 650 and
657 by fitting to the human's 134.5 and had to discard both -- they would have been human-derived
caps, which the constraint forbids.

## Where it slots

Queued after `abrake_k_075`, before `ksp_025`. One existing key, 8 stations, and the largest
per-station denial on the lap. It does not interact with `abrake_k` (braking model) or `ksp`
(curvature source); it moves `map_w` only.

Worth stating plainly: this is a fix to a boundary that was set by **round numbers**.
`mbc_a_lo/hi` = 470/608 and `mbc_b_lo/hi` = 638/702 are all suspiciously round. **The other three
boundaries deserve the same `d2z/ds2` check** before anyone trusts them.

---

# BLOCKED: the stored map there is an artifact, and the fix is not local

## Provenance of `map_w` at the 8 released stations

**1.5500 at all eight -- exactly the ceiling.** MBC has clamped these to 1.0 in use since 07-08,
so no value above 1.0 has ever been applied. History across every snapshot pair:

| when | map@596-603 |
|---|---|
| 07-03 (pre-MBC) | **0.8000** — the FLOOR |
| 07-07 (pre-MBC) | 1.5500 |
| 07-13 | 1.1900 |
| 08-01 | 0.8000 |
| **08-02 onward** | **1.5500**, pinned across ~20 consecutive snapshots over 4 days |

Boosting above 1.0 is free while the clamp is on -- the learner gets no feedback for it -- so the
value drifted to the ceiling and welded there. **It is the same ceiling-drift artifact identified
on the straights, not an earned number.** The one time these stations were plausibly exercised
(07-03, before MBC) they learned the FLOOR.

So releasing the boundary alone applies an **untested +48.4 km/h in a single step**.

## And the obvious fix does not work

Reset `map_w` to 1.0 at exactly the released stations, so day one is neutral and the learner
earns the boost live. Measured:

| | at stn 596-603 | upstream stn 579-595 |
|---|---|---|
| release alone | **+48.4** (untested) | 0 |
| release + reset to 1.0 | **+0.0** | **−47 to −62** (worst −62.3 at stn 584) |

**`map_w` is a window-MIN over the next 18 stations.** Writing 1.0 at 596-603 pulls down the
window-min for 17 stations upstream that sit OUTSIDE the MBC span and currently read 1.55 through
their lookahead. The reset is not local, and it cannot be made local by choosing a different
value: avoiding the upstream loss requires keeping 1.55 stored, which is precisely the untested
number. **The two goals are in direct conflict.**

This is the same window-min coupling that defeated the `ksp` map migration. Any edit to the
learned map propagates 18 stations backwards.

**Status: SOLVED at the USE level** -- see below. The storage-level fix stays rejected.

---

# Geometric audit: all four MBC boundaries are wrong, in both directions

The spans exist to clamp convex (crest) geometry. Where `d2z/ds2` actually crosses zero:

| boundary | value | at the boundary | error |
|---|---|---|---|
| `mbc_a_lo` | 470 m | **convex** (−0.00003) | **MISSES 30 m of crest** before the clamp starts |
| `mbc_a_hi` | 608 m | concave (+0.00376) | clamps **12 m** of concave track past the hazard |
| `mbc_b_lo` | 638 m | concave (+0.00218) | clamps **8 m** of concave track |
| `mbc_b_hi` | 702 m | concave (+0.00295) | clamps **6 m** of concave track past the hazard |

**Not one of the four sits on the geometry it exists to guard.** Three clamp non-crest track
(6-12 m each); one starts 30 m *late* and misses real crest -- so span A is simultaneously too
short at its entry and too long at its exit.

Findings only. Every one inherits the same artifact-and-coupling problem documented above, so
none is actionable until that is solved. Worth noting the direction: `mbc_a_lo` missing 30 m of
crest is a **safety** gap, not a speed one, and is the more interesting of the four.

---

# The fix: a use-time cap (`rzc`), not a storage edit

MBC itself clamps the *applied* `map_w` inside its span and never touches the stored map -- which
is exactly why upstream stations kept their 1.55. The released zone can work the same way.

```python
if rzc > 0.0 and rzc_lo <= s_of[i0] <= rzc_hi:
    map_w = min(map_w, rzc)
```

`mbc_b_lo` 638 -> 646 releases the 8 stations from MBC; `rzc` then caps them at use time.
**`rzc = 1.0` reproduces the MBC clamp exactly**, so the pair is bit-identical to shipped, and the
cap ramps from there in bounded steps. **No learner writes at any rung**, so the window-min
coupling never enters.

## Acceptance: verified

| config | @596-603 | delta | @579-595 | @604-660 | elsewhere |
|---|---|---|---|---|---|
| `mbc_b_lo=646 rzc=1.0` | 88.1 | **+0.0** | 0.0000 | 0.0000 | 0.0000 |
| `rzc=1.15` (rung 1) | 101.3 | **+13.2** | 0.0000 | 0.0000 | 0.0000 |
| `rzc=1.30` (rung 2) | 114.5 | +26.4 | 0.0000 | 0.0000 | 0.0000 |
| `rzc=1.55` (rung 3) | 136.5 | +48.4 | 0.0000 | 0.0000 | 0.0000 |

**Bit-identical at default: max |diff| 0.00e+00 across all 1000 stations.** At every rung the
delta is nonzero *only* at 596-603 -- zero upstream, zero across the crest, zero everywhere else.

Queued as `mbc_rzc_115` (rung 1) after `abrake_k_075`; rungs 2 and 3 conditional on clean windows.

---

# `mbc_a_lo` safety gap: real crest, no incidents -- WATCH ITEM

The 30 m of crest that `mbc_a_lo` misses (s=440-470, stations 415-441) is genuinely convex
(`d2z/ds2` mean −0.00138, against a lap p5 of −0.00262), so the geometry is real.

| | ticks | off-track | \|sideslip\| p99 | \|cte\| p90 | lat g p90 | slip p90 |
|---|---|---|---|---|---|---|
| **the gap** | 38,101 | **0.00%** | 3.50 | 2.82 | 1.53 | 1.60 |
| lap baseline | 741,339 | 0.55% | 9.30 | 3.37 | 2.55 | 2.58 |

**Zero off-track ticks in 38,101**, sideslip p99 2.7x lower than the lap, and none of the 25
worst off-track stations lap-wide falls inside it. The hazard is real geometry that is **not
currently biting**.

**Recorded as a watch item, no entry.** It costs speed to fix and buys nothing measurable today.
The reason to keep watching: it is unclamped crest, so if anything ever raises entry speed into
it -- `abrake_k`, or a future line change -- this is where a new excursion would appear first.
Re-check off-track at stations 415-441 after any arm that changes the approach.
