# FH6 AFK Self-Driving — Desktop Setup

Autonomous self-driving credit farmer for **Forza Horizon 6**: reads Data Out telemetry,
generates a per-tick merge path onto a computed racing line (Frenet local planner), and
drives via an injected virtual Xbox pad. This bundle moves the whole project + the Claude
Code conversation to a new machine.

> **IMPORTANT — keep the same path.** The scripts hardcode `C:\Users\talon\FH6-AFK-Farm\...`
> and the Claude session is keyed to that project path. If your desktop user is also `talon`,
> extract to the same locations and everything just works. If the username/path differs, you'll
> need to find/replace `C:\Users\talon\FH6-AFK-Farm` in the `.py` files (and the project dir
> name `C--` won't match — start a fresh session instead of resuming).

## 1. Where to extract

| In this bundle | Put it on the desktop at |
|---|---|
| `FH6-AFK-Farm\` | `C:\Users\talon\FH6-AFK-Farm\` |
| `claude-project-C--\*.jsonl` | `C:\Users\talon\.claude\projects\C--\` |
| `claude-project-C--\memory\` | `C:\Users\talon\.claude\projects\C--\memory\` |

## 2. Install dependencies

1. **Python 3.12** from python.org (NOT the Microsoft Store version — the Store `python` is a
   no-op stub on this account).
2. From a terminal in the project folder:
   ```
   python -m pip install -r requirements.txt
   ```
   (Smart App Control note: if SAC is on, run pip via the real `python.exe`, not a venv `.exe`
   shim, or it gets blocked.)
3. **ViGEmBus driver** (required by `vgamepad` to create the virtual controller):
   https://github.com/nefarius/ViGEmBus/releases — install the latest, then reboot.

## 3. Forza Horizon 6 setup

Settings → HUD and Gameplay → **Data Out: ON**, IP `127.0.0.1`, **Port `7777`**.

## 4. Resume the conversation

```
cd C:\Users\talon\FH6-AFK-Farm
claude --resume
```
Pick this session from the list. (Or use Remote Control from the laptop instead — see chat.)
The persistent memory in `.claude\projects\C--\memory\MEMORY.md` carries the full project
history if you'd rather start a fresh session.

## 5. Quick-start commands

- **Record your own laps** (reference data; upgraded recorder now logs accel + tire slip):
  ```
  python fh6_telemetry.py --port 7777 --out ./recordings
  ```
  Drive, then Ctrl+C. Sanity check: slip values ~0 at standstill, spike under load.
- **Rebuild the racing line** from a session CSV:
  ```
  python build_corridor.py recordings\<session>.csv
  ```
- **Run the follower** (current good config — planner ON, ~40 s clean laps):
  ```
  python follow.py --recover --planner-alat 14 --safety 0.8 --speed-cap 40 --max-throttle 0.9 ^
    --k-ff 6 --k-head 3.8 --kp 0.4 --ki 0.1 --kd 0.12 --t-ff 0.18 ^
    --ld-base 5 --ld-k 0.15 --ld-min 5 --beta-soft 8 --beta-hard 16 ^
    --cte-soft 2.5 --cte-hard 5 --shift-up-rpm 6200 --shift-down-rpm 2800 --top-gear 8
  ```
  `recordings\tune.json` hot-reloads safety/speed_cap/planner_alat/gains live (no restart).

## 6. Operating gotchas (hard-won)

- The follower only drives while **Forza is the FOREGROUND window** — it pauses telemetry
  otherwise (this was the "random death" cause). Background processes can't force focus on
  Windows, so keep FH6 focused.
- **Always relaunch with `--recover`** — stopping the follower drops the virtual pad, raising
  FH6's "reconnect controller" screen; `--recover` taps A→B to clear it.
- `--speed-cap` is in **m/s** (not km/h). `--planner-alat` is the corner-grip limit (m/s²).

## 7. Where the project is (state as of this bundle)

- **Working:** Frenet merge-path local planner + cross-track PID = 100% on-track, ~0.3 m off
  line, 0 spins, consistent ~40 s laps. Solid AFK farmer.
- **Next (planned):** the car has ~2.8–3.9 g of cornering grip (from your hot laps) but the
  follower only uses ~1.4 g — the gap is control, not grip. Build: (1) slip-handling steering /
  counter-steer, (4) grip-aware throttle, then (2) re-plan the line to measured per-section grip
  and co-tune to convergence, (3) with a light grade term. Downforce is negligible for this truck.
- The recorder was just upgraded to capture accel + tire slip so your next 50 laps give a clean
  reference-driver dataset for that work.

See `.claude\projects\C--\memory\fh6-afk-farm-project.md` for the detailed history.
