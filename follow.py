#!/usr/bin/env python3
"""
FH6 autonomous follower (Stage 3) -- INJECTS INPUT via a virtual Xbox pad.

Reads live Data Out telemetry, locates the car on the planned racing line, and
drives it with pure-pursuit steering + a speed-profile tracker, output through a
ViGEmBus virtual Xbox 360 controller.

Safety:
  - Only sends input while Forza is the FOREGROUND window (alt-tab away = car stops).
  - Starts gentle: throttle and speed are capped (raise once steering is confirmed).
  - Ctrl+C (alt-tab to this console first) releases all inputs.
  - --duration auto-stops after N seconds as a backstop.

Setup: FH6 Data Out On / 127.0.0.1 / port 7777, ALL assists off, keyboard OR
controller scheme (the virtual pad drives either way). Start with the car ON the
track near the racing line, then run and alt-tab into FH6 during the countdown.

Run (gentle first test):
    & "C:\\Users\\talon\\AppData\\Local\\Programs\\Python\\Python312\\python.exe" .\\follow.py
Then raise limits once it tracks:
    ... .\\follow.py --max-throttle 1.0 --speed-cap 90 --safety 0.95
Flip steering if it turns the wrong way:
    ... .\\follow.py --steer-sign 1
"""
from __future__ import annotations

import argparse
import csv
import ctypes
import json
import math
import os
import socket
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fh6_telemetry import parse_packet
try:
    from afk_recover import (recover_to_racing, reset_car, close_map, ocr_text,
                             has_disconnect_dialog, screen_state, key_enter)
except Exception:
    import traceback
    print("[afk] WARNING: afk_recover import failed -- OCR self-recovery DISABLED:\n"
          + traceback.format_exc(), flush=True)
    recover_to_racing = reset_car = close_map = ocr_text = None
    has_disconnect_dialog = screen_state = key_enter = None
from racing_line import menger_curvature

user32 = ctypes.windll.user32

# Make this process DPI-aware so window rects (GetClientRect/ClientToScreen) and screen
# grabs (PIL ImageGrab) share the same PHYSICAL pixel space. Without this, under display
# scaling (e.g. 150%) the window box is computed in scaled-down "logical" pixels while the
# grab is in physical pixels, so captures only cover the top-left fraction of the window.
try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))   # PER_MONITOR_AWARE_V2
except Exception:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)          # PER_MONITOR_AWARE
    except Exception:
        try:
            user32.SetProcessDPIAware()                         # system-DPI aware (fallback)
        except Exception:
            pass


_GAME_EXE = "forzahorizon6.exe"
_kernel32 = ctypes.windll.kernel32


def _window_exe(hwnd) -> str:
    """Basename of the executable that owns hwnd (lowercased), or ''."""
    from ctypes import wintypes
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = _kernel32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        _kernel32.CloseHandle(h)


def foreground_is_forza() -> bool:
    # Match by owning process, not window title -- the chat/console window title may
    # itself contain "forza" (e.g. a session named after this project), which would
    # otherwise fool a title substring check.
    h = user32.GetForegroundWindow()
    if _window_exe(h) == _GAME_EXE:
        return True
    ln = user32.GetWindowTextLengthW(h)                  # fallback: exact title
    buf = ctypes.create_unicode_buffer(ln + 1)
    user32.GetWindowTextW(h, buf, ln + 1)
    return buf.value.strip().lower() == "forza horizon 6"


def _force_foreground(hwnd):
    """Bring hwnd to the foreground (AttachThreadInput trick beats the fg lock)."""
    try:
        fg = user32.GetForegroundWindow()
        ct = user32.GetWindowThreadProcessId(fg, None)
        tt = user32.GetWindowThreadProcessId(hwnd, None)
        user32.AttachThreadInput(ct, tt, True)
        user32.ShowWindow(hwnd, 9)                       # SW_RESTORE
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.AttachThreadInput(ct, tt, False)
    except Exception:
        pass


class _KBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_uint), ("time", ctypes.c_uint),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _KBDU(ctypes.Union):
    _fields_ = [("ki", _KBDINPUT)]


class _KBDIN(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint), ("u", _KBDU)]


def _send_enter():
    # keyboard ENTER via SendInput: the Controller-Disconnected dialog only answers
    # to Enter (a vpad A press does NOT clear it), and afk_recover may be absent
    for flags in (0, 2):                                 # down, up (KEYEVENTF_KEYUP)
        inp = _KBDIN(type=1, u=_KBDU(ki=_KBDINPUT(0x0D, 0, flags, 0, None)))
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_KBDIN))
        time.sleep(0.05)


def find_forza_window():
    """HWND of the actual Forza game window (matched by process), or None."""
    from ctypes import wintypes
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(h, _):
        if user32.IsWindowVisible(h) and _window_exe(h) == _GAME_EXE:
            found.append(h)
        return True

    user32.EnumWindows(_cb, 0)
    if found:
        return found[0]
    # fallback: window whose title is exactly "Forza Horizon 6"
    title_match = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb2(h, _):
        if user32.IsWindowVisible(h):
            n = user32.GetWindowTextLengthW(h)
            if n:
                b = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(h, b, n + 1)
                if b.value.strip().lower() == "forza horizon 6":
                    title_match.append(h)
        return True

    user32.EnumWindows(_cb2, 0)
    return title_match[0] if title_match else None


def grab_window(hwnd):
    """Screenshot a window's client area via PIL (no focus change). Returns a PIL Image."""
    from ctypes import wintypes
    from PIL import ImageGrab
    r = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    p = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(p))
    return ImageGrab.grab(bbox=(p.x, p.y, p.x + r.right, p.y + r.bottom), all_screens=True)


def wrap(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))


def main() -> int:
    import vgamepad as vg

    ap = argparse.ArgumentParser(description="FH6 autonomous racing-line follower")
    ap.add_argument("--port", type=int, default=7777)
    ap.add_argument("--plan", default=r"C:\Users\talon\FH6-AFK-Farm\recordings\session_20260621_093038_plan.npz")
    ap.add_argument("--steer-sign", type=int, default=-1, help="flip if it steers the wrong way")
    # steering: curvature feedforward + PID on cross-track error
    ap.add_argument("--k-ff", type=float, default=6.0, help="curvature feedforward gain (1/m -> stick)")
    ap.add_argument("--kp", type=float, default=0.18, help="PID proportional gain (stick per m of cte)")
    ap.add_argument("--ki", type=float, default=0.05, help="PID integral gain (kills steady offset)")
    ap.add_argument("--kd", type=float, default=0.6, help="PID derivative gain (damps overshoot)")
    ap.add_argument("--k-head", type=float, default=0.7, help="pursuit heading-alignment gain (preview)")
    # legacy gains (no longer used by the PID law, kept so old invocations don't error)
    ap.add_argument("--k-cte", type=float, default=3.5, help="(legacy)")
    ap.add_argument("--v-eps", type=float, default=5.0, help="(legacy)")
    ap.add_argument("--k-yaw", type=float, default=0.25, help="(legacy)")
    ap.add_argument("--yr-beta", type=float, default=0.4, help="(legacy)")
    ap.add_argument("--yaw-rate-sign", type=float, default=1.0, help="(legacy)")
    ap.add_argument("--t-ff", type=float, default=0.18, help="feedforward preview time (s)")
    ap.add_argument("--lff-min", type=float, default=4.0, help="min feedforward preview distance (m)")
    ap.add_argument("--lff-max", type=float, default=12.0, help="max feedforward preview distance (m)")
    ap.add_argument("--steer-rate", type=float, default=0.12, help="max steering change per tick (slew limit)")
    # DEPRECATED ALIASES (kept so old invocations still work): map onto k_head / k_cte
    ap.add_argument("--steer-gain", type=float, default=None, help="DEPRECATED alias for --k-head")
    ap.add_argument("--kc", type=float, default=None, help="DEPRECATED alias for --k-cte")
    ap.add_argument("--launch-m", type=float, default=5.0, help="limit steering for the first N m (launch)")
    ap.add_argument("--launch-cap-kmh", type=float, default=32.0, help="speed cap at the very start, ramped up over --launch-settle-m (eases onto the line from a grid/off-line start)")
    ap.add_argument("--launch-settle-m", type=float, default=80.0, help="distance over which the launch speed cap ramps up to full")
    ap.add_argument("--yaw-sign", type=float, default=-1.0, help="world heading = yaw_sign*yaw + yaw_offset")
    ap.add_argument("--yaw-offset", type=float, default=1.586, help="radians (calibrated to track)")
    ap.add_argument("--ld-base", type=float, default=6.0, help="lookahead at 0 speed (m)")
    ap.add_argument("--ld-k", type=float, default=0.3, help="lookahead growth per m/s")
    ap.add_argument("--ld-min", type=float, default=7.0)
    ap.add_argument("--ld-max", type=float, default=40.0)
    ap.add_argument("--safety", type=float, default=0.85, help="fraction of planned speed to target")
    ap.add_argument("--speed-cap", type=float, default=25.0, help="hard speed target cap (m/s)")
    ap.add_argument("--max-throttle", type=float, default=0.45, help="throttle ceiling (0..1)")
    ap.add_argument("--kp-thr", type=float, default=0.18)
    ap.add_argument("--kp-brk", type=float, default=0.20)
    ap.add_argument("--thr-rate", type=float, default=0.06, help="max throttle increase per tick")
    # --- stability / recovery (NEW): keep the car from spinning and recover when it slides ---
    ap.add_argument("--beta-soft", type=float, default=8.0, help="sideslip deg where throttle starts derating")
    ap.add_argument("--beta-hard", type=float, default=16.0, help="sideslip deg: cut throttle + cap steer (spin recovery)")
    # sideslip-based counter-steer (point #1): catch slides the yaw-rate detector misses
    ap.add_argument("--slide-deg", type=float, default=7.0, help="sideslip deg where counter-steer-into-slide begins")
    ap.add_argument("--k-slide", type=float, default=0.045, help="counter-steer gain (steer units per deg sideslip)")
    ap.add_argument("--full-slide-deg", type=float, default=22.0, help="sideslip deg where counter-steer fully overrides path lock")
    # slip-INDUCTION (point #1, second half): trail-brake to ROTATE the car when the front
    # steering saturates in a tight corner and it still won't turn enough (understeer).
    ap.add_argument("--slip-brake", type=float, default=0.0, help="trail-brake amount to induce rotation when steering-saturated + understeering in a tight corner (0=off)")
    ap.add_argument("--slip-steer-sat", type=float, default=0.85, help="|steer| above which the front is considered saturated (slip-induction trigger)")
    ap.add_argument("--slip-kap-min", type=float, default=0.05, help="min |path curvature| (1/m) for slip-induction to engage (tight corners only)")
    ap.add_argument("--cte-soft", type=float, default=2.5, help="off-line m where the speed governor starts")
    ap.add_argument("--cte-hard", type=float, default=5.0, help="off-line m: force slow to rejoin the line")
    ap.add_argument("--lowspeed-steer-kmh", type=float, default=8.0, help="below this speed (post-launch) cap steer (heading noise)")
    # --- local planner (NEW): generate a merge path onto the line each tick, track THAT ---
    ap.add_argument("--no-planner", action="store_true", help="disable the Frenet merge-path planner; fall back to raw-line pursuit")
    ap.add_argument("--planner-alat", type=float, default=13.0, help="base lateral grip alat0 (m/s^2) at low speed; corner-speed + merge feasibility")
    ap.add_argument("--planner-alat-k", type=float, default=0.00383, help="DOWNFORCE term: a_lat(v)=alat0+alat_k*v^2 (measured ~2.45g->3.9g, k=0.00383)")
    ap.add_argument("--slip-target", type=float, default=1.1, help="grip-optimal combined-slip; the foot feathers throttle above this (measured ~0.8-1.2 at the limit)")
    # --- point #2: counter-steer (oversteer) + speed-ease (understeer), ESC-style ---
    # (--yaw-rate-sign already defined above (legacy); reused here -- pass -1 for this rig)
    ap.add_argument("--k-counter", type=float, default=0.5, help="counter-steer gain on yaw-rate error when oversteering (stick per rad/s)")
    ap.add_argument("--r-thr", type=float, default=0.2, help="yaw-rate-error deadband (rad/s) before over/understeer engages")
    ap.add_argument("--understeer-gain", type=float, default=0.9, help="when understeering, ease target speed to this fraction of current")
    ap.add_argument("--understeer-thr", type=float, default=0.75, help="understeer if |r_meas| < this * |r_des| (turning <75% of commanded)")
    ap.add_argument("--top-gear", type=int, default=8)
    ap.add_argument("--shift-up-rpm", type=float, default=6200.0, help="upshift above this rpm (absolute)")
    ap.add_argument("--shift-down-rpm", type=float, default=2800.0, help="downshift below this rpm (absolute)")
    ap.add_argument("--no-clutch", action="store_true", help="shift without the clutch (diagnostic)")
    ap.add_argument("--duration", type=float, default=1800.0, help="auto-stop after N s")
    ap.add_argument("--log", default=r"C:\Users\talon\FH6-AFK-Farm\recordings\follow_log.csv")
    ap.add_argument("--path-log", default=r"C:\Users\talon\FH6-AFK-Farm\recordings\paths_log.jsonl",
                    help="periodic dump of the planner's merge paths (for offline viz)")
    ap.add_argument("--path-log-every", type=int, default=20, help="frames between merge-path dumps")
    ap.add_argument("--recover", action="store_true", help="on startup, tap --recover-keys to claim controller input / clear the reconnect-controller screen")
    ap.add_argument("--recover-keys", default="AB", help="button(s) to tap during recovery (e.g. 'A' to just claim controller input without menu nav; 'AB' = legacy)")
    ap.add_argument("--recover-delay", type=float, default=1.2, help="seconds to wait before the recovery taps (raise it so you can focus Forza first)")
    ap.add_argument("--afk", action="store_true", help="fully hands-off: OCR-self-recover from any non-driving state (dialog/pause/results/free roam) and auto-relaunch the EventLab race -- never needs a human")
    ap.add_argument("--capture", action="store_true", help="snap the Forza window every --capture-every-m, tagged with telemetry (telemetry-aligned frames + manifest)")
    ap.add_argument("--capture-dir", default=r"C:\Users\talon\FH6-AFK-Farm\recordings\frames")
    ap.add_argument("--capture-every-m", type=float, default=8.0, help="meters of travel between captured frames")
    ap.add_argument("--capture-laps", type=int, default=1, help="stop capturing after this many full laps")
    ap.add_argument("--tune-file", default=r"C:\Users\talon\FH6-AFK-Farm\recordings\tune.json",
                    help="live-tunable params (safety/speed_cap/max_throttle/ld_*/k_ff/k_head/k_cte/v_eps/k_yaw/t_ff), hot-reloaded ~2x/s")
    args = ap.parse_args()

    d = np.load(args.plan)
    line, vplan, left_w, right_w = d["line"], d["speed"], d["left"], d["right"]
    elev_w = d["elev"]   # line elevation profile (for the 3D preview's vertical dimension)
    n = len(line)
    seg = np.hypot(*(np.roll(line, -1, 0) - line).T)        # closed segment lengths
    print(f"plan: {n} pts, {seg.sum():.0f} m, target speed {vplan.min()*3.6:.0f}-{vplan.max()*3.6:.0f} km/h")
    s_of = np.concatenate([[0.0], np.cumsum(seg)])[:-1]   # arc length per station

    # SELF-CALIBRATED per-station corner-speed map (INDEPENDENCE: the bot determines how
    # fast IT can go at each corner from ITS OWN experience -- never bound to the human's
    # speeds. The human's laps are for EVALUATION only; user 07-03). The cap becomes
    # v_curve * vtrim_map[s]: starts at 1.0 everywhere, earns speed where the bot corners
    # with measured spare grip and clean tracking, cuts fast where it exceeds budget, and
    # an off/slide event cuts the stations 15-55 m UPSTREAM (offs land downstream of their
    # cause -- the S11 lesson) at most once per station per lap. Persisted across launches.
    VTRIM_PATH = os.path.join(os.path.dirname(args.plan), "vtrim_map.npz")
    vtrim_map = np.ones(n)
    # GENERALIZING form (user 07-03: 'instead of indexed by position... like the NN with
    # its features'): effective map(s) = clip(net(features(s)) + delta(s), lo, hi).
    # The tiny feature net (curvature windows, grade, crest, clearance, width, model
    # speed, measured camber proxy) EXTRAPOLATES across similar places; the per-station
    # delta absorbs genuinely unique spots (LOSO: held-out S6 predicted 2.03 vs true
    # 1.03 -- one track has too few corner archetypes for features alone). delta was
    # initialized so net+delta == the converged position map exactly (zero-regression
    # switch-on). Both learn online from the same credit/debit/incident signals; net
    # steps are scaled by vtrim_netscale. Falls back to plain-table mode if the
    # feature/net files are missing.
    _rec_dir = os.path.dirname(args.plan)
    VTRIM_DELTA_PATH = os.path.join(_rec_dir, "vtrim_delta.npz")
    VTRIM_NET_PATH = os.path.join(_rec_dir, "vtrim_net.npz")
    VTRIM_FEAT_PATH = os.path.join(_rec_dir, "vtrim_features.npz")
    vnet = None; vXf = None
    vdelta = np.zeros(n)
    try:
        from vtrim_net import VtrimNet
        with np.load(VTRIM_FEAT_PATH) as _f:
            _X, _mu, _sd = _f["X"], _f["mu"], _f["sd"]
        if len(_X) != n:
            raise ValueError("feature table station count mismatch")
        vXf = (_X - _mu) / _sd
        vnet = VtrimNet.load(VTRIM_NET_PATH)
        with np.load(VTRIM_DELTA_PATH) as _f:
            _d2 = _f["delta"].astype(float)
        if len(_d2) == n:
            vdelta = _d2
        print(f"vtrim: net+delta mode ({vXf.shape[1]} features; |delta| p90 "
              f"{np.percentile(np.abs(vdelta), 90):.3f})")
    except Exception as e:
        print(f"vtrim: net unavailable ({e}) -> plain table mode")
        try:
            with np.load(VTRIM_PATH) as _vt:
                _m = _vt["map"].astype(float)
            if len(_m) == n:
                vdelta = _m - 1.0     # table mode = constant-1 base + delta
        except Exception:
            pass

    # SURFACE-FRAME CAP (pure-controller step 1, 07-04): absolute per-station speed cap
    # from the surveyed surface sheet -- full 3D physics: bank assists the turn
    # (v^2 k cos t - g sin t) and loads the tires (+v^2 k sin t / g); crest/compression
    # scale load (+z'' v^2/g). Brake-cone smoothed at build time. Replaces the crest
    # factor and load_map tables. Track-agnostic: rebuild on any surveyed track via
    # build_surface_cap.py. During migration it rides min() alongside the learned map;
    # where the physics predicts correctly the map re-equilibrates toward flat 1.0
    # (the extraction test) -- residual map structure = located missing physics.
    surface_fac = np.ones(n)
    scap_zpp = np.zeros(n)
    try:
        with np.load(os.path.join(_rec_dir, "surface_cap.npz")) as _sc:
            _fac = _sc["fac"].astype(float)
            _zpp = _sc["zpp"].astype(float)
        if len(_fac) == n:
            surface_fac = _fac
            scap_zpp = _zpp
            print(f"surface factor: loaded (min {surface_fac.min():.2f} @ "
                  f"s={s_of[int(np.argmin(surface_fac))]:.0f}, max {surface_fac.max():.2f}; "
                  f"zpp range {scap_zpp.min():+.4f}..{scap_zpp.max():+.4f})")
    except Exception as e:
        print(f"surface factor: unavailable ({e}) -> 1.0")
    # rolling 12 m forward-min of z'' -- the crest gate asks 'is a light zone imminent'
    zpp_min12 = scap_zpp.copy()
    for _i in range(n):
        _d, _j = 0.0, _i
        while _d < 12.0:
            if scap_zpp[_j] < zpp_min12[_i]:
                zpp_min12[_i] = scap_zpp[_j]
            _d += seg[_j]; _j = (_j + 1) % n

    # forward look-ahead z'' at ~6 m and ~10 m (candidates #2 correction-restore, #3 throttle-hold)
    def _zpp_ahead(dist):
        out = scap_zpp.copy()
        for _i in range(n):
            _d, _j = 0.0, _i
            while _d < dist:
                _d += seg[_j]; _j = (_j + 1) % n
            out[_i] = scap_zpp[_j]
        return out
    zpp_ahead6 = _zpp_ahead(6.0)
    zpp_ahead10 = _zpp_ahead(10.0)


    def vtrim_base():
        return vnet.forward(vXf) if vnet is not None else np.ones(n)

    vt_base = vtrim_base()
    vtrim_map = np.clip(vt_base + vdelta, 0.80, 1.55)   # EFFECTIVE map the cap reads
    print(f"vtrim effective: mean {vtrim_map.mean():.3f}, min {vtrim_map.min():.2f} "
          f"@ s={s_of[int(np.argmin(vtrim_map))]:.0f}, max {vtrim_map.max():.2f}")

    def save_vtrim():
        # a bookkeeping failure must NEVER kill the driver mid-race: report, retry later
        try:
            tmp = VTRIM_PATH + ".tmp.npz"
            np.savez(tmp, map=vtrim_map)
            os.replace(tmp, VTRIM_PATH)
            tmp = VTRIM_DELTA_PATH + ".tmp.npz"
            np.savez(tmp, delta=vdelta)
            os.replace(tmp, VTRIM_DELTA_PATH)
            if vnet is not None:
                vnet.save(VTRIM_NET_PATH)
            return True
        except Exception as e:
            print(f"vtrim: save failed ({e}); will retry", flush=True)
            return False

    from local_planner import LocalPlanner
    planner = None if args.no_planner else LocalPlanner(line, a_lat=args.planner_alat)
    planner_alat = args.planner_alat        # hot-reloadable (base corner-grip / merge feasibility)
    planner_alat_k = args.planner_alat_k    # downforce term (grip rises with speed)
    slip_target = args.slip_target          # grip-aware foot's target combined-slip
    k_counter = args.k_counter; r_thr = args.r_thr          # point #2 (counter-steer)
    understeer_gain = args.understeer_gain; understeer_thr = args.understeer_thr
    r_meas_f = 0.0                          # low-passed measured yaw rate
    print(f"local planner: {'OFF (raw-line pursuit)' if planner is None else 'ON (Frenet merge-path, a_lat=%.0f)' % args.planner_alat}")

    # RESIDUAL CORRECTOR NET (residual policy learning): a small learned trim ON TOP of the
    # nominal control. Hot-loads weights from recordings/residual_net.npz (the trainer writes
    # them ~each candidate); stays OFF until resid_on=1 in tune.json. Zero weights == no-op.
    from residual_net import ResidualNet, N_FEAT
    RESID_PATH = r"C:\Users\talon\FH6-AFK-Farm\recordings\residual_net.npz"
    resid_net = ResidualNet(n_hidden=16)
    resid_on = 0.0
    resid_mtime = 0.0
    try:
        resid_net.load(RESID_PATH); resid_mtime = os.path.getmtime(RESID_PATH)
        print(f"residual net: loaded {RESID_PATH} ({resid_net.n_params} params)")
    except Exception:
        print(f"residual net: no weights yet (zero=no-op); will hot-load {RESID_PATH}")

    # SFT POLICY (behavioral-cloned from the human's laps): when bc_on=1 in tune.json it DRIVES
    # (full control: steer/thr/brk = net output) during normal racing; base recovery still handles
    # off-track/reset/relaunch. The 35 line-invariant features + numpy forward come from
    # track_features (same code as build_bc_dataset.py -> no feature mismatch). Hot-loads bc_policy.npz.
    # Default OFF, and bc_on is NOT in the startup args/watchdog keys -> any restart reverts to base (safe).
    from track_features import sft_features, bc_forward, load_bc_policy, cumlen as _cumlen, boundary_preview3d
    BC_PATH = r"C:\Users\talon\FH6-AFK-Farm\recordings\bc_policy.npz"
    bc_on = 0.0
    bc_clen = _cumlen(line)
    bc_policy = None
    bc_mtime = 0.0
    try:
        bc_policy = load_bc_policy(BC_PATH); bc_mtime = os.path.getmtime(BC_PATH)
        print(f"SFT policy: loaded {BC_PATH}")
    except Exception:
        print(f"SFT policy: none yet; will load {BC_PATH} when bc_on=1")

    # steering law params: curvature feedforward + pursuit-heading + PID(cte). hot-reloadable.
    k_ff, k_head, kp, ki, kd = args.k_ff, args.k_head, args.kp, args.ki, args.kd
    t_ff, lff_min, lff_max, steer_rate = args.t_ff, args.lff_min, args.lff_max, args.steer_rate
    kp_thr = args.kp_thr                    # throttle gain on speed error (hot-reloadable)

    # live-tunable params (hot-reloaded from tune-file so we never restart to tune)
    safety, speed_cap, max_throttle = args.safety, args.speed_cap, args.max_throttle
    ld_base, ld_k, ld_min = args.ld_base, args.ld_k, args.ld_min
    beta_soft, beta_hard = args.beta_soft, args.beta_hard
    slide_deg, k_slide, full_slide_deg = args.slide_deg, args.k_slide, args.full_slide_deg
    slip_brake_gain = args.slip_brake       # trail-brake rotation amount (hot-reloadable)
    cte_soft, cte_hard = args.cte_soft, args.cte_hard
    ff_use_line = 0.0                        # 1.0 = FF reads stable line curvature (anti-hunt)
    head_use_line = 0.0                       # 1.0 = pursuit aims at stable line point (anti-hunt)
    try:
        json.dump({"safety": safety, "speed_cap": speed_cap, "max_throttle": max_throttle,
                   "ld_base": ld_base, "ld_k": ld_k, "ld_min": ld_min,
                   "k_ff": k_ff, "k_head": k_head, "kp": kp, "ki": ki, "kd": kd, "t_ff": t_ff,
                   "kp_thr": kp_thr,
                   "beta_soft": beta_soft, "beta_hard": beta_hard,
                   "slide_deg": slide_deg, "k_slide": k_slide, "full_slide_deg": full_slide_deg,
                   "slip_brake": slip_brake_gain,
                   "cte_soft": cte_soft, "cte_hard": cte_hard,
                   "planner_alat": args.planner_alat, "planner_alat_k": args.planner_alat_k,
                   "slip_target": args.slip_target, "k_counter": args.k_counter, "r_thr": args.r_thr,
                   "understeer_gain": args.understeer_gain, "understeer_thr": args.understeer_thr},
                  open(args.tune_file, "w"), indent=2)
    except Exception:
        pass

    # --- precompute signed, smoothed plan curvature (menger is UNSIGNED) ---
    p0 = np.roll(line, 1, 0); p2 = np.roll(line, -1, 0)
    cross = (line[:, 0] - p0[:, 0]) * (p2[:, 1] - p0[:, 1]) - \
            (line[:, 1] - p0[:, 1]) * (p2[:, 0] - p0[:, 0])
    kappa_signed = menger_curvature(line) * np.sign(cross)
    _kk = np.ones(5) / 5
    kappa_signed = np.convolve(np.r_[kappa_signed[-5:], kappa_signed, kappa_signed[:5]], _kk, "same")[5:-5]

    # --- GENERALIZABLE grip-margin mask (cg_geo, 2026-07-05): the A/B-validated fix for the
    # compression-crest-turn slide is to SLOW THE APPROACH to a light crest that sits in a turn,
    # so the (already-maxed) outward steering correction has grip to un-inside the car before the
    # grip returns. Derived closed-form from the SURVEY (zpp crest depth + kappa_ref turn) -- it is
    # NOT a hardcoded s-range, so it transfers to any surveyed track (the s600-680 hand-gate was a
    # dev instrument; this mask reproduces it at S9 and fires at any similar crest-turn). Validated
    # A/B: cg_on 0.90 over s600-680 gave 0/56 kill-zone laps at +0.05 s.
    # SELECTIVE signature: a light CREST immediately followed by a COMPRESSION (the grip-return)
    # WHILE turning -- THIS is the slide mechanism (light -> heavy over-rotates the inside-pinned
    # car), not just any crest-turn. Isolates S9 (kill zone) + S7->S8; skips S10/11 & fast crests
    # that don't slide, so the generalizable policy stays cheap. (Naive any-crest-turn cost +0.69 s.)
    CG_ZC, CG_ZP, CG_KT, CG_APPR, CG_GAP = -0.0035, 0.0035, 0.010, 80.0, 20.0
    _crest_turn = np.zeros(n, dtype=bool)             # here: the crest->compression-in-turn point

    def _wmin(a, i, back, fwd):
        v = a[i]; d = 0.0; j = i
        while d < fwd:
            d += seg[j]; j = (j + 1) % n; v = min(v, a[j])
        d = 0.0; j = i
        while d < back:
            j = (j - 1) % n; d += seg[j]; v = min(v, a[j])
        return v

    def _wmax(a, i, back, fwd):
        v = a[i]; d = 0.0; j = i
        while d < fwd:
            d += seg[j]; j = (j + 1) % n; v = max(v, a[j])
        d = 0.0; j = i
        while d < back:
            j = (j - 1) % n; d += seg[j]; v = max(v, a[j])
        return v
    _absk = np.abs(kappa_signed)
    for _i in range(n):
        _crest_turn[_i] = (_wmin(scap_zpp, _i, 12.0, 2.0) < CG_ZC          # crest just before
                           and _wmax(scap_zpp, _i, 0.0, 14.0) > CG_ZP      # compression just after
                           and _wmax(_absk, _i, 3.0, 10.0) > CG_KT)        # turning
    # margin applies in the APPROACH [GAP, APPR] metres before a hazard -- ENDING GAP m short of it
    # so it NEVER slows INTO the light-crest/kill zone (slowing there is CATASTROPHIC: 07-05 an
    # in-crest mask gave 51% kill-zone slides; slowing the approach only gave 0). Matches the S9
    # hand-gate zone s600-680 (here s611-684) + the S7->S8 approach.
    cg_geo_mask = np.zeros(n, dtype=bool)
    for _i in range(n):
        _d, _j = 0.0, _i
        while _d < CG_GAP:                            # skip the GAP nearest the hazard
            _d += seg[_j]; _j = (_j + 1) % n
        while _d < CG_APPR:
            if _crest_turn[_j]:
                cg_geo_mask[_i] = True; break
            _d += seg[_j]; _j = (_j + 1) % n
    if cg_geo_mask.any():
        _z = [s_of[_k] for _k in range(n) if cg_geo_mask[_k]]
        print(f"cg_geo mask: {int(cg_geo_mask.sum())} stations "
              f"({100.0*cg_geo_mask.sum()/n:.0f}%), s {min(_z):.0f}-{max(_z):.0f} span", flush=True)

    # === ADAPTIVE CREST MARGIN (acm, 2026-07-05) -- the GENERALIZABLE S9 solution ===============
    # The survey finds candidate crest->compression->turn HAZARD CORES (generalizable, any track);
    # a LEARNED per-core incident counter then self-selects which cores ACTUALLY bite from the car's
    # OWN slides (S9 accrues hits and gets the grip margin; S7 never slides so it stays FREE). The
    # margin is applied ONLY in a tripped core's APPROACH -- fixing every flaw of the earlier
    # vtrim_hold_geo (no S7 scarring: needs ACM_ENABLE repeat hits, not one-off noise; fast: trips
    # in a handful of laps; correctly positioned: the [GAP,APPR] approach, never into the crest).
    # Closed-form learned table -- NO neural net, NO track-position hardcoding.
    ACM_ENABLE = 3.0                                  # a core must slide this many times to earn margin
    acm_core_start, acm_core_end = [], []             # cluster the sig (_crest_turn) into cores
    _i = 0
    while _i < n:
        if _crest_turn[_i]:
            _k = _i
            while True:                               # extend while the next sig is within 40 m
                _d, _j, _nxt = 0.0, _k, None
                while _d < 40.0:
                    _d += seg[_j]; _j = (_j + 1) % n
                    if _crest_turn[_j]:
                        _nxt = _j; break
                if _nxt is not None and _nxt > _k:
                    _k = _nxt
                else:
                    break
            acm_core_start.append(_i); acm_core_end.append(_k)
            _i = _k + 1
        else:
            _i += 1
    n_acm = len(acm_core_start)
    acm_core_of = np.full(n, -1, dtype=int)           # core whose APPROACH contains this station
    acm_haz_of = np.full(n, -1, dtype=int)            # core whose HAZARD region contains it (attribution)
    for _c in range(n_acm):
        cs, ce = acm_core_start[_c], acm_core_end[_c]
        _d, _j = 0.0, cs                              # approach [cs-APPR, cs-GAP] behind the cluster
        while _d < CG_APPR:
            if _d >= CG_GAP:
                acm_core_of[_j] = _c
            _j = (_j - 1) % n; _d += seg[_j]
        _j = cs                                       # hazard = cluster .. +40 m (where the slide lands)
        while _j != (ce + 1) % n:
            acm_haz_of[_j] = _c; _j = (_j + 1) % n
        _d = 0.0
        while _d < 40.0:
            acm_haz_of[_j] = _c; _d += seg[_j]; _j = (_j + 1) % n
    acm_hits = np.zeros(max(n_acm, 1))                # persisted learned counter
    ACM_PATH = os.path.join(_rec_dir, "acm_hits.npy")
    try:
        _saved = np.load(ACM_PATH)
        if len(_saved) == n_acm:
            acm_hits = _saved.astype(float)
    except Exception:
        pass
    acm_penalized = set()                             # once-per-lap-per-core incident guard
    acm_lap = -1
    print("acm: %d hazard cores at s=%s; hits=%s" % (
        n_acm, ",".join("%.0f" % s_of[acm_core_start[c]] for c in range(n_acm)),
        acm_hits[:n_acm].round(1).tolist()), flush=True)

    def save_acm():
        try:
            _t = ACM_PATH + ".tmp.npy"
            np.save(_t, acm_hits); os.replace(_t, ACM_PATH)
        except Exception:
            pass

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", args.port))
    sock.settimeout(0.5)
    gp = vg.VX360Gamepad()
    BTN_A = vg.XUSB_BUTTON.XUSB_GAMEPAD_A                # clutch (in race) / confirm (in menus)
    BTN_B = vg.XUSB_BUTTON.XUSB_GAMEPAD_B                # circle: back / resume race
    BTN_RB = vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER  # shift up
    BTN_LB = vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER   # shift down
    BTN_START = vg.XUSB_BUTTON.XUSB_GAMEPAD_START        # pause / open menu (AFK recovery)
    BTN_DRIGHT = vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT  # menu navigate (AFK recovery)
    BTN_X = vg.XUSB_BUTTON.XUSB_GAMEPAD_X                # pause-menu "Reset Car Position"
    RECOVER_BTN = {"A": BTN_A, "B": BTN_B, "START": BTN_START, "RB": BTN_RB,
                   "Dright": BTN_DRIGHT, "X": BTN_X}
    logf = open(args.log, "w", newline="")
    pathf = open(args.path_log, "w") if planner is not None else None
    logw = csv.writer(logf)
    logw.writerow(["t", "x", "z", "spd_kmh", "yaw", "head_deg", "i0", "tx", "tz",
                   "alpha_deg", "cte_m", "steer", "thr", "brk", "tgt_kmh", "gear", "rpm", "on_track",
                   "max_rpm", "shift",
                   "ff", "p_t", "i_t", "d_t", "cte_int", "cte_dot", "kappa_ff",
                   "lap_no", "lap_t", "sideslip", "plan_d0", "plan_L", "plan_deg",
                   "psi_deg", "km_max", "kap_car", "vcurve_kmh", "thr_cap", "yawrate",
                   "meas_latg", "drive_slip", "alat_max_g", "fc_frac",
                   "r_des", "r_meas", "e_r", "over", "under", "race_pos",
                   "y", "pitch_deg", "roll_deg"])   # appended: surface survey channels

    def neutral():
        gp.left_joystick_float(x_value_float=0.0, y_value_float=0.0)
        gp.right_trigger_float(value_float=0.0)
        gp.left_trigger_float(value_float=0.0)
        gp.release_button(button=BTN_A)
        gp.release_button(button=BTN_RB)
        gp.release_button(button=BTN_LB)
        gp.update()

    def tap(btn, hold=0.18):
        gp.press_button(button=btn); gp.update(); time.sleep(hold)
        gp.release_button(button=btn); gp.update(); time.sleep(0.25)

    if args.recover:
        print(f"recovering: waiting {args.recover_delay:.0f}s (focus Forza now!), then tapping "
              f"[{args.recover_keys}] to claim controller input ...", flush=True)
        time.sleep(args.recover_delay)
        _km = {"A": BTN_A, "B": BTN_B}
        for _ch in args.recover_keys.upper():
            if _ch in _km:
                tap(_km[_ch]); time.sleep(1.0)
        print("driving. Alt-tab away or Ctrl+C to stop.\n")
    else:
        print(">>> driving starts in 4 s (alt-tab into FH6 if not focused)...")
        for k in range(4, 0, -1):
            print(f"  {k}...")
            time.sleep(1.0)
        print("driving. Alt-tab away or Ctrl+C to stop.\n")

    t0 = time.time()
    throttle = 0.0
    frames = 0
    prev = None            # baseline position for travel-heading
    cur_heading = None
    idx = None             # current line index (windowed, monotonic localization)
    traveled = 0.0         # distance since takeover (for the launch guard)
    last_pos = None
    shift_frames = 0       # frames remaining in the current shift
    shift_kind = None      # "up" or "down"
    shift_cd = 0           # cooldown frames after a shift
    stuck = 0              # frames wedged at ~0 speed while on throttle (wall-grind guard)
    held = False           # latched stuck state -> output neutral briefly, then auto-retry
    held_frames = 0
    launched = False       # set once the car has actually moved this run (so the pre-GO
                           # standstill at the grid is never mistaken for a wedge)
    steer_prev = 0.0       # previous steering output (for the slew-rate limit)
    t_prev = None          # previous loop timestamp (for the PID dt)
    cte_prev = 0.0         # previous cross-track error (for the PID derivative)
    cte_int = 0.0          # integral of cross-track error (anti-windup clamped)
    cte_dot_f = 0.0        # low-passed cross-track error rate (PID derivative)

    # --- optional screenshot capture (telemetry-aligned, off-thread so it never
    # stalls the control loop; frames are dropped rather than blocking if the
    # grab worker falls behind) ---
    cap = None
    if args.capture:
        import threading
        import queue as _queue
        os.makedirs(args.capture_dir, exist_ok=True)
        hwnd = find_forza_window()
        if hwnd is None:
            print("[capture] Forza window not found -- capture disabled")
        else:
            capq = _queue.Queue(maxsize=8)
            manf = open(os.path.join(args.capture_dir, "manifest.csv"), "w", newline="")
            manw = csv.writer(manf)
            manw.writerow(["seq", "t", "i0", "x", "z", "spd_kmh", "on_track", "cte_m", "gear", "rpm", "png"])
            manf.flush()

            def _cap_worker():
                while True:
                    item = capq.get()
                    if item is None:
                        break
                    seq, meta = item
                    try:
                        img = grab_window(hwnd)
                        png = os.path.join(args.capture_dir, f"f{seq:03d}_i{meta['i0']:03d}.png")
                        img.save(png)
                        manw.writerow([seq, meta["t"], meta["i0"], meta["x"], meta["z"],
                                       meta["spd"], meta["on_track"], meta["cte"], meta["gear"],
                                       meta["rpm"], png])
                        manf.flush()
                    except Exception as e:
                        print(f"\n[capture] frame {seq} failed: {e}")
                    capq.task_done()

            capt = threading.Thread(target=_cap_worker, daemon=True)
            capt.start()
            cap = {"q": capq, "seq": 0, "dist": 0.0, "lastxz": None,
                   "laps": 0, "prev_i0": None, "started": False}
            print(f"[capture] every {args.capture_every_m:.0f} m, {args.capture_laps} lap(s) -> {args.capture_dir}")

    # --- AFK self-recovery state (only used with --afk) ---
    race_t_last = 0.0; racing_seen = time.time(); last_recover = 0.0; last_map_check = 0.0
    no_telem_t0 = None; last_blind_kick = 0.0      # no-telemetry streak / last-resort kick
    prev_tgt = None; desc_f = 0.0; brk_ff = 1.0   # brake feedforward (gain tunable; 0 disables)
    thr_i = 0.0; ki_thr = 0.5                     # throttle integral (standing-pedal supply)
    rejoin_kmin = 0.004; rejoin_gain = 2.0        # coast-lock fix: straight-line rejoin floor
    scap_on = 1.0                                 # surface-frame physics cap (survey sheet)
    ff_loadcomp = 0.85                            # steering-FF load compensation exponent (0=off)
    # --- chain-fix A/B candidates (2026-07-05), all default OFF; hot-reloadable ---
    aw_on = 0.0        # #1 steer-clip anti-windup: decay cte_int when the wheel saturates
    cr_on = 0.0        # #2 correction-restore: un-damp p_t in the grip-return window
    th_on = 0.0        # #3 anticipatory throttle-hold on rotating-into-rising-load
    hd_on = 0.0        # #4 heading-deweight when inside at the light crest (value = h_t scale, e.g. 0.5)
    cg_on = 0.0        # #5 crest grip-margin (value = target_v scale in s600-680, e.g. 0.92; DEV s-range)
    cg_geo_on = 0.0    # #5-geo generalizable grip-margin (value = target_v scale where cg_geo_mask; SHIP form)
    ha_on = 0.0        # #6 hold-the-arc: steer slew-rate scale on the light crest (e.g. 0.3)
    lb_on = 0.0        # #7 outward line-bias at S9 entry (value = metres, e.g. 1.0)
    s7m_on = 0.0       # S7-APPROACH MARGIN (07-06): value = target_v scale in [s7m_lo, s7m_hi];
    s7m_lo = 470.0     #   slows the car before/into the S7 crest so it stops understeering WIDE
    s7m_hi = 560.0     #   (the ROOT cause; the S9 margin is only a downstream patch). 0 = off.
    acm_on = 0.0       # ADAPTIVE CREST MARGIN (the generalizable ship fix): value = target_v scale
                       # (e.g. 0.90) applied in a tripped hazard core's approach; 0 = off
    vtrim_hold_geo = 0.0  # generalizable SHIP path: freeze vtrim RE-EARN inside cg_geo_mask so
                          # incident-cuts STICK there -> the car self-selects which crest-turns are
                          # dangerous FROM ITS OWN SLIDES (S9 accrues cuts, S7 never slides -> stays free)
    _th_hold = 1.0     # throttle-hold latched ceiling (state for #3)
    crest_hold = 0.0                              # hold-the-arc gate: corrections attenuate when
    cte_int_prev_hold = 0.0                       # predicted load ahead < this (0=off)
    vtrim_on = 1.0                                # self-calibrated corner-speed map: apply + learn
    vtrim_up = 0.0005                             # per-tick credit where grip spare + tracking clean
    vtrim_dn = 0.002                              # per-tick cut where over grip budget
    vtrim_cut = 0.02                              # per-incident cut, stations 15-55 m upstream
    vtrim_gutil = 0.93                            # credit ceiling: earn while g_util below this.
                                                  # NOT corner_gutil (0.82): that made the map's
                                                  # equilibrium hug 0.82 utilization = a global ~7%
                                                  # corner tax (measured: g_util med 0.78 -> 0.62,
                                                  # laps flat 31.1). Debit at 0.98 unchanged.
    vtrim_lo, vtrim_hi = 0.80, 1.55               # map bounds
    vtrim_netscale = 0.1                          # net step = table step x this (generalization rate)
    vtrim_reset = 0.0                             # hot: change to a NEW nonzero value -> delta := 0
    vtrim_dirty = 0                               # unsaved map changes pending
    acm_dirty = False                             # unsaved adaptive-crest-margin hits pending
    vtrim_penalized = set()                       # stations already incident-cut this lap
    vtrim_lap = -1                                # lap tracker for the once-per-lap cut set
    stuck_off_since = 0.0; last_reset = 0.0      # off-track wedge -> Reset Car Position
    stuck_slow_since = 0.0                        # launched but crawling ANYWHERE -> Reset Car Position
    freeroam_since = 0.0                          # MOVING off-corridor a while -> free roam? recover
    reversing = False; reverse_until = 0.0; reverse_from = None   # REVERSE-unstuck maneuver
    reverse_attempts = 0; wedge_ref = None; wedge_ref_t = 0.0; ok_since = 0.0
    v_curve_trim = 1.0                            # closed-loop corner-speed trim (realized-g feedback)
    corner_gutil = 0.80                           # trim target: creep corner speed up until this frac of grip
    corner_fcgate = 0.55                          # min friction-circle headroom to keep creeping (lower=push harder)
    fz_hwnd = find_forza_window()
    def get_frame():
        latest = None
        sock.setblocking(False)
        while True:
            try:
                latest = parse_packet(sock.recvfrom(2048)[0]) or latest
            except (BlockingIOError, OSError):
                break
        sock.settimeout(0.5)
        return latest

    try:
        while time.time() - t0 < args.duration:
            try:
                data, _ = sock.recvfrom(2048)
            except socket.timeout:
                neutral()
                _now_nt = time.time()
                if no_telem_t0 is None:
                    no_telem_t0 = _now_nt
                # NO-TELEMETRY unstick: FH6 pauses the Data Out stream whenever the game is
                # paused -- the Controller-Disconnected dialog (vpad respawn after a follower
                # restart), the full-screen map, or the pause menu. The packet-loop recovery
                # can never see these (no packets), so clear them from here.
                if args.afk and close_map is not None and foreground_is_forza() \
                        and _now_nt - last_map_check > 2.5:
                    last_map_check = _now_nt
                    if has_disconnect_dialog(fz_hwnd):
                        print("\n[afk] no telemetry + disconnect dialog -> A/Enter to clear", flush=True)
                        tap(BTN_A); key_enter()
                    else:
                        t_ocr = ocr_text(fz_hwnd)
                        _st = screen_state(t_ocr)
                        if "close map" in t_ocr:
                            print("\n[afk] map open (telemetry paused) -> closing (map -> pause -> game)", flush=True)
                            close_map(gp, RECOVER_BTN, fz_hwnd, log=lambda m: print(m, flush=True))
                        elif _st == "disconnect":        # OCR backup for the color check
                            print("\n[afk] no telemetry + disconnect (OCR) -> A/Enter to clear", flush=True)
                            tap(BTN_A); key_enter()
                        elif _st == "pause":
                            print("\n[afk] no telemetry + pause menu -> B to resume", flush=True)
                            tap(BTN_B)
                # LAST RESORT: telemetry dead a long time and nothing above recognized the
                # screen -- both detectors CAN miss (07-05: the disconnect dialog beat the
                # color check while OCR read the HUD behind it; 07-04 morning: 10 watchdog
                # relaunches into the same wall). A blind A+Enter advances every
                # telemetry-pausing screen (dialog, pause, results, load); once frames flow
                # the real recovery takes over. Only steal focus from the game itself or the
                # bare desktop -- never from an app the user is actively using.
                if args.afk and _now_nt - no_telem_t0 > 45.0 and _now_nt - last_blind_kick > 8.0:
                    _fg_exe = _window_exe(user32.GetForegroundWindow())
                    if _fg_exe in (_GAME_EXE, "explorer.exe", ""):
                        last_blind_kick = _now_nt
                        print(f"\n[afk] telemetry dead {_now_nt - no_telem_t0:.0f}s, screen "
                              f"unrecognized -> blind A+Enter kick", flush=True)
                        if fz_hwnd:
                            _force_foreground(fz_hwnd)
                            time.sleep(0.3)
                        tap(BTN_A)
                        _send_enter()
                continue
            no_telem_t0 = None                               # telemetry flowing again
            sock.setblocking(False)                          # drain to freshest packet
            while True:
                try:
                    data = sock.recvfrom(2048)[0]
                except (BlockingIOError, OSError):
                    break
            sock.settimeout(0.5)

            if not foreground_is_forza():                    # safety gate
                throttle = 0.0
                neutral()
                continue

            f = parse_packet(data)
            if f is None:
                neutral()
                continue
            # --- AFK: drive only while ACTIVELY racing (the race clock is ticking). If it
            # stalls -- disconnect dialog / pause menu / results / free roam / load -- then
            # OCR-self-recover back to a live race instead of idling. ---
            now_t = time.time()
            # race_position is 1..N IN A RACE, 0 in FREE ROAM. is_race_on AND the race clock are
            # both 1 in free roam too, so they falsely read free-roam DRIVING as racing -- that was
            # the bug where the follower drove the open world instead of restarting the event.
            # race_position is the reliable "in a race" signal.
            if f.race_position >= 1:
                race_t_last = f.cur_race_time; racing_seen = now_t
            # Recover when NOT in a race for >3s (free roam / results / menu / load) -- REGARDLESS
            # of speed, so a car DRIVING in free roam is caught (the old speed<20 guard missed it).
            # Mid-race race_position stays >=1 so this never false-fires into the STORE nav; a
            # genuinely stuck car IN-race is handled by the main loop's reverse-unstuck/reset.
            if (f.race_position < 1) and (now_t - racing_seen > 3.0):
                neutral()
                if args.afk and recover_to_racing is not None and now_t - last_recover > 6.0:
                    print("\n[afk] not racing -> self-recovering to a live race ...", flush=True)
                    # post_race=True if the race clock had been running (a real race just
                    # finished) -> collect the winnings (A-through) before restarting.
                    recover_to_racing(gp, RECOVER_BTN, get_frame, fz_hwnd,
                                      log=lambda m: print(m, flush=True),
                                      post_race=(race_t_last > 10.0), line=line)
                    idx = None; traveled = 0.0; launched = False     # fresh race -> reset state
                    held = False; stuck = 0; held_frames = 0
                    race_t_last = 0.0; racing_seen = time.time(); last_recover = time.time()
                continue

            if frames % 30 == 0:                            # hot-reload tuning ~2x/sec
                try:
                    _t = json.load(open(args.tune_file))
                    safety = float(_t.get("safety", safety))
                    speed_cap = float(_t.get("speed_cap", speed_cap))
                    max_throttle = float(_t.get("max_throttle", max_throttle))
                    ld_base = float(_t.get("ld_base", ld_base))
                    ld_k = float(_t.get("ld_k", ld_k))
                    ld_min = float(_t.get("ld_min", ld_min))
                    k_ff = float(_t.get("k_ff", k_ff))
                    k_head = float(_t.get("k_head", k_head))
                    kp = float(_t.get("kp", kp))
                    ki = float(_t.get("ki", ki))
                    kd = float(_t.get("kd", kd))
                    t_ff = float(_t.get("t_ff", t_ff))
                    kp_thr = float(_t.get("kp_thr", kp_thr))
                    beta_soft = float(_t.get("beta_soft", beta_soft))
                    beta_hard = float(_t.get("beta_hard", beta_hard))
                    slide_deg = float(_t.get("slide_deg", slide_deg))
                    k_slide = float(_t.get("k_slide", k_slide))
                    full_slide_deg = float(_t.get("full_slide_deg", full_slide_deg))
                    slip_brake_gain = float(_t.get("slip_brake", slip_brake_gain))
                    cte_soft = float(_t.get("cte_soft", cte_soft))
                    cte_hard = float(_t.get("cte_hard", cte_hard))
                    planner_alat = float(_t.get("planner_alat", planner_alat))
                    planner_alat_k = float(_t.get("planner_alat_k", planner_alat_k))
                    slip_target = float(_t.get("slip_target", slip_target))
                    k_counter = float(_t.get("k_counter", k_counter))
                    r_thr = float(_t.get("r_thr", r_thr))
                    understeer_gain = float(_t.get("understeer_gain", understeer_gain))
                    understeer_thr = float(_t.get("understeer_thr", understeer_thr))
                    corner_gutil = float(_t.get("corner_gutil", corner_gutil))
                    corner_fcgate = float(_t.get("corner_fcgate", corner_fcgate))
                    brk_ff = float(_t.get("brk_ff", brk_ff))
                    ki_thr = float(_t.get("ki_thr", ki_thr))
                    rejoin_kmin = float(_t.get("rejoin_kmin", rejoin_kmin))
                    rejoin_gain = float(_t.get("rejoin_gain", rejoin_gain))
                    scap_on = float(_t.get("scap_on", scap_on))
                    ff_loadcomp = float(_t.get("ff_loadcomp", ff_loadcomp))
                    crest_hold = float(_t.get("crest_hold", crest_hold))
                    aw_on = float(_t.get("aw_on", aw_on))
                    cr_on = float(_t.get("cr_on", cr_on))
                    th_on = float(_t.get("th_on", th_on))
                    hd_on = float(_t.get("hd_on", hd_on))
                    cg_on = float(_t.get("cg_on", cg_on))
                    cg_geo_on = float(_t.get("cg_geo_on", cg_geo_on))
                    ha_on = float(_t.get("ha_on", ha_on))
                    lb_on = float(_t.get("lb_on", lb_on))
                    s7m_on = float(_t.get("s7m_on", s7m_on))
                    s7m_lo = float(_t.get("s7m_lo", s7m_lo))
                    s7m_hi = float(_t.get("s7m_hi", s7m_hi))
                    acm_on = float(_t.get("acm_on", acm_on))
                    vtrim_hold_geo = float(_t.get("vtrim_hold_geo", vtrim_hold_geo))
                    vtrim_on = float(_t.get("vtrim_on", vtrim_on))
                    vtrim_up = float(_t.get("vtrim_up", vtrim_up))
                    vtrim_dn = float(_t.get("vtrim_dn", vtrim_dn))
                    vtrim_cut = float(_t.get("vtrim_cut", vtrim_cut))
                    vtrim_gutil = float(_t.get("vtrim_gutil", vtrim_gutil))
                    vtrim_lo = float(_t.get("vtrim_lo", vtrim_lo))
                    vtrim_hi = float(_t.get("vtrim_hi", vtrim_hi))
                    vtrim_netscale = float(_t.get("vtrim_netscale", vtrim_netscale))
                    _vr = float(_t.get("vtrim_reset", vtrim_reset))
                    if _vr != vtrim_reset and _vr != 0.0:
                        vdelta[:] = 0.0
                        vt_base = vtrim_base()
                        vtrim_map = np.clip(vt_base + vdelta, vtrim_lo, vtrim_hi)
                        save_vtrim()
                        print("vtrim: delta RESET to 0 (tune trigger; net retained)")
                    vtrim_reset = _vr
                    ff_use_line = float(_t.get("ff_use_line", ff_use_line))
                    head_use_line = float(_t.get("head_use_line", head_use_line))
                    # planner internals (momentum + rejoin geometry + kink de-spike) live-tunable
                    if planner is not None:
                        planner.w_speed   = float(_t.get("w_speed",   planner.w_speed))
                        planner.kappa_pct = float(_t.get("kappa_pct", planner.kappa_pct))
                        planner.w_hyst    = float(_t.get("w_hyst",    planner.w_hyst))
                        planner.w_dev     = float(_t.get("w_dev",     planner.w_dev))
                        planner.w_len     = float(_t.get("w_len",     planner.w_len))
                        planner.w_merge   = float(_t.get("w_merge",   planner.w_merge))
                        planner.k_d       = float(_t.get("k_d",       planner.k_d))
                        planner.S_max     = float(_t.get("S_max",     planner.S_max))
                        planner.d0p_max   = float(_t.get("d0p_max",   planner.d0p_max))
                    resid_on = float(_t.get("resid_on", resid_on))
                    bc_on = float(_t.get("bc_on", bc_on))
                except Exception:
                    pass
                try:    # hot-reload residual net weights when the trainer rewrites the file
                    _rm = os.path.getmtime(RESID_PATH)
                    if _rm != resid_mtime:
                        resid_net.load(RESID_PATH); resid_mtime = _rm
                except OSError:
                    pass
                try:    # hot-reload the SFT policy when retrained (RL phase rewrites bc_policy.npz)
                    _bm = os.path.getmtime(BC_PATH)
                    if _bm != bc_mtime:
                        bc_policy = load_bc_policy(BC_PATH); bc_mtime = _bm
                except OSError:
                    pass

            x, z, spd = f.pos_x, f.pos_z, f.speed_mps
            # sideslip angle: velocity is CAR-LOCAL (vz forward, vx lateral), so the angle
            # of the velocity vector off straight-ahead = how sideways the car is sliding.
            # ~0 when gripping, grows fast in a slide/spin. Only meaningful above walking pace.
            sideslip = math.degrees(math.atan2(f.vel_x, abs(f.vel_z))) if spd > 3.0 else 0.0
            # heading: prefer true world travel direction (position-delta over ~1 m);
            # fall back to calibrated yaw only at a standstill (position is world-frame,
            # velocity is NOT -- it's car-local -- so never use velocity here).
            yaw_h = wrap(args.yaw_sign * f.yaw + args.yaw_offset)
            if cur_heading is None:
                cur_heading = yaw_h
            if prev is None:
                prev = (x, z)
            if math.hypot(x - prev[0], z - prev[1]) >= 1.0:
                cur_heading = math.atan2(z - prev[1], x - prev[0])
                prev = (x, z)
            elif spd < 2.0:
                cur_heading = yaw_h
            heading = cur_heading

            # localize: windowed forward search around the last index so it tracks
            # progress and can't snap across the track where it nears itself; global
            # re-acquire only if we've clearly lost the line.
            if idx is None:
                idx = int(np.argmin((line[:, 0] - x) ** 2 + (line[:, 1] - z) ** 2))
            else:
                win = [(idx + k) % n for k in range(-3, 26)]
                wd = [(line[j, 0] - x) ** 2 + (line[j, 1] - z) ** 2 for j in win]
                idx = win[int(np.argmin(wd))]
                if min(wd) > 625.0:                      # >25 m off the line -> re-acquire
                    idx = int(np.argmin((line[:, 0] - x) ** 2 + (line[:, 1] - z) ** 2))
            i0 = idx

            ld = min(max(ld_base + ld_k * spd, ld_min), args.ld_max)
            # LOCAL PLANNER: build a merge path from the car's state onto the line, then
            # aim the tracker at a point on THAT path -- so the car glides onto the line
            # instead of snapping to it. --no-planner falls back to raw-line lookahead.
            if planner is not None:
                planner.a_lat = planner_alat + planner_alat_k * spd * spd   # speed-aware (downforce) grip
            pl = planner.plan(x, z, heading, spd, i_hint=i0) if planner is not None else None
            plan_degraded = bool(pl["degraded"]) if pl is not None else False
            kap_car = float(planner.kappa_at(pl, ld)) if pl is not None else 0.0
            # --- ESC-style yaw-rate error: distinguish OVER- vs UNDER-steer (point #2) ---
            r_des = spd * kap_car                          # yaw rate the planned path wants (signed)
            r_meas = args.yaw_rate_sign * f.angvel_y       # measured yaw rate, sign-corrected (-1 here)
            r_meas_f = 0.7 * r_meas_f + 0.3 * r_meas
            e_r = r_meas_f - r_des
            _fast = spd * 3.6 > 30.0
            oversteer = _fast and r_des != 0.0 and (r_meas_f * r_des > 0.0) and (abs(r_meas_f) > abs(r_des) + r_thr)
            understeer = _fast and abs(r_des) > 0.06 and (abs(r_meas_f) < understeer_thr * abs(r_des))
            if pl is not None and head_use_line < 0.5:
                tx, ty = planner.lookahead_target(pl, ld)      # merge lookahead point (wobbles)
            else:
                # head_use_line (or no planner): aim the pursuit at a STABLE point on the LINE
                # ld ahead, so the heading term doesn't wobble with the per-tick merge shape.
                # Bearing to a line point ahead still pulls an off-line car toward the line.
                d_acc, i = 0.0, i0
                while d_acc < ld:
                    d_acc += seg[i]
                    i = (i + 1) % n
                tx, ty = line[i]
            alpha = wrap(math.atan2(ty - z, tx - x) - heading)
            # cross-track: signed perpendicular offset from the line (car right of path
            # = positive). Added Stanley-style so the car actively returns to the line
            # instead of holding a wide offset and riding the wall.
            # raw-line tangent at i0 -- always needed (on_track/dirt detection below uses it)
            jn = (i0 + 1) % n
            tgx, tgz = line[jn, 0] - line[i0, 0], line[jn, 1] - line[i0, 1]
            tl = math.hypot(tgx, tgz) or 1.0
            # PID closes the TRUE offset from the racing line. The merge path shapes the
            # pursuit target + curvature feedforward (so commands stay feasible/smooth), but
            # a real understeering car needs an active closing term or it sits wide of the
            # line forever (the merge alone left mean ~3 m offset). This is the hybrid:
            # feasible merge for SHAPE + cross-track PID for CLOSURE.
            cte = (tgz * (x - line[i0, 0]) - tgx * (z - line[i0, 1])) / tl

            # --- chain-fix candidate common signals (all no-ops when their keys are 0) ---
            _sm = s_of[i0]
            _ksgn = 1.0 if kappa_signed[i0] >= 0 else -1.0
            _erri = cte * _ksgn                        # >0 = car INSIDE the turn
            _lp_now = 1.0 + float(scap_zpp[i0]) * spd * spd / 9.81
            _turn = abs(kappa_signed[i0]) > 0.008
            # #7 outward line-bias at S9 entry: the control cross-track targets a line lb_on m
            # WIDER (erri_ctrl = erri + lb_on -> the P term settles the car lb_on m outside).
            # Logged cte stays the true offset; only p_t/integrator see the bias.
            cte_ctrl = cte
            if lb_on > 0.0 and 636.0 <= _sm <= 680.0:
                cte_ctrl = cte + lb_on * _ksgn

            # --- steering: curvature FEEDFORWARD + a PID on the cross-track error,
            # then a slew-rate (anti-jitter) limit. One error signal (cte), three gains. ---
            STEER_SIGN = args.steer_sign
            KP_VSCALE, CTE_INT_MAX, CTE_D_BETA = 30.0, 3.0, 0.3
            # signed plan curvature at a short speed-scaled preview point ahead (feedforward)
            s_ff = min(max(t_ff * spd, lff_min), lff_max)
            if pl is not None:
                # FF anticipation: stable LINE curvature (ff_use_line) breaks the planner<->tracker
                # limit cycle, vs the per-tick MERGE curvature (kappa_at) that wobbles with d0/psi.
                kappa_ff = (planner.kappa_line_ahead(pl, s_ff) if ff_use_line > 0.5
                            else planner.kappa_at(pl, s_ff))
            else:
                d_acc, i_ff = 0.0, i0
                while d_acc < s_ff:
                    d_acc += seg[i_ff]; i_ff = (i_ff + 1) % n
                kappa_ff = float(np.mean([kappa_signed[(i_ff - 1) % n], kappa_signed[i_ff],
                                          kappa_signed[(i_ff + 1) % n]]))
            now = time.time()
            dt = (now - t_prev) if t_prev is not None else 0.025
            t_prev = now
            # PID on cross-track error (cte>0 = car RIGHT of line). D on the filtered error
            # rate; I anti-windup clamped; P eased at high speed so it can't overcorrect/spin.
            raw_dot = (cte - cte_prev) / max(dt, 1e-3)   # D on the TRUE offset (bias is constant)
            cte_dot_f = (1.0 - CTE_D_BETA) * cte_dot_f + CTE_D_BETA * raw_dot
            cte_prev = cte
            cte_int = max(-CTE_INT_MAX, min(CTE_INT_MAX, cte_int + cte_ctrl * dt))
            kp_eff = kp / (1.0 + spd / KP_VSCALE)
            # LOAD-COMPENSATED FF (S9 crest fix, 07-05): the steer angle a given curvature
            # needs GROWS as load falls (understeer gradient); the FF had no load term, so
            # over a crest it underdelivers exactly when margin vanishes -> wash -> late
            # PID -> overcorrect -> oversteer (the user's observed chain at a0=27).
            # Predicted load from the surveyed z'' at the current station+speed: the extra
            # angle arrives BEFORE the wash, like a driver who sees the crest coming.
            if ff_loadcomp > 0.0:
                _lp = min(max(1.0 + float(scap_zpp[i0]) * spd * spd / 9.81, 0.5), 1.3)
                _comp = min(max(_lp ** -ff_loadcomp, 0.75), 1.45)
            else:
                _comp = 1.0
            ff  = k_ff * kappa_ff * _comp
            # CORRECTION SCHEDULING (user's S7->S8->S9 diagnosis, 07-05): the S-oscillation
            # is choreographed by the compression-crest sequence -- (a) in COMPRESSIONS
            # (load>1) every steering term is over-effective, so line corrections OVERSHOOT
            # (measured: err swings inside->outside through S8); (b) the rejoin swing then
            # lands ON the crest where lateral authority ~ 0 and the wheel pins. Fix:
            # (a) corrections damped by the same load factor in compressions;
            # (b) CREST GATE -- when a light zone is within ~12 m, HOLD THE ARC: attenuate
            # corrections + freeze the integrator; rejoin after landing (the S9/S10
            # compression right after provides the grip to do it safely).
            corr = min(_comp, 1.0) if ff_loadcomp > 0.0 else 1.0
            gate_hold = False
            if crest_hold > 0.0:
                _lp_ahead = 1.0 + float(zpp_min12[i0]) * spd * spd / 9.81
                if _lp_ahead < crest_hold:
                    gate_hold = True
                    corr *= max(0.30, (_lp_ahead - 0.5) / max(crest_hold - 0.5, 1e-3))
            if gate_hold:
                cte_int = cte_int_prev_hold   # freeze the integrator across the crest
            cte_int_prev_hold = cte_int
            # #4 heading-deweight: shrink the pursuit heading term when the car is INSIDE at
            # the light crest (data: h_t there competes with the un-inside correction).
            _hw = 1.0
            if hd_on > 0.0 and _erri > 1.5 and _lp_now < 1.0 and _turn:
                _hw = hd_on
            # #2 correction-restore: un-damp the P (line-closing) term in the crest->compression
            # grip-return window so the freed budget is spent closing the line.
            _corr_p = corr
            if cr_on > 0.0 and zpp_ahead6[i0] > 0.002 and float(scap_zpp[i0]) < 0.002 and _turn:
                _corr_p = 1.0
            h_t = k_head * alpha * corr * _hw   # pursuit: align heading with the line
            p_t = kp_eff * cte_ctrl * _corr_p
            i_t = ki * cte_int
            d_t = kd * cte_dot_f * corr
            steer = STEER_SIGN * (ff + h_t + p_t + i_t + d_t)
            # COUNTER-STEER (point #2): when the car is OVER-rotating (rear sliding out), add a
            # yaw-rate damping term that steers to bring yaw back to commanded. dr/dsteer < 0 on
            # this rig, so +k_counter*e_r reduces excess yaw = steers INTO the slide. Only when
            # oversteering -- during understeer, adding lock just scrubs the front (handled by speed).
            if oversteer:
                steer += k_counter * e_r
            # #1 steer-clip anti-windup: when the unclipped command saturates the wheel and
            # the integrator is winding the SAME side, bleed cte_int (stops the S7 clipped
            # inside-drift pinning i_t at its clamp into the crest). Uses the pre-clip command.
            if aw_on > 0.0 and abs(steer) >= 0.999 and (cte_ctrl * cte_int) > 0.0:
                cte_int *= 0.97
            steer = max(-1.0, min(1.0, steer))
            # slew-rate limit (anti-jitter); #6 hold-the-arc tightens it on the light crest so
            # the wheel can't slam to full lock and wash the front (rejoin after grip returns).
            _srate = steer_rate
            if ha_on > 0.0 and _lp_now < 0.9 and _turn:
                _srate = steer_rate * ha_on
            steer = steer_prev + max(-_srate, min(_srate, steer - steer_prev))
            steer_prev = steer
            # launch guard: heading is unreliable until the car has moved a few meters,
            # so cap steering to avoid weaving off-line right off the standstill start.
            # A large one-frame position jump is a teleport (race restart / reset car
            # position) -- re-arm the gentle launch from the new spot instead of adding
            # the jump to the travelled distance (which would defeat the launch caps).
            if last_pos is not None:
                step = math.hypot(x - last_pos[0], z - last_pos[1])
                if step > 15.0:
                    traveled = 0.0
                    cur_heading, prev, idx = yaw_h, (x, z), None
                    held, stuck = False, 0
                else:
                    traveled += step
            last_pos = (x, z)
            # launch guard: only a BRIEF cap right off a standstill/reset start, while the planner
            # re-localizes (cte is garbage for ~1 frame after a teleport). Heading is from yaw_h
            # (reliable even at 0 km/h), and a reset often drops the car OFF-LINE (sometimes at speed),
            # so it must be free to use full lock to rejoin. The old +-0.6 cap held for the whole
            # launch_settle_m (70 m) and made the car wash wide off every reset (cte ran to -13 m,
            # speed cratered) = the cold-start lag. Now gentle ONLY for the first launch_m, then full.
            if traveled < args.launch_m:                 # ~5 m: gentle while localization settles
                steer = max(-0.6, min(0.6, steer))

            # anticipatory speed: target the SLOWEST planned speed within braking range
            # ahead (so it brakes BEFORE the corner, not once it's already in it)
            # brake at the GRIP LIMIT, not early: the latest speed I can hold NOW and still
            # brake to vplan[j] by station j (d2 ahead) at the measured braking grip A_BRAKE.
            # min over the window picks the binding corner; far corners don't over-constrain
            # (sqrt grows with distance), so it stops bleeding speed ~70 m before each corner.
            A_BRAKE = 25.0                                   # m/s^2 (~2.55g). Tried 28 (brake later) -> carried
                                                             # too much speed into corners the steering can't hold
                                                             # -> off-track. Braking IS control-gated (leads corners).
            look = 20.0 + spd * spd / (2.0 * A_BRAKE)        # cover the braking distance, not a fixed 1.2*v
            d2, j, tv = 0.0, i0, vplan[i0]
            while d2 < look:
                v_brake_ok = math.sqrt(vplan[j] ** 2 + 2.0 * A_BRAKE * d2)
                tv = min(tv, v_brake_ok)
                d2 += seg[j]
                j = (j + 1) % n
            # apply the corner derating (safety) mainly to slow CORNER targets; let fast
            # STRAIGHT targets run near full plan speed -- straights are easy to track, so
            # the follower's corner-grip limit shouldn't throttle them. safety_eff ramps
            # from `safety` (tv<=20 m/s, corner) up to 1.0 (tv>=45 m/s, straight).
            safety_eff = safety + (1.0 - safety) * min(max((tv - 20.0) / 25.0, 0.0), 1.0)
            target_v = min(tv * safety_eff, speed_cap)
            # PLANNER speed coupling: slow for the curvature of the merge path actually
            # planned (v_curve = sqrt(a_lat/kappa)), and ease off if no feasible merge exists.
            v_curve = 0.0
            if pl is not None:
                # only let v_curve govern the IMMEDIATE corner (short window). Using the full
                # braking-distance `look` here made it slow for the next tight corner ~40 m
                # early -> crawling the straights (108 vs human 181) and flowing curves (1g vs
                # 2.2g). The braking-distance anticipation over vplan (tv, above) already slows
                # in time for what's ahead; v_curve just caps the corner the car is entering.
                # STABLE corner-speed cap (hairpin fix 2, final form). The old cap used the
                # MERGE PATH's total curvature (line + rejoin bulge), which re-plans every tick
                # and BREATHES with the car's state -- measured flapping 110->190->86 km/h
                # inside one braking zone, pulsing the brake (0.51->0.04->0.74) -> +26 km/h hot
                # hairpin entry -> the wash that excited the limit cycle. Decompose instead:
                #   - the LINE term owns the corner: ground truth, cannot breathe;
                #   - the MERGE term owns ONLY the rejoin arc (kappa_merge, the curvature the
                #     merge ADDS): ~0 when near the line (no noise), real when off-line.
                # (Same cure as ff_use_line for the steering FF: stable source, no filtering.)
                # speed-dependent grip (downforce): corner speed solves v^2 = a_lat(v)/kappa
                # with a_lat(v)=alat0 + alat_k*v^2  ->  v = sqrt(alat0/(kappa - alat_k)).
                k_line = planner.max_kappa_line_ahead(pl, min(look, 18.0))
                kk_l = max(abs(k_line) - planner_alat_k, 1e-4)
                k_rejoin = max(float(pl.get("kappa_merge_max", 0.0)) - planner_alat_k, 1e-4)
                # One global a_lat(v) can't serve heterogeneous corners (S12 banked, S7/S9
                # crest, S1/S2 flat -- the k=0.004 probe proved it: S10 cashed it, others
                # collapsed). Per-corner correction comes from vtrim_map below: SELF-learned
                # from the bot's own telemetry, never bound to the human's speeds
                # (independence goal -- human laps are for evaluation only).
                v_line = math.sqrt(planner_alat / kk_l)
                v_rejoin = math.sqrt(planner_alat / k_rejoin)
                if abs(k_line) < rejoin_kmin:
                    # COAST-LOCK fix (exit-starvation d): on a NEAR-STRAIGHT line a 1-2 m
                    # offset kept a merge arc alive whose kappa capped target AT current
                    # speed (measured: vcurve==tgt==spd==210 for 25 m after S13's kink;
                    # v_rejoin = sqrt(24.3/0.007) = 212 exactly) -- no throttle, offset
                    # persists, lock self-sustains. Straights may always gain a little
                    # while merging; CORNERS keep the rejoin term's full authority.
                    v_rejoin = max(v_rejoin, spd + rejoin_gain)
                v_curve = min(v_line, v_rejoin)
                # SELF-CALIBRATED map scales the cap: min over the same 18 m corner window
                # (the map value for the corner being entered, not just this station).
                # Global v_curve_trim is SHED-ONLY now: fast transient safety stays, but
                # RAISING speed is exclusively the learned map's job -- two independent
                # optimists multiplying is how zones got defeated (step-7 lesson).
                map_w = 1.0
                if vtrim_on > 0.0:
                    # seed with the FIRST station's value, then window-min. Seeding with 1.0
                    # computed min(1.0, window) -- cuts applied, raises silently never did
                    # (weeks-of-laps bug class: map climbed to 1.4 with zero speed change,
                    # and with the loop open the credit rule saturated the map at its bound).
                    map_w = float(vtrim_map[i0])
                    _d, _j = 0.0, i0
                    while _d < 18.0:
                        if vtrim_map[_j] < map_w:
                            map_w = float(vtrim_map[_j])
                        _d += seg[_j]; _j = (_j + 1) % n
                sfac = float(surface_fac[i0]) if scap_on > 0.0 else 1.0
                target_v = min(target_v, v_curve * map_w * min(v_curve_trim, 1.0) * sfac)
                if plan_degraded:
                    # don't DEADLOCK at standstill: min(target, spd) is 0 when spd=0, so a car
                    # that lost the merge (wedged/badly placed) never gets throttle to recover.
                    # Keep a crawl floor so it can always move to re-establish the plan.
                    target_v = min(target_v, max(spd, 4.0))
            # launch speed cap: ramp the allowed speed from launch-cap up to full over
            # the first launch-settle-m of travel, so a grid/off-line start eases onto
            # the racing line under control instead of blasting off-line and overshooting
            if traveled < args.launch_settle_m:
                frac = traveled / max(args.launch_settle_m, 1e-3)
                launch_cap = args.launch_cap_kmh / 3.6
                target_v = min(target_v, launch_cap + frac * (speed_cap - launch_cap))
            # off-line speed governor: if the car has drifted off the racing line, don't
            # floor toward a straight's target while sideways/off-track -- ease toward the
            # current speed so it can rejoin under control (more off => slower).
            acte = abs(cte)
            if acte > cte_soft:
                g = max(0.0, 1.0 - (acte - cte_soft) / max(cte_hard - cte_soft, 1e-3))
                # crawl floor (4 m/s) so an off-corridor car at standstill can drive itself
                # back onto the line instead of deadlocking at target~=0 (same trap as plan_degraded)
                target_v = min(target_v, max(spd * (0.5 + 0.5 * g) + 1.0, 4.0))
            # UNDERSTEER (point #2): front washing wide (turning less than the path commands) ->
            # ease speed so it regains front grip and makes the corner instead of running off.
            if understeer:
                target_v = min(target_v, spd * understeer_gain)
            # #5 crest grip-margin: shave the target through the crest approach so the
            # (already-maxed) outward correction has grip to un-inside before the s704 grip-return.
            if cg_on > 0.0 and 600.0 <= s_of[i0] <= 680.0:
                target_v = min(target_v, target_v * cg_on)
            if s7m_on > 0.0 and s7m_lo <= s_of[i0] <= s7m_hi:   # S7-approach margin (root-cause test)
                target_v = min(target_v, target_v * s7m_on)
            if cg_geo_on > 0.0 and cg_geo_mask[i0]:      # generalizable (survey-derived) form
                target_v = min(target_v, target_v * cg_geo_on)
            # ADAPTIVE CREST MARGIN: margin only in the approach of a hazard core the car has
            # actually slid at >= ACM_ENABLE times (self-selects S9; S7 stays free).
            if acm_on > 0.0 and acm_core_of[i0] >= 0 and acm_hits[acm_core_of[i0]] >= ACM_ENABLE:
                target_v = min(target_v, target_v * acm_on)
            # (the temporal brake-integrity rate limiter tried here twice was removed: any
            # time-domain gate that suppresses target rises also extends dips -> phantom lifts
            # on fast sweepers. The spike source is fixed at the ROOT instead: v_curve is now
            # min(merge, LINE) curvature -- see the v_curve block above.)
            # --- GRIP-AWARE "FOOT": modulate throttle/brake to AVAILABLE grip instead of
            # flooring and clawing back. Two factors, both from MEASURED telemetry:
            #  (a) friction circle -- a_lat_now = |measured ax|; spare longitudinal grip
            #      fraction = sqrt(1 - (a_lat_now/a_lat_max(v))^2). Cornering hard -> less
            #      throttle/brake headroom (downforce raises a_lat_max with speed).
            #  (b) tire slip -- if the (AWD) drive wheels exceed the grip-optimal slip target,
            #      feather off so the tires stay near peak grip (proactive traction control).
            # GLOBAL grip model: speed/downforce base * vertical-load scaling from LIVE ay
            # (measured: grip ~ load_factor^0.705, load=1+ay/9.81; ~0.72 over the lightest
            # crest = -21% grip, >1 in compressions). Track-agnostic physics.
            load_factor = min(max(1.0 + f.ay / 9.81, 0.55), 2.40)
            grip_scale = load_factor ** 0.705
            alat_max_now = (planner_alat + planner_alat_k * spd * spd) * grip_scale
            a_lat_now = abs(f.ax)                                   # measured lateral accel (m/s^2)
            fc_frac = math.sqrt(max(1.0 - (a_lat_now / max(alat_max_now, 1e-3)) ** 2, 0.0))
            # CLOSED-LOOP corner-speed trim: pure-pursuit cuts the corner, so the car drives a
            # gentler path than planned and has grip to SPARE at v_curve (pulls ~1.7g of 2.6g).
            # When realized lateral g is under budget AND throttle headroom exists, nudge the
            # corner cap UP next tick; back off FAST if over budget. Self-tunes to the real grip;
            # asymmetric rates + clamp keep it safe (creeps up, sheds speed instantly).
            if spd * 3.6 > 35.0 and a_lat_now > 2.0:
                g_util = a_lat_now / max(alat_max_now, 1e-3)
                if g_util < corner_gutil and fc_frac > corner_fcgate:
                    v_curve_trim = min(1.30, v_curve_trim + 0.0015)
                elif g_util > 0.98:
                    v_curve_trim = max(0.85, v_curve_trim - 0.010)
            else:
                v_curve_trim += (1.0 - v_curve_trim) * 0.02      # relax toward 1.0 on straights
            drive_slip = max(abs(f.combined_slip_fl), abs(f.combined_slip_fr),
                             abs(f.combined_slip_rl), abs(f.combined_slip_rr))
            # (fix-b attempt REVERTED 07-03: gating this on longitudinal slip_ratio alone
            # -- to stop the S12 bank's lateral load from muting the pedal -- caused
            # power-on oversteer: sideslip p99 7.4 -> 27.8 deg, off 1.4 -> 8.4%. The
            # combined-slip mute IS the power-oversteer guard. Any retry must keep a
            # combined ceiling, just softer, e.g. derate from ~1.5 instead of 1.05.)
            if drive_slip <= slip_target:
                slip_frac = 1.0
            else:
                slip_frac = max(0.15, 1.0 - (drive_slip - slip_target) / max(slip_target, 1e-3))
            # crest throttle-ease: lift when the truck goes light over a crest (grip_scale<1)
            # -- prevents power-oversteer over crests (gating it OFF on straights caused 9% slides).
            thr_cap = max_throttle * fc_frac * slip_frac * grip_scale
            brake_cap = max(fc_frac, 0.2)                           # ease braking while cornering hard
            # brake ANTI-LOCK: the brake had NO slip feedback, so hard braking LOCKED the wheels
            # (drive_slip spikes to 8-10, lateral g collapses to ~0.5g, the car skids straight and
            # can't rotate -> arrives at the apex pointed wrong, then waits to get back to throttle).
            # Derate the brake past the lock threshold so the contact patch stays alive and lateral
            # g stays loaded under braking -- real trail-braking instead of a lockup skid. Mirrors
            # the throttle's slip_frac (proven), with a higher lock-specific threshold.
            LOCK_SLIP = 2.0
            brake_slip_frac = 1.0 if drive_slip <= LOCK_SLIP else \
                max(0.25, 1.0 - (drive_slip - LOCK_SLIP) / LOCK_SLIP)
            err = target_v - spd
            # BRAKE FEEDFORWARD (braking-zone fix): the brake was pure-proportional, so it
            # NEEDED a standing speed error to hold any pedal -- following the anticipation
            # curve (which descends at A_BRAKE=2.55 g by design) it equilibrated at half pedal
            # / 1.9 g, 40 m late, and finished braking inside the corner where the friction
            # circle blocks it (human: full pedal at 3.1 g, done before turn-in). Mirror of the
            # throttle's t_ff: command the pedal that DELIVERS the target's own descent rate
            # upfront; the P-term only trims the residual. 30 m/s^2 = measured full-pedal decel.
            desc = 0.0
            if prev_tgt is not None and 0.0 < dt < 0.3:
                desc = max(0.0, (prev_tgt - target_v) / dt)         # target descent (m/s^2)
            desc_f += 0.3 * (min(desc, 26.0) - desc_f)              # low-pass, clip spikes
            prev_tgt = target_v
            if err >= 0:
                # THROTTLE INTEGRAL (exit-starvation fix a): pure-P needs 9 km/h of standing
                # error for full pedal, so the pedal melts as the car approaches target --
                # measured +2-4 km/h permanent error lap-wide (S9 control zone: 100% of ticks
                # P-limited at thr 0.1-0.5). The integral supplies the standing pedal; P only
                # trims transients. Anti-windup: no integration while the grip cap binds.
                desired = kp_thr * err + thr_i
                if desired < thr_cap:
                    thr_i = min(thr_i + ki_thr * err * dt, 1.0)
                desired = min(desired, thr_cap)
                throttle = min(desired, throttle + args.thr_rate)   # rate-limit up
                # #3 anticipatory throttle-hold: when predicted load ~10 m ahead is rising into
                # compression AND the car is already rotating/counter-steering, HOLD throttle at
                # its pre-gate value so the returning grip doesn't tip the rotating rear over.
                if th_on > 0.0:
                    _lp_ah = 1.0 + float(zpp_ahead10[i0]) * spd * spd / 9.81
                    _rotating = oversteer or abs(e_r) > 0.5
                    if _lp_ah > 1.3 and _rotating and throttle > 0.35:
                        throttle = min(throttle, _th_hold)          # cap at the latched value
                    else:
                        _th_hold = throttle                         # not gated -> track (latch on next entry)
                brake = 0.0
            else:
                throttle = 0.0
                _th_hold = 0.0                                      # reset the hold latch off-throttle
                thr_i *= 0.90                                       # bleed the integral fast
                ff = brk_ff * (desc_f / 30.0)
                brake = min(ff + args.kp_brk * -err, brake_cap) * brake_slip_frac

            # --- SLIP-INDUCTION (point #1): trail-brake to ROTATE the car when the front
            # steering is SATURATED in a tight corner but it still understeers (won't turn
            # enough). Brake-induced weight transfer lightens the rear so the car points
            # tighter than full front-lock alone allows; the sideslip counter-steer (applied
            # later) catches the rear if it steps out too far. Grip-capped so it can't lock up.
            if (slip_brake_gain > 0.0 and launched and spd * 3.6 > 25.0 and understeer and
                    abs(steer) > args.slip_steer_sat and abs(kap_car) > args.slip_kap_min):
                slip_b = min(slip_brake_gain, brake_cap)
                if slip_b > brake:
                    brake = slip_b
                    throttle = 0.0                     # lift so the rotation takes

            # --- manual-with-clutch shifting: clutch=A, up=RB, down=LB (absolute rpm) ---
            gear = f.gear
            clutch = up_btn = dn_btn = False
            shift_log = 0
            if shift_frames > 0:
                clutch = not args.no_clutch
                throttle = 0.0                              # lift through the shift
                press = 2 <= shift_frames <= 5              # hold the shift button ~4 frames
                up_btn = press and shift_kind == "up"
                dn_btn = press and shift_kind == "down"
                shift_log = 1 if shift_kind == "up" else -1
                shift_frames -= 1
                if shift_frames == 0:
                    shift_cd = 10
            elif shift_cd > 0:
                shift_cd -= 1
            elif (gear < 1 and throttle > 0.05) or (1 <= gear < args.top_gear and f.rpm > args.shift_up_rpm):
                shift_kind, shift_frames = "up", 6
            elif gear > 1 and f.rpm < args.shift_down_rpm:
                shift_kind, shift_frames = "down", 6

            # --- dirt detection: is the car between the corridor walls at this station? ---
            cwx = 0.5 * (left_w[i0, 0] + right_w[i0, 0])
            cwz = 0.5 * (left_w[i0, 1] + right_w[i0, 1])
            half = 0.5 * math.hypot(left_w[i0, 0] - right_w[i0, 0], left_w[i0, 1] - right_w[i0, 1])
            off_c = (x - cwx) * (-tgz / tl) + (z - cwz) * (tgx / tl)
            on_track = abs(off_c) <= half + 0.5

            # --- SELF-CALIBRATION of the per-station corner-speed map (independence: the
            # bot earns its own speed from its own telemetry; human laps = evaluation only).
            # Credit: cornering with spare measured grip + clean tracking + on surface ->
            # the governing 18 m window creeps up (slow: consistency must be demonstrated).
            # Debit: over grip budget -> fast local cut. INCIDENT (off / slide / blown cte):
            # cut the stations 15-55 m UPSTREAM -- offs land downstream of their cause (the
            # S11 lesson) -- at most once per station per lap so one long excursion doesn't
            # nuke a corner the bot then spends an evening re-earning.
            if vtrim_on > 0.0 and f.race_position >= 1 and launched:
                if int(f.lap_no) != vtrim_lap:
                    vtrim_lap = int(f.lap_no); vtrim_penalized.clear()

                def _vt_bump(idxs, amt):
                    # bump delta locally + step the feature net (generalizes to similar
                    # places); freeze at the effective bounds so pinned stations don't
                    # accumulate unbounded delta (the saturation-creep lesson)
                    nonlocal vtrim_dirty, vtrim_map
                    if amt > 0:
                        idxs = [j for j in idxs if vtrim_map[j] < vtrim_hi - 1e-6]
                    else:
                        idxs = [j for j in idxs if vtrim_map[j] > vtrim_lo + 1e-6]
                    if not idxs:
                        return
                    for j in idxs:
                        vdelta[j] += amt
                        vtrim_map[j] = min(vtrim_hi, max(vtrim_lo, vt_base[j] + vdelta[j]))
                    if vnet is not None and vtrim_netscale > 0.0:
                        vnet.step(vXf[idxs], amt * vtrim_netscale)
                    vtrim_dirty += 1

                incident = (not on_track) or acte > 8.0 or abs(sideslip) > args.full_slide_deg
                if incident:
                    hit = []
                    d_b, j_b = 0.0, i0
                    while d_b < 55.0:
                        j_b = (j_b - 1) % n; d_b += seg[j_b]
                        if d_b >= 15.0 and j_b not in vtrim_penalized:
                            vtrim_penalized.add(j_b); hit.append(j_b)
                    if hit:
                        _vt_bump(hit, -vtrim_cut)
                    # ACM: credit the slide to its hazard core (once per lap per core) -> the core
                    # earns its grip margin from the car's own experience of sliding there.
                    if int(f.lap_no) != acm_lap:
                        acm_lap = int(f.lap_no); acm_penalized.clear()
                    _hc = int(acm_haz_of[i0])
                    if _hc >= 0 and _hc not in acm_penalized:
                        acm_penalized.add(_hc); acm_hits[_hc] += 1.0; acm_dirty = True
                elif spd * 3.6 > 35.0 and a_lat_now > 2.0:
                    # LOCAL attribution (+-6 m around the car): the measured g RIGHT NOW
                    # proves/disproves the speed AT THIS STATION (window-ahead attribution
                    # left corner entries never earning). No fc_frac gate: redundant with
                    # the g_util ceiling.
                    # cleanliness gate = EDGE MARGIN, not absolute line offset: the bot's
                    # natural tracking offset through a fast sweeper is ~2.5 m (S3 kink cte
                    # med 2.49/p90 3.26), so an acte<2 gate FROZE credit there forever --
                    # map stuck at 0.96 from old cuts -> mid-sweeper brake slam while the
                    # human is flat. 2.5 m off-line with 3 m to the edge is proven-safe;
                    # 1 m off-line beside a wall is not. Margin says which is which.
                    # ...and require steering NOT saturated: at the S9 crest the wheel is
                    # pinned at 1.00 while g_util reads 0.62 -- low measured g there is the
                    # SYMPTOM of execution saturation, not spare grip. Crediting it earns
                    # speed the tracker cannot deliver (probe -> wash -> incident cycle).
                    edge_margin = half - abs(off_c)
                    g_util_m = a_lat_now / max(alat_max_now, 1e-3)
                    # (SATURATION DEBIT tried + REVERTED 07-03: continuous cuts while
                    # steer-pinned dug a sharp hole the map's 18 m window turns into STEP
                    # braking mid-crest while light -> rear unloads -> slides (sideslip p90
                    # 5 -> 25 deg) -> incident cuts -> spiral to the 0.80 floor at 87 km/h.
                    # Map debits must stay SLOW; sharp local cuts need cone-smearing like
                    # the static tables. The credit gate + incident cuts are the guards.)
                    # vtrim_hold_geo: in survey-marked crest->compression->turn zones, allow the
                    # DEBIT/incident-cut but FREEZE the positive re-earn -> cuts from actual slides
                    # STICK (the g_util earn-rule is blind to the transient grip-return slide there).
                    _earn_frozen = vtrim_hold_geo > 0.0 and cg_geo_mask[i0]
                    if g_util_m > 0.98 or (g_util_m < vtrim_gutil and edge_margin > 1.2
                                           and abs(steer) < 0.95 and not _earn_frozen):
                        win = []
                        d_f, j_f = 0.0, (i0 - 6) % n
                        while d_f < 12.0:
                            win.append(j_f)
                            d_f += seg[j_f]; j_f = (j_f + 1) % n
                        _vt_bump(win, -vtrim_dn if g_util_m > 0.98 else vtrim_up)
                elif (spd * 3.6 > 60.0 and abs(err) * 3.6 < 5.0 and (half - abs(off_c)) > 1.2
                      and brake == 0.0 and not (vtrim_hold_geo > 0.0 and cg_geo_mask[i0])):
                    # STRAIGHT RE-EARN: incident cuts can land on low-lateral stations
                    # (bank exits, kink run-ups) that the cornering credit -- gated on
                    # a_lat>2 -- can never raise again: permanent scar tissue capping
                    # straights (fix-b's slides left s0-40 at 0.80 = a 200 km/h ceiling
                    # on the s/f straight). Driving a station cleanly AT target without
                    # cornering load proves it deserves more; half-rate credit, same
                    # freeze-at-bounds guard.
                    win = []
                    d_f, j_f = 0.0, (i0 - 6) % n
                    while d_f < 12.0:
                        win.append(j_f)
                        d_f += seg[j_f]; j_f = (j_f + 1) % n
                    _vt_bump(win, 0.5 * vtrim_up)
                if vnet is not None and frames % 256 == 0:
                    # absorb net drift everywhere (steps at one corner move similar
                    # corners -- that's the generalization; refresh the effective map)
                    vt_base = vtrim_base()
                    vtrim_map = np.clip(vt_base + vdelta, vtrim_lo, vtrim_hi)
                if vtrim_dirty and frames % 2048 == 0:
                    if save_vtrim():
                        vtrim_dirty = 0
                if acm_dirty and frames % 512 == 0:
                    save_acm(); acm_dirty = False

            # --- AFK off-track wedge escape: a car wedged OFF the track at ~0 speed can't
            # drive itself out (wall/ditch); the stuck-guard's hold just cycles. So after a
            # few seconds wedged off-track, Reset Car Position via the pause menu, then
            # re-localize and re-arm the launch guard. ---
            if args.afk and reset_car is not None:   # (no 'launched' gate: a car wedged off
                if (not on_track) and spd * 3.6 < 4.0:  # the track never launches; grid is on-track)
                    freeroam_since = 0.0
                    if stuck_off_since == 0.0:
                        stuck_off_since = time.time()
                    elif time.time() - stuck_off_since > 7.0 and time.time() - last_reset > 12.0:
                        print("\n[afk] wedged off-track -> Reset Car Position", flush=True)
                        reset_car(gp, RECOVER_BTN, fz_hwnd, log=lambda m: print(m, flush=True))
                        idx = None; traveled = 0.0; launched = False
                        held = False; stuck = 0; held_frames = 0
                        stuck_off_since = 0.0; last_reset = time.time()
                        race_t_last = 0.0; racing_seen = time.time()
                        neutral(); continue
                elif (not on_track) and spd * 3.6 > 10.0 and recover_to_racing is not None:
                    # MOVING off the race corridor for a while = FREE ROAM (or badly lost), not
                    # a race. Recover -- the recovery's HUD check confirms: a real race off-line
                    # returns immediately; free roam re-launches the EventLab.
                    stuck_off_since = 0.0
                    if freeroam_since == 0.0:
                        freeroam_since = time.time()
                    elif time.time() - freeroam_since > 6.0 and time.time() - last_recover > 10.0:
                        print("\n[afk] moving off the race corridor -> recover (free roam?)", flush=True)
                        recover_to_racing(gp, RECOVER_BTN, get_frame, fz_hwnd,
                                          log=lambda m: print(m, flush=True), post_race=False, line=line)
                        idx = None; traveled = 0.0; launched = False
                        held = False; stuck = 0; held_frames = 0
                        freeroam_since = 0.0; race_t_last = 0.0
                        racing_seen = time.time(); last_recover = time.time()
                        neutral(); continue
                else:
                    stuck_off_since = 0.0; freeroam_since = 0.0

                # catch-all wedge: launched but crawling/stopped for a sustained time,
                # regardless of on_track. The track-edge wedge flickers on_track (so the
                # off-track reset never arms) and the stuck-guard's held state zeroes the
                # throttle (so 'stuck' never accumulates) -> the car crawls/cycles forever.
                if (launched or plan_degraded) and spd * 3.6 < 9.0:
                    if stuck_slow_since == 0.0:
                        stuck_slow_since = time.time()
                    else:
                        stuck_for = time.time() - stuck_slow_since
                        # MAP guard: a stray VIEW / ghost press opens the full-screen map mid-race;
                        # the game pauses so the car reads as wedged, but Reset Car can't fix a map.
                        # While stuck, OCR (off the hot path, throttled) for the "Close Map" hint and,
                        # if up, close it back to the race (map -> pause -> game) BEFORE the reset.
                        if close_map is not None and stuck_for > 2.0 and time.time() - last_map_check > 1.5:
                            last_map_check = time.time()
                            if "close map" in ocr_text(fz_hwnd):
                                print("\n[afk] in-game MAP open mid-race -> closing (map -> pause -> game)", flush=True)
                                neutral()
                                close_map(gp, RECOVER_BTN, fz_hwnd, log=lambda m: print(m, flush=True))
                                stuck_slow_since = 0.0; race_t_last = 0.0; racing_seen = time.time()
                                neutral(); continue
                        if stuck_for > 5.0 and time.time() - last_reset > 12.0:
                            print("\n[afk] wedged (crawling <9km/h) -> Reset Car Position", flush=True)
                            reset_car(gp, RECOVER_BTN, fz_hwnd, log=lambda m: print(m, flush=True))
                            idx = None; traveled = 0.0; launched = False
                            held = False; stuck = 0; held_frames = 0
                            stuck_slow_since = 0.0; stuck_off_since = 0.0; last_reset = time.time()
                            race_t_last = 0.0; racing_seen = time.time()
                            neutral(); continue
                else:
                    stuck_slow_since = 0.0

            # --- stuck guard: if wedged at ~0 speed while on throttle, stop grinding and
            # hold; auto-resume (gentle launch re-armed) once moving again, e.g. after
            # Reset Car Position. Fires whether ON or OFF track (a tight corner can wedge
            # the car against a wall while still "in the corridor"), but only AFTER the
            # car has launched, so the pre-GO standstill at the grid is never a false wedge.
            if spd * 3.6 > 10.0:
                launched = True
            if launched and spd * 3.6 < 1.5 and throttle > 0.1:
                stuck += 1
            else:
                stuck = max(0, stuck - 2)
            if stuck > 40 and not held:
                held = True; held_frames = 0
                print("\n[follower] STUCK ({}) -- pausing ~1s then auto-retrying.".format(
                      "off-track" if not on_track else "on-track wall"), flush=True)
            if held:
                held_frames += 1
                # AUTO-RELEASE: never deadlock holding throttle=0 (the car can't move, so it
                # never un-sticks). Pause ~1s to settle, then resume NORMAL control with
                # idx/traveled reset (gentle launch caps re-arm) so it drives itself off.
                if spd * 3.6 > 6.0 or held_frames > 60:
                    held, stuck, held_frames, traveled, idx = False, 0, 0, 0.0, None
                else:
                    steer = throttle = brake = 0.0
                    clutch = up_btn = dn_btn = False

            # --- slide-aware stability + counter-steer (point #1, applied last) ---------
            # A real slide shows up in SIDESLIP, not yaw-rate: the yaw-rate oversteer flag
            # MISSES a four-wheel slide where the car rotates LESS than the path demands
            # while skating wide (a -44 deg spin once ran with over=0 the whole time and the
            # steering pinned at full path lock, which only deepened it). So act on sideslip
            # directly: ease/cut throttle to hand grip back to the tyres, and actively
            # COUNTER-STEER into the slide (steer toward the velocity vector) rather than
            # holding path lock. Works down to 12 km/h so it doesn't release mid-spin.
            absb = abs(sideslip)
            if launched and spd * 3.6 > 12.0 and absb > beta_soft:
                if absb >= beta_hard:
                    throttle = 0.0                       # big slide/spin -> kill power to regain grip
                else:
                    throttle *= max(0.0, 1.0 - (absb - beta_soft) / max(beta_hard - beta_soft, 1e-3))
            if launched and spd * 3.6 > 12.0 and absb > slide_deg:
                # counter-steer target ~ proportional to sideslip; sideslip<0 -> negative steer
                # (verified from the spin trace). Blend over the path steer as the slide grows,
                # so a developed slide commands mostly opposite lock instead of full path lock.
                cs = max(-1.0, min(1.0, k_slide * sideslip))
                w = min(1.0, (absb - slide_deg) / max(full_slide_deg - slide_deg, 1e-3))
                steer = (1.0 - w) * steer + w * cs
            if launched and spd * 3.6 < args.lowspeed_steer_kmh:
                steer = max(-0.5, min(0.5, steer))       # low-speed heading is noise -> don't thrash
            steer = max(-1.0, min(1.0, steer))

            # --- REVERSE-UNSTUCK (position-based; immune to wheelspin) -----------------------
            # A wedged car spins its wheels (SPEED reads high) but its POSITION doesn't advance.
            # When stuck, back up while steering the body toward the line, then hand back to
            # forward drive to re-align. Reset Car Position only if reversing fails repeatedly.
            if args.afk:
                if not launched:
                    wedge_ref = None; reversing = False
                elif not reversing:
                    if wedge_ref is None:
                        wedge_ref = (x, z); wedge_ref_t = time.time()
                    elif time.time() - wedge_ref_t > 3.0:
                        moved = math.hypot(x - wedge_ref[0], z - wedge_ref[1])
                        if moved < 5.0 and throttle > 0.25 and time.time() - last_reset > 8.0:
                            reversing = True; reverse_until = time.time() + 2.5
                            reverse_from = (x, z); reverse_attempts += 1
                            print("\n[afk] wedged (%.1fm/3s, wheels spinning) -> REVERSE-unstuck #%d"
                                  % (moved, reverse_attempts), flush=True)
                        wedge_ref = (x, z); wedge_ref_t = time.time()
                    if spd * 3.6 > 25.0:                  # a clean stretch clears the attempt count
                        ok_since = ok_since or time.time()
                        if time.time() - ok_since > 8.0:
                            reverse_attempts = 0
                    else:
                        ok_since = 0.0
                if reversing:
                    throttle = 0.0; brake = 1.0           # hold brake at standstill -> reverse
                    clutch = up_btn = dn_btn = False
                    # steer the body toward the line (cte). reversing inverts the response, so
                    # steering toward the side the car is on backs it onto the line. (live-tunable sign)
                    steer = max(-0.6, min(0.6, 0.15 * cte))
                    backed = reverse_from is not None and \
                        math.hypot(x - reverse_from[0], z - reverse_from[1]) > 4.0
                    if time.time() > reverse_until or (on_track and backed):
                        reversing = False; wedge_ref = None
                        traveled = 0.0; idx = None; held = False; stuck = 0
                        if reverse_attempts >= 3 and reset_car is not None:
                            print("[afk] reverse-unstuck failed 3x -> Reset Car Position", flush=True)
                            reset_car(gp, RECOVER_BTN, fz_hwnd, log=lambda m: print(m, flush=True))
                            reverse_attempts = 0; last_reset = time.time()

            # RESIDUAL CORRECTOR: small learned trim ON TOP of the nominal control. Normal driving
            # only (skip recovery/reverse/off-track, where it isn't trained). Feature order MUST
            # match residual_net.FEATURE_SPEC. Bounded by the net -> can't destabilize the base.
            if resid_on > 0.5 and on_track and not reversing:
                feats = [spd, f.ax, f.ay, f.az, f.vel_x, f.vel_y, f.angvel_x, f.angvel_y, f.angvel_z,
                         f.pitch, f.roll, f.rpm / max(f.max_rpm, 1.0), float(gear),
                         f.combined_slip_fl, f.combined_slip_fr, f.combined_slip_rl, f.combined_slip_rr,
                         drive_slip, sideslip, cte, cte_dot_f, alpha,
                         fc_frac, (target_v - spd), v_curve, steer, throttle, brake]
                feats += boundary_preview3d(x, f.pos_y, z, yaw_h, i0 if i0 is not None else 0,
                                            line, left_w, right_w, elev_w, bc_clen)   # 48-feature 3D vision
                d_st, d_th, d_br = resid_net.forward(feats)
                steer = max(-1.0, min(1.0, steer + float(d_st)))
                throttle = max(0.0, min(1.0, throttle + float(d_th)))
                brake = max(0.0, min(1.0, brake + float(d_br)))
            # SFT POLICY DRIVES: when bc_on, the learned policy REPLACES the base control during normal
            # racing (full steer/thr/brk = net output). Recovery/reverse/off-track stay on the base so
            # the AFK loop still self-heals. yaw_h (yaw-derived heading) matches the training features.
            if bc_on > 0.5 and bc_policy is not None and on_track and not reversing and spd * 3.6 > 70.0:
                # SFT as a BOUNDED RESIDUAL CORRECTOR on top of the base (NOT full control): nudge the
                # base's command toward the human's, clamped, so the BASE still drives and self-recovers
                # (no OOD cascade). Speed-gated to where the human data is dense (racing >70 km/h).
                bc_feats = sft_features(spd, f.vel_x, f.vel_y, f.vel_z, f.angvel_x, f.angvel_y, f.angvel_z,
                                        f.pitch, f.roll, f.rpm, float(gear),
                                        x, z, yaw_h, (i0 if i0 is not None else 0),
                                        line, left_w, right_w, bc_clen)
                bc_st, bc_th, bc_br = bc_forward(bc_policy, bc_feats)
                B_S, B_P = 0.15, 0.20    # max correction the SFT may apply to base steer / pedals
                steer    = max(-1.0, min(1.0, steer    + max(-B_S, min(B_S, bc_st - steer))))
                throttle = max(0.0, min(1.0, throttle + max(-B_P, min(B_P, bc_th - throttle))))
                brake    = max(0.0, min(1.0, brake    + max(-B_P, min(B_P, bc_br - brake))))
            gp.left_joystick_float(x_value_float=float(steer), y_value_float=0.0)
            gp.right_trigger_float(value_float=float(throttle))
            gp.left_trigger_float(value_float=float(brake))
            (gp.press_button if clutch else gp.release_button)(button=BTN_A)
            (gp.press_button if up_btn else gp.release_button)(button=BTN_RB)
            (gp.press_button if dn_btn else gp.release_button)(button=BTN_LB)
            gp.update()

            logw.writerow([round(time.time() - t0, 3), round(x, 1), round(z, 1),
                           round(spd * 3.6, 1), round(f.yaw, 3), round(math.degrees(heading), 1),
                           i0, round(tx, 1), round(ty, 1), round(math.degrees(alpha), 1),
                           round(cte, 2), round(steer, 3), round(throttle, 3), round(brake, 3),
                           round(target_v * 3.6, 1), gear, round(f.rpm), int(on_track),
                           round(f.max_rpm), shift_log,
                           round(ff, 4), round(p_t, 4), round(i_t, 4), round(d_t, 4),
                           round(cte_int, 3), round(cte_dot_f, 3), round(kappa_ff, 6),
                           f.lap_no, round(f.cur_lap_time, 2), round(sideslip, 1),
                           round(pl["d0"], 2) if pl is not None else 0.0,
                           round(pl["horizon"], 1) if pl is not None else 0.0,
                           int(plan_degraded),
                           round(math.degrees(pl["psi"]), 1) if pl is not None else 0.0,
                           round(pl["kappa_merge_max"], 4) if pl is not None else 0.0,
                           round(kap_car, 4), round(v_curve * 3.6, 1), round(thr_cap, 3),
                           round(f.angvel_y, 3),
                           round(f.ax / 9.81, 2), round(drive_slip, 2),
                           round(alat_max_now / 9.81, 2), round(fc_frac, 2),
                           round(r_des, 3), round(r_meas_f, 3), round(e_r, 3),
                           int(oversteer), int(understeer), f.race_position,
                           round(f.pos_y, 2), round(math.degrees(f.pitch), 2),
                           round(math.degrees(f.roll), 2)])
            frames += 1
            if pathf is not None and pl is not None and frames % args.path_log_every == 0:
                pathf.write(json.dumps({
                    "t": round(time.time() - t0, 2), "x": round(x, 1), "z": round(z, 1),
                    "head": round(math.degrees(heading), 1), "spd": round(spd * 3.6, 1),
                    "d0": round(pl["d0"], 2), "L": round(pl["horizon"], 1),
                    "deg": int(plan_degraded), "tgt": [round(float(tx), 1), round(float(ty), 1)],
                    "path": [[round(float(px), 1), round(float(pz), 1)] for px, pz in pl["path"]],
                }) + "\n")

            # telemetry-aligned screenshot trigger (enqueue only; the worker grabs)
            if cap is not None:
                if cap["lastxz"] is not None:
                    cap["dist"] += math.hypot(x - cap["lastxz"][0], z - cap["lastxz"][1])
                cap["lastxz"] = (x, z)
                if cap["prev_i0"] is not None and cap["prev_i0"] > 350 and i0 < 50 and cap["started"]:
                    cap["laps"] += 1
                cap["prev_i0"] = i0
                if cap["dist"] >= args.capture_every_m or cap["seq"] == 0:
                    cap["dist"] = 0.0
                    cap["started"] = True
                    meta = {"t": round(time.time() - t0, 3), "i0": i0,
                            "x": round(x, 1), "z": round(z, 1), "spd": round(spd * 3.6),
                            "on_track": int(on_track), "cte": round(cte, 2),
                            "gear": gear, "rpm": round(f.rpm)}
                    try:
                        cap["q"].put_nowait((cap["seq"], meta))
                        cap["seq"] += 1
                    except Exception:
                        pass                              # worker behind / queue full -> skip, never block driving
                if cap["laps"] >= args.capture_laps:
                    cap["q"].put(None)
                    print(f"\n[capture] {cap['seq']} frames over {args.capture_laps} lap(s) -> {args.capture_dir}")
                    cap = None

            if frames % 30 == 0:
                logf.flush()
                if pathf is not None:
                    pathf.flush()
            if frames % 15 == 0:
                print(f"\r {spd*3.6:5.1f}->{target_v*3.6:4.0f}km/h g{gear} {f.rpm:4.0f}rpm | "
                      f"st{steer:+.2f} th{throttle:.2f} br{brake:.2f} | "
                      f"{'DIRT' if not on_track else 'trk'} i{i0:3d}   ", end="", flush=True)
    except KeyboardInterrupt:
        print("\nstopping (Ctrl+C)")
    finally:
        neutral()
        sock.close()
        logf.close()
        if pathf is not None:
            pathf.close()
    print(f"\ndone. log -> {args.log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

