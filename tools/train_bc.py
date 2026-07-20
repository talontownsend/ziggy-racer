#!/usr/bin/env python3
"""Behavioral cloning of the human's control from (car state + track-boundary preview), on the GPU.

Learns steer/throttle/brake = f(state, preview) by weighted regression to the human's recorded
control, weighted toward the fastest laps. The boundary preview gives the net ANTICIPATION (it
sees the track shape ahead) -- the thing the reactive base controller lacks. Saves a numpy export
(bc_policy.npz) so the follower can run it with a tiny dependency-free forward pass.
"""
import numpy as np, torch, torch.nn as nn
DIR = r"C:\Users\talon\FH6-AFK-Farm\recordings"
d = np.load(DIR + r"\bc_dataset.npz", allow_pickle=True)
X, Y, W, mean, std = d["X"], d["Y"], d["W"], d["mean"], d["std"]
feat = list(d["feat_names"])
dev = "cuda" if torch.cuda.is_available() else "cpu"
print(f"device {dev} | X{X.shape} Y{Y.shape} | {len(feat)} features")

Xn = (X - mean) / std
g = torch.Generator().manual_seed(0)
idx = torch.randperm(len(X), generator=g).numpy()
ntr = int(0.9 * len(X)); tr, va = idx[:ntr], idx[ntr:]
def T(a): return torch.tensor(a, dtype=torch.float32, device=dev)
Xtr, Ytr, Wtr = T(Xn[tr]), T(Y[tr]), T(W[tr])
Xva, Yva, Wva = T(Xn[va]), T(Y[va]), T(W[va])

class Policy(nn.Module):
    def __init__(self, nin, h=256):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(nin, h), nn.ReLU(), nn.Dropout(0.1),
                                 nn.Linear(h, h), nn.ReLU(), nn.Dropout(0.1),
                                 nn.Linear(h, 3))
    def forward(self, x):
        o = self.net(x)
        return torch.cat([torch.tanh(o[:, :1]), torch.sigmoid(o[:, 1:])], 1)  # steer[-1,1], thr/brk[0,1]

net = Policy(X.shape[1]).to(dev)
opt = torch.optim.Adam(net.parameters(), lr=1e-3, weight_decay=1e-4)
def wmse(p, y, w): return (w[:, None] * (p - y) ** 2).mean()

best, best_state = 1e9, None
for ep in range(600):
    net.train(); opt.zero_grad()
    perm = torch.randperm(len(Xtr), device=dev)
    loss = wmse(net(Xtr[perm]), Ytr[perm], Wtr[perm])
    loss.backward(); opt.step()
    if ep % 50 == 0 or ep == 599:
        net.eval()
        with torch.no_grad():
            vl = wmse(net(Xva), Yva, Wva).item()
        if vl < best: best, best_state = vl, {k: v.cpu().clone() for k, v in net.state_dict().items()}
        print(f"ep {ep:3d}  train {loss.item():.4f}  val {vl:.4f}")

net.load_state_dict(best_state); net.eval()
# per-channel val MAE (in control units) for interpretability
with torch.no_grad():
    pv = net(Xva).cpu().numpy()
mae = np.abs(pv - Y[va]).mean(0)
print(f"\nbest val wMSE {best:.4f} | val MAE  steer {mae[0]:.3f}  thr {mae[1]:.3f}  brk {mae[2]:.3f}  (0..1 / -1..1 scale)")

# export to numpy for the follower (dependency-free forward): linear weights + norm
sd = net.state_dict()
layers = [(sd["net.0.weight"].cpu().numpy(), sd["net.0.bias"].cpu().numpy()),
          (sd["net.3.weight"].cpu().numpy(), sd["net.3.bias"].cpu().numpy()),
          (sd["net.6.weight"].cpu().numpy(), sd["net.6.bias"].cpu().numpy())]
np.savez(DIR + r"\bc_policy.npz",
         W0=layers[0][0], b0=layers[0][1], W1=layers[1][0], b1=layers[1][1], W2=layers[2][0], b2=layers[2][1],
         mean=mean, std=std, feat_names=np.array(feat))
print(f"saved bc_policy.npz  (numpy forward: ReLU,ReLU,then tanh/sigmoid; {X.shape[1]} in -> 3 out)")
