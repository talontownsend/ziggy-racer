# Operations Runbook

## 1. Start / pause the farm

**Start** (the watchdog launches and keeps the follower alive, re-adding `$addKeys` to
tune.json after every restart):
```powershell
Start-Process pwsh -ArgumentList '-NoProfile','-File','C:\Users\talon\FH6-AFK-Farm\watchdog.ps1' -WindowStyle Hidden
```
**Pause** (order matters - watchdog first or it relaunches the follower):
```powershell
Get-CimInstance Win32_Process -Filter "Name='pwsh.exe'"   | ? { $_.CommandLine -match 'watchdog' }  | % { Stop-Process -Id $_.ProcessId -Force }
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | ? { $_.CommandLine -match 'follow.py' } | % { Stop-Process -Id $_.ProcessId -Force }
```
Verify paused: `follow_log.csv` stops growing.

Manual follower launch: always pass `--plan recordings\refline_plan.npz` (the argparse default
is a stale plan - see PROJECT_MAP). Archive `follow_log.csv` first (startup truncates it).

## 2. Record your own hot laps
Farm must be paused (port 7777 is exclusive). Then:
```powershell
C:\Users\talon\FH6-AFK-Farm\record_my_laps.ps1     # Ctrl+C when done
```
Output: `recordings\run_<timestamp>.csv`. A fast recorded session (≤26.5s laps) feeds:
refline rebuild (`tools/build_refline2.py`), speed targets, and the BC dataset
(`tools/build_bc_dataset_v2.py`).

## 3. Hot-reload config (tune.json, picked up ~2.4 Hz)
Key groups (testing rules for these live in METHODOLOGY.md):
- **Steering FF:** `ffm_w` (0.15 = shipped optimum; 0=off), `ffm_gsc` (reactive-gain shed, 0.5),
  `t_ff` (FF lead time, 0.21 = includes +30ms latency compensation)
- **Braking:** `bla_tau` (onset anticipation, 0.70), `brk_ff` (1.0 - do NOT raise; chatter)
- **Speed caps:** `mbc_on` (map-boost cap, 1.0) + `mbc_a_lo/a_hi/b_lo/b_hi` spans;
  `mbc_geo` (survey-zone variant - new-track bootstrap only)
- **Pursuit:** `hul_lo/hul_hi` (stable-line aim zone 515-565), `head_use_line` (global - off)
- **Learning:** `vtrim_up/dn/cut/netscale` (0.0002/0.002/0.03/0.1 operating; all-0 = frozen
  for A/B, keep `vtrim_on=1`), `vtrim_reset` (nonzero-new-value → delta reset)
- **Dormant/experimental:** `s7m_on`, `acm_on` (retired margins), `bc_on/bc_w/...` (BC blend),
  `vt2_on/...` (line-adherence diagnostic), `ffm` map file hot-swaps on mtime
- **Watchdog persistence:** any key not in watchdog.ps1 `$addKeys` reverts on restart.

## 4. A/B protocol (the short version - full rules in METHODOLOGY.md)
1. Freeze vtrim (rates→0, `vtrim_on=1`) or plan for equilibrium windows.
2. Calibrate abort thresholds on the current config (hunt baseline etc.).
3. Arm via tune.json; put arm keys in watchdog `$addKeys` if the window must survive restarts.
4. Monitor with a script that **writes the rollback itself** on trigger.
5. ≥30 min re-equilibration before scoring; 50+ laps; ABAB washouts; session-aware scans.
6. Revert, restore learning rates, verify racing before walking away.

## 5. Post-game-update checklist
1. Telemetry: packet rate + column count parse (71.4 Hz, 57 cols).
2. Recovery: does it reach "racing confirmed"? (new screens usually yield to B+Esc ladder).
3. **Latency: steer→yawrate cross-correlation lag** - the only probe that catches input-pipeline
   changes (07-13: +28 ms, zero physics/settings changes). Compensate via `t_ff` (+lead), never gain.
4. Physics: speed-matched pedal-decel bins; corner-matched lateral-g percentiles. Aggregate
   medians WILL lie (METHODOLOGY.md, rule 5).
5. Settings: user checks in-game assists (a patch can reset them).
6. Watch the first hour: stall sites + excursion rates vs the previous band.

## 6. Known failure modes & responses
| Symptom | Likely cause | Response |
|---|---|---|
| Log stale >180 s | follower hang / game dialog | watchdog handles (cap 30); press_enter clears the disconnect dialog |
| Recovery loops "unrecognized screen" | game stuck outside race | usually resolves via B+Esc ladder; if looping >10 min, needs a human to restart the EventLab race |
| Wedge storms at one corner | arrival too hot for conditions | wedge-cut now carves the approach automatically; if it persists, check for a latency/physics shift (§5) |
| Full throttle + idle RPM | vpad not reaching game (ghost pad / Steam Input) | kill follower by PID, restart Forza (memory: fh6-throttle-not-reaching) |
| Farm dead, watchdog gave up | 30-restart cap hit | human: fix game state, restart watchdog |
