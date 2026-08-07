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
