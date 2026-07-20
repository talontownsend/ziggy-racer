# Ziggy Racer

**An autonomous, self-taught racing driver for Forza Horizon 6 — a full control stack that learns a race circuit from physics and its own experience, then drives it at the limit through a virtual gamepad.**

![Ziggy Racer driving Shimanoyama Circuit with the live telemetry HUD](docs/media/ziggy_driving.gif)

*Ziggy on Shimanoyama Circuit — every input (steering gauge, throttle/brake bars, gear) is being generated in real time by the controller from the telemetry stream, not by a human.*

Ziggy reads the game's ~71 Hz telemetry stream (position, velocity, yaw, per-wheel slip, suspension load, surface roll/pitch), runs a complete sense → plan → act control loop in real time, and injects steering, throttle, and brake through a virtual Xbox controller. No memory hacking, no scripting the game's own AI, no reading the game's internal state — it drives exactly like a human would: from what the sensors say, through the pad, one 14-millisecond tick at a time.

The car is a modded X-class Toyota Tacoma; the track is **Shimanoyama Circuit**. It laps consistently and unattended for hours, and it has taught itself to be **competitive with Forza's own driving AI** — its best clean lap sits about a second off the game's built-in Auto Drive and about two seconds off the human it learned from:

| Driver | Best clean lap (Shimanoyama Circuit) |
|---|---|
| **Ziggy Racer** (this controller, self-taught) | **28.36 s** |
| Ana — Forza's built-in *Auto Drive* AI | 27.29 s |
| Talon Townsend (human reference) | 25.68 s |

A ~2.3 s gap to a skilled human, closed entirely from physics and the car's own experience — and still closing, one corner at a time.

> **Why this is unusual.** Most "self-driving in a game" projects either read the game's internal physics state directly or replay a scripted line. Ziggy does neither. It identifies the car's grip envelope from telemetry, plans a feasible path each tick, modulates the pedals to a measured friction circle, and — crucially — **learns which corners it can actually carry speed through from its own slides.** It is a controls-engineering project that happens to run inside a video game, not a game bot that happens to use some control theory.

---

> **Project docs:** [docs/CONSTRAINTS.md](docs/CONSTRAINTS.md) (design principles & operating rules) ·
> [docs/PROJECT_MAP.md](docs/PROJECT_MAP.md) (repo layout) · [docs/OPERATIONS.md](docs/OPERATIONS.md) (runbook)

## Table of contents

- [What it does](#what-it-does)
- [Architecture: the sense → plan → act loop](#architecture-the-sense--plan--act-loop)
- [The control theory, made explicit](#the-control-theory-made-explicit)
- [The offline track-survey → physics-model pipeline](#the-offline-track-survey--physics-model-pipeline)
- [The hardest problem solved: the S9 crest-turn](#the-hardest-problem-solved-the-s9-crest-turn)
- [Experimental methodology](#experimental-methodology)
- [Autonomy: the AFK recovery state machine](#autonomy-the-afk-recovery-state-machine)
- [Tech stack](#tech-stack)
- [Module guide](#module-guide)
- [What it can't do (yet)](#what-it-cant-do-yet)
- [Setup](#setup)

---

## What it does

Given only a recording of the track's boundaries and a reference lap, Ziggy will:

1. **Localize** itself on a precomputed racing line every tick, in a Frenet (arc-length / lateral-offset) frame.
2. **Plan** a short, smooth, grip-feasible *merge trajectory* from wherever the car actually is back onto the line.
3. **Steer** with a curvature feedforward + cross-track PID + pursuit-heading term, plus load compensation and slide-catching counter-steer.
4. **Modulate the pedals** ("the foot") against a measured friction circle so it corners at the grip limit instead of flooring-and-clawing-back.
5. **Cap its own corner speeds** from a closed-form surface-physics model built by surveying the track, and *refine those caps from its own experience* via a self-calibrating per-corner speed map.
6. **Recover itself** from crashes, menus, disconnect dialogs, and even accidental map/store screens — so it farms unattended for hours.

Everything is a **pure heuristic controller**: closed-form physics plus a few interpretable learned scalars. There is no black-box neural net in the driving path.

---

## Architecture: the sense → plan → act loop

```
                         Forza Horizon 6  "Data Out"  UDP :7777   (~71 Hz, 324-byte packets)
                                                │
                                                ▼
   ┌──────────────────────────────────────────────────────────────────────────────────┐
   │  SENSE            fh6_telemetry.py — parse packet → Frame                            │
   │   pos / vel / yaw │ ax,ay,az (car-local g) │ per-wheel slip ratio + slip angle       │
   │   + combined slip │ suspension via ay load │ roll / pitch │ race_position            │
   └──────────────────────────────────────────────────────────────────────────────────┘
                                                │
                                                ▼
   ┌──────────────────────────────────────────────────────────────────────────────────┐
   │  LOCALIZE + PLAN   local_planner.py                                                 │
   │   • windowed nearest-point localization on the racing line (monotonic, no snapping) │
   │   • Frenet state (d, d', d'')  where d = cross-track offset                          │
   │   • QUINTIC merge trajectory  (d0,d0',0) → (0,0,0)  over a speed/offset-adaptive     │
   │     horizon; sample 5 horizons, score by cost, pick the best (temporal hysteresis)  │
   │   • feasibility checked on the MERGE-ADDED curvature only — the planner corners      │
   │     instead of rejecting every corner as "too tight"                                │
   └──────────────────────────────────────────────────────────────────────────────────┘
                                                │
                          ┌─────────────────────┼─────────────────────┐
                          ▼                                            ▼
   ┌──────────────────────────────────────────┐  ┌──────────────────────────────────────┐
   │  ACT — STEERING (follow.py)               │  │  ACT — SPEED / "THE FOOT" (follow.py) │
   │   steer =                                 │  │   target_v = min(                     │
   │     k_ff·κ·load_comp   (feedforward)      │  │     braking-anticipated plan speed,   │
   │   + k_head·α           (pursuit heading)  │  │     v_curve = √(a_lat(v)/κ)  cornering,│
   │   + PID(cross-track e)  (feedback)        │  │     surface-physics cap,              │
   │   + counter-steer(β)    (slide catch)     │  │     self-learned per-corner trim,     │
   │   → slew-limited stick                    │  │     adaptive crest margin )           │
   │                                           │  │   throttle/brake ← friction circle    │
   │                                           │  │     + anti-lock + anti-windup integral│
   └──────────────────────────────────────────┘  └──────────────────────────────────────┘
                          │                                            │
                          └─────────────────────┬─────────────────────┘
                                                ▼
   ┌──────────────────────────────────────────────────────────────────────────────────┐
   │  OUTPUT   vgamepad (ViGEmBus) — virtual Xbox 360 pad: L-stick X, triggers, shifts   │
   │  SAFETY   drives only while FH6 is foreground; Ctrl+C / alt-tab releases all input  │
   └──────────────────────────────────────────────────────────────────────────────────┘
                                                │
                                                ▼
                              AFK recovery state machine (afk_recover.py)
                     off-track · wedged · menu · disconnect dialog · results · free-roam
                                → OCR + gamepad nav back to a live race
```

The whole loop runs in **numpy only**, well under a millisecond per tick, comfortably inside the ~14 ms telemetry budget.

---

## The control theory, made explicit

This project is, at heart, an exercise in classical process/motion control applied to a fast, nonlinear, load-transferring plant. The interesting parts:

### 1. Feedforward + feedback steering

The steering command decomposes cleanly into an open-loop **feedforward** and a closed-loop **feedback** part:

```
steer = k_ff · κ_ahead · load_comp        ← FEEDFORWARD: bend the wheel for the corner you can see
      + k_head · α                          ← pursuit heading alignment
      + kp·e + ki·∫e + kd·ė                 ← FEEDBACK: PID on cross-track error e
      + counter-steer(sideslip)             ← slide catch (applied last)
```

The feedforward reads the **stable racing-line curvature** a preview distance ahead (speed-scaled), *not* the per-tick planned-path curvature. That distinction was load-bearing: feeding the wobbling merge-path curvature back into the feedforward created a **planner ↔ tracker limit cycle** — the plan re-anchored to the car, the car chased the plan, and the two rang together into a bang-bang steering oscillation through the hairpin. Anchoring the feedforward to ground-truth line geometry broke the loop. This is a textbook lesson in *not closing a fast inner loop through a signal that itself depends on the loop's output.*

### 2. Anti-windup

The cross-track integrator (`cte_int`) is clamped (`±3`), and integration is **suppressed while the actuator saturates** — the throttle integral stops accumulating once the grip cap binds, and an optional steer-clip anti-windup bleeds the integrator when the wheel is pinned at full lock and the integrator is winding the same direction. Classic integrator anti-windup, in two channels.

### 3. The friction circle (tire modelling)

The "foot" treats each tire as having a finite grip budget shared between lateral and longitudinal forces — the **friction circle**. Available longitudinal grip is

```
fc_frac = √( 1 − (a_lat_now / a_lat_max(v))² )
```

where `a_lat_now = |measured car-local lateral g|` and `a_lat_max(v)` is the speed-dependent grip envelope. Corner hard → little throttle/brake headroom; on a straight → full headroom. This is what lets the car brake and accelerate *at* the limit rather than bang-bang around it.

### 4. Load transfer and downforce (vertical dynamics)

Grip is not constant — it scales with vertical tire load. Ziggy models this from **live measured vertical acceleration**:

```
load_factor = 1 + a_y / g          grip_scale = load_factor^0.705
```

The 0.705 exponent is a fitted tire load-sensitivity. Over a crest the car goes light (`load_factor` → ~0.66), grip drops ~21 %, and the foot lifts *before* the rear steps out; in a compression the extra load is cashed as extra grip. The steering feedforward carries the **same** load term (`ff · load_comp`) so the wheel angle grows as load falls — the extra steer arrives *before* the wash, like a driver who sees the crest coming. Downforce is folded into the cornering model as `a_lat(v) = a0 + k·v²`.

### 5. System identification from telemetry

Nothing about the car's limits is hand-guessed at runtime — they are **identified**:

- The grip envelope slope `k ≈ 0.0025` and intercept `a0 ≈ 26 m/s²` were fit from the reference driver's lateral-g-per-speed-bin data, then cross-checked against the car's in-game tuning-menu stats (the fitted slope matched the menu-derived slope within 4 %, and the game-vs-menu friction scale came out a consistent ~1.55× — two independent sources agreeing).
- Braking decel (`A_BRAKE ≈ 25 m/s²`) and full-pedal decel (`30 m/s²`) are measured, not assumed.
- The per-corner surface/load corrections come from an **offline survey** (below) and from the car's **own logged laps**.

### 6. ESC-style over/understeer logic

A yaw-rate reference `r_des = v·κ` is compared against filtered measured yaw rate. **Oversteer** (`|r_meas| > |r_des|`, same sign) triggers a counter-steer damping term; **understeer** (`|r_meas| < 0.75·|r_des|`) eases the speed target so the front regains grip. A separate **sideslip-angle** detector catches four-wheel slides the yaw-rate flag misses (a slide where the car rotates *less* than commanded while skating wide) and blends the steering from path-lock toward counter-lock as the slide develops.

### 7. Brake & throttle feedforward (killing standing error)

Both pedals were originally pure-proportional and so needed a *standing error* to hold pedal — the brake equilibrated at half-pedal, 40 m late, finishing its braking inside the corner where the friction circle then blocked it. The fix is a **brake feedforward** that commands the pedal delivering the target's own descent rate up front (mirroring the steering's preview), plus a **throttle integral** with anti-windup that supplies the standing pedal so the P-term only trims transients. Both are direct analogs of feedforward control eliminating steady-state offset.

---

## The offline track-survey → physics-model pipeline

This is the chemical-engineering heart of the project: **fit a model to data, then solve the closed-form physics.**

Ziggy autonomously **surveys the whole circuit** — `survey_plans.py` generates nine offset racing lines (−4 m … +4 m laterally, corridor-clamped) and an orchestrator drives all of them at gentle speeds over ~40 unattended minutes, logging position, elevation, roll, and pitch across the full width of the track.

`build_surface_sheet.py` then fits a per-station quadratic surface model

```
y(s, d) = a(s) + b(s)·d + c(s)·d²
```

giving, at any lateral offset: the road **elevation**, the **bank angle** (`tan θ = ∂y/∂d`), and the surface **curvature** (crown, crest, compression). The fit is validated hard: bank at the racing line reproduces the driver's ground-truth camber ("S12 is banked", "S11 feels off-camber") and cross-checks against telemetry roll at **corr −0.99**. The fit is defended by three permanent data-hygiene filters born from real artifacts: a coverage-bounded quadratic (never extrapolate curvature past surveyed span), a conditioning guard (narrow spans fit line-only), and a **grade-relative** outlier gate (reject samples whose along-path slope deviates from the road's local grade — *never* an absolute threshold, because legitimate physics reaches its extremes exactly where the interesting features live).

`build_surface_cap.py` then closes the physics. At each station it solves, by fixed-point iteration, the full 3-D cornering balance:

```
v²·κ·cos θ − g·sin θ  =  a_lat(v) · load(v)^0.705
                                                                bank assists the turn
load(v) = cos θ + z''·v²/g + (v²·κ/g)·sin θ                     crest/compression + bank load
```

The output is a per-station speed cap, smoothed with a **brake cone** (`√(v² + 2·A·d)`) so every cap drop has a physically-brakeable approach ramp — a hard-won lesson: a bare speed-cap step becomes 1.5 g of braking mid-corner. The cap is bounded to ±25 % of the flat-world value, because corrections beyond that are almost certainly fit artifacts, not physics.

The philosophy (the "final-product principle"): per-station tables and feature-nets are **dev-time instruments** whose job is to *reveal* structure; that structure is then re-expressed as closed-form terms computable on any surveyed track — the acquisition procedure is entirely track-agnostic.

---

## The hardest problem solved: the S9 crest-turn

This is the centerpiece, and it is worth reading as a case study in disciplined diagnosis.

**The symptom.** At one corner — a light crest sitting inside a turn (internally "S9") — the car kept sliding. It would arrive, wash wide or over-rotate, and either go off or scatter its exit so badly that the *next* two corners fell apart too. This single zone put an incident in roughly every other lap, and because **incident frequency drives the lap median far more than raw section pace**, killing it was worth ~1 second of median lap time.

**The wrong diagnoses, ruled out.** The obvious levers all *looked* plausible and all **failed** in testing:
- Anti-windup on the saturating wheel — no effect (`13.3` incidents/1k).
- P-term restoration in the grip-return window — slower, +3.8.
- Anticipatory throttle-hold — kill-zone incidents *up* to 20 %.
- Heading de-weighting — 20 %.
- Steering slew-rate limiting on the crest — **catastrophic**, 40/1k.

**The real diagnosis: steering-authority exhaustion.** The car arrives at the crest already too far *inside* the turn, and the wheel is **already correctly maxed outward** trying to un-inside it (`corr(cte, steer) = −0.65` everywhere, with *no* sign flip — the tempting "positive-feedback" reading was an artifact of a `sign()` term). Under the *light-crest grip*, the correction the car needs simply exceeds ±1.0 of available steering. The budget is already spent, and spent correctly. So **no steering-law lever can help** — you cannot fix a saturation by asking for more of a resource that's exhausted. The car washes (71 % of failures) or, when grip suddenly returns on the compression, over-rotates (29 %).

**The fix that worked: an arrival-geometry lever.** If you can't add steering authority, reduce the demand: **shave the target speed by ~10 % in the crest *approach*** — *ending 20 m short of the hazard so it never slows during the light crest itself* (slowing *in* the crest is catastrophic — a mis-placed in-crest mask produced a 51 % slide rate). Slowing the approach gives the maxed-out correction the grip to un-inside the car *before* the grip returns. Exactly the grip-limited reading predicts.

**Proven, not asserted.** Seven candidates were tested live, ~30 minutes each, on one continuous log sliced by hot-key config markers. The grip-margin candidate gave **0 kill-zone incident-laps out of 56** (vs 7/55 baseline) at **+0.05 s** — essentially free — with a clean, monotonic dose-response (0.92 partial, 0.90 the zero-kill knee, 0.88 over-slowing). Pooled across doses ≤ 0.90: **0/108 kill-zone laps vs 7/55**, a **Fisher exact p ≈ 0.0001**. Definitive.

**Generalizing it — the adaptive crest margin.** A hardcoded corner range isn't a controller, it's a memorized answer. The shipped form is the **Adaptive Crest Margin (ACM)**:
- The survey finds candidate **crest → compression → turn hazard cores** from pure geometry (a light crest `z'' < −0.0035` immediately followed by a compression while `|κ| > 0.010`) — generalizable to any surveyed track.
- A **learned per-core incident counter** then self-selects which cores *actually* bite, from the car's **own slides**: S9 accrues hits and earns the grip margin; a geometrically-similar fast crest that never slides stays free. (No static survey feature separates the two — S9's danger is *dynamic*, an accumulated inside-error from the previous corner, invisible to any static map. So the selection *must* be learned.)
- The margin applies only in a tripped core's approach `[GAP, APPR]`, never into the crest.

It is a closed-form learned table — no neural net, no track-position hardcoding — that reproduces the hand-tuned fix while transferring to tracks it has never seen.

---

## Experimental methodology

Every change is measured, not eyeballed. The discipline that emerged over the project:

- **Hot-key-gated live A/B on one continuous log.** Candidates live dormant behind `tune.json` flags; an operator arms one at a time and slices the single log by timestamp config-markers (`seg_ab.py`). No restart, same conditions, apples-to-apples.
- **Incident-lap metrics, not just section times.** A 130 km/h slalom costs little *time* but is wild and off-track-risky — so section time alone is *not* an acceptance criterion. Every re-measure now also reports cross-track RMS/p90, steer-reversal counts, sideslip p90/p99, and off-track %.
- **Statistical significance.** Kill-zone incident rates are compared with **Fisher's exact test** (the S9 fix landed at p ≈ 0.0001); distributions are never truncated when checking for regressions (an early readout that showed "only the calmest 12 of 23 laps" taught that lesson the hard way).
- **Offline false-positive footprint checks before deploy.** Any threshold-gated behavior change is first run against logged laps to measure *what fraction of ticks it fires on and where* — a candidate that looked surgical turned out to fire on 29 % of all racing ticks across the whole track.
- **Confound control.** The grip-intercept recalibration was initially confounded by location-specific execution defects; the rule that emerged: *the grip intercept is only measurable after the location-specific failures stop being the binding failure mode.*
- **A living engineering logbook.** `BASE_CONTROLLER_PLAN.md` records every lever tried, its result with real numbers, and — most valuably — the **failed** approaches and *why*, so they're never retried.

Representative results from the logbook: median lap `32.3 s → ~29 s`; best lap `28.30 s`; off-track rate `6.4 % → 1.4 %`; the self-calibrated corner-speed map converging from a flat 1.0 to a per-corner profile *purely from the bot's own telemetry* over ~100 laps, at one point **self-learning the crest corner faster than the human-derived floor** did.

---

## Autonomy: the AFK recovery state machine

To farm for hours unattended, the controller must survive everything the game throws at it. `afk_recover.py` is an OCR + gamepad state machine that drives the game from *any* non-driving state back to a live race:

- **Race-vs-free-roam** is decided by `race_position` (1..N in a race, 0 in free roam) — the *only* reliable signal, since `is_race_on` and the race clock are both 1 in free roam too (a subtle bug that once had the bot happily driving the open world instead of restarting the event).
- **Controller-Disconnected dialog** (pops on every virtual-pad reconnect) — detected by its chartreuse color band *and* OCR, cleared with A + keyboard Enter.
- **Off-track wedge** → pause menu → *Reset Car Position*; **wheel-spinning wedge** → a position-based reverse-unstuck maneuver (immune to the wheelspin that fools a speed reading).
- **Accidental full-screen map / pause / results / free roam** — each has a handler; a hard guard *never* navigates into the paid **Store** screen (which would open a real purchase overlay).
- **Last-resort blind kick** when telemetry has been dead >45 s and no screen is recognized, force-foregrounding the game and tapping A+Enter — and it only ever steals focus from the game itself or the bare desktop, never from an app the user is using.

There is a companion watchdog that relaunches the follower and archives the dying process's output, so even a rare hang leaves evidence.

---

## Tech stack

- **Language:** Python 3.12, **numpy** for all real-time math (no heavy frameworks in the driving path).
- **I/O:** raw UDP socket to Forza's "Data Out" broadcast (`struct`-unpacked 324-byte packets); **vgamepad** + the **ViGEmBus** kernel driver for the virtual Xbox 360 pad.
- **Offline / analysis:** scipy (surface fits, KD-trees), matplotlib (visualization), Pillow + Windows OCR (`winocr`) for the recovery vision.
- **Platform:** Windows (ctypes / Win32 for foreground-window gating, DPI-aware screen capture, SendInput).
- **No game modification** of any kind — telemetry is the broadcast Forza sends by design; input goes through a standard virtual controller.

---

## Module guide

### Core controller + pipeline (the product)

| File | Role |
|---|---|
| `follow.py` | **The real-time controller** — the main loop: localization, steering law, the grip-aware foot, self-calibrating corner-speed map, adaptive crest margin, and the AFK state machine. |
| `local_planner.py` | Frenet-frame receding-horizon **local planner** (quintic merge trajectory, feasibility, temporal consistency). |
| `racing_line.py` | Racing-line geometry: minimum-curvature line solve + two-pass velocity profiling + curvature helpers. |
| `fh6_telemetry.py` | The Forza **"Data Out" UDP packet parser** and recorders. |
| `build_surface_sheet.py` | Fits the 2-D surface model `y(s,d)` from survey sweeps. |
| `build_surface_cap.py` | Solves the closed-form surface-frame **speed cap** from the sheet. |
| `survey_plans.py` | Generates the offset lines for the autonomous track survey. |
| `afk_recover.py` | OCR + gamepad **self-recovery** state machine. |
| `build_refline*.py`, `build_corridor*.py` | Build the reference line / corridor from recorded laps. |

### Analysis & one-off scripts (dev instruments)

The repository also contains a large number of single-purpose analysis, diagnosis, and visualization scripts written to answer one question and then archived — e.g. `section_compare.py` (per-section controller-vs-human timing), `exit_starvation.py`, `s11_profile.py`, `seg_ab.py` (A/B log slicing), and dozens of `analyze_*` / `extract_*` / `verify*` scripts. These are the *how-we-figured-it-out* trail, not part of the shipped controller.

### The logbook

- `BASE_CONTROLLER_PLAN.md` — the full engineering narrative: every lever, every result, every dead end and why.
- `SETUP.md` — machine setup and operating notes.

---

## What it can't do (yet)

Honest limitations:

- **It follows a human-recorded reference line.** The line (and its speed scaffolding) is still the reference driver's median path. Drawing its *own* line — feeding its self-learned grip map into a minimum-lap-time optimizer — is the next milestone, not a solved feature.
- **The residual gap is execution precision, not knowledge.** At the crest the car knows it *should* carry ~130 km/h but can only place ~121 while the wheel is light — a tracking-precision limit. Closing it wants a better tracker, not a better plan.
- **Single car, single track (so far).** The pipeline is designed to be track- and car-agnostic (the survey and the menu-derived vehicle-spec recipe are both generalizable), but it has been *proven* on one circuit and one vehicle. Transfer is designed-for, not yet demonstrated.
- **It needs the game as the foreground window.** By design (a safety gate) — background input injection isn't attempted.
- **One rough edge, currently.** A tight hairpin elsewhere on the circuit regressed during a night of incident-heavy experiments (the self-calibrating speed map's shared feature-net generalized some cuts the wrong way): the car approaches too fast and runs wide there on a minority of laps. It self-recovers every time, and the online speed map is already re-learning it down — but it's the current #1 cleanup item, honestly noted rather than hidden.

### Future work

- Own-line optimization coupling the self-learned grip map to a min-lap-time solver.
- A precision-improving inner tracker to cash the corners the map knows are faster than it can currently execute.
- Cross-track / cross-car transfer validation using the track-agnostic survey + vehicle-spec recipe.

---

> **Port-conflict note:** FH6 TC — a separate traction-control project for
> human driving, at `C:\Users\Talon\FH6-TC` — also listens on UDP 7777.
> Don't run it while `follow.py` is farming (and vice versa).

---

## Setup

Brief; see `SETUP.md` for the full version.

1. **Python 3.12** (not the Microsoft Store stub) and `pip install -r requirements.txt`.
2. **ViGEmBus driver** installed (required by `vgamepad` for the virtual controller), then reboot.
3. **Forza Horizon 6** → Settings → HUD and Gameplay → **Data Out: ON**, IP `127.0.0.1`, Port `7777`.
4. Record reference laps (`fh6_telemetry.py`), build the line, optionally run the autonomous survey, then run the follower:
   ```
   python follow.py --recover --afk   # plus the tuned gain flags (see SETUP.md)
   ```
   `recordings/tune.json` hot-reloads gains, safety, and every experimental lever live — no restart needed.

Stop it by alt-tabbing to its console and pressing **Ctrl+C** (this releases all controller inputs).

---

*Ziggy Racer is a personal control-systems project applying process-control and chemical-engineering rigor — system identification, closed-form physics modelling, feedforward/feedback design, anti-windup, and rigorous experimental methodology — to the novel domain of a self-taught racing driver.*
