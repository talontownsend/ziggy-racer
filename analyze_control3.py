import numpy as np, csv, sys
sys.path.insert(0, r"C:/Users/talon/FH6-AFK-Farm")
from racing_line import menger_curvature
plan=np.load(r"C:/Users/talon/FH6-AFK-Farm/recordings/session_20260621_093038_plan.npz")
line=plan["line"];N=len(line);kappa=menger_curvature(line);radius=np.where(kappa>1e-9,1/kappa,1e9)
rows=list(csv.DictReader(open(r"C:/Users/talon/FH6-AFK-Farm/recordings/follow_log.csv")))
g=lambda n,tp=float:np.array([tp(d[n]) for d in rows])
t=g("t");i0=g("i0",int);spd=g("spd_kmh");alpha=g("alpha_deg");cte=g("cte_m");steer=g("steer");head=g("head_deg")
spd_mps=spd/3.6
# dedupe identical timestamps for gradient
tt=t.copy()
for k in range(1,len(tt)):
    if tt[k]<=tt[k-1]: tt[k]=tt[k-1]+1e-4
mask=(t-t[0])>=15.0
sr=radius[np.clip(i0,0,N-1)];pk=kappa[np.clip(i0,0,N-1)]
ST=mask&(sr>200);CO=mask&(sr<80)
hu=np.unwrap(np.deg2rad(head));dpsi=np.gradient(hu,tt)
ak=np.abs(dpsi)/np.maximum(spd_mps,2.0)
# smooth achieved kappa a bit (5-sample median)
def medfilt(x,w=5):
    out=x.copy();h=w//2
    for k in range(h,len(x)-h):out[k]=np.median(x[k-h:k+h+1])
    return out
aks=medfilt(ak,7)
print("=== achieved vs plan curvature in CORNERS ===")
print(f"plan R mean={1/pk[CO].mean():.1f}m   plan kappa mean={pk[CO].mean():.4f}")
print(f"achieved kappa mean={np.nanmean(aks[CO]):.4f} -> R={1/max(np.nanmean(aks[CO]),1e-6):.1f}m")
print(f"median achieved/plan ratio={np.nanmedian(aks[CO]/np.maximum(pk[CO],1e-6)):.2f}")
print(f"frac under-turn (achieved<plan)={np.mean(aks[CO]<pk[CO]):.2f}")

# Verify steer sign vs heading change: in a right-hand corner heading decreases? establish polarity
# correlate commanded steer with achieved yaw rate
def corr(a,b):
    a=a-np.nanmean(a);b=b-np.nanmean(b)
    return np.nansum(a*b)/np.sqrt(np.nansum(a*a)*np.nansum(b*b))
print(f"\ncorr(steer, yawrate dpsi) corner={corr(steer[CO],dpsi[CO]):+.2f}  (sign tells which steer dir = which turn)")
print(f"mean dpsi in corners={np.degrees(dpsi[CO].mean()):+.2f} deg/s (sign of the right-hander)")
print(f"mean steer in corners={steer[CO].mean():+.3f}")

# So positive steer corresponds to the corner-direction turn. cte<0 = outside/wide.
# Among wide samples, is steer LESS than what's needed? compare steer to corner-average and to apex (cte>0) samples.
wide=CO&(cte<-0.5); inside=CO&(cte>0.2)
print(f"\nwide(cte<-0.5): n={wide.sum()} steer={steer[wide].mean():+.3f} alpha={alpha[wide].mean():+.1f} achkappa={np.nanmean(aks[wide]):.4f}")
print(f"inside(cte>0.2): n={inside.sum()} steer={steer[inside].mean():+.3f} alpha={alpha[inside].mean():+.1f} achkappa={np.nanmean(aks[inside]):.4f}")

# entry vs exit of corners: bin corner samples by where in the corner (cte trend). Is car wide on entry (turn-in late)?
# Look at cte as function of relative corner progress using i0 within corner runs.
# Simpler: lag between steer and cte: does steer respond AFTER going wide?
# cross-correlate steer and cte at small lags
s=steer[mask]-steer[mask].mean();c=cte[mask]-cte[mask].mean()
print("\n=== steer/cte lag (steady-state) ===")
for lag in [-6,-3,-1,0,1,3,6]:
    if lag>=0: a=s[lag:];b=c[:len(c)-lag]
    else: a=s[:lag];b=c[-lag:]
    cc=np.sum(a*b)/np.sqrt(np.sum(a*a)*np.sum(b*b))
    print(f"  lag {lag:+d} ({lag*25:+d}ms): corr(steer_t, cte_t-lag)={cc:+.3f}")

# Quantify steady-state: on a long straight does cte settle to nonzero? regression of cte on cumulative time within straight runs
print(f"\nstraight |cte| mean={np.abs(cte[ST]).mean():.2f} signed mean={cte[ST].mean():+.2f} (small signed => not pure offset; large |cte| + slow crossings => slow wander)")
