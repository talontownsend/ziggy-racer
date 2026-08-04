# The brake side is closed, and it closes by construction

Eighteen would have been the arm count. There is no eighteenth worth a window.

## The brake cannot reach the deficit

`follow.py:1913`:

```python
if err >= 0 and (err_b >= 0 or err > 1.0):   # throttle branch
else:                                        # brake branch
```

The brake branch is reachable **only when `err <= 1.0 m/s`**. Measured over 59,205 brake ticks:
**max `err` on any brake tick = 1.000000 m/s = 3.60 km/h.** Not approximately: the predicate is
the bound.

| quantity | s/lap |
|---|---|
| whole own-target control gap | **2.491** |
| the slice sitting on brake ticks | **0.027 (1.08%)** |
| delivery-limited slice (`tgt - v > 10 km/h`), 44.1% of ticks | **2.223** |
| fraction of those ticks with brake applied | **0.00%** |

The 2.22 s/lap that is 67% of the gap lives entirely in a state the brake **cannot occupy**.
This is not a small effect, it is a structural impossibility, and it holds for any brake-side
change of any magnitude.

## And the brake's own budget is under the floor

Most generous verified ceiling: **~0.17 s/lap**, of which 79.6% accrues *after* the pedal has
released (re-acceleration through the already-saturated delivery channel, not brake-attributable).
Genuinely pedal-down slice: **0.016 s/lap**. The measurement floor is 0.30 s.

On the metric actually scored, the median lap:

| candidate | mean s/lap | **median s/lap** | laps with zero footprint |
|---|---|---|---|
| `gov_floor` (pdg / bind 4) | 0.0000 | **0.0000** | 85/85 |
| cte governor headroom | 0.0080 | 0.0088 | 34/85 |
| all brake | 0.0271 | 0.0266 | 0/85 |

## The two candidates I most expected to survive

**`gov_floor`.** The boundary defect is real and confirmed at source: when the governor binds
with `g~=1` its cap is `spd + 1.0`, `err` lands at exactly 1.0, the strict `> 1.0` fails, and
control drops into the brake branch. But it moves the **median lap by 0.000 s** (34 of 85 laps
have zero governor braking). Worse, the required floor is state-dependent
(`F > 1.0 + 0.5*spd*(1-g)`), so a fixed floor only translates the trap outward to where `g` is
lower and the target step is larger. It re-forms, worse. And governor incidence is a *symptom
sensor*: 0.008 s/lap here against 0.46 s/lap in the failed PADCLAMP_TC arm. It would be tested
where it costs nothing and load-bearing where it costs something.

**`pdg_gain`.** Causal estimate +0.095 s/lap, CI [-0.038, +0.227], which **flips to -0.094 s/lap**
once the placebo exposure and `|cte|`/`|psi|` are controlled, negative in all four logs
independently. `corr(bind4 dwell, lap time) = -0.227`; the top tercile is 0.29 s **faster**.
`plan_degraded` is a consequence of carrying speed (`klim ~ a_lat/v²`), not a cause of losing it.

## Operational gotcha worth keeping

`watchdog.ps1` force-writes `pdg_gain=0.0` into `tune.json` on every restart, so any arm that
bundles it silently decomposes mid-window. The same applies to every key in `$addKeys`: check it
before bundling.

## Standing count

**Seventeen arms, no lap-time gain, and the eighteenth axis closed without spending a window.**
Five single-axis relaxations, three joint-axis, three feedforward, six pad_clamp; plus the path
route (inert: all five worst corners are delivery-limited) and now the brake side (unreachable
by construction). The relaxation prior is 0 for 6.
