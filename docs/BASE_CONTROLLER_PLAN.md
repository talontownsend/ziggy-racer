# Base-controller refinement plan (section-by-section)

Goal ladder: beat 30.873 (keyboard) [** BEATEN 07-03: median 29.78 on the median line **]
-> 27.285 (Ana) -> 27.28 (controller pad).

## MEDIAN-LINE RESULT (07-03) — the definitive baseline
User's correction (reference = MEDIAN path/speeds of their 49 laps, not the 26.1 s outlier) was
transformative: **lap med 31.37 -> 29.78, best 28.70, off-track 6.4 -> 2.6%, cte p90 6.5 -> 4.3,
20/20 laps clean.** Total gap to human median now 2.31 s (was 4.9 at session start). Per-section:
S4 and S5 BEAT the human (hairpin -0.06!); S1 +0.28, S2 +0.30 (was +0.92), S12 +0.32 (was +0.88);
biggest remaining: S3 +0.43, S10 +0.39 — the sweeper caps (vmin 143 vs 154 / 128 vs 150) = grip
model still binding there. vmins now match the human nearly everywhere else (S1 122 vs 123!).
IMPLICATIONS: (1) most of the old "tracking tax" was really an UNDRIVABLE-LINE tax; (2) with
canaries this calm, RETRY a higher alat_k step on this line (S3/S10 upside); (3) the residual NN
now has a stable, high-quality base.
ALAT_K RETRY ON MEDIAN LINE (07-03): k=0.004 (a0 held 24.3), 18 laps -- NET NEGATIVE (med 30.50)
but NOT instability (off 2.4%): **PER-CORNER HETEROGENEITY.** S10 cashed it fully (-0.26, vmin
128->147, gap +0.13) while S1/S2/S11/S12 vmins COLLAPSED (S1 122->87) with clean tracking -- the
model over-promises specifically in (likely) crest/off-camber corners. ROOT: v_curve's grip term
has NO load/elevation correction (the throttle-foot's ay-based grip_scale does; the SPEED CAP
does not). A global scalar k cannot serve both corner populations; k=0.0025 is the global
optimum. FUTURE LEVERS: (a) load-corrected v_curve using the plan's grade/elev (d2elev/ds2 ->
expected load factor at each station); (b) per-zone grip margins; (c) the residual NN -- its
vision includes vertical/elevation features, so this is exactly learnable. REVERTED to 0.0025.
Probe log archived: follow_log_ml_k004_probe.csv. Config: median line + alat 24.3/k 0.0025 + d0p_max 0.30 +
decomposed v_curve + brk_ff 1.0. Log: current follow_log (20 laps).
Process (user-defined): divide track into sections -> compare controller vs human per section ->
deep-diagnose ONE section at a time (biggest gap first) -> tweak -> re-measure -> next section.
Residual-NN training is PAUSED until the base controller is refined (fresh 680s-window run queued at gen 0).

## Sections (user-chosen, recordings/sections.json)
13 sections, boundaries at stations [56,136,236,340,388,428,512,568,596,656,732,820,928] (refline 0-999, lap 1073.9 m).
Working order by gap: S3 (+0.82) -> S1 (+0.80) -> S12 (+0.73) -> S11 (+0.52) -> S2 (+0.44) -> S13 (+0.37) -> S10 (+0.31) -> rest.
Comparison pipeline: `section_compare.py` (never global-unwrap s; local modular crossings).
Baseline: 391 controller laps (D:\FH6-AFK-Farm-backup-20260628 log, med 32.34/best 30.65) vs 49 human laps (med 27.47/best 26.15).

## S3 diagnosis (2026-07-02, DONE)
Gap +0.82 s. Two failure chains, ~55/45:
1. S2-EXIT THROTTLE STARVATION -> S3 entry 109 vs human 157 km/h. Equal apex speeds (96!); on exit the
   controller holds |steer| 0.6-1.0 for 60 m (vs human 0.2) -> fc_frac pinned at the 0.52 gate -> thr_cap
   0.33-0.49 -> throttle ~0.2 while 20+ km/h under target. Root cause below (line, not gate).
2. SWEEPER TARGET TOO LOW + understeer-ease lifts: live vcurve 115-127 in the S3 kink where the human does
   210-216 km/h at 4.2-4.7 g; grip model (24.3 + 0.000993 v^2 = ~2.9 g @ 215) underestimates downforce ~40%.
   Plus `und` throttle lifts to ~0 at s 276-316 while ~2 m off-line.
Line investigation (user-prompted): the controller does NOT run wide on exit -- it faithfully tracks the
refline, which swings to within 1 m of the OUTSIDE edge; the human's fast laps cut 6.8 m INSIDE it
(negative offset = inside through S2 exit; verified from curvature sign). PROVENANCE: refline_plan.npz was
built 06-26 21:05 by build_refline.py from `recordings/refline/session_20260626_130821.csv` best lap
(27.28 s) -- NOT the 06-25 fast runs (26.05 s). The plan's speeds are that session's speeds x1.05. The
controller is executing an outdated line at outdated speeds. The 1 m edge-clearance clip pinned the old
exit line to the recorded outside edge.

## Levers (ranked; pull ONE at a time, re-run section_compare after each)
1. [DONE 07-02, pending measurement] REDRAW REFERENCE LINE from the user's real best lap
   (run_20260625_120907.csv lap 29 @ 26.10 s), via build_refline2.py. Live in refline_plan.npz.
   - Geometry moved up to 8.3 m (S2 exit) and 7.8 m (S5/S6 hairpin exit); plan speed +6.8 avg,
     +45 km/h peak at the S3 kink. Old plan: refline_plan_v1_27s.npz (instant revert).
   - Edge clearance 0.4 m (user's call -- they ride 0.05-0.10 m from the recorded edges at s~221
     S2-exit, s~404 S4, s~843 S11). Implemented as buffered-clip + smooth + clearance verify;
     a hard post-smooth re-clip KINKED the line (p99turn 90 deg = phantom hairpins) -- never do that.
     Final: min clear 0.39 m, p99 turn 9.0 deg. KNOWN RESIDUAL: smoothing still shaves up to
     1.4-1.9 m off the raw lap at the three wall-riding apexes; revisit only if those sections
     still lag after measurement (options: re-record edges, narrower smooth window).
   - refline_plan_v2_clip1m.npz = the 1.0 m-clearance variant kept for A/B.
   - MEASURED (07-02, 28 laps): NET NEGATIVE overall -- lap med 32.34 -> 32.93 (+0.59), best 30.65 -> 32.00.
     BUT the targeted zones IMPROVED: S1 -0.24, S3 -0.16, S7 -0.13, S2 -0.12 (S3 entry vmin 109->124).
     Regressions split into two distinct mechanisms:
     (a) COMMANDED collapse (grip model refuses the tighter line): S11 vmin 113->79 with vcurve 68-82
         in the wall zone (human: 139) -- brakes hard on command, off% only mildly up. Same flavor in
         S13 (-8 km/h vmin). THIS IS LEVER 2'S JOB (vcurve = f(curvature, alat model)).
     (b) TRACKING failure (can't drive the human's hairpin line): S5 cte median 4.3 m, S6 off-track
         21.7% (!), S5+S6+S4 net +0.78 s vs v1 line. The controller was ~EVEN with the human here on
         the v1 line -- the 26.05 hairpin line (deep trail-brake entry) exceeds its tracking ability.
     CANDIDATE NEXT MOVES: splice S4-S6 back to the v1 geometry (per-section line choice), keep v2
     elsewhere; then lever 2 to unlock the commanded zones. Gates for all comparisons stay pinned to
     v1 stations (section_compare.py loads refline_plan_v1_27s.npz for projection -- permanent).
2. [DONE 07-03 -- LANDED at 24.3 + 0.0025 v^2] DOWNFORCE RECALIBRATION, ramped with 15-lap gates:
   - CALIBRATED envelope from human telemetry (p98 lat-g per speed bin): true grip ~ 27 + 0.005 v^2
     (5.19 g p98 at 209-230 km/h!). NOTE: naive envelope fit is poisoned by speed bins with no
     corners (230+ km/h straights read 2 g); fit only bins with genuine hard cornering.
   - STEP 1 (24.3+0.0025v^2): **lap med 32.84 -> 31.73 (-1.11 s, biggest single gain of the
     project), best 30.19 = record.** S11 -0.32 (gap +0.15), S2 -0.24. Canaries at caution
     (off 8.2%, cte p90 7.0).
   - STEP 2 (26+0.004): CATASTROPHIC (+4.6 s, off 10.3%, vmins crashed everywhere) -- aborted.
   - STEP 1.5 (26+0.0025): mixed-negative (S1/S3 best-ever gaps but hairpin+wall zones destabilized,
     med 33.59) -- rejected.
   LESSON: the PHYSICAL envelope (~0.005) is not the CONTROLLER'S USABLE envelope (~0.0025) -- the
   difference is the tracking-precision tax; pushing the model past what the tracker can place the
   car for converts grip into wash, worst in tight-clearance wall zones. Raising a0 (low-speed)
   destabilizes wall pinches at ALL speeds (additive). Per-zone grip margins or a better tracker
   would be needed to cash more of the envelope (candidate future lever; also exactly what the
   residual NN could learn). watchdog.ps1 + resume_training.ps1 fargs updated to 0.0025.
   Step logs archived: follow_log_lever2_step1/step2_failed/step15_failed.csv.
   *** LINE SOURCE CORRECTED (user, 07-03): the reference must be the MEDIAN path + MEDIAN speeds
   across ALL ~50 laps (run_20260625 files), NOT the single 26.1 s best lap -- one hot lap has
   one-off moments (wall-kissing!) the user doesn't drive consistently, and the section comparison
   is against their MEDIAN times. build_refline2.py now has MEDIAN mode (49 laps pooled, best lap
   = projection base only). THE MEDIAN LINE IS INHERENTLY BETTER-BEHAVED: only 8 stations violate
   0.4 m clearance (max displacement 0.18 m!) vs the best lap's three big wall-clip zones -- the
   entire clip-kink saga was an artifact of the outlier lap. Median vs best-lap geometry: mean
   1.34 m, max 3.68 m (hairpin exit). Deployed (best-lap line kept as refline_plan_v2_bestlap.npz);
   best-lap-line results below CARRY A CAVEAT (measured on the wrong reference); median-line
   revalidation at the landed grip model pending. NOTE: with no wall-kissing zones, the
   tracking-tax may shrink -- a higher alat_k step may become viable on this line (future retry).
   [best-lap-line results, for the record:] VALIDATED (16 laps): lap med 31.37, best 30.23, off 6.4%, cte p90 6.5 — stable. BASE
   CONTROLLER FINAL STATE: S4/S7 BEAT human, S6/S8 even (+0.04/+0.02); remaining gaps S2 +0.92,
   S12 +0.88, S5 +0.63, S1 +0.51, S3 +0.50 (all tracking-tax family). vs session start: median
   32.34 -> 31.37, best 30.63 -> 30.19, on the user's real line with calm tracking. The keyboard
   goal (30.873) falls on best laps routinely; median is 0.5 s above it. NEXT: resume the residual
   NN on this settled base (its job = exactly the per-zone tracking-tax the global model can't cash).
3. [PENDING] THROTTLE SUPPRESSION (fc-gate + understeer-ease): may largely self-resolve on the new line
   (steering unwinds earlier -> gate opens; on-line running quiets the und detector). Re-measure after
   1+2; tune only the residual starvation.
4. [INVESTIGATED 07-02 -- CONFIRMED, fix pending] PLANNER-OVERSHOOT / LIMIT CYCLE. User called it on the
   hairpin regression (rejected line-splice as a band-aid); the data proves a deterministic limit cycle:
   - 38/38 laps ring through S5-S6 with 3-5 line crossings, peak +-8.3 m, ~130 m wavelength, persisting
     200+ m past the apex. Steering is saturated BANG-BANG (median pinned at -1.00 / +1.00 through each swing).
   - THE PLANNER RINGS WITH THE CAR: the merge-path target swings -8.2 -> +7.2 m; per-zone regression of
     target-offset on car-offset gives slope ~0.7-1.0 (r up to 0.96) and >1 at entry (2.29 at s410-422,
     1.95 at 434-446) -- the merge path re-anchors to the car (w_dev=0.3 too cheap to deviate from line?)
     and AMPLIFIES at entry instead of damping. Zero restoring reference.
   - WHAT EXCITES IT (hot entry, +26 km/h over target at s418): (a) the braking zone s378-394 is >50%
     OFF-SURFACE (median lap 1.4-1.7 m off the tight S4 line puts wheels on grass while braking); (b)
     BRAKE PULSING: vcurve breathes 110->190->86 mid-brake-zone (merge-path curvature fluctuates as it
     re-anchors) so the follower releases/reapplies the brake (brk 0.51->0.04->0.74).
   - Same mechanism at lower amplitude = the S1-exit/S2-entry wash (+8 -> -1.7 -> +2.4 swing seen earlier).
   FIX (i) IMPLEMENTED + MEASURED 07-02: `d0p_max` clamp in local_planner.py (new live-tunable, in
   tune.json addKeys, set 0.30; default 2.6 = no-op). The quintic must match the car's drift slope
   d0'=tan(psi)(1-kr*d0) (was allowed to 2.57 = 69 deg) -> with big heading error the plan BULGED PAST
   the car (offline repro: path swung to -17.8 m for a car at -6.7!). Clamp caps the projected drift:
   same repro peaks -8.7 and leads straight back = restoring reference.
   A/B (21 laps vs the 38-lap v2-line baseline, follow_log_v2line_baseline.csv):
   - S6 3.205 -> 2.594 (-0.61 s) = AT the human's 2.547. S11 -0.12. Lap med 32.93 -> 32.36 (-0.57),
     best 32.00 -> 31.69. Sum of section deltas -0.64 s. Back to v1-line lap times but ON the new line
     (sweeper gains intact, lever-2 unlock still pending).
   - Oscillation: ringing TAIL damped (several laps now 1-2 crossings vs uniform 3-5; worst rms 4.13
     -> 2.82; entry amplification slope 2.29 -> 1.86) BUT the FIRST excursion (~7 m wash) remains --
     it is excited by ENTRY OVERSPEED, which is fix (ii)'s job. S5 still +0.6 vs human.
   FIX (ii) FINAL FORM 07-02 (after 3 failed temporal iterations -- ALL REMOVED): **decomposed
   v_curve** in follow.py + local_planner.max_kappa_line_ahead(). v_curve = min(v_line, v_rejoin):
   the LINE's curvature owns the corner cap (ground truth, cannot breathe); the merge path
   contributes ONLY its ADDED curvature kappa_merge_max (the rejoin arc), ~0 near the line. The old
   cap used the merge path's TOTAL curvature -> double-counted line+rejoin and re-planned every tick
   -> flapped 110->190->86 mid-braking -> brake pulsing -> hot hairpin entry.
   FAILED-PATH LESSONS (do not retry): (a) plain rise-rate limiter: dips at speed stranded the
   target low -> phantom lifts (S13 +0.59); (b) 0.4s arming on RAW target: the vcurve spike itself
   disarms the gate (self-defeating); (c) arming on LIMITED target: still net-negative (S13 +0.36,
   hairpin gain not recovered). Temporal gates on a bidirectional-noise signal trade one artifact
   for another -- fix the SOURCE (stable line curvature), like ff_use_line did for steering.
   MEASURED (20 laps vs fix1): lap med 32.36 -> 32.08, best 31.69 -> 31.24. S3 -0.29, S5 -0.20
   (entry 101->94), S7 beats human. tgt_rise key REMOVED everywhere (d0p_max=0.30 stays).
   Archived: follow_log_fix2_broad/_armed_raw/_armed_v2/_linecap_v1.csv.
   *** RETRACTION (user caught it by SPECTATING): fix 2 is NOT cleanly banked. Whole-lap weave
   analysis (analyze_oscillation.py / s12_weave.py): **S12 cross-track rms TRIPLED 1.05 -> 3.50 m
   (p90 6.26); the MEDIAN path swings -3 -> +7.7 m; worst lap +12.6 m; mid-weave speed crawls to
   73 km/h** (fix1: within ~2 m, 127 km/h there). S6/S8/S9/S11 weave also up; steer reversals up in
   S1/S5. Section-TIME showed only +0.06 s in S12 -- a 130 km/h slalom costs little time but is
   visibly wild and off-track-risky. MECHANISM: the old double-counted cap dipped whenever the car
   was off-line (merge bulge + line curvature summed) = an ACCIDENTAL "off-line -> slow down"
   governor, strongest in S11's wall zone; the honest decomposed cap removed it -> laps exit S11
   3-4 m scattered at speed -> front-wash S-swing through S12 (steer pinned +1.0 while diverging,
   same slip-saturation signature as the hairpin) -> rejoin term finally binds on the huge offset
   -> target collapses -> crawl. PROCESS LESSONS: (1) section times alone are NOT sufficient
   acceptance criteria -- weave/tracking metrics (cte-rms p90, steer reversals) are now part of
   every re-measure; (2) never truncate a sorted distribution when checking regressions (the first
   readout showed only the calmest 12 of 23 laps).
   USER REJECTED both symptom fixes -> ROOT CAUSE FOUND (line-geometry audit, s12_rootcause.py):
   **THE REBUILT LINE ITSELF WAS DEFECTIVE.** Two defect classes:
   (a) WALL-CLIP KINKS: the edge clip worked in the corridor-centerline frame (line = c2+off*nrm),
       whose station pairing jumps around; reconstruction DISCARDS the tangential component ->
       points shuffle along-track -> phantom R=12 m kink at s~836 in a 151 km/h zone (demands
       5.5x grip; the plan speed is the human's, who never drove the clipped shape). The FF reads
       line curvature -> violent steer pulse at the wall -> front slip 3.76 -> scattered S11 exit
       -> S12 wash/weave. fix1's accidental off-line slowdowns masked the cascade; fix2 unmasked it.
   (b) SEAM KINK: resample_closed leaves R=5.3 m at station 0 (start/finish, 256 km/h) -- v1 was
       clean (R=94; its global end-smoothing masked it). Under fix2 the line-cap READS this ->
       braking before start/finish = the real cause of fix2's S13 +0.17 (another grip-model
       misattribution corrected).
   LINE BUILDER FIXED (build_refline2.py): clearance now solved as an OBSTACLE PROBLEM in the
   human line's OWN normal frame (per-station edge-projected bounds, deviation diffused under the
   box constraint -- taut string against the wall; human's real apexes untouched) + seam-local
   diffusion closure. Repaired line audit: S12 wall zone R 12->42 m, seam R 5.3->752 m, hairpin
   apex R~10 preserved, clearance 0.39 m. FAILED approaches (do not retry): global curvature
   invariant with the conservative alat model (flags real corners), hard-edged blend masks
   (generate kinks at their own boundaries), reconstructing offsets from raw telemetry points
   (injects jitter). Deployed 07-02 (kinked line kept as refline_plan_v2_kinked.npz; fix-2 kinked
   laps archived follow_log_fix2_kinkedline.csv).
   MEASURED (18 laps, full suite): **REPAIRS VALIDATED + ALL-TIME BEST LAP 30.56 s** (prev 30.63
   v1-era / 31.24 fix2-kinked). S13 3.158->2.540 (-0.62, seam fix; gap to human now +0.27),
   S12 -0.28 + S11 -0.23 (wall fix), S4 -0.16, S6 -0.18. WEAVE: S12 rms back to 1.01 (was 3.50),
   whole-lap steer reversals med 33 (fix1) -> 18 = CALMEST CONFIG YET across most of the lap.
   BUT lap med 33.73: **NEW BOTTLENECK UNMASKED at S1/S2** (+0.13/+1.50 vs kinked; S1 cte-rms
   2.0->6.2, S2 1.2->4.0, off-track 20-38% through s 140-230, speeds crash to 53-73 km/h).
   MECHANISM: the seam kink's phantom braking at start/finish had been slowing every lap into S1;
   with it gone the car approaches S1 at ~250+ km/h FOR THE FIRST TIME and the entry overspeed
   wash (hairpin pattern, higher speed) cascades S1->S2.
   BRAKING-ZONE DIAGNOSIS (07-02): human brakes FULL PEDAL at s/f exactly (3.1 g, straight, done
   by turn-in); controller braked 40 m late at HALF PEDAL (0.51 -> 1.9 g vs the A_BRAKE=2.55 g the
   anticipation assumes) because the brake was PURE-PROPORTIONAL -- it needs a standing error to
   hold pedal, so following the smoothly-descending anticipation curve it equilibrates at half
   pedal, and the leftover braking lands INSIDE the corner where fc_frac correctly blocks it.
   FIX SHIPPED: **BRAKE FEEDFORWARD** (mirror of t_ff) in follow.py -- command pedal = target's
   own descent rate / 30 m/s^2 (measured full-pedal decel) + kp_brk trim; `brk_ff` gain hot-tunable
   (0 disables). watchdog/resume addKeys updated.
   MEASURED (13 laps): lap med 33.73 -> **32.84**, best 30.56 -> **30.30 (all-time record, 0.57 s
   under the 30.873 keyboard goal)**. S2 -0.61, S5 -0.26, S1 -0.06. Braking zone: pedal 0.55-0.70,
   peak 2.4 g, on-target through the zone (was chasing +20-30 km/h hot). Minor FF side-effects:
   S4 +0.10, S6 +0.16, S12 +0.11 (watch).
   REMAINING S1 WASH IS NO LONGER A BRAKING PROBLEM: car is ON-target through s 90-130 yet still
   runs 7-8 m wide -- the corner demands ~2.8 g at 130 km/h, the CONSERVATIVE GRIP MODEL's edge
   (human pulls it at ~70% of their real grip). Together with the s/f speed deficit (198 vs 254 --
   S13-exit cap) and the S3-kink ceiling, EVERY remaining top gap now points at **LEVER 2
   (downforce/grip recalibration)** -- next up, with evidence from 4 independent angles.

5. [TESTING 07-03] PROVEN-SPEED FLOOR on the corner cap (load/camber correction, data-driven).
   USER GROUND TRUTH (07-03, resolves the k=0.004 heterogeneity): S1/S2 are COMPLETELY FLAT (no
   camber/crest) -- so their k=0.004 collapse means the true FLAT-ground envelope there is ~the
   0.0025 model, and the higher lat-g in the same speed bins comes from CAMBERED corners. S12 is
   ON-CAMBER (banked -- more grip than any flat model; "we should be able to go faster in S12 than
   what the model says"). S11 has elevation change + OFF-camber. Major crests: S7 (huge, also
   off-camber, Laguna-Seca-like) and S9.
   DESIGN: don't model camber we can't see (plan has no camber data). Instead FLOOR the v_curve
   LINE term at the human's proven median speed: v_line = max(sqrt(alat/kk), vfloor*vplan_min18),
   where vplan_min18 = rolling 18 m forward-min of plan speed (same window as the cap's kappa).
   vplan = median x1.05, so vfloor=0.95 ~= exactly proven speed. Every camber/crest/load effect is
   baked into that number because the human drove it. ABOVE-proven headroom (banked S12) comes from
   the measured-g trim (v_curve_trim), whose load_factor sees bank load via live ay. The REJOIN
   term is NOT floored (off-line curvature is real extra demand). `vfloor` hot-tunable (0 disables),
   in both scripts' addKeys. Offline preview (floor_preview.py): binds on 47% of stations; biggest
   cap raises S3 +75 km/h (the kink), S12 +43, S8 +38, S9 +37, S7 +36, S11 +35; S1/S2 small
   (+14/+10 at slowest points -- model already right on flat, as predicted); S4/S5/S13 ~nil.
   RISK: mid-corner caps up to +40-75 km/h higher -- guarded by measured-g trim shed (0.010/tick),
   understeer ease, cte governor; vfloor can be dialed down live if hot.
   MEASURED STEP 1 (vfloor=0.95 everywhere, 26 laps, follow_log_floor_v1.csv): **lap med 29.78 ->
   29.55, best 28.66 (all-time), gap to human 2.31 -> 2.09 s.** Wins where predicted: S3 -0.16
   (kink; biggest gap now S12), S2 -0.14, S9 -0.12 (crest, vmin 128 vs human 118, CALMER: cte p90
   2.22->1.81), S10 -0.10, S8 -0.06 (gap +0.006 = AT human). S1/S4/S5/S6/S7 unchanged (flat/nil
   zones, as predicted). Weave: S12 cte p90 4.88->1.89, S13 2.60->1.75, most sections calmer.
   ONE CASCADE (s11_s12_cascade.py): S11 -0.13 (vmin 122->136) BUT off-track 3.9%->16.5%, ALL offs
   at the EXIT WALL ZONE s 846-882 (off-camber, user ground truth). Lap split proves the coupling:
   S11-clean laps (15): S12 = 2.417 s, vmin 152 vs human 157 -- **the on-camber S12 unlock IS real
   when entered clean** (user's prediction validated); S11-off laps (12): S12 = 3.042 s, vmin 100
   (scattered exit -> rejoin term binds -> target collapse). Net S12 med +0.22 (misleading avg of
   two populations).
   STEP 2 SHIPPED (testing): ZONE-ATTENUATED FLOOR -- withdraw floor trust where the tracker
   demonstrably can't hold proven speed. New hot keys vf2=0.90, vf2_lo=825, vf2_hi=890 (median-plan
   meters; V1->median scale verified within 4 m), soft 8 m edges, lead-in covers the cap's 18 m
   look-ahead. Everywhere else keeps vfloor=0.95. In both scripts' addKeys.
   MEASURED STEP 2 (vf2=0.90, 18 laps, floor_v2_soak): **section sum 29.31 -> 28.96 (gap to human
   1.74 s), best lap 28.27 (all-time, 5 laps under 28.9)**, off 2.7%. S10 -0.15 further (1.768,
   vmin 142), S12 recovered 2.819 -> 2.637 (vmin 141), S13 -0.03. BUT the attenuation itself was
   a NEAR NO-OP: zone vcurve 148 -> 142, zone speed UNCHANGED at 138, zone offs UNCHANGED at 26%.
   MECHANISM UNDERSTOOD: at vf2=0.90 the floor still caps ABOVE the zone's tv/trim-limited speed
   (138), so nothing bound. Baseline safety (3.9% offs) lived at vmin ~122 => the zone cap must
   come down to ~125, i.e. vf2 ~= 0.80. The S12 recovery in this soak came from S10/S12's own
   floor gains on clean laps, not the zone change. STEP 3 (testing): vf2=0.80 hot-dialed (no
   relaunch; config marker t=705.6 in the live log; analyze laps after it). Expected: S11 gives
   back ~0.05, S12 cashes toward its clean-lap 2.42, zone offs -> baseline, slow-tail laps
   (32.9/34.4 = S11-off laps) disappear.
   MEASURED STEP 3 (vf2=0.80 zone 825-890, 18 laps): mixed. **Off-track 1.5% (best-ever canary,
   was 2.6% baseline), lap med 29.54, slow tail shrunk** -- but sections REGRESSED vs v2@0.90:
   S11 +0.13 (vmin 120, BELOW baseline 122 = dug too deep), S12 +0.18 (vmin 141 -> 129).
   ROOT CAUSE OF THE S12 HIT: zone hi=890 + the cap's 18 m LOOK-AHEAD means cars from s~807
   onward were attenuated all the way through S12's banked ENTRY (S11/S12 boundary = arc ~878) --
   strangled the exact on-camber unlock. Zone offs only 26 -> 21% (still hot at 129; baseline
   safety was ~122). LESSON: zone bounds must account for the 18 m look-ahead on BOTH ends
   (attenuation acts on [car, car+18]); hi must be (last off point - 18 m).
   STEP 4 (testing): vf2=0.84, zone 827-866 -- covers the wall stretch exactly, releases the
   banked entry. Config marker t=1362.7.
   MEASURED STEP 4 (vf2=0.84 zone 827-866, 11 valid laps): zone offs BACK to 23% (speed med 140).
   The narrow car-position zone releases the cap while the car is still INSIDE the off region
   (car at 860 caps [860,878] = mostly past hi=866 -> re-throttles through the last third of the
   wall stretch, offs at 870-882 = the histogram's biggest buckets). DESIGN FLAW PROVEN: zone-by-
   CAR-position cannot both hold the car slow through 846-882 AND release S12's banked entry --
   the requirements collide in the boundary 18 m. (Best lap 28.30 though; off total 1.8%.)
   NOTE this soak also demonstrated the race's ~50-lap limit + AFK re-entry: lap_no resets to 0,
   race_pos dips to 0 (free roam) during recovery -- config markers + lap filters must handle it
   (trim_after.py's t>marker filter alone silently drops post-restart laps).
   STEP 5 SHIPPED (testing): PER-STATION FLOOR TABLE (build_floor_tbl in follow.py) -- attenuation
   baked into the floor-speed table BEFORE the rolling 18 m min, so a cap window containing any
   zone station inherits the zone floor and a window fully inside S12 gets full floor; the min does
   the boundary arithmetic exactly. Zone now in TABLE space = the actual off region 843-885,
   vf2=0.80 (~122 km/h = the speed baseline held with 3.9% offs). Table rebuilds on hot change of
   any floor key. Scripts' addKeys updated (vf2=0.80, 843-885).
   MEASURED STEP 5 (per-station table, plain 18 m window-min, 19 laps): zone speed landed EXACTLY
   on target (med 119) but **zone offs EXPLODED to 43% -- at a speed baseline held with 3.9%!**
   MECHANISM FLIP: no longer corner overspeed -- the bare window-min makes the zone edge a STEP
   in the cap: 18 m of warning for a 26 km/h shed = ~1.5 g braking MID-CORNER on the off-camber
   wall = weight forward on light rear = offs. tv never does this (its anticipation allows
   sqrt(v^2+2Ad) over true distance); the floor cap had no such cone. (lap med 29.66, off 3.7%.)
   STEP 6 SHIPPED (testing): BRAKE-CONE floor table -- out[i] = min over 200 m ahead of
   sqrt(fl[j]^2 + 2*A_FLOOR*d), A_FLOOR=15 m/s^2 (gentler than A_BRAKE=25 because this braking
   can land mid-corner). Any floor drop now gets a physically-brakeable approach ramp; nearby
   stations still dominate at small d, so the cone subsumes the original 18 m corner window.
   MEASURED STEP 6 (brake-cone table, zone 843-885 @0.80, 14 laps): zone speed BACK UP to 135,
   offs 28%, lap med 29.79 -- and the profile dump (s11_profile.py) finally exposed the real
   geometry, TWO compounding errors in steps 2-6:
   (a) A FLOOR CANNOT LOWER THE CAP: v_line = max(model, floor). In 843-885 the line's own
       curvature is GENTLE (model cap 139-165) -- attenuating the floor there hands control back
       to the model. v3 "worked" by accident: its long zone covered the upstream stations where
       the model cap IS low (109-130) and the floor was what raised them.
   (b) WRONG TARGET STATIONS: per-station profile vs the v2 soak: through the S11 APEX (809-849,
       model 109-130, plan 151-154) the car runs AT human speed (148-153) cleanly, 0% off. The
       collapse is the EXIT 859-878 (speed 137->92, off 33-52%) -- the human ACCELERATES along
       the wall there (plan 157-169); the controller's ~3 m exit scatter vs a 0.4 m corridor is
       what goes off. Exit scatter is a function of APEX speed -> attenuate the APEX stations
       (800-850) where the floor genuinely rules, not the wall stretch.
   STEP 7 (testing): vf2=0.85, zone 800-850 (apex ~130 = halfway baseline-safe 122 <-> proven
   148), brake-cone table retained. Config marker t=722.5 (soak log floor_v6_soak continues).
   MEASURED STEP 7 (apex zone 800-850 @0.85, 19 laps): apex speed UNCHANGED at 147 (target ~130),
   exit-wall off 43.5%. THE OVERRIDER: **v_curve_trim** -- the measured-g feedback sees spare grip
   at the apex (there IS spare; the limit is exit TRACKING, not grip -- that's the whole point)
   and creeps the cap back up toward 1.30x, defeating the intentional attenuation. Four knobs now
   interact at every corner (tv/plan, model cap, floor, trim); an attenuation scheme must account
   for ALL of them or the strongest optimist wins.
   STEP 8 SHIPPED (testing): TRIM CLAMP in attenuated zones -- build_floor_tbl also returns an
   attenuation MASK (final table vs zone-disabled table, so cone ramps are included); where masked,
   trim_eff = min(v_curve_trim, 1.0) (can shed, cannot raise). Relaunched (fresh log).
   MEASURED STEP 8 (trim clamp, 15 laps) -- **LANDED. THE BIG ONE: lap med 29.55 -> 28.71, twelve
   of 15 laps under 28.9 (spread 0.31 s!), best 28.53, off 2.6% = baseline canary.** Apex finally
   obeys (127), exit-wall offs 43% -> 3.0%. Section sum 28.69 (gap to human +1.48 s; was +2.54 at
   session start on this line). WHY THE WHOLE LAP JUMPED: S11's 45%-per-lap incident rate put an
   incident in ~every other lap, so the MEDIAN lap always contained one; killing the zone lifted
   the entire distribution. Reliability IS median speed. Bonus: S1 gap collapsed to +0.03 (vmin
   133 vs human 123 -- clean S13 exits + elevated trim carry into S1), S5 beats human -0.10,
   S2 +0.06. S11 gave back its floor gain (2.593 ~ baseline; accepted price), S12/S13 ~ baseline
   times with FAR calmer weave (cte p90 1.82/1.34 vs 4.88/2.60).
   WATCH ITEM: S1 off% 10 -> 16.3% (pre-existing; amplified by the new S1 speed; laps stay tight
   so these offs are cheap). If it starts costing: S1 is the next zone-attenuation candidate --
   the mechanism is proven and takes ~10 min to test (hot keys).
   LANDED CONFIG (RETIRED same day -- see INDEPENDENCE PRINCIPLE + lever 6): vfloor=0.95,
   vf2=0.85, vf2_lo=800, vf2_hi=850 (brake-cone per-station table + trim clamp). Landed log:
   recordings/follow_log_floor_landed.csv; section JSON: section_compare_floor_v8.json.
   *** RETIRED BY DESIGN PRINCIPLE (user, 07-03): "you cannot bind the bot to my speed. That
   removes the independence goal. It needs to determine how fast it can go. Eventually it will
   even need to draw its own line instead of using mine." The floor made the human's laps the
   AUTHORITY for the grip envelope -- backwards. HUMAN DATA IS FOR EVALUATION ONLY. (The plan's
   line/speed profile remains as desired-speed scaffolding ONLY until the own-line milestone.)
   The 28.71/28.53 result stands as evidence of what per-corner knowledge is worth (~1 s of
   median) -- the bot must now EARN that knowledge itself (lever 6).
   FLOOR-LEVER LESSONS (hard-won, do not relearn):
   (1) A FLOOR CANNOT LOWER A CAP -- attenuation only bites where the floor was the binding term
       (check the model-cap profile FIRST: s11_profile.py).
   (2) FOUR OPTIMISTS COMPETE at every corner: tv(plan), model cap, floor, g-util trim. Any
       localized slowdown must silence ALL of them or the strongest wins (trim clamp via
       attenuation mask).
   (3) CAP DROPS NEED BRAKE CONES (sqrt(v^2+2Ad), A_FLOOR=15): a bare window-min is a step ->
       1.5 g mid-corner braking -> offs at LOWER speed than baseline.
   (4) ATTENUATE THE APEX, NOT THE CRASH SITE: exit scatter is a function of apex speed; the offs
       happen downstream of their cause (profile the speed/off% by station before picking zones).
   (5) INCIDENT FREQUENCY DRIVES THE LAP MEDIAN more than section pace: a 45%-rate incident zone
       costs ~0.8 s of MEDIAN even when section medians look mild. Kill incident zones first.
6. [TESTING 07-03] SELF-CALIBRATED PER-STATION SPEED MAP (vtrim_map) -- the independence-
   compliant replacement for lever 5. The cap = v_curve * vtrim_map[18 m window min] *
   min(v_curve_trim, 1.0). The map (recordings/vtrim_map.npz, atomic persist, survives
   relaunches/crashes; fresh = 1.0 everywhere) is learned ONLY from the bot's own telemetry:
   - CREDIT (slow, +vtrim_up=0.0002/tick over the governing 18 m window): cornering >35 km/h,
     a_lat>2, measured g_util < corner_gutil, fc_frac > gate, |cte| < 2 m, on track.
   - DEBIT (fast, -vtrim_dn=0.002/tick): measured g_util > 0.98.
   - INCIDENT CUT (-vtrim_cut=0.02): off-track OR |cte|>8 OR |sideslip|>full_slide_deg cuts
     stations 15-55 m UPSTREAM (lesson 4 baked into the rule), once per station per lap
     (else one long excursion nukes a corner). Bounds [0.80, 1.35]. Only learns while racing
     (race_pos>=1) and launched. Global v_curve_trim is SHED-ONLY now (lesson 2: one raiser).
   - Hot keys: vtrim_on/up/dn/cut; vtrim_reset (set to a NEW nonzero value -> map := 1.0).
   - EXPECTED: first laps ~29.8-31 (map flat, shed-only trim), re-earning the floor's ~1 s of
     per-corner knowledge over ~30-40 laps -- but as ITS OWN answer. Convergence pattern also
     tells us where the model is wrong per corner (map >> 1 = model conservative there).
   CHECKPOINT 1 (18 laps, window-ahead attribution): laps flat 31.0-31.2, off 2.1%, map mean
   1.103 but max 1.335 piled at the HAIRPIN EXIT (s=444) while corner ENTRIES stayed ~1.0 ->
   ATTRIBUTION BUG: crediting the 18 m window AHEAD of a hard-cornering car puts apex proof on
   exit stations; entry stations (which govern the approach cap via the window-min) only sit
   ahead of a still-straight braking car (no g) so they never earn. FIXED: LOCAL attribution --
   measured g proves the CURRENT station (+-6 m); map reset, fresh learn.
   CHECKPOINT 2 (49 laps, local attribution): learning WORKS but equilibrium TOO TIMID -- laps
   dead-flat 31.1 (map mean 1.0->1.17 with zero lap-time response), off 0.7% (over-safe).
   MEASURED CAUSE: cornering g_util med 0.78 (baseline) -> 0.62. The map's credit ceiling was
   corner_gutil=0.82 so the map STALLS at 0.82 utilization, while the old free trim (7.5x faster
   up-rate) rode near the 0.98 debit ceiling = the map re-parked every corner ~7% slow. Also the
   fc_frac>0.52 credit gate is redundant with the g-ceiling and blocks credit above g_util ~0.86.
   RETUNED: new hot key vtrim_gutil=0.93 (credit ceiling, decoupled from the throttle gate's
   corner_gutil), fc gate dropped from map credit, vtrim_up 0.0002->0.0005, vtrim_hi 1.35->1.55
   (S3-kink-class corners need >1.35; floor evidence said up to ~1.7 is real), lo/hi hot now.
   Map CARRIED OVER (honest under-estimates, climbs from 1.175 mean).
   CHECKPOINT 3 (07-03): retuned-band soak WASTED -- the follower CRASHED 29 s after relaunch:
   np.load on the carried-over vtrim_map.npz returns a lazy NpzFile that HOLDS THE FILE OPEN;
   the first periodic save's os.replace onto the open file -> PermissionError WinError 5 ->
   process death. Didn't bite on the first soak (no map file existed -> no handle). No watchdog
   was running -> 29 min of nothing. FIXED: context-manager the load (with np.load(...) as f)
   + save_vtrim() returns False on failure instead of raising (a bookkeeping error must never
   kill the driver mid-race; dirty flag stays set, retries next cycle).
   LESSON (general): always close np.load NpzFile handles on Windows before anything replaces
   that file; and persistence code in the control loop must be failure-isolated.
   CHECKPOINT 4 (55 laps at retuned band): STILL flat 31.1-31.2, and the smoking gun: map mean
   1.40 with 618 stations at the 1.55 bound, g_util still 0.63, ZERO lap-time response across
   THREE map levels (1.0 / 1.17 / 1.40). APPLICATION BUG: the cap's window-min was SEEDED WITH
   1.0 -- computed min(1.0, window), so cuts applied but raises silently never did; with the
   loop open, credit never stopped (raising the map never raised speed -> g_util never rose)
   and the map saturated at its bound. The saturated values are meaningless -> map reset.
   FIXED: seed map_w with vtrim_map[i0], then window-min.
   LESSON (general): when a learned signal shows zero behavioral response across large value
   changes, suspect the APPLICATION path before the learning rule -- and test the plumbing with
   an extreme value first (vtrim_hi=1.55 everywhere would have exposed this in one lap).
   MEASURED (closed loop, 54 laps): **IT LEARNS.** Progression: first-10 med 30.58 -> mid 30.09
   -> last-10 med 29.69 / best 29.47 -- past the old 29.78 baseline within one soak, earned
   entirely from the bot's own telemetry. g_util med 0.63 -> 0.72 and climbing, off 1.0%. Two
   probe-too-far incident laps (~lap 25: 35.5/33.4) followed by visible cut-and-recover =
   intended probe/retreat. Map mean 1.33; 277 stations pinned at 1.55 = places the cap never
   binds at any multiplier (straights/gentle bends: g never rises, credit never stops) --
   cosmetic, but a future refinement is gating credit on the cap actually being near-binding.
   Trend still descending at soak end -> continued.
   CONVERGED (108 laps total): equilibrium lap med ~29.9-30.0, best 29.46, off 1.0%, g_util med
   0.73 -- essentially MATCHES the old 29.78 baseline, now honestly earned per-station and
   persistent. Section picture (37-lap tail, section_compare_vtrim.json) is a REDISTRIBUTION:
   the bot runs fastest-ever where it can verify safety itself -- **S7 2.047 (best of ANY
   config, beats the floor: it self-learned the crest corner!)**, S13 2.462 (best ever, vmin
   161), S5 beats human -0.10, S8/S4 at/above -- and stays deliberately timid where its own
   execution noise makes probing costly: S11 2.811 (map ~0.90 there: its experience says
   danger, which is TRUE for its tracking scatter), S1/S3/S10 under-earned vs the flat-model
   base. vs the floor's 28.71: the ~1.2 s difference = per-corner knowledge hidden from the
   bot behind its own line-wobble (it cannot distinguish 'track limit' from 'my scatter').
   THE LEVER THAT CLOSES IT: control PRECISION (the residual NN) -- less wobble => probes
   verify higher speeds => the map re-earns them autonomously. Map snapshot:
   vtrim_map_converged_20260703.npz. Refinements queued: gate credit on cap-near-binding
   (stops saturation creep on straights), light map smoothing.

7. [TESTING 07-03] GENERALIZING VTRIM (user: 'instead of vtrim being indexed by position,
   it could be something similar to the neural network with its features'). Architecture:
   **map(s) = clip(net(features(s)) + delta(s), lo, hi)** -- vtrim_net.py (10 -> 16 -> 1 tanh
   MLP, numpy) + per-station delta table. Files: vtrim_features.npz / vtrim_net.npz /
   vtrim_delta.npz (all in recordings; fallback to plain-table mode if missing).
   FEATURES (all self-derived, per-station statics): kappa windows (18 m fwd / 20 m back /
   40 m fwd), d|kappa|/ds, grade, d2elev/ds2 (crest), min edge clearance over 30 m, corridor
   width, physics-model speed, and a TELEMETRY CAMBER PROXY = median(v^2*kap_car - |a_lat|)
   over own laps, gated to >65 km/h + demand in (2,32) m/s^2 (ungated it read +70 phantom
   bank at hairpins from sideslip; meas_latg in the log is SIGNED -- take abs).
   CAMBER PROXY VALIDATED vs user ground truth: NEGATIVE = banked (accelerometer picks up
   +g sin(bank)): S12 -2.12 (only negative section = the bank), S11 +1.97 (off-camber),
   S1/S2 ~ +1-2.7 baseline bias, S7 +0.63. Known artifact: -26.7 spike at s~707 (S10, few
   samples). Signal is real.
   OFFLINE LOSO (leave-one-section-out) VERDICT: geometry features predict repeated corner
   archetypes well (S3/S8/S13 held-out wMAE ~0.00-0.03) but FAIL on unique places -- held-out
   S6 (hairpin exit, true 1.03) predicted 2.03; S1 overshot +0.34. Also 396/637 informative
   labels censored at the 1.55 bound. => pure offline distillation NOT deployable; the delta
   table absorbs uniqueness instead.
   ZERO-REGRESSION SWITCH-ON: delta initialized = converged_map - clip(net) at informative
   stations (pretrain wMAE 0.011) -> effective map identical where it matters. Both learn
   online with the SAME credit/debit/incident signals: delta gets the full increment, net
   gets increment x vtrim_netscale (0.1, hot) via normalized-gradient output steps
   (VtrimNet.step moves f(x) by exactly the requested amount). Bumps freeze at effective
   bounds (kills saturation creep in delta). vt_base refreshed every 256 frames (net drift =
   the generalization spreading). vtrim_reset now zeroes DELTA (net retained). Effective map
   still saved as vtrim_map.npz for tooling. PAYOFF: incidents/credits at one corner nudge
   similar-featured corners; on a line redraw or new track the net gives an informed prior
   instead of 1.0.
   MEASURED: (parity soak in progress -- expect ~converged times, then divergence as the
   net generalizes)

8. [DIAGNOSED 07-03, fixes pending] SWEEPER EXIT-THROTTLE STARVATION -- four mechanisms
   (exit_starvation.py binding attribution over 37 laps; per-tick classes P-lim/cap-lim/
   brake/shift + coast_diag.py + vcurve check):
   (a) P-ONLY THROTTLE ASYMPTOTE (global; control section S9 shows it pure: 100% P-limited,
       thr 0.1-0.5, standing err +2-4 km/h). desired = kp_thr*err needs 9 km/h error for
       full pedal -> pedal melts as target approaches. Same standing-error disease the brake
       had pre-brk_ff; t_ff is a STEERING lookahead, throttle never got a feedforward.
       FIX: integral term with anti-windup (bounded by thr_cap) or hold-throttle FF.
   (b) FOOT CAP ON THE BANK (S12 s879-918: thr_cap 0.13-0.42): fc_frac reads sustained
       0.8-0.9 lateral util AND drive_slip 1.2-1.7 derates further -- but that slip is
       LATERAL loading (combined_slip includes slip angle), not wheelspin. The foot refuses
       throttle for being loaded sideways; the human accelerates there. FIX: traction gate
       on slip_ratio (longitudinal, exists in fh6_telemetry.py, unused) instead of
       combined_slip for the THROTTLE path (keep combined for the brake anti-lock).
   (c) SHIFT LIFTS on the S12->S13 climb: up to 20% of ticks are throttle-zero shift lifts
       (8-frame lift + cooldown x many close gears). FIX: shorten lift frames / no-clutch.
   (d) REJOIN COAST-LOCK after S13's kink (s1020-1044): CONVICTED by vcurve==tgt==spd==~210
       with kappa_merge 0.0095 (v_rejoin = sqrt(24.3/0.007) = 212 exactly). A 1-2 m offset
       on the straight makes the planner's merge arc cap target AT current speed; weak
       high-speed steering can't close the offset (r_des 0.1-0.2 vs r_meas 0.02-0.07,
       und% 45-93 ON THE STRAIGHT) -> self-sustaining coast for ~25 m -> arrives s/f at 210
       vs human 243. FIX: floor v_rejoin at spd + ~2 m/s ONLY where the line ahead is
       near-straight (k_line < ~0.004) -- straights shouldn't let rejoin arcs veto
       acceleration; corners keep full rejoin authority.
   ALSO REFRAMED: S3's mid-section loss is NOT throttle -- it is a LEARNED MAP CUT braking
   at the kink (s282-300, map ~1.0, tgt drops to 132) + P-asymptote crawl during recovery
   (s316-330, 100% P-limited) -> belongs to the cut/earn-asymmetry avenue.
   Est. value: (a) ~0.3-0.5 s/lap global, (b) big share of S12's +0.40, (c) ~0.15-0.3 s,
   (d) ~0.3-0.5 s incl. compounding into S1. Order: (a) then (d) then (c) then (b).
   FIX (a) SHIPPED + VERIFIED (thr integral, ki_thr=0.5 hot, anti-windup at cap, x0.90
   bleed while braking): standing err lap-wide 2.90 -> 2.10 km/h, S9 3.10 -> 1.50; best
   29.01. Side effect: S12 bank speed +9 (pedal now actually pressed against the cap).
   Off 3.3% (watch). Log: follow_log_fixa_thr_integral.csv.
   FIX (d) SHIPPED + VERIFIED (v_rejoin floored at spd + rejoin_gain(2.0) when |k_line| <
   rejoin_kmin(0.004), both hot): **s/f speed 193.5 -> 207.9 km/h, lap med 30.03 -> 29.60,
   best 29.00, off 2.6%.** Coast zone now shows braking-for-S1 instead of coasting =
   arriving fast enough to need it. Log: follow_log_fixd_rejoinfloor.csv.
   FIX (c) SHIPPED + VERIFIED: shift lift 8 -> 6 frames, hold 4, cooldown 10. Climb
   shift-lift ticks 2.7 -> 0.7%, ZERO missed shifts (no limiter-pinned ticks), best 28.60,
   off 1.4%. Log: follow_log_fixc_shiftlift.csv.
   FIX (b) FAILED -> REVERTED: slip_ratio-only traction gate caused POWER-ON OVERSTEER
   (sideslip p99 7.4 -> 27.8 deg, off 1.4 -> 8.4%, S12 bank speed DOWN 161 -> 147, s/f
   208 -> 178 -- slides scrub the very speed the fix chased, and the slides fed unearned
   incident cuts into the vtrim map, which must re-earn them). LESSON: the combined-slip
   mute IS the power-oversteer guard; lateral load muting the pedal is partly load-bearing
   safety, not pure waste. Any retry keeps a combined ceiling, just softer (derate from
   ~1.5 instead of 1.05) -- do NOT ship pure slip_ratio again. Log:
   follow_log_fixb_slipratio_failed.csv. FINAL STACK: a + d + c.
   SCAR REPAIR + DESIGN-HOLE FIX: fix-b's slides cut LOW-LATERAL stations (s0-40 at 0.80 =
   a 200 km/h ceiling on the s/f straight; also s743-760, s1061-1070) which the cornering
   credit (a_lat>2 gate) could NEVER re-raise -- permanent scar class. Added STRAIGHT
   RE-EARN: half-rate credit when driving cleanly at target (>60 km/h, |err|<5 km/h,
   |cte|<2, no brake, no cornering g). Healing measured within one soak: s743-760
   0.80->0.89, s1061-1070 0.84->0.93, s/f speed creeping 195->198 (s0-40 slowest -- the
   brake-for-S1 zone rarely satisfies the credit gate; heals over farming hours).
   **FIX-ARC RESULT (heal soak, 20 laps): lap med 29.30 / best 28.55 / off 2.0% --
   best-ever independence-compliant config, still improving as scars heal.**
   Arc today: 29.78 (old baseline) -> 28.71 (floor, retired by principle) -> ~29.95
   (self-calibrated converged) -> 29.30 (+ fixes a/d/c, healing). Gap to human med 27.47
   ~= 1.8 s. Next known levers: cut/earn asymmetry (S1/S3/S10/S11 learned-caution zones),
   softer combined-slip ceiling retry (b'), residual NN on this base.

9. [SHIPPED 07-03, testing] S3 BRAKE-SLAM DIAGNOSIS (user spotted it spectating: bot slams
   brakes at the sweeper apex where they are FLAT). NOT throttle, NOT incident cuts (s3_diag:
   incidents cluster at S3 ENTRY s240-270, their cut windows land s185-255, ZERO apex hits).
   ROOT CAUSE: **credit-starved apex** -- kink stations satisfied every credit condition
   (g_util med 0.62 = 40% margin, a_lat 20.8) EXCEPT the cte<2.0 cleanliness gate: the bot's
   natural tracking offset through a 4.5 g sweeper is ~2.5 m (cte med 2.49/p90 3.26) ->
   credit permanently blocked -> map frozen at 0.96 from old cuts -> cap V-dips target to
   ~142 mid-sweeper (profile: tgt 188 -> 142 @ s312 -> 215 @ s328), brk pulse 0.33.
   FIX: cleanliness gate = EDGE MARGIN (half - |off_c| > 1.2 m), not absolute line offset --
   2.5 m off-line with 3 m to the edge is proven-safe; 1 m off-line beside a wall is not.
   Applied to both cornering credit and straight re-earn. GENERAL LESSON: learning-gate
   conditions must be checked against the controller's NATURAL operating envelope per zone,
   or the gate silently freezes learning exactly where the tracking tax is highest (which
   is where the gap lives). Expect: kink map 0.96 -> climbs to g_util equilibrium, S3
   toward the floor-era 2.34.

10. [SHIPPED 07-03, testing] S9 CREST DIAGNOSIS + LOAD-AWARE CREST FACTOR. User called the
   S9 crest+turn as the root of the S10/S11 trouble (watching); investigation confirmed the
   mechanism in the SPEED/throttle channel: the crest at s684-702 (grade rolls -7% -> -13%)
   drops measured load to 0.66 while the bot holds |steer|=1.00 SATURATED for 40 m (s660-700,
   sideslip to 5 deg, cte to 2.1) -- it enters at 129 km/h (FASTER than the human's 123)
   because S9-mid is compressed (load 1.1-1.65) so the map earned high there; the cap models
   grip as f(speed) only and cannot see the load about to vanish. Fighting the wash keeps
   the throttle shut until s~720 while the human is at full power from the apex: by s744 the
   bot is 151 vs 187 km/h -> the whole S10 gap (+0.43). Honest nuance: per-lap S11-incident
   state carryover NOT confirmed statistically (21% overlap; S11's routine incidents are its
   own probing) -- but the worst-case crest exits are the crash tail, and the time loss is
   unambiguous.
   FIX: **measured-load crest factor** -- build_load_map.py backs out per-station load from
   the bot's own telemetry (alat_max_g / model; crest 0.66, S12 bank ~1.0 -- measurement
   cannot confuse a bank roll with a crest the way elevation geometry does; an elev-only
   table wrongly derated the bank 30% and re-imposed base caps everywhere = discarded),
   solves v^2 k = alat(v) * load(v)^0.705 per station (v^2-scaled load), factor = v_loaded/
   v_full over the cap's 18 m window, =1 where near-straight or not light, backward-smeared
   0.004/m for a lift-not-slam approach. Applied OUTSIDE the vtrim map (physics is absolute;
   the map re-equilibrates around it): target *= crest_fac[i0], hot key crest_on.
   Factor: S9 crest 0.86, S7 crest 0.90, S12 bank-entry light spot 0.86 (real: 223 incident
   ticks there), S11 wall 0.94; 292 stations < 0.98.
   MEASURED (26 laps): the factor did NOT move the mechanism -- crest speed 128 -> 125,
   steer saturation unchanged 64%, S10 mid unchanged 149 (S9-zone incident ticks halved
   14.8 -> 8.5/1k; S12 zone worsened 3.6 -> 6.3/1k, watch). WHY: the load-corrected grip
   math says the crest-turn supports ~145 -- the derated cap (~150) still sits ABOVE the
   car's natural ~128 arrival. The cap was never binding there: the crest is EXECUTION-
   limited (steer pinned at 1.00 while light), not grip-limited. A cap-side derate cannot
   control an entry speed the cap does not set. Factor kept as a mild physics prior.
   FIX 2 SHIPPED (testing): **STEER-SATURATION CREDIT GATE** -- the deeper design flaw:
   vtrim credit saw g_util 0.62 at the crest and read it as spare grip, but low measured g
   with the wheel pinned is the SYMPTOM of execution saturation; the map kept re-earning a
   speed the tracker cannot deliver (probe -> wash -> incident cycle). Credit now also
   requires |steer| < 0.95. The crest equilibrium settles wherever steering unsaturates --
   self-calibrated depth, no hand-tuned factor. (Hairpins unaffected: already bound-pinned.)
   Expect: crest map values cut down over ~30-50 laps (incidents cut, credit no longer
   refills), crest entry drifting toward ~115, steer unsaturating, S10 exit speed rising.
   MEASURED (46 laps): **incident chain COLLAPSED -- s680-880 ticks 14.8 -> 4.7/1k (-68%),
   s920-1000 3.6 -> 1.0/1k (-72%)**, exit cte 1.89 -> 1.67, laps flat (med 29.73). BUT the
   crest itself still saturated (62% pinned, entry 126, S10 mid 148): with credit blocked,
   the map only descends via incident cuts -- and incidents got RARE, so the correction
   throttled itself. Equilibrium stuck at 'safe but saturated'.
   FIX 3 (SATURATION DEBIT) FAILED -> REVERTED: continuous cuts while pinned dug a sharp
   local hole; the map's bare 18 m window turned it into STEP BRAKING mid-crest while
   light -> rear unloads -> slides (sideslip p90 5 -> 24.8 deg!) -> incident cuts -> spiral
   to the 0.80 floor: crest speed 87, S10 mid 118, med 31.79, 19/42 incident laps.
   LESSON (same class as floor step 5, now proven for the MAP too): map DEBITS must stay
   slow/incremental -- any strong local cut needs brake-cone anticipation or it creates a
   mid-corner step exactly where braking destabilizes. Crest zone repaired to 1.30
   (artifact damage from the reverted mechanism, like the fix-b scars). LANDED STATE for
   the S9 arc = crest factor (mild physics prior) + steer-saturation credit gate:
   chain incidents -68%/-72% at held lap times; the crest stays saturated-but-safe -- the
   residual speed there is an EXECUTION-precision problem (the tracker cannot deliver the
   curvature while light at >120), which is residual-NN territory, not map territory.
   REPAIR SAGA + LESSON: hand-restoring the debit damage to a 1.30 floor REGRESSED the zone
   (crest ran 133 with slides, 33.6 ticks/1k): the system's own deep-cut stations (min
   ~0.99) WERE the equilibrium anchors -- window-min needs them; wholesale 'repair' removed
   signal along with damage. Re-anchoring the crest-turn proper (s680-704) at 1.10 fixed it.
   DO NOT hand-edit the map except to re-anchor after a reverted mechanism, and preserve
   the low anchors when doing so.
   **ARC LANDED (26 laps): ZERO incident laps, chain ticks 5.2/1k (was 14.8), S12 zone 0.0,
   crest entry 121, sideslip normal, lap med 29.51 (pre-arc 29.68), best 28.96.** Remaining
   crest gap (bot 121 vs human ~130 accelerating) = tracker precision while light ->
   residual NN.

## FINAL-PRODUCT PRINCIPLE (user, 07-03 -- supersedes architecture choices)
The final product is a PURE HEURISTIC CONTROLLER: no neural net glued on, and NO track-
position-indexed knowledge ("no track position aware cheating") -- it must generalize to
tracks it has never seen. Per-station tables (vtrim map/delta, load_map, crest_fac) and the
feature net are DEV-TIME INSTRUMENTS ONLY: their job is to reveal structure ("see what the
net does for whatever reason") which must then be re-expressed as explicit closed-form
terms in the controller, computable from (a) plan geometry available on any track (line
curvature, elevation profile, corridor width/clearance) and (b) live telemetry (measured
load, slip, yaw). EXTRACTION PLAN: fit interpretable forms to the converged learned state
(map values vs physical features at cap-binding stations), identify the few terms that
explain it, bake them into v_curve/the foot as formulas with global constants, then A/B
pure-formula vs learned-table on THIS track; ship the formula config as the product.

11. [DONE 07-03] CORRIDOR SURFACE SURVEY (user: 'dozens of laps to completely map the
   dynamics... the driving line we create in future iterations also gets the information').
   Infrastructure: survey_plans.py (9 offset plans, d=-4..+4 m, corridor-clamped 1.2 m
   margin, gentle speeds), run_survey.ps1 (autonomous sweep orchestrator, ~40 min, restores
   racing config), follow.py now logs y/pitch_deg/roll_deg (appended columns),
   build_surface_sheet.py fits y(s,d) = a + b*d + c*d^2 per station.
   RESULT: 913/1000 stations fitted (median 7 offset bins), **roll cross-check corr -0.98**
   = the sheet IS the surface. FINDINGS: (a) the track banks MILDLY TOWARD THE TURN nearly
   everywhere (+2.4..+7.1 deg; S12 strongest +6-7 = user's 'banked' confirmed; S1/S2 +2.4-3.7
   = reads 'flat' to a human; S11 exit +3-5 = its 'off-camber' FEEL is the crest/load-loss
   + wall, not tilt -- no off-camber strip found across the corridor); (b) crown is modest
   (p90 0.011 ~ 2 deg per 3 m); (c) **the telemetry camber proxy is RETIRED as a magnitude
   measure** (S3 read -6.5 m/s^2 ~ 40 deg of bank = absurd; it conflates drift dynamics
   with tilt -- keep g*sin(bank) from the SHEET instead).
   Files: recordings/surface_sheet.npz (a,b,c,dlo,dhi per station), recordings/survey/
   sweep_*.csv. The acquisition procedure is track-agnostic (~40 autonomous minutes).
   ARTIFACT FIX (user spotted a false mound at the S3->S4 sweeper edge, 07-04): NOT wall
   contact (extreme-offset samples were pristine: |dy/ds| <= 0.04, sweeps agreed) --
   **quadratic EXTRAPOLATION beyond survey coverage**: the line hugs one edge there, so
   sweeps covered only [-4,0] m while the corridor extends to -10.8 m; c fitted on a
   3-5 m span evaluated at the far edge fabricated +1.5 m of elevation. THREE FILTERS
   (permanent, in build_surface_sheet.py, for all future tracks): (1) coverage bounds
   dlo/dhi stored per station -- CONSUMER CONTRACT: evaluate the quadratic only within
   coverage, extend linearly at the edge slope beyond; (2) conditioning guard: span < 6 m
   -> line-only fit (c=0; 368 stations); (3) wall-jump gate: reject samples with
   along-path |dy/ds| > 0.15 (dilated +-8 frames; 11.9k samples = launch/curb transients;
   insurance for tracks where wall-riding DOES happen). Seam repair folded into the
   builder. Post-fix: roll cross-check improved to -0.99, validation table unchanged,
   crown p90 corrected 0.011 -> 0.0039 (much of the reported 'crown' was ill-conditioned
   fit curvature, not surface).
   GATE v2 (user spotted bumpy S7-S9 crests after v1, 07-04): the ABSOLUTE 15% slope gate
   disqualified the legitimate -15.3% crest descents wholesale (100% rejection at
   s592-598, 24% across crest zones vs 3.5% elsewhere) -> empty cells -> ragged fits
   exactly before/after the crest apexes where grade peaks (user called the location
   exactly). FIX: gate is now RELATIVE to the plan's local grade (reject
   |dy/ds - grade_ref| > 0.12, dilation +-4): a wall climb deviates from what the road
   does; a steep road does not. Rejections 11.9k -> 1.2k, crest bumps eliminated (worst
   156 mm -> nothing above ~50 mm seam-joint noise; joints also feathered). LESSON:
   outlier gates on physical signals must be referenced to the local expected value,
   never absolute thresholds -- legitimate physics reaches its extremes exactly where
   the interesting features live.
   S/F BUMPS FIX (user, 07-04): the two 'bumps' flanking start/finish were -0.4/-0.6 m
   DIPS from the gap fill: 3-bin stations (the near-one-sided s/f corridor collapses the
   clamped sweeps onto few offsets) failed the >=4-bin fit rule and were NEIGHBOR-COPIED
   from up to 50 stations away. FIX: (a) 3-bin stations now fit LINE-ONLY from their own
   data (own measurements beat any copy); (b) remaining fills use ANCHORED BLEND (plan-
   elevation shape pinned to surveyed values at both run edges -- continuous joints by
   construction; replaces copy+feather). Result: 986/1000 stations self-fitted (14
   filled), seam A tracks plan elev within +-1 cm, worst roughness anywhere 4-7 mm
   (genuine texture; the artifact era peaked at 156 mm).
12. [SHIPPED 07-04, testing] SURFACE-FRAME CAP (pure-controller step 1). build_surface_cap.py
   solves v^2 k cos(t) - g sin(t) = a_lat(v) * load(v)^0.705 per station with
   load(v) = cos(t) + z'' v^2/g + (v^2 k/g) sin(t); bank t from the SHEET (its lateral
   knowledge), z'' from the PLAN elevation (dense; the sheet's A too smoothed for second
   derivatives -- the offline validation table caught BOTH a flipped z'' sign and the
   washed-out z'' source before any track time). Brake-cone smoothed. Direction checks
   6/7 zones (S12 +3 bank gain, S9 crest -7, S3 -5 physical light spots; S7 flag: +10
   where measurement says cut -- the map vetoes optimism during migration). Wired into
   follow.py replacing crest_fac (crest_fac + load_map RETIRED; scap_on hot key). Runtime:
   absolute min() bound alongside the learned map. MIGRATION PLAN: map learning re-enabled
   (farming profile) -> where physics predicts correctly the map re-equilibrates flat ->
   residual map structure = LOCATED missing physics -> recal ramp absorbs the intercept ->
   final A/B vtrim_on=0 (pure) vs learned. Overnight ES stopped (base changing invalidates
   it; verdict + doubling rule recorded). NOTE: watchdog.ps1 addKeys = FARMING profile
   (resid_on=0, live map rates); resume_training.ps1 = TRAINING profile (resid_on=1,
   frozen map) -- align watchdog before any future training run.
   ABSOLUTE-WIRING FAILURE (first soak): med 34.15, 14/16 incident laps. Root causes:
   (a) the cap used the UNCALIBRATED base constants -- as an absolute min() it undercut
   the map-corrected runtime wherever physics gain < the ~27% calibration gap (S8/S9
   cap 81 vs runtime 117-128); (b) independent menger curvature disagreed with the
   planner's kappa_ref at sharp transitions (invented R=20 m corners); (c) bank sign
   ill-defined at S-bend curvature flips (spurious -5.6 deg). S13's collapse was pure
   collateral (its cap was fine). LESSONS: (1) relative corrections compose, absolute
   bounds collide with calibration layers -- ship physics as FACTORS until recal;
   (2) derived tables must use the runtime's own curvature source; (3) direction-signed
   terms need tapering through sign flips; (4) the +-25% sanity clamp stays forever.
   V2 SHIPPED (factor wiring, planner kappa_ref, bank taper, clamp): **soak 24 laps,
   med 29.88 / best 28.58 / off 2.5% -- parity restored with the physics layer live.**
   S9 improved (1.855 -> 1.812, vmin 122 vs human 118), S10 -0.28; S3/S12 slightly down
   with the map still re-earning the failed soak's cuts (self-heals while farming).
   EXTRACTION TEST RESULT (5.3 h / 586 laps after v2, 07-04): **med stable 29.0-29.2, best
   28.30, off 1.4%, incidents falling 7 -> 2 per 80 laps — best sustained state ever.**
   Map: 845/1000 stations pinned at the 1.55 bound (the global intercept is the dominant
   residual = the RECAL RAMP is justified and ready). Remaining sub-1.30 structure = the
   located missing-physics/caution list: (1) s558-576 S7 crest apex (the flagged +7
   optimism — plan-elev z'' under-represents the broad crest); (2) s32-103 S13exit/S1
   complex (0.80 — scar remnants + entry execution); (3) s690-693 S9 crest-turn
   (execution limit, not cap physics); (4) s770-808 S10/S11 transition (0.85-0.88).
   MORNING OUTAGE (09:27-10:33): 10 consecutive follower launches never wrote a log row
   (game likely stuck on a dialog recovery could not clear); watchdog burned its cap and
   gave up; restart #10 self-cleared and ran 5.3 h clean. Watchdog restarted with fresh
   budget + now archives the dying follower's stdout/stderr per restart (wd_fail_*.log)
   so the next mystery failure leaves evidence.
   NEXT: base recal ramp (absorb the intercept; surface cap flips to ABSOLUTE then),
   then the pure-config A/B (vtrim_on=0) --
   lateral demand = v^2 k cos(bank) - g sin(bank); load = cos(bank) - z'' v^2/g +
   (v^2 k/g) sin(bank) -- replacing crest_fac + load_map tables; then base recal ramp;
   then A/B pure-formula vs learned-table config.

## VEHICLE SPEC LAYER (user idea, 07-04 -- car-agnostic constants)
Tuning-menu stats read for the Tacoma (recordings/vehicle_spec.json). THE FINDINGS:
(1) menu lat-g at 60/120 mph -> a_lat(v) = 16.5 + 0.00241 v^2: the SLOPE matches our
    fitted usable k=0.0025 within 4% (two independent sources agree -- k is settled;
    this also retires the contaminated 'physical 0.005' envelope estimate).
(2) the INTERCEPT is sandbagged ~1.47x (bot already corners at 24.3 vs menu 16.5) and
    braking ~1.54x (measured 30 vs menu 19.5 m/s^2) -- the SAME factor: the game applies
    one consistent conservative scale to friction for this X-class build (menu friction
    circle internally coherent, brake/grip 0.95). User's caveat quantitatively confirmed.
(3) CAR-AGNOSTIC RECIPE: new vehicle = read menu -> take the SHAPE (slope k, brake/grip
    ratio, power curve from 0-60/0-100/top speed) -> multiply magnitudes by the measured
    game-vs-menu scale (~1.5, likely engine-consistent; verify per car with minutes of
    driving) -> measurement always outranks menu UPWARD (never leave performance on the
    table). Longitudinal model (3.77 / 1.41 m/s^2 bands) = the line optimizer's missing
    ingredient.
RECAL RAMP now menu-anchored: hold k = 0.0025 (confirmed twice), ramp a0 only
(24.3 -> 26 -> 28, canaries at each step; map re-equilibrates down as a0 absorbs it).
RAMP EXECUTED 07-04 (procedure: at each step scale the map's effective values by
sqrt(a0_old/a0_new) so caps are CONTINUOUS at the switch, then let credit re-earn):
- a0=26: PASS (med 29.15/29.35, off 1.1%, 1 inc/31 laps, map re-pinned 664 stations
  within 31 laps -- track validated the raise).
- a0=28: OVERSHOOT (med 29.73, off 4.5%, sideslip p99 22.3 = slides; refill slowed).
- a0=27: FAIL (second half med 30.14, off 2.9%, slides p99 12.8).
**LANDED a0=26, k=0.0025.** [SUPERSEDED BY THE 07-05 CONFOUND FINDING BELOW -- 26 is the
intercept GIVEN unfixed local defects, not the track's truth.]
USER PUSHBACK VALIDATED (07-05, they watched 27 fail at the S9 crest): incident-location
analysis confirms the intercept probes were CONFOUNDED -- a0=27's failures were 46%
S9-chain (s760-800 worst: the crest cascade), a0=28's were the S1 complex (s80-200,
~3000 ticks). Both are known located defects. RULE: the grip intercept is only
measurable after the location-specific execution defects stop being the binding
failure mode.
FIX SHIPPED (07-05, green-lit): **LOAD-COMPENSATED STEERING FF** -- steady-state
steering authority at light load measured SUFFICIENT (pinned-wheel envelope: kappa ~=
0.031 x load at 100-160 km/h >> the crest-turn's 0.013 need), so the defect is the
TRANSIENT: the FF (k_ff x kappa) has no load term; as the crest collapses load
1.1 -> 0.66 the same curvature needs more steer angle, the FF underdelivers exactly
when margin vanishes -> wash -> late PID -> overcorrect -> oversteer (the user's
observed chain). Now: ff *= clip(load_pred^-ff_loadcomp, 0.75, 1.45), load_pred =
1 + z''v^2/g from the surveyed zpp (surface_cap.npz), hot key ff_loadcomp=0.85.
VALIDATED: transient metrics improved at 26 (sideslip p90 5.5->4.4, exit cte
1.69->1.52, S10 exit +2); **27 RE-PROBE: incident ticks 27.3 -> 16.7/1k (-39%) at
identical medians** -- 27 moved from failing to borderline-viable; remaining chain
ticks cluster at the S10/S11 transition's own pre-existing caution zone.
INTERCEPT EXPERIMENT RUNNING: long soak at a0=27 + ff_loadcomp (watchdog aligned to
27) -- judge after hours of map equilibration; 26 remains the proven fallback. Note the coherence: 26/16.5 = 1.58 grip scale vs menu ~=
brake scale 1.54 -- the game-vs-menu sandbag factor is ~1.55 across the friction model
(vehicle_spec.json updated implication: new-car recipe = menu friction shape x ~1.55,
then verify). surface_cap + load_map builders updated to ALAT=26 and the cap table
rebuilt; watchdog + resume fargs aligned to --planner-alat 26.

LEVER 14 SOLVED THE CHAIN (07-05, 7-candidate in-game A/B, ~7 h of soaks): **CREST
GRIP-MARGIN**. After the crest_hold failure, a Workflow (4 analyses x 600-1300 historical
laps + adversarial verify) + hand analysis proved the S9 kill (s700-720 slide) is
STEERING-AUTHORITY EXHAUSTION: the car arrives at the crest too far INSIDE and the wheel
is ALREADY correctly maxed OUTWARD trying to un-inside (corr(cte,steer)=-0.65 everywhere,
NO sign flip -- the "positive-feedback" reading was a ks*sign artifact); it saturates
because the required correction exceeds +-1.0 under the LIGHT-crest grip -> washes (Pop A
71%) / over-rotates on the grip-return (Pop B 29%). So NO steering-law lever can help (the
budget is already spent right). USER DIRECTIVE: test all 7 candidates in-game, ~30 min
each, one at a time (hot-key gated, one continuous log sliced by t; arm.ps1 + seg_ab.py).
RESULTS vs baseline (kill-zone incident-LAPS 7/55=13%, med 29.32): steering/throttle-term
levers ALL FAIL -- aw_on(anti-windup) all-inc 13.26/1k, cr_on(P-restore) slower+3.82,
th_on(throttle-hold) kill 20%, hd_on(heading-deweight) kill 20%, ha_on(slew-limit)
CATASTROPHIC 40/1k. The ARRIVAL-GEOMETRY levers WORK: **cg_on (shave target_v x0.90 in the
crest APPROACH) -> kill 0/56, total incident-laps 1/56 (cleanest of all), med 29.37 =
+0.05 s FREE**; dose-response monotonic (0.92 free/partial, 0.90 free/zero-kill knee, 0.88
zero-kill/+0.47 s). Pooled cg<=0.90: 0/108 kill vs 7/55 -> Fisher p~0.0001 DEFINITIVE.
lb_on (outward S9 line-bias) kills S9 (0/54) but RELOCATES the slide to S10/S11 (s800-850)
even at 0.5 m -> out. WHY it works: slowing the APPROACH gives the maxed outward correction
the grip to un-inside BEFORE the grip returns -- exactly the grip-limited reading. WHY the
existing surface cap didn't: it binds AT the crest, not with brake-anticipation in the
approach. SHIP FORM (independence/final-product): cg_geo -- a survey-derived mask (approach
to any station with zpp<-0.0018 crest co-located with |kappa_ref|>0.010 turn, within 45 m)
replaces the s600-680 hand-gate; NOT track-position-hardcoded, transfers to any surveyed
track. Mask on this track = 294 st (29%), s361-853 (S7, S9, S10/11 crest-turns). cg_geo A/B
confirmation RUNNING (does the geometric trigger reproduce 0-kill? at what lap cost, since
it also slows S7/S10-11 which don't slide?). Keys: cg_on (dev s-range), cg_geo_on (ship);
all 7 candidates dormant behind hot keys in follow.py. LESSON: the offline footprint/verify
predicted every steering-lever failure correctly, but the WINNER (grip-margin) needed the
in-game A/B -- offline could not have ranked it. User was right to demand the soaks.

GENERALIZATION of LEVER 14 (07-05, the hard part): the s600-680 hand-gate (cg_on) is
track-position-specific. Attempts to make it survey-derived + generalizable:
(a) cg_geo NAIVE (slow approach to ANY light-crest-turn): reproduces the S9 fix (kill 0/53)
but +0.69-0.72 s -- also slows the FAST S7 approach (~150 km/h, 10% shave is expensive) which
never slides. (b) cg_geo SELECTIVE (crest->COMPRESSION-in-turn signature, the actual slide
mechanism): isolates S9 + S7->S8, BUT the first attempt anchored the mask s645-705 = INTO the
crest/kill zone -> CATASTROPHIC 51% kill (slowing DURING the light crest wrecks it; slowing the
APPROACH fixes it -- WHERE you apply margin is everything). (c) cg_geo CORRECTED (approach mask
[GAP=20,APPR=80] ENDING 20 m short of the hazard, s515-684): fixes the chain (kill 0/51,
chain 0.00/1k) but still +0.72 s from the S7 approach. KEY FINDING: **NO static survey feature
separates S9 (slides) from S7 (doesn't)** -- grip deficit, surface_fac, and speed all rank S7
WORSE, because S9's slide is DYNAMIC (accumulated inside-error from S8), invisible to any static
map. So the only principled generalizable path is LEARNED: vtrim_hold_geo -- freeze vtrim RE-EARN
inside the survey crest-compression-turn mask so incident-cuts STICK, self-selecting S9 from the
car's OWN slides. CONVERGENCE SOAK (80 min): self-selection PROVEN -- S9 map 1.53->1.17 (min .90)
vs S7 1.54->1.30, S9 dropping ~4x faster; kill 18->13% declining. BUT not clean: S7-S8 slides
occasionally too (gets scarred, frozen re-earn can't recover -> +0.71 s), and the vtrim cut lands
s645-705 (into-crest) not the effective s600-680 approach. Needs a PERSISTENT-HAZARD filter
(freeze only where incidents recur, not one-off learning noise) + upstream cut positioning.
DECISION: shipped the validated **cg_on=0.90 hand-gate** (kill 0, +0.05 s, watchdog-persisted) as
the working fix; generalizable form (cg_geo corrected at +0.72 s, or the vtrim-experience refined)
is a documented open problem. SEPARATE ISSUE surfaced: s400-450 braking corner throws intermittent
hard spins (100s of ticks) across many segments -- dominant "all-incident" inflator, unrelated to
the chain; needs its own diagnosis. Keys (all hot, dormant): cg_on, cg_geo_on, vtrim_hold_geo,
aw_on/cr_on/th_on/hd_on/ha_on/lb_on.

LEVER 13 FAILED + REVERTED (07-05): **crest_hold CORRECTION SCHEDULING** -- attempt at
the user's detailed S7->S8->S9 mechanism (compression adds grip -> controller turns too
sharply -> positioned inside before the S9 crest -> outward correction across the crest
-> fatal turn-back-in). Implementation: corr = min(_comp,1) on h_t/p_t/d_t + a crest
gate (1 + zpp_min12*v^2/g < 0.85 -> attenuate corr to >=0.30, freeze integrator).
RESULT: med 32.21 / incidents 104/1k / chain 56/1k (worse than old-27's 33.5) -- the
gate fired on **29% of ALL racing ticks** spread over the whole track: a 12 m forward-
min of zpp at speed trips on every mild downhill (zpp < -0.0009 at 150 km/h), not just
real crests. Reverted (crest_hold=0.0 everywhere: tune.json, watchdog addKeys, follow.py
DEFAULT -- the code stays, dormant). The 21 bad laps carved 125 stations to the 0.80
floor (s379-415, s552-614, s653-677); repaired by re-anchor rule (bogus zones back to
ceiling, the legit S7 apex s558-576 kept at its measured 1.06).
**LESSON (new discipline): any threshold-gated behavior change gets an OFFLINE
FALSE-POSITIVE FOOTPRINT CHECK against logged laps BEFORE deploying** -- fired-%-of-
ticks + zone distribution (scratchpad gate_diag/gate2_footprint pattern).
NEXT CANDIDATE (footprint-checked, awaiting user green light): target the CAUSE not the
symptom -- compression over-rotation damping. Full condition (crest ahead) AND
(compressed NOW: 1+zpp*v^2/g > 1.05) AND (turning: |kappa_ref| > 0.010) fires on only
1.5% of ticks, exactly at the compression->crest+turn sites (S7 entry s500, S8->S9
s600-650, S10/11 s800). Cleaner still: gain-schedule h_t/p_t/d_t by 1/load_pred
(clip [0.7,1.0]) -- pure plant-gain physics (compression = more grip = more yaw per
steer unit), no thresholds, generalizes; needs an offline check that S12's sustained
bank load tolerates the damping before trying.

## PRE-TELEMETRY DEADLOCK -- ROOT CAUSE + PERMANENT FIX (07-05)
The 07-04 morning outage (10 watchdog relaunches, 66 min, zero log rows) and tonight's
6-min stall are the same class: kill+relaunch drops the vpad -> Forza pops the
Controller-Disconnected dialog and PAUSES (Data Out stops) -> the new follower blocks
in socket.timeout forever; BOTH detectors can miss the dialog (the chartreuse color
check missed it tonight while OCR read the race HUD BEHIND the dialog -> state "other"
-> silent spin). Fixes shipped in follow.py: (1) OCR "disconnect" state now handled in
the no-telemetry branch (backup for the color check); (2) LAST-RESORT blind kick --
telemetry dead >45 s + screen unrecognized -> force-foreground + vpad A + SendInput
Enter every 8 s (only steals focus from the game/desktop, never a user app); (3)
afk_recover import failure now prints loudly instead of silently disabling recovery.
watchdog.ps1 additionally presses Enter (press_enter.py 2) after every relaunch.
Diagnostic gotcha: a probe socket on UDP 7777 reads NOTHING while a follower holds the
port (only one binder gets each datagram) -- "no telemetry" from a probe is a FALSE
NEGATIVE whenever the follower is running; check follow_log growth instead.

## RESIDUAL ES STANDING RULE (user, 07-04)
Overnight fresh run (07-03->07-04, 5 gens, 680 s windows, best base ever, map frozen):
NO improvement -- best fit 32.03 at gen 1 never beaten, median fitness drifted worse
(39->47), crashes up (0.7->1.8), lap_med flat 29.5. The ES remains NOISE-LIMITED at
680 s candidate windows. **RULE: if another NN training run is attempted, DOUBLE the
candidate evaluation time again -> 1360 s (~24 laps/candidate, ~4 h/gen, ~6 gens/day).**
Also note the residual NN is a DEV PROBE under the final-product principle (cannot ship);
the mainline remains the pure-controller extraction.

## INDEPENDENCE PRINCIPLE (user, 07-03 -- governs all future levers)
The bot determines its own limits from its own telemetry/experience. Human data may be used to
EVALUATE (section_compare) but never as an operating bound (no speed floors from human laps, no
human-derived caps). Current scaffolding explicitly tolerated until replaced: the reference LINE
(and its speed profile driving tv) is still the human's median -- the eventual milestone is the
bot drawing ITS OWN line (mlt_line/eval_optimizer exist as starting points; its grip model +
vtrim map would feed the optimizer). Anything new that reads human laps at runtime: reject.

## Measurement discipline
- Fresh clean-base laps (resid_on=0, zeroed net) on each new configuration; follow_log.csv TRUNCATES on
  launch -- archive it if it matters. Re-run section_compare.py; compare per-section vs this file's table.
- Diagnosis artifacts: recordings/section_compare_base_vs_human.json, scratchpad diag_s3/line_compare scripts.
