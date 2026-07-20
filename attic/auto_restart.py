"""auto_restart.py — detect race finish and re-launch the EventLab race via vpad.

Replays the human's restart macro (captured 2026-06-25):
  [finish] -> A (dismiss results) -> wait free roam -> START (pause menu) ->
  RB x4 (cycle to event/map tab) -> A -> D-right -> A,A,A (Play Event + confirm)
  -> wait for the 50-lap grid -> racing.

The EventLab "Play Event" re-runs the SAVED race config (50 laps / No AI) and
teleports to the grid, so there is NO drive-to-start and NO settings menu.

Gated by telemetry (is_race_on / lap_no) + reference screenshots saved each step
(recordings/restart_replay_<ts>/) so a failed replay is debuggable. Screenshot
verification of key screens can be layered on once the blind macro is validated.

Usage:
  python auto_restart.py --now            # run the restart macro immediately (TEST)
  python auto_restart.py --laps 50        # watch telemetry; restart after lap 50 finishes
  python auto_restart.py --now --dry       # log the steps but DON'T press anything
"""
import argparse, ctypes, os, socket, sys, time
sys.path.insert(0, r"C:\Users\talon\FH6-AFK-Farm")
from fh6_telemetry import parse_packet

# --- keyboard ENTER via SendInput (Forza's confirm screens flap to wanting Enter,
#     not the vpad's A; sending Enter commits them when Forza is the focused window) ---
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_VK_RETURN = 0x0D; _KEYUP = 0x0002
class _KBD(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]
class _U(ctypes.Union):
    _fields_ = [("ki", _KBD)]
class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("u", _U)]
def key_enter():
    for flags in (0, _KEYUP):
        inp = _INPUT(type=1, u=_U(ki=_KBD(_VK_RETURN, 0, flags, 0, None)))
        _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))
        time.sleep(0.04)
try:
    from winshot import grab_window, find_forza_window
except Exception:
    grab_window = find_forza_window = None
try:
    import winocr
except Exception:
    winocr = None

PORT = 7777


def make_pad():
    import vgamepad as vg
    gp = vg.VX360Gamepad()
    B = vg.XUSB_BUTTON
    btn = {
        "A": B.XUSB_GAMEPAD_A, "B": B.XUSB_GAMEPAD_B, "X": B.XUSB_GAMEPAD_X, "Y": B.XUSB_GAMEPAD_Y,
        "RB": B.XUSB_GAMEPAD_RIGHT_SHOULDER, "LB": B.XUSB_GAMEPAD_LEFT_SHOULDER,
        "START": B.XUSB_GAMEPAD_START, "BACK": B.XUSB_GAMEPAD_BACK,
        "Dup": B.XUSB_GAMEPAD_DPAD_UP, "Ddown": B.XUSB_GAMEPAD_DPAD_DOWN,
        "Dleft": B.XUSB_GAMEPAD_DPAD_LEFT, "Dright": B.XUSB_GAMEPAD_DPAD_RIGHT,
    }
    return gp, btn


class Telem:
    """Background-ish UDP poll (drain to latest) for is_race_on / lap / speed."""
    def __init__(self):
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s.bind(("0.0.0.0", PORT)); self.s.setblocking(False)
        self.fr = None
    def poll(self):
        while True:
            try:
                data, _ = self.s.recvfrom(2048)
            except BlockingIOError:
                break
            f = parse_packet(data)
            if f is not None:
                self.fr = f
        return self.fr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--now", action="store_true", help="run the restart macro immediately (test)")
    ap.add_argument("--from-roam", action="store_true", help="skip the results-dismiss; start at the pause-menu nav (test the fragile part from free roam)")
    ap.add_argument("--laps", type=int, default=0, help="restart after this many laps complete")
    ap.add_argument("--dry", action="store_true", help="log steps but do not press buttons")
    args = ap.parse_args()

    shotdir = r"C:\Users\talon\FH6-AFK-Farm\recordings\restart_replay_%d" % int(time.time())
    os.makedirs(shotdir, exist_ok=True)
    tel = Telem()
    gp = btn = None
    if not args.dry:
        gp, btn = make_pad()
        time.sleep(0.5)
    nshot = [0]
    hwnd = find_forza_window() if find_forza_window else None

    def snap(tag):
        if grab_window is None: return
        try:
            img = grab_window(hwnd)
            if img is None: return
            img = img.convert("RGB"); img = img.resize((img.width // 3, img.height // 3))
            fn = os.path.join(shotdir, f"r_{nshot[0]:03d}_{tag}.jpg"); img.save(fn, quality=60)
            nshot[0] += 1
        except Exception:
            pass

    def press(name, hold=0.12, after=0.6):
        f = tel.poll()
        race = f.is_race_on if f else "?"
        print(f"  press {name:6s} (race={race})", flush=True)
        snap(f"before_{name}")
        if not args.dry and name in btn:
            gp.press_button(button=btn[name]); gp.update(); time.sleep(hold)
            gp.release_button(button=btn[name]); gp.update()
        time.sleep(after)

    def wait_race(target, timeout, label):
        print(f"  wait is_race_on=={target} ({label}, <= {timeout}s)", flush=True)
        t0 = time.time(); stable = 0
        while time.time() - t0 < timeout:
            f = tel.poll()
            if f and f.is_race_on == target:
                stable += 1
                if stable >= 8:  # ~0.8s stable to ride out loading flicker
                    print(f"    -> race={target} stable after {time.time()-t0:.1f}s", flush=True)
                    snap(f"reached_race{target}")
                    return True
            else:
                stable = 0
            time.sleep(0.1)
        print(f"    !! timeout waiting race={target}", flush=True)
        snap(f"timeout_race{target}")
        return False

    def restart_macro():
        print("=== RESTART MACRO ===", flush=True)
        snap("00_start")
        print("  [focus] waiting 6s -- click/focus FORZA now (keyboard Enter needs it foreground)", flush=True)
        time.sleep(6)
        # 0) the vpad just connected -> Forza flashes "Controller Disconnected" as the
        # virtual pad takes over from the physical one. Dismiss it (A) before navigating.
        print("  [dialog-dismiss] tapping A + Enter to clear any Controller-Disconnected box", flush=True)
        for _ in range(2):
            press("A", after=0.4)
            key_enter()
            time.sleep(0.6)
        snap("01_after_dialog_dismiss")
        if not args.from_roam:
            # 1) dismiss the results / finish screen (press A until we leave the race-finished state)
            for _ in range(3):
                press("A", after=1.0)
            # 2) wait to be back in free roam (loading settles; is_race_on rides back to 1)
            wait_race(1, 25, "free roam after finish")
            time.sleep(1.5)
        # 3) open the pause/map menu and navigate to Play Event.
        # verify it opened (is_race_on -> 0 when paused); retry once if it didn't.
        press("START", after=1.3)
        f = tel.poll()
        if f and f.is_race_on == 1:
            print("  [retry] pause menu didn't open (race still 1) -> START again", flush=True)
            press("START", after=1.3)
        for _ in range(4):
            press("RB", after=0.5)
        # navigate CREATIVE HUB(EventLab) -> My Events -> blueprint -> Solo -> confirm car.
        # (verified screen-by-screen 2026-06-25; the LAST A confirms the car-select screen,
        # which is what launches the race -- the bug was missing this 5th A.)
        press("A", after=1.6)        # open EventLab (Create & Browse Events)
        press("Dright", after=0.9)   # Play Event -> My Events
        press("A", after=2.0)        # open My Events (My Local Events list; loads from cloud)
        press("A", after=2.5)        # select the blueprint card -> Choose Race Type
        # COMMIT via OCR (Windows.Media.Ocr): READ each setup screen and act on it. PRESS
        # menus (A; Enter fallback if A doesn't move that screen), WAIT through loads (NEVER
        # press during a load -- a "Season Changing" load appears twice, loading the overview
        # then launching, and a press into a load CANCELS it), and finish only when the race
        # clock confirms a live race. The prompts flap between vpad-"A" and keyboard-"Enter".
        def ocr_text():
            if winocr is None:
                return ""
            img = grab_window(hwnd)
            if img is None:
                return ""
            try:
                img = img.convert("RGB")
                if img.width > 1800:
                    img = img.resize((img.width // 2, img.height // 2))
                r = winocr.recognize_pil_sync(img, "en")
                txt = r.get("text", "") if isinstance(r, dict) else getattr(r, "text", "")
                return txt.lower()
            except Exception as e:
                print(f"  [ocr] err: {e}", flush=True)
                return ""
        def screen_type(t):
            if "season changing" in t or "loading" in t or "please wait" in t:
                return "load"
            if "choose race type" in t:
                return "choose"
            if "start race event" in t:
                return "start"
            if "current car" in t or "my cars" in t:
                return "car"
            if "select" in t:
                return "menu"
            return "other"
        def tap_A():
            if not args.dry and gp is not None:
                gp.press_button(button=btn["A"]); gp.update(); time.sleep(0.12)
                gp.release_button(button=btn["A"]); gp.update()
        def racing():
            # robust: is_race_on=1 on BOTH samples AND cur_race_time advancing near real-time
            # from a small base. A fresh race starts ~0 and ticks ~1s/s; rejects stale garbage
            # (e.g. a 722s reading during a load) and non-monotonic flickers.
            a = tel.poll(); ra, ta = (a.is_race_on, a.cur_race_time) if a else (0, 0.0)
            time.sleep(1.2)
            b = tel.poll(); rb, tb = (b.is_race_on, b.cur_race_time) if b else (0, 0.0)
            return ra == 1 and rb == 1 and 0.3 < (tb - ta) < 5.0 and tb < 300.0
        started = False
        for attempt in range(24):
            st = screen_type(ocr_text())
            snap(f"commit_{attempt}_{st}")
            print(f"  [commit] {attempt}: screen={st}", flush=True)
            if st in ("choose", "car", "start", "menu"):
                tap_A(); time.sleep(1.7)              # advance the menu (A; Enter fallback)
                if screen_type(ocr_text()) == st:
                    print(f"  [commit]   A held on '{st}' -> Enter", flush=True)
                    key_enter(); time.sleep(1.7)
                continue
            # st is "load"/"other": loading toward the race. "Season Changing" appears TWICE
            # (loading the overview, then launching), so NEVER press here -- a press into a
            # load CANCELS it. Just check the race clock; else wait for the load to resolve.
            if racing():
                f = tel.poll()
                print(f"  [commit] RACE CONFIRMED -- clock advancing (t={f.cur_race_time:.1f}s)", flush=True)
                started = True; break
            time.sleep(1.6)
        if not started:
            print("  [commit] !! never confirmed a live race (stuck or cancelled)", flush=True)
        time.sleep(2.0)
        snap("99_done")
        f = tel.poll()
        print(f"=== MACRO DONE  started={started} race={f.is_race_on if f else '?'} "
              f"t={f.cur_race_time if f else '?'} lap={f.lap_no if f else '?'} ===", flush=True)
        return started

    if args.now:
        restart_macro()
        # keep the pad ALIVE so Forza doesn't flash a disconnect dialog on exit.
        # (in the real system the follower owns this pad and keeps driving.) 90s comfortably
        # outlasts the "Season Changing" load + cinematic + countdown so the race fully starts.
        print("  [hold] keeping vpad alive 90s (Ctrl-C / kill to release)...", flush=True)
        t0 = time.time(); last_hs = -10
        while time.time() - t0 < 90:
            f = tel.poll()
            if gp is not None:
                gp.update()
            el = time.time() - t0
            if el - last_hs >= 8:        # screenshot the load->grid->race progression
                last_hs = el
                rt = f.cur_race_time if f else 0.0
                snap(f"hold_{int(el):02d}s_race{f.is_race_on if f else 'x'}_t{rt:.0f}_lap{f.lap_no if f else 'x'}")
            time.sleep(0.2)
        return

    if args.laps > 0:
        print(f"watching: will restart after lap {args.laps} completes...", flush=True)
        peak = 0
        while True:
            f = tel.poll()
            if f:
                peak = max(peak, f.lap_no)
                # finish = we were on/after the target lap and the race ended
                if peak >= args.laps and f.is_race_on == 0:
                    print(f"finish detected (peak lap {peak})", flush=True)
                    restart_macro()
                    peak = 0
            time.sleep(0.1)

    print("nothing to do (pass --now or --laps N)")


if __name__ == "__main__":
    main()
