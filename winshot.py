"""winshot.py — screenshot the Forza window's client area (no focus change).

Reused by the restart recorder (reference frames) and the replay engine (live
menu-state verification). PIL ImageGrab of the window rect -- "screenshots taken
by the script", which the user sanctioned; NOT computer-use control.
"""
import ctypes, os
from ctypes import wintypes

user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_GAME_EXE = "forzahorizon6.exe"

def _window_exe(hwnd) -> str:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = _kernel32.OpenProcess(0x1000, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024); size = wintypes.DWORD(1024)
        if _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        _kernel32.CloseHandle(h)

def find_forza_window():
    found = []
    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(h, _):
        if user32.IsWindowVisible(h) and _window_exe(h) == _GAME_EXE:
            found.append(h)
        return True
    user32.EnumWindows(_cb, 0)
    if found:
        return found[0]
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

def grab_window(hwnd=None):
    """Return a PIL Image of Forza's client area, or None if the window is gone."""
    from PIL import ImageGrab
    if hwnd is None:
        hwnd = find_forza_window()
    if not hwnd:
        return None
    r = wintypes.RECT(); user32.GetClientRect(hwnd, ctypes.byref(r))
    p = wintypes.POINT(0, 0); user32.ClientToScreen(hwnd, ctypes.byref(p))
    if r.right <= 0 or r.bottom <= 0:
        return None
    return ImageGrab.grab(bbox=(p.x, p.y, p.x + r.right, p.y + r.bottom), all_screens=True)

if __name__ == "__main__":
    img = grab_window()
    print(f"Forza window: {'found' if img else 'NOT found'}" + (f", size {img.size}" if img else ""))
    if img:
        out = r"C:\Users\talon\FH6-AFK-Farm\recordings\winshot_test.jpg"
        img.convert("RGB").save(out, quality=70)
        print(f"saved {out}")
