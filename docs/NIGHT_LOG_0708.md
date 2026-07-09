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

- **N5 (bla_tau=0.55): KEEPER, locked.** Overshoot +8.8 med / +20.5 p90 (from +20.3/+29.8); S11 arrival −2.6 (≈0); deduped hairpin wedges 1/21min (N4: 2/16min); final ~16 min of window: zero stall events track-wide. Locked into watchdog addKeys; committed locally (b929dc8).
- Secondary stall sites s225/s950 are NOT overshoot-driven (run −14/−40 BELOW target) — different mechanism (tracking/recovery), documented as future work, not chased tonight.
- **Long soak (90 min) running** — restart-aware stats: lap med/best/p25, complex time, deduped stall rate, top off-track bands.

## Cycle 2 — consistency equilibrium [second half of night]
- 90-min soak post-N5: pace present (best 30.44) but med ~33 — INCIDENT-RATE problem: ~8 deduped stall episodes/90 min at s230/s425/s950. s950 diagnosis: NOT hot-arrival (speeds ≤ pre-change); the re-earned map lets the fast tail of laps reach target at a tracking-fragile corner → ~5% of fast attempts off → vtrim oscillates (re-earn↔cut).
- **Consistency bias applied (00:50): vtrim_up 0.0005→0.0002, vtrim_cut 0.02→0.03** (repeat-incident sites ratchet down instead of oscillating; converged-at-ceiling zones unaffected). Snapshot first: vtrim_delta_preConsistBias_0709.npz. Persisted in watchdog addKeys.
- Checkpoint 1 (~03:00) looked degraded but was an ANALYTICS artifact (cumulative window double-counting). Fresh-window trend showed hairpin off-rate 10.5%→9.0%→5.9% by thirds = bias converging.
- **Checkpoint 2 (05:15, fresh 2 h): CONVERGED. 50 laps, med 30.43 / best 29.90 / p25 30.20, ZERO stall episodes, off rows s425 6353→513, s950→118.** vs deployed-ship reference 32.13 med: **−1.7 s median, stall-free.**
- Note: s415 "overshoot vs target" is no longer comparable across configs (the carved map lowers the target); judge by outcomes (stalls/offs/laps).

- **Final checkpoint (06:50, fresh 90 min): med 30.23 / best 29.69 / p25 30.01 / p75 30.43 — ZERO stalls again.** 3.5 h straight incident-free; distribution spread p25-p75 just 0.42 s; still trending down.

## Night summary (for morning report)
- Shipped + validated: **mbc** (map-boost cap replacing s7m/acm margins), **bla_tau=0.55** (brake-onset anticipation), **hul 515-565** (scoped stable-line pursuit), **consistency bias** (vtrim_up 0.0002/cut 0.03). All in watchdog addKeys; code committed locally b929dc8.
- Fastest observed: best lap 29.23 (N4 window), complex best 11.43 s, S10 exit ~156 km/h (was 128).
- Converged overnight state: med ~30.4, p25 ~30.2, zero stalls/2 h (ship reference was 32.13 med with regular resets).
- Open items: s225/s950 tracking-class wedges (rare now; below-target mechanism, future work); BC policy remains the ceiling for the human +40 km/h technique gap.
- GitHub: local commit only — offer push in the morning.

## Config keys reference (current arm)
mbc_on=1.0 (a 470-608, b 638-702), s7m_on=0, acm_on=0, hul 515-565, bla_tau=0.4, vtrim learning on, vt2_on=0, brk_ff=1.0.
NOTE: bla_tau NOT yet in watchdog addKeys — a watchdog restart drops it until validated+added.
