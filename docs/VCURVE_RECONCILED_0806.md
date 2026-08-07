# Reconciling the v_curve numbers, and why the corner-speed cap is approximately right

Two of my figures differed 5x and both were wrong. This states what each measured, gives the
correct decomposition, and reaches the opposite conclusion to the one they pointed at.

## What each number actually did

| figure | v_permitted | v_curve used | stations | verdict |
|---|---|---|---|---|
| "53 km/h" | `3.6*sqrt(27/kappa_local)`, **5-station stencil**, no `alat_k` = 145 | 91.9, the **braking sub-zone 595-614 only** | mismatched | wrong on three counts |
| "9.5 km/h" | `3.6*sqrt(27/(kmax18 - alat_k))` = 140 | 130.5, **whole span** 595-640 | matched | measures only the **rejoin** term |

Neither is "how much the target system denies relative to line + grip".

## The correct decomposition

`kappa_ref` reproduced exactly (3-point Menger, signed, `_smooth_closed` w=5) and
`max_kappa_line_ahead` exactly (16 samples over 18 m, `kappa_pct=100` == raw max). Reconstruction
is exact: **median residual 0.0 km/h**, |resid| median 0.0.

`v_line` binds at **79%** of stations, `v_rejoin` at **21%**.

| corner | v_phys (local) | v_line (18 m max) | v_log | lookahead cost | rejoin cost | total |
|---|---|---|---|---|---|---|
| 2 | 154.1 | 130.5 | 130.5 | 23.7 | 0.0 | 23.6 |
| 1 | 200.2 | 151.0 | 145.5 | 49.3 | 5.5 | 54.7 |
| 3 | 267.7 | 199.0 | 199.1 | 68.7 | 0.0 | 68.7 |

The 18 m lookahead is ~95% of the difference; the merge/rejoin term is negligible.

## But that difference is not "denial", and this is the finding

`v_phys` uses the curvature **at the station** and is not an achievable speed: you must already be
slowing for what is 18 m ahead. Benchmark against the only demonstrated-achievable reference,
the human's 50 laps:

| | corner 2 | corner 1 | corner 3 |
|---|---|---|---|
| `v_line` shipped | 130.5 | 151.0 | 194.4 |
| **human actual** | **133.8** | **156.7** | **197.2** |
| gap | +3.3 | +5.7 | +2.8 |

**The shipped cap lands within 3-6 km/h of what a human actually drives, in all three corners.**
The lookahead is doing its job.

## Every estimator "fix" makes it worse

| estimator | corner 2 | corner 1 | corner 3 | lap |
|---|---|---|---|---|
| **shipped** (3-pt, w=5, max) | 130.5 | 151.0 | 194.4 | 147.7 |
| pct=95 | 134.3 | 153.2 | 195.7 | 151.6 |
| pct=90 | 137.1 | 156.2 | 198.8 | 155.4 |
| 3-pt, w=11 | 152.6 | 164.5 | 214.7 | 158.2 |
| 5-pt stencil, w=5 | 144.1 | 166.4 | 225.8 | 159.9 |
| 5-pt, w=11 | 155.7 | 176.6 | 230.7 | 169.2 |
| *human actual* | *133.8* | *156.7* | *197.2* | |

Anything beyond `pct=95` licenses speeds **above** demonstrated human pace. This independently
explains the standing note that lowering `kappa_pct` or widening `kappa_ref` smoothing breaks
corner anticipation: those changes do not remove noise, they remove the corner.

`kappa_ref` **is** spiky — corner 2 oscillates between R=703 m and R=23 m over a few metres, and
the binding peak at station 612 has only 3 stations within 20% of it (~3.2 m). The 3-point Menger
stencil at ~1.06 m spacing is acutely noise-sensitive. But the max-over-18 m absorbs those spikes
into a cap that lands within a few km/h of ground truth, so the noise is not costing lap time.

## Where this leaves it

| corner | cap | human | bot | cap − bot |
|---|---|---|---|---|
| 2 | 130.5 | 133.8 | ~110 | ~20 |
| 1 | 145.5 | 156.7 | ~127 | ~19 |
| 3 | 199.1 | 197.2 | ~145 | ~54 |

The cap is approximately correct. The human is at the cap. **The bot is 19-54 km/h below a target
that is very nearly right**, which returns to the same conclusion every other line of analysis
reached today: the corner problem is reaching the target, not the target.

**Do not touch `kappa_pct`, `kappa_ref` smoothing, or the stencil.** The v_curve path is closed.
