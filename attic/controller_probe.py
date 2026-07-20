"""controller_probe.py — find which API can see the user's controller.

Polls XInput (slots 0-3) AND the legacy winmm joystick API (ids 0-15) and prints
any device that responds + live button/axis changes. Run ~10s while the user
wiggles sticks and presses buttons.
"""
import ctypes, time
from ctypes import wintypes

# ---- XInput ----
xi = None
for d in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
    try: xi = ctypes.WinDLL(d); break
    except OSError: pass
class GP(ctypes.Structure):
    _fields_ = [("b", wintypes.WORD), ("lt", ctypes.c_ubyte), ("rt", ctypes.c_ubyte),
                ("lx", ctypes.c_short), ("ly", ctypes.c_short), ("rx", ctypes.c_short), ("ry", ctypes.c_short)]
class XS(ctypes.Structure):
    _fields_ = [("pkt", wintypes.DWORD), ("gp", GP)]
def xinput(i):
    s = XS()
    return s.gp if (xi and xi.XInputGetState(i, ctypes.byref(s)) == 0) else None

# ---- legacy winmm joystick (catches DirectInput pads) ----
winmm = ctypes.WinDLL("winmm")
class JOYINFOEX(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("X", wintypes.DWORD), ("Y", wintypes.DWORD), ("Z", wintypes.DWORD),
                ("R", wintypes.DWORD), ("U", wintypes.DWORD), ("V", wintypes.DWORD),
                ("btns", wintypes.DWORD), ("btnNo", wintypes.DWORD), ("pov", wintypes.DWORD),
                ("r1", wintypes.DWORD), ("r2", wintypes.DWORD)]
JOY_RETURNALL = 0x000000ff
def joy(i):
    info = JOYINFOEX(); info.dwSize = ctypes.sizeof(JOYINFOEX); info.dwFlags = JOY_RETURNALL
    return info if winmm.joyGetPosEx(i, ctypes.byref(info)) == 0 else None

ndev = winmm.joyGetNumDevs()
print(f"XInput DLL: {'loaded' if xi else 'MISSING'} | winmm joyGetNumDevs={ndev}")
print("Wiggle the sticks and press A/B/D-pad now...\n", flush=True)

xseen = set(); jseen = set()
xprev = {}; jprev = {}
t0 = time.time()
while time.time() - t0 < 20:
    for i in range(4):
        g = xinput(i)
        if g is not None:
            if i not in xseen:
                xseen.add(i); print(f"  [XInput slot {i}] CONNECTED", flush=True)
            sig = (g.b, g.lt, g.rt, g.lx // 4000, g.ly // 4000)
            if xprev.get(i) != sig:
                xprev[i] = sig
                print(f"  [XInput {i}] btn={g.b:#06x} LT={g.lt} RT={g.rt} LX={g.lx} LY={g.ly}", flush=True)
    for i in range(min(ndev, 16)):
        j = joy(i)
        if j is not None:
            if i not in jseen:
                jseen.add(i); print(f"  [winmm joy {i}] CONNECTED", flush=True)
            sig = (j.btns, j.X // 4000, j.Y // 4000, j.pov)
            if jprev.get(i) != sig:
                jprev[i] = sig
                print(f"  [winmm joy {i}] btns={j.btns:#06x} X={j.X} Y={j.Y} POV={j.pov}", flush=True)
    time.sleep(0.02)

print(f"\nRESULT: XInput slots seen={sorted(xseen) or 'NONE'} | winmm joys seen={sorted(jseen) or 'NONE'}")
