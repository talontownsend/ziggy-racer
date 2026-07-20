"""record_restart.py (v2) — capture a manual race-restart sequence for replay.

Captures TWO streams on one monotonic clock to a JSONL:
  1. telemetry (UDP 7777, ~30 Hz): is_race_on, x, z, speed, accel/brake/steer,
     gear, lap  -- driving inputs + position (always, even in menus)
  2. controller (winmm joyGetPosEx, ~120 Hz, event-on-change): the user's pad,
     which is a legacy/DirectInput device invisible to XInput. Logs raw button
     bitmask transitions, POV (D-pad) hat, and stick/trigger axes.

Raw bits are logged map-agnostically; decode_restart.py applies the button map.

Pure ctypes -- no installs. Run in background; stop with TaskStop / Ctrl-C.
Output: recordings/restart_capture_<ts>.jsonl
"""
import ctypes, json, os, socket, sys, time
from ctypes import wintypes
sys.path.insert(0, r"C:\Users\talon\FH6-AFK-Farm")
from fh6_telemetry import parse_packet
try:
    from winshot import grab_window, find_forza_window
except Exception:
    grab_window = find_forza_window = None

PORT = 7777
JOY_ID = 0
_TS = int(time.time())
OUT = r"C:\Users\talon\FH6-AFK-Farm\recordings\restart_capture_%d.jsonl" % _TS
FRAMES = r"C:\Users\talon\FH6-AFK-Farm\recordings\restart_frames_%d" % _TS
SHOT_EVERY = 1.5   # seconds between reference screenshots

winmm = ctypes.WinDLL("winmm")
class JOYINFOEX(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("X", wintypes.DWORD), ("Y", wintypes.DWORD), ("Z", wintypes.DWORD),
                ("R", wintypes.DWORD), ("U", wintypes.DWORD), ("V", wintypes.DWORD),
                ("btns", wintypes.DWORD), ("btnNo", wintypes.DWORD), ("pov", wintypes.DWORD),
                ("r1", wintypes.DWORD), ("r2", wintypes.DWORD)]
JOY_RETURNALL = 0x000000ff
def joy(i=JOY_ID):
    info = JOYINFOEX(); info.dwSize = ctypes.sizeof(JOYINFOEX); info.dwFlags = JOY_RETURNALL
    return info if winmm.joyGetPosEx(i, ctypes.byref(info)) == 0 else None

def main():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("0.0.0.0", PORT)); s.setblocking(False)
    out = open(OUT, "w", buffering=1)
    t0 = time.perf_counter()
    def ev(d): d["t"] = round(time.perf_counter() - t0, 3); out.write(json.dumps(d) + "\n")
    have_joy = joy() is not None
    os.makedirs(FRAMES, exist_ok=True)
    hwnd = find_forza_window() if find_forza_window else None
    ev({"type": "start", "wall": time.time(), "joy": have_joy, "frames_dir": FRAMES})
    last_telem = 0.0; nt = nb = npov = nax = nshot = 0; last_print = 0.0; race = -1
    last_shot = 0.0
    pb = 0; ppov = 65535; pax = (32767, 32767, 0, 0)
    def snap(tag):
        nonlocal nshot
        if grab_window is None: return
        try:
            img = grab_window(hwnd)
            if img is None: return
            img = img.convert("RGB"); img = img.resize((img.width // 3, img.height // 3))
            fn = os.path.join(FRAMES, f"f_{nshot:04d}.jpg"); img.save(fn, quality=60)
            ev({"type": "shot", "file": os.path.basename(fn), "tag": tag}); nshot += 1
        except Exception:
            pass
    print(f"RECORDING -> {OUT}  (joy={'OK' if have_joy else 'MISSING'}, frames -> {FRAMES})\n", flush=True)
    try:
        while True:
            now = time.perf_counter()
            # --- telemetry: drain to latest, log ~30 Hz + phase transitions ---
            latest = None
            while True:
                try: data, _ = s.recvfrom(2048)
                except BlockingIOError: break
                fr = parse_packet(data)
                if fr is not None: latest = fr
            if latest is not None and now - last_telem >= 0.033:
                last_telem = now
                ev({"type": "telem", "race": int(latest.is_race_on),
                    "x": round(latest.pos_x, 1), "z": round(latest.pos_z, 1),
                    "spd": round(latest.speed_mps * 3.6, 1), "accel": latest.accel,
                    "brake": latest.brake, "steer": latest.steer, "gear": latest.gear,
                    "lap": latest.lap_no}); nt += 1
                if latest.is_race_on != race:
                    race = latest.is_race_on; ev({"type": "phase", "race": race})
                    snap(f"phase_race{race}")
            # periodic reference screenshot
            if now - last_shot >= SHOT_EVERY:
                last_shot = now; snap("periodic")
            # --- controller (winmm) transitions ---
            j = joy()
            if j is not None:
                if j.btns != pb:
                    changed = j.btns ^ pb
                    for bit in range(16):
                        if changed & (1 << bit):
                            ev({"type": "btn", "bit": bit, "down": bool(j.btns & (1 << bit)),
                                "raw": j.btns}); nb += 1
                    pb = j.btns
                if j.pov != ppov:
                    ev({"type": "pov", "pov": j.pov}); ppov = j.pov; npov += 1
                ax = (j.X, j.Y, j.Z, j.R)
                if (abs(ax[0]-pax[0])>3000 or abs(ax[1]-pax[1])>3000
                        or abs(ax[2]-pax[2])>3000 or abs(ax[3]-pax[3])>3000):
                    ev({"type": "ax", "x": j.X, "y": j.Y, "z": j.Z, "r": j.R}); pax = ax; nax += 1
            if now - last_print >= 3.0:
                last_print = now
                tag = "RACE" if race == 1 else "menu/roam"
                p = f" pos=({latest.pos_x:.0f},{latest.pos_z:.0f}) spd={latest.speed_mps*3.6:.0f} lap={latest.lap_no}" if latest else ""
                print(f"[{now-t0:6.1f}s] {tag}{p}  telem={nt} btn={nb} pov={npov} shots={nshot}", flush=True)
            time.sleep(0.008)
    except KeyboardInterrupt:
        ev({"type": "stop"}); out.close()
        print(f"\nstopped. telem={nt} btn={nb} pov={npov} ax={nax} -> {OUT}", flush=True)

if __name__ == "__main__":
    main()
