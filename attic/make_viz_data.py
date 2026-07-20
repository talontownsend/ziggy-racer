"""Emit compact JSON (corridor walls + speed-colored racing line) for the widget."""
import json
import numpy as np

d = np.load(r"C:\Users\talon\FH6-AFK-Farm\recordings\session_20260621_093038_plan.npz")
left, right, line, speed = d["left"], d["right"], d["line"], d["speed"] * 3.6
ox, oy = float(line[:, 0].min()), float(line[:, 1].min())


def pts(a, step=3):
    return [[round(float(p[0]) - ox, 1), round(float(p[1]) - oy, 1)] for p in a[::step]]


L = line[::3]
S = speed[::3]
out = {
    "line": [[round(float(p[0]) - ox, 1), round(float(p[1]) - oy, 1), round(float(s))]
             for p, s in zip(L, S)],
    "left": pts(left), "right": pts(right),
    "vmax": round(float(speed.max())), "vmin": round(float(speed.min())),
}
print(json.dumps(out))
