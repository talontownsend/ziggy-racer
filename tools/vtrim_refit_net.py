"""Refit the vtrim net to the CURRENT effective map, so the net carries the map again.

Why this exists. `map = clip(clip(net(features)) + delta, lo, hi)`. The net is supposed to be the
generalising part (features -> multiplier) and `delta` the per-station residual that absorbs
genuinely unique places. `VtrimNet.step()` nudges shared weights on every credit and debit, and
`forward()` is unbounded, so over weeks the net drifts out of the range a multiplier can occupy
and `delta` silently takes over the whole job. Measured 08-02 before this ran: net raw output
-2.864 to +4.856 with 87.6% outside [0.80, 1.55], `|delta|` mean 0.397 with 28.5% of stations
pinned at the delta bound. At that point the net contributes nothing and a port to a new track
starts from noise.

What this does NOT do: it does not retrain from `vtrim_features.npz`'s stored labels the way
`python vtrim_net.py` does. Those labels are the 07-03 converged map, so that path silently
discards everything learned since. This fits the net to whatever the map is RIGHT NOW, then sets
`delta = current_map - clip(net(X))`, so the effective map is reproduced exactly and the deployed
behaviour is unchanged on the first tick. Only the learning dynamics change.

Behaviour-neutrality is enforced, not assumed: nothing is written unless the reconstruction is
exact and every delta fits inside the bound.

    python tools/vtrim_refit_net.py            # report only
    python tools/vtrim_refit_net.py --write    # stage + deploy (snapshots the old pair first)

Requires a follower restart to take effect: `delta` is read at startup.
"""
import os
import sys
import argparse
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from vtrim_net import VtrimNet

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REC = os.path.join(ROOT, "recordings")
SNAP = os.path.join(REC, "snapshots")
LO, HI = 0.80, 1.55
DMAX = HI - LO


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="deploy (snapshots the old pair first)")
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--epochs", type=int, default=4000)
    ap.add_argument("--tag", default="preREFIT", help="snapshot suffix when writing")
    a = ap.parse_args()

    with np.load(os.path.join(REC, "vtrim_features.npz")) as f:
        X, mu, sd = f["X"], f["mu"], f["sd"]
    Xn = (X - mu) / sd
    cur = np.load(os.path.join(REC, "vtrim_map.npz"))["map"].astype(float)
    old_delta = np.load(os.path.join(REC, "vtrim_delta.npz"))["delta"].astype(float)
    old_raw = VtrimNet.load(os.path.join(REC, "vtrim_net.npz")).forward(Xn)

    print(f"BEFORE  net raw : mean {old_raw.mean():+.3f}  min {old_raw.min():+.3f}  "
          f"max {old_raw.max():+.3f}  | {np.mean((old_raw < LO) | (old_raw > HI)) * 100:.1f}% out of range")
    print(f"        |delta| : mean {np.abs(old_delta).mean():.4f}  "
          f"at-bound {np.mean(np.abs(old_delta) >= DMAX - 1e-4) * 100:.1f}%")

    best = None
    for seed in range(1, a.seeds + 1):
        net = VtrimNet(X.shape[1], seed=seed)
        net.pretrain(Xn, cur, np.ones(len(cur)), np.zeros(len(cur), dtype=bool),
                     epochs=a.epochs, lr=3e-3)
        d = cur - np.clip(net.forward(Xn), LO, HI)
        s = float(np.abs(d).mean())
        print(f"  seed {seed}: |delta| mean {s:.4f}  max {np.abs(d).max():.4f}")
        if best is None or s < best[0]:
            best = (s, net, d)

    _, net, d = best
    raw = net.forward(Xn)
    recon = np.clip(np.clip(raw, LO, HI) + np.clip(d, -DMAX, DMAX), LO, HI)
    err = float(np.abs(recon - cur).max())
    print(f"\nAFTER   net raw : mean {raw.mean():+.3f}  min {raw.min():+.3f}  max {raw.max():+.3f}")
    print(f"        |delta| : mean {np.abs(d).mean():.4f}  max {np.abs(d).max():.4f}  "
          f"at-bound {np.mean(np.abs(d) >= DMAX - 1e-4) * 100:.1f}%")
    print(f"        exact map reproduction: max err {err:.8f}")

    if err > 1e-6 or np.abs(d).max() > DMAX + 1e-6:
        print("\nREFUSING to write: the refit does not reproduce the current map exactly, so it "
              "would be a silent behaviour change. Try more seeds or epochs.")
        return 1
    if not a.write:
        print("\nreport only; pass --write to deploy")
        return 0

    os.makedirs(SNAP, exist_ok=True)
    for n in ("vtrim_net.npz", "vtrim_delta.npz", "vtrim_map.npz"):
        shutil.copy(os.path.join(REC, n), os.path.join(SNAP, n.replace(".npz", f"_{a.tag}.npz")))
    np.savez(os.path.join(REC, "vtrim_net.npz"), W1=net.W1, b1=net.b1, W2=net.W2, b2=net.b2)
    np.savez(os.path.join(REC, "vtrim_delta.npz"), delta=np.clip(d, -DMAX, DMAX))
    print(f"\ndeployed; previous pair snapshotted as *_{a.tag}.npz")
    print("RESTART THE FOLLOWER: delta is read at startup.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
