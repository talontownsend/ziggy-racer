"""map_buttons.py — clean winmm button/POV mapping (ignores sticks).

Press ONE control at a time with ~2s gaps, hands OFF the sticks. Logs each
button-bit DOWN and each POV (D-pad) direction so we can map raw winmm bits to
logical Xbox buttons for capture+replay.
"""
import ctypes, time
from ctypes import wintypes
winmm = ctypes.WinDLL("winmm")
class JOYINFOEX(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("X", wintypes.DWORD), ("Y", wintypes.DWORD), ("Z", wintypes.DWORD),
                ("R", wintypes.DWORD), ("U", wintypes.DWORD), ("V", wintypes.DWORD),
                ("btns", wintypes.DWORD), ("btnNo", wintypes.DWORD), ("pov", wintypes.DWORD),
                ("r1", wintypes.DWORD), ("r2", wintypes.DWORD)]
JOY_RETURNALL = 0x000000ff
def joy(i=0):
    info = JOYINFOEX(); info.dwSize = ctypes.sizeof(JOYINFOEX); info.dwFlags = JOY_RETURNALL
    return info if winmm.joyGetPosEx(i, ctypes.byref(info)) == 0 else None
POVN = {0: "UP", 9000: "RIGHT", 18000: "DOWN", 27000: "LEFT", 4500: "UP-RIGHT",
        13500: "DOWN-RIGHT", 22500: "DOWN-LEFT", 31500: "UP-LEFT"}
print("MAP: press one control at a time, hands off sticks. Order suggestion:")
print("  A, B, X, Y, LB, RB, LT, RT, then D-pad UP/RIGHT/DOWN/LEFT, then Start, Back\n", flush=True)
prevb = 0; prevp = 65535; t0 = time.time()
while time.time() - t0 < 32:
    j = joy(0)
    if j is None:
        time.sleep(0.05); continue
    if j.btns != prevb:
        new = j.btns & ~prevb
        for bit in range(16):
            if new & (1 << bit):
                print(f"  [{time.time()-t0:5.1f}s] BUTTON bit{bit} (0x{1<<bit:04x})  rawbtns=0x{j.btns:04x}", flush=True)
        prevb = j.btns
    if j.pov != prevp:
        if j.pov in POVN:
            print(f"  [{time.time()-t0:5.1f}s] DPAD {POVN[j.pov]} (pov={j.pov})", flush=True)
        prevp = j.pov
    time.sleep(0.01)
print("\nmapping window closed.", flush=True)
