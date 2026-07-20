#!/usr/bin/env python3
"""BC training v2 (07-13): lap-level held-out split + lock-upweighted loss.

Fixes vs train_bc.py (v1): (1) held-out LAPS, not random frames (adjacent 71-103Hz frames leak);
(2) full-lock frames (|steer|>=0.99) upweighted so MSE cannot buy loss by softening the human's
commitment (the v1 net emitted ~0.5 where the human held 1.0 -- the S6/S7 signature the whole
deployment targets); (3) saves bc_policy_v2fast.npz (never overwrites bc_policy.npz -- the live
follower hot-reloads that file on mtime; copy at arm time only).
Acceptance gates printed at the end (blueprint): >=60% of held-out human-lock frames predicted at
|s|>=0.9; 100% sign agreement on |s|>=0.5; held-out steer MAE <= ~0.20.
"""
import numpy as np, torch, torch.nn as nn
DIR = r"C:\Users\talon\FH6-AFK-Farm\recordings"
d = np.load(DIR + r"\bc_dataset_v2fast.npz", allow_pickle=True)
X, Y, W, LAP, mean, std = d["X"], d["Y"], d["W"], d["lap_id"], d["mean"], d["std"]
feat = list(d["feat_names"])
dev = "cuda" if torch.cuda.is_available() else "cpu"
laps = np.unique(LAP)
print(f"device {dev} | X{X.shape} | {len(laps)} laps")

# lap-level split: hold out every 6th lap (deterministic, spreads across both recordings)
va_laps = set(laps[::6].tolist())
va_m = np.isin(LAP, list(va_laps)); tr_m = ~va_m
print(f"held-out laps: {sorted(va_laps)} ({va_m.sum()} frames) | train {tr_m.sum()} frames")

# lock-upweight: the whole point is reproducing commitment
W2 = W * (1.0 + 4.0 * (np.abs(Y[:, 0]) >= 0.99))

Xn = (X - mean) / std
def T(a): return torch.tensor(a, dtype=torch.float32, device=dev)
Xtr, Ytr, Wtr = T(Xn[tr_m]), T(Y[tr_m]), T(W2[tr_m])
Xva, Yva, Wva = T(Xn[va_m]), T(Y[va_m]), T(W2[va_m])

class Policy(nn.Module):
    def __init__(self, nin, h=256):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(nin, h), nn.ReLU(), nn.Dropout(0.1),
                                 nn.Linear(h, h), nn.ReLU(), nn.Dropout(0.1),
                                 nn.Linear(h, 3))
    def forward(self, x):
        o = self.net(x)
        return torch.cat([torch.tanh(o[:, :1]), torch.sigmoid(o[:, 1:])], 1)

net = Policy(X.shape[1]).to(dev)
opt = torch.optim.Adam(net.parameters(), lr=1e-3, weight_decay=1e-4)
def wmse(p, y, w): return (w[:, None] * (p - y) ** 2).mean()

best, best_state = 1e9, None
for ep in range(1500):
    net.train(); opt.zero_grad()
    loss = wmse(net(Xtr), Ytr, Wtr)
    loss.backward(); opt.step()
    if ep % 50 == 0 or ep == 1499:
        net.eval()
        with torch.no_grad():
            vl = wmse(net(Xva), Yva, Wva).item()
        if vl < best: best, best_state = vl, {k: v.cpu().clone() for k, v in net.state_dict().items()}
        print(f"ep {ep:4d}  train {loss.item():.4f}  val {vl:.4f}")

net.load_state_dict(best_state); net.eval()
with torch.no_grad():
    pv = net(T(Xn[va_m])).cpu().numpy()
yv = Y[va_m]
mae = np.abs(pv - yv).mean(0)
lock = np.abs(yv[:, 0]) >= 0.99
sat = np.mean(np.abs(pv[lock, 0]) >= 0.9) if lock.any() else float("nan")
com = np.abs(yv[:, 0]) >= 0.5
sign = np.mean(np.sign(pv[com, 0]) == np.sign(yv[com, 0])) if com.any() else float("nan")
print(f"\nbest val wMSE {best:.4f} | HELD-OUT-LAP steer MAE {mae[0]:.3f} thr {mae[1]:.3f} brk {mae[2]:.3f}")
print(f"ACCEPTANCE: lock-saturation {100*sat:.1f}% (gate >=60) | sign-agree {100*sign:.1f}% (gate 100) | steer MAE {mae[0]:.3f} (gate <=0.20)")

sd = net.state_dict()
layers = [(sd["net.0.weight"].cpu().numpy(), sd["net.0.bias"].cpu().numpy()),
          (sd["net.3.weight"].cpu().numpy(), sd["net.3.bias"].cpu().numpy()),
          (sd["net.6.weight"].cpu().numpy(), sd["net.6.bias"].cpu().numpy())]
np.savez(DIR + r"\bc_policy_v2fast.npz",
         W0=layers[0][0], b0=layers[0][1], W1=layers[1][0], b1=layers[1][1], W2=layers[2][0], b2=layers[2][1],
         mean=mean, std=std, feat_names=np.array(feat))
print("saved bc_policy_v2fast.npz (NOT copied to bc_policy.npz; copy only at arm time)")
