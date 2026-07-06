"""press_enter.py — clear FH6's "Controller Disconnected" dialog programmatically.

That dialog is dismissed by the keyboard ENTER key (its prompt literally shows
"Enter  Ok") — a virtual-pad A press does NOT clear it. When we kill + relaunch
the follower, the virtual pad drops for a moment and Forza pops this dialog and
pauses. This script finds the Forza window, brings it to the foreground, and
sends Enter via SendInput so the race resumes without a human keypress.

Input injection only (same category as the vgamepad the follower already uses) —
no screen reading, no computer-use.

Usage:  python press_enter.py            # one Enter
        python press_enter.py 3          # three Enters, 0.4s apart
"""
import ctypes, sys, time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

# ---- find the Forza top-level window by process name --------------------------
def _forza_pids():
    import subprocess
    pids = set()
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq ForzaHorizon6.exe", "/FO", "CSV", "/NH"],
            text=True, stderr=subprocess.DEVNULL)
        for line in out.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2 and parts[1].isdigit():
                pids.add(int(parts[1]))
    except Exception:
        pass
    return pids

def find_forza_hwnd():
    target = _forza_pids()
    found = []
    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in target:
            found.append(hwnd)
            return False
        # fall back to title match
        n = user32.GetWindowTextLengthW(hwnd)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if "forza" in buf.value.lower():
                found.append(hwnd)
                return False
        return True
    user32.EnumWindows(_cb, 0)
    return found[0] if found else None

# ---- foreground (with the AttachThreadInput trick to beat the fg lock) ---------
def force_foreground(hwnd):
    fg = user32.GetForegroundWindow()
    cur_t = user32.GetWindowThreadProcessId(fg, None)
    tgt_t = user32.GetWindowThreadProcessId(hwnd, None)
    user32.AttachThreadInput(cur_t, tgt_t, True)
    user32.ShowWindow(hwnd, 9)        # SW_RESTORE
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    user32.AttachThreadInput(cur_t, tgt_t, False)

# ---- SendInput ENTER ----------------------------------------------------------
VK_RETURN = 0x0D
KEYEVENTF_KEYUP = 0x0002

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]
class _IN(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]
class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _IN)]
INPUT_KEYBOARD = 1

def _send(vk, up):
    flags = KEYEVENTF_KEYUP if up else 0
    inp = INPUT(type=INPUT_KEYBOARD, u=_IN(ki=KEYBDINPUT(vk, 0, flags, 0, None)))
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

def press_enter():
    _send(VK_RETURN, False); time.sleep(0.05); _send(VK_RETURN, True)

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    hwnd = find_forza_hwnd()
    if not hwnd:
        print("Forza window not found"); sys.exit(1)
    force_foreground(hwnd)
    time.sleep(0.25)
    for i in range(n):
        press_enter()
        print(f"sent Enter {i+1}/{n}", flush=True)
        time.sleep(0.4)
