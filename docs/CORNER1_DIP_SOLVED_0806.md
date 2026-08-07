# The corner-1 dip is the cross-track governor, and it explains the ileak result

> **PARTLY SUPERSEDED (see docs/STATE_OF_KNOWLEDGE_0806.md, item 5 and section 3b).** The governor identification is correct and exact. But the cascade costs only ~0.38 s (11% of the gap), not the dominant share implied by its 70% tick count -- time, not tick share, is the currency.

The largest single loss chain of 08-06. Traced to the decimal; two of my own attributions were
wrong first. Run: `python tools/tv_trace.py`. Logs and code only, farm down.

## It is not `tv`, and it is not `v_curve`

`tv` reproduced exactly from the follower's own braking pass: **median error +0.00 km/h, p90
|err| 0.04, 100% within 1 km/h** across 584 stations where `bind_code==1`.

With `vown_w = 0.0`, `vplan_eff = vplan` — the human reference lap's speed profile. The
multi-scale curvature `_kl` and `v_own` are computed at startup but **unused**, so the
R=23-class spikes are NOT reaching `tv` by a second path. That hypothesis is dead.

At the dip, `tv` predicts **153.5** km/h and the log says **119.7**. So `tv` does not set it
either. `bind_code 3` fires on 1-3% of ticks there, so `v_curve` does not set it.

## It is `bind_code 6`, the cross-track governor

| stn | logTGT | bot | \|cte\| | plan/tv | v_curve | **cte gov** |
|---|---|---|---|---|---|---|
| 786 | 124.3 | 123.3 | 5.73 | 30% | 0% | **70%** |
| 790 | 121.5 | 119.3 | 5.57 | 30% | 0% | **70%** |
| 795 | 119.7 | 114.9 | 5.21 | 37% | 2% | **61%** |
| 796 | 120.8 | 113.8 | 5.09 | 43% | 2% | **55%** |
| 797 | **154.1** | 112.8 | **4.98** | 50% | 1% | 49% |

Formula confirmed exactly: `max(spd*(0.5+0.5g)+1.0, 4.0)` with
`g = 1 - (|cte| - cte_soft)/(cte_hard - cte_soft)` predicts **115.6** vs logged **115.6**
(err −0.0). `cte_soft = 5.0`, `cte_hard = 25.0`.

**The car arrives at corner 1 already 5.7 m off-line**, trips the governor, and the target
collapses to roughly its own current speed. **A governed car cannot accelerate — only hold.**
The dip releases the instant `|cte|` crosses back under 5.0 at station 797, where the target
steps 120.8 -> 154.1.

Cost where it binds: target **115.7** vs **153.5** ungoverned = **37.8 km/h denied**.

## This is the mechanism behind the ileak result

`cte_ileak 0.5` does not touch the governor. It reduces `|cte|`, so the governor trips less:

| | \|cte\| | gov binds | target | speed |
|---|---|---|---|---|
| ileak 0.0 (corner-1 entry) | 5.37 | **67%** | 120.7 | 115.5 |
| ileak 0.5 (corner-1 entry) | 5.08 | **53%** | 125.5 | 117.7 |
| ileak 0.0 (whole lap) | p90 3.33 | 3.44% of ticks | | |
| ileak 0.5 (whole lap) | p90 3.09 | **2.42%** | | |

Ticks with `|cte| > 5.0` fall 3.4% -> 2.4%. That is a complete, quantified causal chain for the
−0.51 s: less cross-track error -> fewer governor trips -> 37.8 km/h of target restored at the
corner entries where it was binding. **It is the best-founded mechanism found all day**, and it
raises the value of the pending replication.

## Why this does not mean "relax the governor"

Raising `cte_soft` was tested twice and lost: off-track went 0.05% -> 2.24%. The guard is
load-bearing. **The lesson is the opposite one — do not weaken the guard, avoid the condition
that trips it.** `cte_ileak` works precisely because it reduces `|cte|` rather than tolerating it.

Two consequences for what to work on:

1. **Anything that reduces `|cte|` pays through this channel**, at 37.8 km/h per governed tick.
   That is a far larger and better-evidenced lever than the curvature estimator.
2. **The governor's formula ties the target to current speed**, so the recovery is
   self-limiting: a car that is off-line and slow is given a target barely above its own speed,
   and has no authority to climb out. A governor that permitted *some* acceleration while
   off-line (e.g. floor at a fraction of the ungoverned target rather than at current speed)
   would break the cascade without weakening the excursion guard. **Untested, and the most
   promising unexplored change on the board.**

## Corrections

1. "The dip is set by the plan's `tv`" — wrong. `tv` there is 153.5.
2. "The same kappa spikes drive `tv` by a second path" — wrong. `vown_w=0`, so `_kl` and
   `v_own` are dead code in the live config; `tv` reads the human speed profile.
