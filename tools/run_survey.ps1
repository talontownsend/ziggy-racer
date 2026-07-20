# run_survey.ps1 -- autonomous corridor surface survey: drive each offset plan for
# SWEEP_S seconds at survey speed, logging y/pitch/roll per station, then restore the
# normal racing config. Sweep logs land in recordings\survey\sweep_{d}.csv.
$ErrorActionPreference = "SilentlyContinue"
$root = "C:\Users\talon\FH6-AFK-Farm"
$rec  = "$root\recordings"
$py   = "C:\Users\Talon\myenv\Scripts\python.exe"
$slog = "$root\survey.log"
$SWEEP_S = 260
function SLog($m){ "$((Get-Date).ToString('HH:mm:ss')) $m" | Add-Content $slog }

function Launch($plan, $cap) {
  $fargs = @("$root\follow.py","--afk","--plan",$plan,
    "--slip-brake","0.0","--understeer-gain","3.0","--kp-thr","0.4","--planner-alat","24.3","--planner-alat-k","0.0025",
    "--slip-target","1.05","--yaw-rate-sign","-1","--k-counter","0.3","--r-thr","0.2","--understeer-thr","0.55",
    "--slide-deg","7","--k-slide","0.045","--full-slide-deg","22","--k-ff","5.5","--k-head","1.8","--kp","0.4","--ki","0.1",
    "--kd","0.12","--t-ff","0.18","--ld-base","10","--ld-k","0.22","--ld-min","9","--safety","1.0","--max-throttle","1.0",
    "--speed-cap",$cap,"--beta-soft","8","--beta-hard","16","--cte-soft","5","--cte-hard","25","--lowspeed-steer-kmh","8",
    "--launch-cap-kmh","28","--launch-settle-m","70","--shift-up-rpm","7200","--shift-down-rpm","2800","--top-gear","11",
    "--duration","1000000")
  $f = Start-Process -FilePath $py -ArgumentList $fargs -WorkingDirectory $root `
       -RedirectStandardOutput "$root\follower_stdout.log" -RedirectStandardError "$root\follower_stderr.log" `
       -WindowStyle Hidden -PassThru
  return $f.Id
}

function SetTune($vtrimOn, $crestOn) {
  $t = Get-Content "$rec\tune.json" -Raw | ConvertFrom-Json
  $addKeys = @{ w_speed=0.08; ff_use_line=1.0; w_merge=6.0; k_d=3.0; head_use_line=0.0; w_len=0.015;
    resid_on=0.0; corner_fcgate=0.52; corner_gutil=0.82; kappa_pct=100.0; S_max=40.0; w_hyst=1.5; w_dev=0.3;
    bc_on=0.0; d0p_max=0.30; brk_ff=1.0; ki_thr=0.5; rejoin_kmin=0.004; rejoin_gain=2.0;
    vtrim_up=0.0005; vtrim_dn=0.002; vtrim_cut=0.02; vtrim_gutil=0.93; vtrim_hi=1.55; vtrim_netscale=0.1 }
  $addKeys["vtrim_on"] = $vtrimOn; $addKeys["crest_on"] = $crestOn
  foreach ($k in $addKeys.Keys) { $t | Add-Member -NotePropertyName $k -NotePropertyValue $addKeys[$k] -Force }
  $t | ConvertTo-Json | Set-Content "$rec\tune.json"
}

function KillFollower {
  Get-CimInstance Win32_Process -Filter "name='python.exe'" |
    Where-Object { $_.CommandLine -like '*follow.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
  Start-Sleep 2
}

SLog "=== survey start ==="
KillFollower
if (Test-Path "$rec\follow_log.csv") { Move-Item "$rec\follow_log.csv" "$rec\follow_log_presurvey.csv" -Force }

foreach ($d in @(0, 1, -1, 2, -2, 3, -3, 4, -4)) {
  $tag = if ($d -ge 0) { "+$d" } else { "$d" }
  $plan = "$rec\survey\plan_off_$tag.npz"
  if (-not (Test-Path $plan)) { SLog "MISSING $plan, skipping"; continue }
  $pid2 = Launch $plan "25"
  Start-Sleep 12
  SetTune 0.0 0.0
  SLog "sweep d=$tag launched PID $pid2"
  Start-Sleep $SWEEP_S
  KillFollower
  if (Test-Path "$rec\follow_log.csv") { Move-Item "$rec\follow_log.csv" "$rec\survey\sweep_$tag.csv" -Force }
  SLog "sweep d=$tag captured"
}

$pid3 = Launch "$rec\refline_plan.npz" "71"
Start-Sleep 12
SetTune 1.0 1.0
SLog "racing config restored PID $pid3"
SLog "=== survey done ==="
