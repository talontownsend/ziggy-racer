"""Tiny feature->cap-multiplier net for the generalizing vtrim (user 07-03).
Single hidden layer (nf -> 16 -> 1), numpy only. Deployed as
    map(s) = clip(net(features(s)) + delta(s), lo, hi)
where delta is the per-station residual table (absorbs genuinely unique places --
LOSO showed held-out S6 predicted 2.03 vs true 1.03: one track has too few corner
archetypes for features alone). Online learning uses step(): a NORMALIZED gradient
step that moves the output at given feature points by exactly `amount`, so the
same credit/debit/incident increments as the table apply, scaled down.
"""
import numpy as np


class VtrimNet:
    def __init__(self, nf, h=16, seed=7):
        rng = np.random.default_rng(seed)
        self.W1 = rng.normal(0, 0.25, (nf, h)); self.b1 = np.zeros(h)
        self.W2 = rng.normal(0, 0.25, (h, 1)); self.b2 = np.zeros(1)

    def forward(self, X):
        return (np.tanh(X @ self.W1 + self.b1) @ self.W2 + self.b2).ravel() + 1.0

    def step(self, X, amount):
        # move mean output over rows of X by `amount` (signed), exactly
        a1 = np.tanh(X @ self.W1 + self.b1)
        gW2 = a1.mean(0)[:, None]; gb2 = np.ones(1)
        d1 = (np.ones((len(X), 1)) @ self.W2.T) * (1 - a1 ** 2) / len(X)
        gW1 = X.T @ d1; gb1 = d1.sum(0)
        n2 = (gW1 ** 2).sum() + (gb1 ** 2).sum() + (gW2 ** 2).sum() + (gb2 ** 2).sum()
        lr = amount / max(n2, 1e-9)
        self.W1 += lr * gW1; self.b1 += lr * gb1
        self.W2 += lr * gW2; self.b2 += lr * gb2

    def save(self, path):
        tmp = path + ".tmp.npz"
        np.savez(tmp, W1=self.W1, b1=self.b1, W2=self.W2, b2=self.b2)
        import os
        os.replace(tmp, path)

    @classmethod
    def load(cls, path):
        with np.load(path) as d:
            net = cls(d["W1"].shape[0], d["W1"].shape[1])
            net.W1 = d["W1"].copy(); net.b1 = d["b1"].copy()
            net.W2 = d["W2"].copy(); net.b2 = d["b2"].copy()
        return net

    def pretrain(self, X, y, w, censored, epochs=4000, lr=3e-3, seed=1):
        params = [self.W1, self.b1, self.W2, self.b2]
        mth = [np.zeros_like(p) for p in params]
        vth = [np.zeros_like(p) for p in params]
        be1, be2 = 0.9, 0.999
        for ep in range(1, epochs + 1):
            a1 = np.tanh(X @ self.W1 + self.b1)
            pred = (a1 @ self.W2 + self.b2).ravel() + 1.0
            err = pred - y
            err = np.where(censored & (err > 0), 0.0, err)   # hinge above the bound
            g = 2.0 * err * w / max(w.sum(), 1e-9)
            gW2 = a1.T @ g[:, None]; gb2 = np.array([g.sum()])
            d1 = (g[:, None] @ self.W2.T) * (1 - a1 ** 2)
            gW1 = X.T @ d1; gb1 = d1.sum(0)
            grads = [gW1, gb1, gW2, gb2]
            for k in range(4):
                grads[k] = grads[k] + 1e-4 * params[k]
                mth[k] = be1 * mth[k] + (1 - be1) * grads[k]
                vth[k] = be2 * vth[k] + (1 - be2) * grads[k] ** 2
                params[k] -= lr * (mth[k] / (1 - be1 ** ep)) / (np.sqrt(vth[k] / (1 - be2 ** ep)) + 1e-8)
        self.W1, self.b1, self.W2, self.b2 = params
        a1 = np.tanh(X @ self.W1 + self.b1)
        pred = (a1 @ self.W2 + self.b2).ravel() + 1.0
        e = np.abs(np.where(censored & (pred > y), 0.0, pred - y))
        return float(np.average(e, weights=w))


if __name__ == "__main__":
    REC = r"C:\Users\talon\FH6-AFK-Farm\recordings"
    F = np.load(REC + r"\vtrim_features.npz")
    X, mu, sd = F["X"], F["mu"], F["sd"]
    Xn = (X - mu) / sd
    y, w, cens = F["label"], F["weight"], F["censored"]
    inf = w > 0.1
    net = VtrimNet(X.shape[1])
    mae = net.pretrain(Xn[inf], y[inf], w[inf], cens[inf])
    pred = np.clip(net.forward(Xn), 0.80, 1.55)
    delta = np.zeros(len(y))
    delta[inf] = y[inf] - pred[inf]          # exact behavior match at informative stations
    net.save(REC + r"\vtrim_net.npz")
    np.savez(REC + r"\vtrim_delta.npz", delta=delta)
    print(f"pretrain wMAE {mae:.3f}; net+delta == converged map at {inf.sum()} informative stations")
    print(f"net-alone range: {pred.min():.2f} - {pred.max():.2f}; |delta| p90 {np.percentile(np.abs(delta[inf]), 90):.3f}")
