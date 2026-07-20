# Project Map - what lives where (post-cleanup, 2026-07-20)

```
FH6-AFK-Farm/
├── follow.py            ← THE controller (drive loop, all subsystems)
├── afk_recover.py       ← OCR screen recovery (menus/dialogs/restarts)
├── local_planner.py     ← Frenet merge-path planner
├── track_features.py    ← boundary-preview features + BC policy forward (shared train/runtime)
├── vtrim_net.py         ← speed-map feature net
├── residual_net.py      ← (dormant) residual corrector net
├── fh6_telemetry.py     ← UDP telemetry reader/recorder
├── press_enter.py       ← keyboard Enter tap (clears controller-disconnect dialog)
├── watchdog.ps1         ← farm keeper: restarts stale follower, re-adds tune keys ($addKeys
│                          = the persistent config; edit + restart watchdog to change)
├── record_my_laps.ps1   ← one-click HUMAN hot-lap recorder (refuses to run while farm is up)
├── README.md / SETUP.md / LICENSE / requirements.txt
├── follower_stdout.log / follower_stderr.log / watchdog.log   ← ACTIVE logs (path-referenced)
│
├── docs/                ← documentation (start with CONSTRAINTS.md)
│   ├── CONSTRAINTS.md          ← program constraints (invariants + exceptions register) ★
│   ├── METHODOLOGY.md          ← A/B testing rules, control-law lessons, artifact envelopes
│   ├── OPERATIONS.md           ← runbook: start/pause/record/A-B/post-update checklist
│   ├── PROJECT_MAP.md          ← this file
│   ├── S9_SOLUTION_REVIEW.md   ← the S9/S7 campaign write-up
│   ├── NIGHT_LOG_0708.md       ← overnight consistency-campaign log
│   ├── BASE_CONTROLLER_PLAN.md ← original architecture plan (historical)
│   └── media/                  ← README images/gif
│
├── tools/               ← maintained offline pipeline (run from repo root)
│   ├── build_refline*.py, build_corridor*.py, build_surface_*.py, build_bank_map2.py,
│   │   build_load_map.py        ← survey → track artifacts
│   ├── build_bc_dataset*.py, train_bc*.py, train_residual.py   ← learning pipelines
│   ├── line_opt_solver.py / line_opt_check.py  ← min-time line optimizer + calibrated lap model
│   ├── section_compare.py / section_analysis.py / analyze_dynamics.py / grip_*.py
│   ├── calibrate_steer.py / calibrate_yaw.py / validate_telem.py
│   ├── arm_vt2_diag.py / arm_vt2_test.py / watchdog_vt2.ps1  ← vtrim2 diagnostic instrument
│   └── _selftest*.py, run_survey.ps1, survey_plans.py, monitor_run.py, ...
│
├── attic/               ← historical one-offs (failed line solvers, old analyses, probes).
│                          Kept for provenance; nothing here is maintained or referenced.
│
├── logs/                ← historical logs (wd_fail_*, old training logs). Safe to delete.
│
└── recordings/          ← DATA. Root = only live/load-bearing artifacts:
    ├── tune.json               ← hot-reload config (~2.4 Hz). See OPERATIONS.md for keys.
    ├── follow_log.csv          ← ACTIVE telemetry log (truncated on relaunch - archive first)
    ├── refline_plan.npz        ← THE reference plan (line/walls/speed = human 27.28 lap)
    ├── session_20260621_093038_plan.npz ← argparse --plan DEFAULT (trap: manual launches
    │                              without --plan load this; watchdog always passes --plan)
    ├── steer_ff_map.npz        ← measured (κ,v)→stick map (ffm feedforward)
    ├── vtrim_map/delta/net/features.npz, acm_hits.npy, vtrim2_map.npz ← learned state
    ├── surface_cap/sheet.npz, bank_map.npz, load_map.npz, limits_edges_plan.npz ← survey physics
    ├── bc_policy.npz, bc_dataset*.npz, residual_net.npz ← learning artifacts
    ├── sections.json, vehicle_spec.json, track_geo.csv, elevation/speed_profile.csv
    ├── run_*.csv, session_*.csv ← HUMAN recordings (BC/refline sources - do not move,
    │                              referenced by absolute path in tools/)
    ├── archive_logs/    ← all historical follow_log_*.csv archives (GBs)
    ├── snapshots/       ← map/policy/plan snapshots & backups (incl. ship_snapshot_0707,
    │                       bc_campaign_0713, plan variants, old policies)
    ├── archive_data/    ← one-off captures, debug outputs, viz exports, ES-era state
    ├── limits_left/ limits_right/ refline/ survey/ ← raw survey data (rebuild inputs - │                       referenced by tools/build_* - keep in place)
```

**Immovable rules:** everything in the repo root is referenced by module name or absolute path
by the runtime chain (follow.py imports, watchdog.ps1 `$root\...`, record_my_laps.ps1). The
`recordings/` root files are loaded at runtime or referenced by tools by absolute path. Move
nothing out of these two levels without grepping for references first.
