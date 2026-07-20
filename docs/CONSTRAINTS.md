# Ziggy Racer — Project Constraints & Operating Principles

These are the rules this project runs by. Most were paid for with lost soak-hours; the ones
marked **(measured)** were established by a specific experiment rather than by decision.

---

## 1. Design principles

### 1.1 Independence principle
**Human data is for evaluation and reference only — never an operating bound.**
The bot must determine its own capabilities from its own telemetry (the self-learned speed map,
the measured steering map, the grip model). The one standing exception, chosen deliberately: the
**reference line** is the human's recorded best lap (computed line solvers failed — six attempts,
all inside-hugging; and the measured-constraint optimizer later *confirmed* the human line is
near-optimal under the bot's own limits **(measured, 07-20)**). Human lap times set the goal
ladder (30.873 keyboard → 27.285 Ana → 27.28 → **25.679 PB**) — they are targets, not caps.

### 1.2 Generalizability
**Mechanisms, not patches. No track-position hardcodes in the shipped control path.**
Anything keyed on arc-length literals is presumed wrong until it has a mechanism-level
replacement. Current status of the exception list:
- **`mbc` spans (s470-608, s638-702)** — literal, but retained deliberately: the survey-derived
  alternative (`mbc_geo`, zero literals) was built and A/B'd twice; its zones under-protect the
  crest *exits* and cost +0.75s→worse **(measured, 07-09 & 07-20)**. Policy: `mbc_geo` is the
  **new-track bootstrap**, literal spans are **this track's tuned override**.
- **`hul` span (s515-565)** — same policy. The condition-based form (`hul_cte`) is wrong-signed
  at sharp corners (aiming at the line during a wide hairpin recovery demands infeasible turn-in;
  9 stalls/45min **(measured, 07-09)**). A curvature-feasibility-gated version is future work.
- **Hairpin map seed — ELIMINATED (07-17).** Was a hand-written delta; replaced by the wedge-cut
  mechanism (§4.4). Zero hand-written map values remain.
Everything else in the shipped path is mechanism-level: measured maps keyed on (κ, v), survey-
derived hazard cores, self-learned per-station speed, physics-conditioned gates.

### 1.3 The car's measured limits are the planning limits
Speed targets, feasibility, and braking all come from **measured** artifacts, each with a
validity envelope (see §5). Raising a cap the tracking can't use produces zero lap time
**(measured: mbc 1.15 delivered +9-12 km/h locally and was net slower)**.

---

## 2. Experimental method (the A/B rules)

1. **Never A/B over a live learner.** The vtrim map adapts to whatever you're testing and
   contaminates the comparison. Freeze it for scored windows (`vtrim_up/dn/cut/netscale = 0`
   **with `vtrim_on=1`** — setting `vtrim_on=0` removes the map's speed boost instead of
   freezing it), or run long equilibrium windows and compare equilibria.
2. **~30 min re-equilibration after any config change.** Short windows measure the transient,
   not the config (S11 re-carves itself after every zone change **(measured)**).
3. **Calibrate every threshold on the current config before using it as an abort.** The steer-
   reversal ("hunt") metric reads 5.3-6.2/s on healthy production; an uncalibrated 4.5/s tripwire
   false-aborted a good rung **(measured, 07-16)**.
4. **Abort monitors must ACT, not report.** A monitor that prints "HARD ABORT" without writing
   the revert key lets a failed arm run 40 minutes **(happened, 07-13)**. Every arm carries a
   monitor that writes the rollback itself (hot-reload picks it up in <0.5 s).
5. **Compare condition-matched, never aggregate.** Aggregate pedal-decel medians "changed -8%"
   after the game update; speed-matched bins showed ±1 m/s² = unchanged **(measured, 07-14)**.
   Same for steering probes (match κ, v, load, brake state).
6. **Fresh windows only; session-aware scans.** Cumulative windows double-count earlier bad
   periods (false degradation alarm, 07-09); follower restarts reset `t` in follow_log — scans
   must detect t-discontinuities. Watchdog restarts silently disarm hot keys mid-window
   (`bc_w_eff`-style effective-state log columns make that visible; a restarted window is void).
7. **Dedupe event counts.** Wedge episodes multi-count within ~60 s; stall counters overstate
   without clustering.
8. **ABAB discipline.** A washout that beats both arms means session drift, not a win
   **(caught the BC-blend "gains", 07-13)**.
9. **Judge frozen-map arms on in-zone metrics; validate downstream with learning on.** Frozen
   arms overstate downstream breakage — the deployed learner absorbs new arrival speeds by
   design (M1→M2, S11 self-heal in ~6 min **(measured)**).

---

## 3. Control-law lessons (constraints on future changes)

- **Compensate latency/braking with ONSET, never GAIN.** Raising `brk_ff` causes throttle/brake
  branch-chatter that *halves* delivered braking **(measured twice: N1 07-08, brk_ff-recal
  07-14)**. The onset knobs are `bla_tau` (brake anticipation) and `t_ff` (steering FF lead).
- **Never cap a corner EXIT.** Exit speed deficits compound down the following straight
  (-0.5 s/lap **(measured, geo-v1)**). Boost-caps cover approach + turn only.
- **Anticipate the onset, never move the setpoint.** The brake-lookahead (`bla`) v1/v2 both
  over-braked by desc·τ because the anticipated error leaked into release/pressure. Entry
  condition only; pressure = FF(descent) + P(plain error); release at the plain target.
- **Feedforward saturates.** `ffm_w=0.15` is optimal; 0.30 is strictly worse (loop friction
  without added line-holding) **(measured, 07-17)**. Reactive gains must shed as FF grows
  (`ffm_gsc`), or the loop chatters at 8/s.
- **Full-stick = front tires at their limit.** The game's speed-sensitive steering puts the
  fronts at/past the grip peak at 100% stick; `fc_frac` is TOTAL grip and stays submaximal in
  understeer (rear loafing). "Steering authority ceiling" framings are wrong — see 07-08 notes.

---

## 4. Operational constraints

1. **UDP port 7777 is exclusive.** One listener: the follower OR the hot-lap recorder
   (`record_my_laps.ps1` refuses to start if the follower is up). Concurrent probes read
   false-negative.
2. **tune.json is wiped at follower startup** (rewritten from args) **and overwritten by
   watchdog `$addKeys` after every restart.** Any hot key not in `$addKeys` silently reverts on
   restart. This is also the **dead-man disarm** for experimental keys (`bc_on`, etc.) — intended.
3. **A running watchdog holds its script in memory** — edit `watchdog.ps1`, then restart the
   watchdog, or the edit does nothing.
4. **Wedge-cut mechanism (07-17):** incident-cuts fire whenever the car is stopped off-track
   ≥0.5 s, regardless of launch state (once per episode). Credits remain launch-gated. This
   closed the wedge-loop blind spot; do not re-gate cuts on `launched`.
5. **After any game update, run the post-update checklist** (docs/OPERATIONS.md §5). The 07-13
   update changed **no physics and no settings** but added **+28 ms input latency** — invisible
   to every physics probe; only the steer→yawrate cross-correlation catches it.
6. **Archive `follow_log.csv` before any manual relaunch** (startup truncates it; the watchdog
   archives automatically). A 9-hour soak was lost this way once.
7. **TALONSPC hard-crashes (bugcheck 0x154) every few days.** Overnight infrastructure must
   survive reboots conceptually (watchdog cap 30, checkpointed analysis, frequent commits).

---

## 5. Measured artifacts and their validity envelopes

| Artifact | What it is | Envelope / caveats |
|---|---|---|
| `recordings/steer_ff_map.npz` | \|stick\| needed for (κ, v), fit from bot telemetry | Steady, flat, no-brake cornering only. Gated off under braking & light load at runtime. Latency-independent (confirmed across the 07-13 update). Rebuild per car via `tools/` fit snippet in git log `3374e97`. |
| `recordings/vtrim_*.npz` | Self-learned per-station speed map (net+delta) | Learning rates are part of the tuned config: `up=0.0002, dn=0.002, cut=0.03`. Faster re-earn (0.0005) is a churn-recovery crutch only — as an operating rate it erodes learned protection. |
| Grip model (in follow.py) | measured a_lat ceiling + downforce + load + friction circle | Total-grip; does not resolve front/rear (see §3 full-stick note). |
| Pedal-decel curve | full pedal ≈ 26-28 m/s² | Speed-matched comparisons only. |
| `line_opt_solver.py` model (tools/) | Offline lap-time simulator | Calibrated within 0.05 s of the bot's real median (07-20). Use for what-ifs before burning farm time. |

---

## 6. Current goal state (as of 2026-07-20)

- Deployed stack: `ffm 0.15 · gsc 0.5 · t_ff 0.21 · bla 0.70 · mbc 1.0 (literal spans) ·
  hul 515-565 · wedge-cut · learning 0.0002/0.002/0.03`.
- Performance: **med ~30.0-30.3, best 29.28, ~1 stall/90 min** (first sub-30 median 07-20).
- Human PB target: **25.679** (set post-update — the +28 ms latency is human-adaptable).
- The remaining gap is **driver-grade commitment through steering-limited corners** (confirmed
  independently by vtrim2, the same-controller human comparison, and the lap model). Paths:
  recorded-PB line/targets rebuild (`record_my_laps.ps1`), and learning-based control on the
  bot's own states (bounded imitation blending measured insufficient — see docs/ history).
