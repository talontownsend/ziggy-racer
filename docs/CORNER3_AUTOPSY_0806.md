# Corner 3 autopsy: the deficit is inherited, and the corners are not independent

Run: `python tools/corner3_autopsy.py`. Logs + the 08-02 human recording (50 laps). Farm down.

## Three claims of mine this overturns

**1. "Raw v_curve there is ~134 km/h" was a selection artifact.** I computed it as
`botTGT / map_w` over **code-3-binding ticks only**, which by construction selects the ticks
where `v_curve` is lowest. The logged `vcurve_kmh` across stations 880-925 is **168-220 km/h**.
Conditioning on a constraint binding and then reporting the constrained quantity's average is
circular; report it over the whole span.

**2. The grip model is not badly wrong here.** Refline radius over the span is **129 m** (not the
51 m I derived from the bad 134), implying **213 km/h** at `planner_alat = 27`. Human lateral g
is median 1.97, p90 2.74, against a model limit of 2.75 g. The human is inside the model.

**3. Corner 3 is not a lateral-saturation corner.** Full lock on **3%** of ticks,
`|steer|` median 0.34-0.62.

## The human is on the same line

| | value |
|---|---|
| \|offset\| from refline | median **0.99 m**, p90 2.44 m |
| signed offset | −0.56 m (marginally right) |
| track width | 12.6 m |

**Geometry is off the table.** There is no wider line being driven, so a refline rebuild buys
nothing here.

## The deficit is inherited from upstream

| station | s_m | bot | human | gap | botTGT | vcurve | code | bot brk | human brk |
|---|---|---|---|---|---|---|---|---|---|
| 800-809 | 858 | 109.7 | 152.1 | **+42.4** | 159.0 | 176.9 | 1 | 4% | 0% |
| 810-819 | 869 | 110.2 | 156.4 | +46.2 | 137.7 | 135.9 | **3** | **29%** | 0% |
| 820-829 | 879 | 115.8 | 161.1 | +45.3 | 136.4 | 143.2 | **3** | **24%** | 2% |
| 860-869 | 922 | 127.8 | 176.7 | +48.9 | 184.5 | 155.9 | 1 | 19% | 0% |
| 890-899 | 954 | 144.9 | 194.9 | +50.0 | 205.4 | 178.3 | 1 | 3% | 0% |
| 920-929 | 986 | 176.2 | 210.6 | +34.4 | 224.6 | 202.1 | 1 | 6% | 0% |

The gap is **already +42 km/h at station 800**, before the corner. Bot minimum through the
section is 109.0 km/h against the human's 149.9. Through 880-925 the bot is accelerating the
whole way (`a_long` +0.89 to +1.21 g) and simply never catches up.

**Corner 3's 71.8 km/h shortfall is a cascade, not a local failure.** Ranking corners
independently by code-3 deficit is therefore invalid, including my own ranking that produced it.

## Where it actually starts: stations 810-829 (= "corner 1")

The largest code-3 deficit on the track, and the origin of this cascade. Two problems stack:

- the cap (**136 km/h**) sits ~15% under what the human demonstrates (**156-161**)
- the bot then undershoots **its own cap** by 20-26 km/h, reaching only 110-116

and it brakes on **24-29%** of ticks there while the human brakes on **0-2%**.

## What this does and does not authorize

- **Refline rebuild: NO.** Paths match within 1 m.
- **Lateral redesign with corner 3 as testbed: NO.** 3% lock there; wrong corner.
- **Open and unresolved:** why the bot brakes 24-29% where the human brakes 0-2%, and why it
  undershoots its own cap by 20-26 km/h at 810-829. That is the origin, and it should be
  autopsied the same way before any multi-hour arm.

The braking finding sits awkwardly against "the brake cannot reach the deficit"
(BRAKE_SIDE_CLOSED_0803.md), which showed the brake branch is reachable only at
`err <= 1.0 m/s`. Braking is plainly happening here at 24-29%. Either the closure generalised
from a span where it held, or the branch is reached another way. **Recheck before trusting
either.**
