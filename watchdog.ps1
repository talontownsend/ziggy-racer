# FH6 follower watchdog -- restarts the follower if follow_log goes stale (a hang).
# Conservative: 180s staleness threshold (well above ~60-90s normal OCR recovery),
# 360s cooldown, and a hard cap of 10 restarts (then it gives up rather than thrash the game).
# Encodes the exact relaunch procedure validated by hand on 2026-06-27.
# Stop it: Get-CimInstance Win32_Process -Filter "name='pwsh.exe'" | ? {$_.CommandLine -like '*watchdog.ps1*'} | % {Stop-Process -Id $_.ProcessId -Force}
$ErrorActionPreference = "SilentlyContinue"
$root = "C:\Users\talon\FH6-AFK-Farm"
$log  = "$root\recordings\follow_log.csv"
$tune = "$root\recordings\tune.json"
$py   = "C:\Users\Talon\myenv\Scripts\python.exe"
$wlog = "$root\watchdog.log"
$fargs = @("$root\follow.py","--afk","--plan","$root\recordings\refline_plan.npz",
  "--slip-brake","0.0","--understeer-gain","3.0","--kp-thr","0.4","--planner-alat","27","--planner-alat-k","0.0025",
  "--slip-target","1.05","--yaw-rate-sign","-1","--k-counter","0.3","--r-thr","0.2","--understeer-thr","0.55",
  "--slide-deg","7","--k-slide","0.045","--full-slide-deg","22","--k-ff","5.5","--k-head","1.8","--kp","0.4","--ki","0.1",
  "--kd","0.12","--t-ff","0.18","--ld-base","10","--ld-k","0.22","--ld-min","9","--safety","1.0","--max-throttle","1.0",
  "--speed-cap","71","--beta-soft","8","--beta-hard","16","--cte-soft","5","--cte-hard","25","--lowspeed-steer-kmh","8",
  "--launch-cap-kmh","28","--launch-settle-m","70","--shift-up-rpm","7200","--shift-down-rpm","2800","--top-gear","11",
  "--duration","1000000")
$addKeys = @{ w_speed=0.08; ff_use_line=1.0; w_merge=6.0; k_d=3.0; head_use_line=0.0; w_len=0.015;
  resid_on=0.0; corner_fcgate=0.52; corner_gutil=0.82; kappa_pct=100.0; S_max=40.0; w_hyst=1.5; w_dev=0.3;
  bc_on=0.0; d0p_max=0.30; brk_ff=1.0; ki_thr=0.5; rejoin_kmin=0.004; rejoin_gain=2.0; scap_on=1.0; ff_loadcomp=0.85; crest_hold=0.0; vtrim_on=1.0; vtrim_up=0.0002; vtrim_dn=0.002; vtrim_cut=0.03; vtrim_gutil=0.93; vtrim_hi=1.55; vtrim_netscale=0.1; cg_on=0.0; acm_on=0.0; s7m_on=0.0; s7m_lo=470.0; s7m_hi=560.0; hul_lo=515.0; hul_hi=565.0;
  mbc_on=0.92; mbc_a_lo=470.0; mbc_a_hi=608.0; mbc_b_lo=638.0; mbc_b_hi=702.0; bla_tau=0.70; mbc_geo=0.0; hul_cte=0.0; ffm_w=0.0; ffm_gsc=0.5 }
function WLog($m) { "$((Get-Date).ToString('MM-dd HH:mm:ss')) $m" | Add-Content $wlog }

$lastRestart = (Get-Date).AddMinutes(-10)
$count = 0
WLog "watchdog started (stale>180s, cooldown 360s, max 10 restarts)"
while ($true) {
  Start-Sleep -Seconds 30
  $li = Get-Item $log
  # missing log = follower never started (e.g. log was archived/renamed with no follower up):
  # treat as maximally stale instead of skipping forever (07-13 blind spot: rename+dead follower)
  $age  = if ($li) { ((Get-Date) - $li.LastWriteTime).TotalSeconds } else { 9999 }
  $cool = ((Get-Date) - $lastRestart).TotalSeconds
  if ($age -gt 180 -and $cool -gt 360) {
    if ($count -ge 30) { WLog "STALE ${age}s but hit 30-restart cap -> giving up (needs human)"; break }
    $count++
    WLog "STALE log ${age}s -> restart #$count"
    Copy-Item "$root\follower_stdout.log" "$root\wd_fail_stdout_$((Get-Date).ToString('HHmmss')).log" -EA SilentlyContinue
    Copy-Item "$root\follower_stderr.log" "$root\wd_fail_stderr_$((Get-Date).ToString('HHmmss')).log" -EA SilentlyContinue
    # the relaunch TRUNCATES follow_log.csv -- archive it first (07-05: lost a 9 h soak)
    Copy-Item $log "$root\recordings\follow_log_wd_$((Get-Date).ToString('MMdd_HHmmss')).csv" -EA SilentlyContinue
    Get-CimInstance Win32_Process -Filter "name='python.exe'" |
      Where-Object { $_.CommandLine -like '*follow.py*' } |
      ForEach-Object { Stop-Process -Id $_.ProcessId -Force; WLog "  killed $($_.ProcessId)" }
    Start-Sleep -Seconds 2
    $p = Start-Process -FilePath $py -ArgumentList $fargs -WorkingDirectory $root `
         -RedirectStandardOutput "$root\follower_stdout.log" -RedirectStandardError "$root\follower_stderr.log" `
         -WindowStyle Hidden -PassThru
    WLog "  relaunched PID $($p.Id)"
    Start-Sleep -Seconds 8
    & $py "$root\press_enter.py" 2 | Out-Null
    Start-Sleep -Seconds 7
    $t = Get-Content $tune -Raw | ConvertFrom-Json
    foreach ($k in $addKeys.Keys) { $t | Add-Member -NotePropertyName $k -NotePropertyValue $addKeys[$k] -Force }
    $t | ConvertTo-Json | Set-Content $tune
    WLog "  tune keys re-added; resuming watch"
    $lastRestart = Get-Date
  }
}


















