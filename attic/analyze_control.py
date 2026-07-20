import numpy as np, csv, sys
sys.path.insert(0, r"C:/Users/talon/FH6-AFK-Farm")
from racing_line import menger_curvature

PLAN = r"C:/Users/talon/FH6-AFK-Farm/recordings/session_20260621_093038_plan.npz"
LOG  = r"C:/Users/talon/FH6-AFK-Farm/recordings/follow_log.csv"

plan = np.load(PLAN)
line = plan["line"]; speed = plan["speed"]
N = len(line)
kappa = menger_curvature(line)          # 1/radius_m per station
radius = np.where(kappa > 1e-9, 1.0/kappa, 1e9)

# load log
rows = []
with open(LOG) as f:
    r = csv.DictReader(f)
    for d in r:
        rows.append(d)
def col(name, typ=float):
    return np.array([typ(d[name]) for d in rows])

t      = col("t")
i0     = col("i0", int)
spd    = col("spd_kmh")
alpha  = col("alpha_deg")
cte    = col("cte_m")
steer  = col("steer")
thr    = col("thr"); brk = col("brk")

# skip first 15 s of steady state, relative to first timestamp
t0 = t[0]
mask_time = (t - t0) >= 15.0
print(f"total samples={len(t)}, after 15s skip={mask_time.sum()}, t range {t[0]:.1f}..{t[-1]:.1f}")

# plan radius at each sample's i0
samp_radius = radius[np.clip(i0, 0, N-1)]
samp_kappa  = kappa[np.clip(i0, 0, N-1)]

STRAIGHT = mask_time & (samp_radius > 200.0)
CORNER   = mask_time & (samp_radius < 80.0)
print(f"STRAIGHT samples={STRAIGHT.sum()}, CORNER samples={CORNER.sum()}")

def signflips_per100(x):
    s = np.sign(x); s = s[s != 0]
    if len(s) < 2: return 0.0
    flips = np.sum(s[1:] != s[:-1])
    return 100.0 * flips / len(s)

spd_mps = spd / 3.6

# ---------------- STRAIGHTS ----------------
st = STRAIGHT
print("\n===== STRAIGHTS (radius>200m) =====")
print(f"n={st.sum()}")
print(f"steer mean={steer[st].mean():+.4f}  std={steer[st].std():.4f}")
print(f"cte mean(signed)={cte[st].mean():+.3f}  |cte| mean={np.abs(cte[st]).mean():.3f}  cte std={cte[st].std():.3f}")
print(f"steer sign-flips/100={signflips_per100(steer[st]):.1f}")
print(f"cte sign-flips/100={signflips_per100(cte[st]):.1f}")
print(f"alpha mean={alpha[st].mean():+.2f} deg std={alpha[st].std():.2f}")
# autocorr of steer lag1 to gauge oscillation
ssz = steer[st] - steer[st].mean()
ac1 = np.sum(ssz[1:]*ssz[:-1])/np.sum(ssz*ssz)
print(f"steer lag-1 autocorr={ac1:.3f}")

# ---------------- CORNERS ----------------
co = CORNER
print("\n===== CORNERS (radius<80m) =====")
print(f"n={co.sum()}")
print(f"signed cte mean={cte[co].mean():+.3f}  |cte| mean={np.abs(cte[co]).mean():.3f}  cte std={cte[co].std():.3f}")
print(f"frac cte<0 (LEFT/outside/wide)={np.mean(cte[co]<0):.3f}")
print(f"frac cte>0 (RIGHT/inside)={np.mean(cte[co]>0):.3f}")
print(f"steer mean={steer[co].mean():+.4f} std={steer[co].std():.4f}")
print(f"frac |steer|>0.9 (saturation)={np.mean(np.abs(steer[co])>0.9):.3f}")
print(f"frac steer<-0.9 (full right, STEER_SIGN=-1)={np.mean(steer[co]<-0.9):.3f}")
print(f"corner speed mean={spd[co].mean():.1f} km/h ({spd_mps[co].mean():.1f} m/s)")
Ld = np.clip(4.0 + 0.2*spd_mps, 4.0, 40.0)
print(f"Ld at corner mean={Ld[co].mean():.2f} m  (range {Ld[co].min():.1f}..{Ld[co].max():.1f})")
print(f"corner plan radius mean={samp_radius[co].mean():.1f} m  median={np.median(samp_radius[co]):.1f}")
print(f"Ld / radius ratio mean={(Ld[co]/samp_radius[co]).mean():.3f}")
print(f"alpha mean={alpha[co].mean():+.2f} deg std={alpha[co].std():.2f}")

# ---------------- correlations ----------------
print("\n===== CORRELATIONS (steady-state, all post-15s) =====")
ss = mask_time
def corr(a,b):
    a=a-a.mean(); b=b-b.mean()
    d=np.sqrt(np.sum(a*a)*np.sum(b*b))
    return np.sum(a*b)/d if d>0 else 0.0
print(f"corr(steer,cte) all   ={corr(steer[ss],cte[ss]):+.3f}")
print(f"corr(steer,alpha) all ={corr(steer[ss],alpha[ss]):+.3f}")
print(f"corr(steer,cte) straight ={corr(steer[st],cte[st]):+.3f}")
print(f"corr(steer,alpha) straight={corr(steer[st],alpha[st]):+.3f}")
print(f"corr(steer,cte) corner   ={corr(steer[co],cte[co]):+.3f}")
print(f"corr(steer,alpha) corner ={corr(steer[co],alpha[co]):+.3f}")

# decompose steer into pursuit vs cross-track term using known gains
# steer = STEER_SIGN*(steer_gain*alpha_rad + atan2(kc*cte, spd_mps+3))
STEER_SIGN=-1; steer_gain=1.2; kc=2.8
alpha_rad = np.deg2rad(alpha)
pursuit  = STEER_SIGN*steer_gain*alpha_rad
crosstrk = STEER_SIGN*np.arctan2(kc*cte, spd_mps+3.0)
print("\n--- term magnitudes (pre-clip) ---")
for nm,msk in [("straight",st),("corner",co)]:
    p=pursuit[msk]; c=crosstrk[msk]
    print(f"{nm}: |pursuit| mean={np.abs(p).mean():.4f}  |crosstrack| mean={np.abs(c).mean():.4f}  "
          f"pursuit mean={p.mean():+.4f} crosstrack mean={c.mean():+.4f}")
