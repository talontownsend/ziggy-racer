"""afk_recover.py — OCR-driven self-recovery for the FH6 follower.

Given the caller's PERSISTENT vpad, drive the game from ANY non-driving state back
to a live race, so the follower never needs a human:
  - Controller-Disconnected dialog -> tap A (+ keyboard Enter; the prompt flaps)
  - pause menu (Restart/Quit Event) -> tap B to close (resume the race)
  - race results / finish -> tap A to advance out to free roam
  - free roam -> open the saved EventLab via the menu list and launch it
  - race-setup menus (Choose Race Type / car-select / Start Race Event) -> A (+Enter)
  - loads ("Season Changing") -> wait (NEVER press into a load; it cancels the launch)

Success = the race clock (cur_race_time) is advancing (the only signal that's true
ONLY in a live race -- is_race_on is also 1 in free roam and on the car-select menu).

Re-evaluates the screen each iteration (OCR) so a variable # of confirm screens and
the A/Enter prompt-flap are both handled. Needs Forza foreground (AFK = it is).
"""
import time, ctypes
try:
    import numpy as np
except Exception:
    np = None
try:
    import winocr
except Exception:
    winocr = None
try:
    from winshot import grab_window, find_forza_window
except Exception:
    grab_window = find_forza_window = None

# ---- keyboard Enter (some confirm prompts flap to wanting Enter, not vpad A) ----
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
_VK_ESCAPE = 0x1B
def _key(vk):
    for fl in (0, _KEYUP):
        inp = _INPUT(type=1, u=_U(ki=_KBD(vk, 0, fl, 0, None)))
        _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))
        time.sleep(0.04)
def key_enter():
    _key(_VK_RETURN)
def key_esc():
    _key(_VK_ESCAPE)

def ocr_text(hwnd):
    if winocr is None or grab_window is None:
        return ""
    img = grab_window(hwnd)
    if img is None:
        return ""
    try:
        img = img.convert("RGB")
        if img.width > 1800:
            img = img.resize((img.width // 2, img.height // 2))
        r = winocr.recognize_pil_sync(img, "en")
        return (r.get("text", "") if isinstance(r, dict) else getattr(r, "text", "")).lower()
    except Exception:
        return ""

def has_disconnect_dialog(hwnd):
    """Detect FH6's 'Controller Disconnected' box by its bright chartreuse center bar --
    robust where OCR fails (OCR reads the menu BEHIND the dialog and misses it)."""
    if np is None or grab_window is None:
        return False
    img = grab_window(hwnd)
    if img is None:
        return False
    try:
        a = np.asarray(img.convert("RGB")); h, w = a.shape[:2]
        band = a[int(h * 0.42):int(h * 0.50), int(w * 0.37):int(w * 0.63)]
        R = band[:, :, 0].astype(int); G = band[:, :, 1].astype(int); B = band[:, :, 2].astype(int)
        green = (R > 120) & (G > 180) & (B < 120) & ((G - B) > 90)
        return float(green.mean()) > 0.30
    except Exception:
        return False

def screen_state(t):
    if "controller disconnected" in t or "reconnect a controller" in t:
        return "disconnect"
    # TOP-LEVEL CAMPAIGN / PAUSE-OVERLAY (World Map | Collection Journal | ... | Exit Game).
    # This is the ESC overlay over FREE ROAM -- B/Esc drops back to driving. It MUST be caught
    # BEFORE the generic "select"->menu branch: that branch presses A, which dives INTO World
    # Map and then B+Esc's back out, an infinite in/out oscillation (the 07-05 9h freeze).
    if "exit game" in t or ("world map" in t and ("collection journal" in t or "what's next" in t
                                                  or "horizon decades" in t)):
        return "home"
    if "close map" in t:                          # the full-screen in-game MAP ("Esc Close Map" hint)
        return "map"
    if "restart event" in t and ("quit event" in t or "freeroam" in t):
        return "pause"
    if "season changing" in t or "loading" in t or "please wait" in t:
        return "load"
    if "choose race type" in t:
        return "choose"
    if "start race event" in t:
        return "start"
    if "current car" in t or "my cars" in t:
        return "car"
    if "watch replay" in t or "show gamer" in t or ("continue" in t and "restart" in t) or \
       "final results" in t or "race complete" in t or "you finished" in t or \
       "finish position" in t or "results" in t:
        return "results"
    if "play event" in t or "my events" in t or "my local events" in t or "eventlab" in t:
        return "eventlab"
    if "select" in t:
        return "menu"
    return "other"   # most likely free roam (festival HUD, no menu text)

def racing(get_frame, hwnd=None):
    """True only in a LIVE RACE. race_position is 1..N in a race and 0 in FREE ROAM -- unlike
    is_race_on AND the race clock, which are BOTH 1 in free roam too (so the old speed/lap-HUD
    heuristics either mistook free-roam DRIVING for a race, or false-negatived into the STORE
    nav). race_position is the single reliable race-vs-freeroam signal."""
    a = get_frame()
    if a is None:
        return False
    return int(getattr(a, "race_position", 0)) >= 1

def reset_car(gp, btn, hwnd=None, log=print):
    """Stuck off-track -> open the pause menu and 'Reset Car Position' (X) to put the car
    back on the track, then resume. Clears any disconnect dialog first."""
    if hwnd is None and find_forza_window:
        hwnd = find_forza_window()
    def tap(name, hold=0.12, after=0.8):
        if name in btn:
            gp.press_button(button=btn[name]); gp.update(); time.sleep(hold)
            gp.release_button(button=btn[name]); gp.update()
        time.sleep(after)
    if has_disconnect_dialog(hwnd):
        tap("A", after=0.4); key_enter(); time.sleep(1.0)
    log("[reset] stuck off-track -> pause -> Reset Car Position (X)")
    tap("START", after=1.4)
    t = ocr_text(hwnd)
    if "reset car" in t or "restart event" in t or "quit event" in t:
        tap("X", after=1.8)          # Reset Car Position
        tap("A", after=1.0)          # confirm if prompted; harmless otherwise
        return True
    log("[reset] pause menu not detected (got: %s); backing out" % t[:60])
    key_esc(); time.sleep(0.8)
    return False

def close_map(gp, btn, hwnd=None, log=print, budget=12):
    """An in-game MAP got opened mid-race (a stray VIEW press / ghost input / mis-nav). The game
    pauses, so the car sits still and telemetry can't flag it (race_position can stay >=1, or the
    Data Out stream pauses). Detect by OCR ("Close Map" hint) and close it back to the race along
    the user's path: MAP -> PAUSE MENU -> GAME. Re-OCRs each step so it converges whether the map
    closes via the pause menu or straight to the game."""
    if hwnd is None and find_forza_window:
        hwnd = find_forza_window()
    def tap(name, hold=0.12, after=0.8):
        if name in btn:
            gp.press_button(button=btn[name]); gp.update(); time.sleep(hold)
            gp.release_button(button=btn[name]); gp.update()
        time.sleep(after)
    t0 = time.time()
    while time.time() - t0 < budget:
        t = ocr_text(hwnd)
        if "close map" in t:                          # MAP open -> Esc closes it (per the hint)
            log("[map] map open -> Esc -> pause menu")
            key_esc(); time.sleep(0.9)
            if "close map" in ocr_text(hwnd):         # Esc didn't take -> pad B as a fallback
                tap("B", after=0.9)
        elif "restart event" in t and ("quit event" in t or "freeroam" in t):
            log("[map] pause menu -> B -> resume race")
            tap("B", after=1.0)                       # resume (same as the 'pause' handler)
        else:
            log("[map] map closed -> back in game")
            return True                               # neither map nor pause text -> back in game
    log("[map] close-map budget exhausted")
    return False

def recover_to_racing(gp, btn, get_frame, hwnd=None, log=print, budget=300, post_race=False, line=None):
    """From any non-driving state, get back to a live race. Returns True if racing.
    post_race=True means we JUST finished a race -> press A through the winnings/accolades
    screens to COLLECT the credits before restarting (the whole point of the farm). Without
    it, the first winnings screens read as 'other' and get B+Esc'd away, wasting the race."""
    if hwnd is None and find_forza_window:
        hwnd = find_forza_window()
    def tap(name, hold=0.12, after=0.6):
        if name in btn:
            gp.press_button(button=btn[name]); gp.update(); time.sleep(hold)
            gp.release_button(button=btn[name]); gp.update()
        time.sleep(after)
    t0 = time.time(); other_runs = 0
    if post_race:
        log("[recover] post-race: will A-through to COLLECT winnings before restart")
    while time.time() - t0 < budget:
        # ALWAYS clear the Controller-Disconnected dialog first -- it pops on every vpad
        # reconnect and sits ON TOP of whatever menu, eating all other inputs. Detect by
        # its green box (OCR reads the menu behind it and misses the dialog).
        if has_disconnect_dialog(hwnd):
            log("[recover] Controller-Disconnected dialog -> A + Enter to close")
            tap("A", after=0.4); key_enter(); time.sleep(1.2)
            other_runs = 0
            continue
        if racing(get_frame, hwnd):
            log("[recover] racing confirmed (lap HUD present)")
            return True
        otext = ocr_text(hwnd)
        st = screen_state(otext)
        log(f"[recover] state={st}")
        if st == "disconnect":
            tap("A", after=0.5); key_enter(); time.sleep(0.8); other_runs = 0
        elif st == "pause":
            tap("B", after=1.2); other_runs = 0          # close pause -> resume / drop to free roam
        elif st == "home":
            # top-level campaign/pause overlay -> B drops to free roam, then the free-roam nav
            # below relaunches the event. NEVER press A here (it opens World Map -> oscillation).
            log("[recover] home/campaign overlay -> B to free roam")
            tap("B", after=1.3); key_esc(); time.sleep(0.6); other_runs = 0
        elif st == "map":
            close_map(gp, btn, hwnd, log); other_runs = 0   # accidental full-screen map -> close it
        elif st == "results":
            post_race = True                              # race finished -> COLLECT winnings mode
            tap("A", after=1.4); other_runs = 0           # A advances + collects, toward free roam
        elif st in ("choose", "car", "start", "menu", "eventlab"):
            tap("A", after=1.7); other_runs = 0          # commit a setup/eventlab screen
            if screen_state(ocr_text(hwnd)) == st:       # A didn't move it -> keyboard Enter
                key_enter(); time.sleep(1.6)
        elif st == "load":
            time.sleep(2.0); other_runs = 0              # NEVER press into a load
        else:  # "other" -> possibly FREE ROAM, or a load that didn't match "load".
            # Only open the menu once we are STABLY in the open world: is_race_on=1 AND the
            # car is PLACED (position != 0,0, i.e. the world finished loading) AND no menu
            # text, for several consecutive reads. This stops us pressing START mid-load
            # (which mis-navigates -- the load-into-free-roam after a race isn't instant).
            fr = get_frame()
            in_world = fr is not None and fr.is_race_on == 1 and \
                (abs(fr.pos_x) > 1.0 or abs(fr.pos_z) > 1.0)
            if not in_world:
                other_runs = 0
                if post_race:
                    # POST-RACE reward screens (winnings / accolades / wheelspin). Press A to
                    # COLLECT + advance toward free roam -- the user's flow. NEVER B/Esc here:
                    # that skips the winnings and WASTES the race's credits (the whole point).
                    log("[recover] post-race -> A to collect winnings")
                    tap("A", after=1.3)
                else:
                    # an UNRECOGNIZED menu the relaunch nav wandered into -- back out toward
                    # free roam with B + Esc. (Loads are caught by "load" above.)
                    log("[recover] unrecognized screen (not in world) -> B + Esc to back out")
                    tap("B", after=0.4); key_esc(); time.sleep(1.0)
            else:
                # CRITICAL: the GRID of a freshly-launched race looks identical to free roam
                # here (is_race_on=1, car placed, no menu text) because PRE-GO the race clock
                # isn't advancing yet, so racing() above returned False. A RACE shows the lap
                # HUD ("X/Y Laps" / "Lap" / "Best"); free roam does not. If it's up, the race is
                # STARTING -> WAIT for GO. Do NOT run the free-roam->EventLab nav: in-race START
                # opens the pause/menu, RB tabs into the STORE, and A on the paid bundle opens
                # the Steam purchase overlay (the 50-lap auto-restart bug).
                if any(k in otext for k in ("lap", "best", "/50", "/ 50", "laps")):
                    log("[recover] race HUD up (grid, pre-GO) -> waiting for GO, NOT re-navigating")
                    other_runs = 0; time.sleep(1.5)
                    continue
                # (The old position guard "car near line -> in-race -> don't navigate" was REMOVED:
                # free roam is on the SAME roads as the race line, so it wrongly fired in free roam
                # and the follower just drove the open world. The race-vs-freeroam decision now lives
                # upstream in the caller's AFK trigger via race_position -- recovery is only CALLED
                # when race_position<1, i.e. genuinely not in a race, so navigating here is correct.
                # A mid-race crash keeps race_position>=1, so recovery is never called then.)
                post_race = False                         # reached free roam -> winnings done
                other_runs += 1
                log(f"[recover] free-roam confirm {other_runs}/4")
                if other_runs >= 4:
                    log("[recover] stable free roam -> opening EventLab")
                    time.sleep(1.5)                      # extra settle before touching anything
                    tap("START", after=1.6)
                    for _ in range(4):
                        tap("RB", after=0.5)
                    # HARD GUARD: never A into the STORE -- a paid item opens the Steam overlay.
                    # If the tabs landed on STORE (wrong opening tab / overshoot), back out.
                    if any(k in ocr_text(hwnd) for k in ("buy it now", "premium upgrade",
                                                          "car pass", "car packs", "treasure map")):
                        log("[recover] nav landed on STORE -> aborting (B+Esc), will retry")
                        tap("B", after=0.4); key_esc(); time.sleep(1.0); other_runs = 0
                        continue
                    tap("A", after=1.6)                  # open EventLab
                    tap("Dright", after=0.9)             # Play Event -> My Events
                    tap("A", after=2.0)                  # open My Events
                    tap("A", after=2.0)                  # select blueprint -> Choose Race Type
                    other_runs = 0
                else:
                    time.sleep(1.0)
    log("[recover] budget exhausted without racing")
    return False
