# Overnight session log — 2026-07-08/09

Goal (user): keep diagnosing/changing/testing/validating to push S6–S10 (and overall laps) **faster + more consistent**.

## State at start of night
- Deployed (evening): **M2** = `mbc=1.0` (map-boost cap s470-608 + s638-702, replaces retired s7m/acm margins) + vtrim learning + scoped `head_use_line` (hul 515-565) + ff ship bundle.
- M2 validated: complex s430-800 11.95→11.57 s, S10 exit 128→156 km/h, in-zone off 0.00%, S11 self-healed by incident-cuts (11.3%→0.0%), converged laps 30.11 med / 29.82 best (deployed-ship ref was 32.13/30.01).
- Watchdog restart cap raised 10→30 for the night (it gave up at 10 today and the farm sat dead ~2 h).

## Cycle 1 — hairpin (s425) reset factory [consistency]
**Diagnosis:** every lap systematically overshoots the brake target at hairpin turn-in (+20.3 med / +29.8 p90 km/h at s415); resets are tail events of that thin margin. Cause chain: brake branch engages only when tgt<spd (reactive onset) → pedal ~0.55 through the heavy phase → profile's steepest descent lands AT turn-in where the slip-guard rightly cuts braking. Human brakes ~2.3 g early, done before turn-in. Measured pedal→decel curve: full pedal ≈ 27.8 m/s² (FF's 30 calibration ~fine); onset, not magnitude.
- **N1 (brk_ff 1.0→1.2): FAILED, reverted.** Overshoot +39/+70, brake median halved — branch-chatter (harder FF → err flips sign → throttle/brake bouncing → pulsed braking sheds less).
- **N2 (bla_tau=0.4, v1): hairpin FIXED but over-brakes everywhere.** Anticipated error `err_b = err − desc_f·τ` used for branch AND P/release → car brakes to desc·τ BELOW target: S11 arrival −25.6 km/h, laps 31.09. But hairpin: **0 stalls, 0 off rows** (ref window: 18 stalls, 2510 off rows), overshoot +12.7/+23.3.
- **N3 (bla_tau v2, running):** anticipate ONSET only — enter brake branch on err_b<0 (desc_f>3 gate), pressure = FF(desc) + P on plain err (max(0,−err)), release at plain target. Expect hairpin fix retained without the S11 undershoot.

- **N3 (onset-only v2): hairpin held (0 stalls, +12.0 med) but S11 STILL −23.9** — my branch condition re-created the setpoint bug from the other side (throttle required BOTH errors ≥0 → car held brake until desc·τ below target). Laps 30.37.
- **N4 (eps-release v3): S11 FIXED (−1.6) + best lap of night 29.23**, but hairpin tail crept back (4 stalls, +14.3 med) — eps-release narrowed anticipation at the hairpin. Structure now correct; magnitude needs one notch.
- **N5 (bla_tau 0.4→0.55, running):** more anticipation, safe now that eps-release prevents undershoot elsewhere. Success = overshoot <+13/stalls ~0/S11 ~0/laps ≤30.1 → then lock into watchdog addKeys + long soak.

## Pending / next
- Validate N3 (overshoot, stalls, S11 arrival ≈ 0, laps vs 30.11 med). If good: add `bla_tau=0.4` to watchdog addKeys (persistence across restarts!) + long soak.
- Then: consistency sweep of remaining off-track bands (s0-150, s925-950); lap-time tracking toward < 29.87.
- Morning: full report; offer GitHub push of night's commits (local commits only overnight).

## Config keys reference (current arm)
mbc_on=1.0 (a 470-608, b 638-702), s7m_on=0, acm_on=0, hul 515-565, bla_tau=0.4, vtrim learning on, vt2_on=0, brk_ff=1.0.
NOTE: bla_tau NOT yet in watchdog addKeys — a watchdog restart drops it until validated+added.
