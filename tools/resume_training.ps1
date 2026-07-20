# resume_training.ps1 -- start (or crash-resume) the full FH6 residual-training stack:
#   follower (base + bounded residual)  +  ES trainer (crash-safe --resume)  +  watchdog.
#
#   pwsh -File resume_training.ps1            # resume from es_state.json (after a crash)
#   pwsh -File resume_training.ps1 -Fresh     # archive old run, zero the net, start a fresh ES
#   pwsh -File resume_training.ps1 -WaitForGame
#       # logon mode: acts ONLY if training was active (training_active.flag) AND an unexpected
#       # shutdown happened since (Event 6008) -- i.e. a crash DURING training. Otherwise exits
#       # immediately, so it never hijacks a normal Forza play session. Waits for Forza telemetry
#       # before launching the driver, then resumes from the checkpoint.
param([switch]$WaitForGame, [switch]$Fresh)
$ErrorActionPreference = "SilentlyContinue"
$root = "C:\Users\talon\FH6-AFK-Farm"
$rec  = "$root\recordings"
$tune = "$rec\tune.json"
$py   = "C:\Users\Talon\myenv\Scripts\python.exe"
$flag = "$root\training_active.flag"
$rlog = "$root\resume_training.log"
Set-Location $root
function RLog($m){ "$((Get-Date).ToString('MM-dd HH:mm:ss')) $m" | Tee-Object -FilePath $rlog -Append | Out-Null }

# ---- logon-mode gate: resume ONLY when a crash interrupted ACTIVELY-RUNNING training.
#      Never fires on a normal everyday boot, and not even after a crash that happened while you
#      were NOT training. Two conditions, both required (fail-closed if boot history is unreadable):
#        (1) THIS boot followed an UNEXPECTED shutdown (a crash, Event 6008) -- not a clean one.
#        (2) the follower was writing follow_log (~71 Hz) during that crashed session -- i.e. training
#            was actually alive at the moment of the crash, not stopped hours/days earlier.
if ($WaitForGame) {
  $boots = @(Get-WinEvent -FilterHashtable @{LogName='System';Id=6005} -MaxEvents 8 -EA SilentlyContinue | Sort-Object TimeCreated -Descending)
  if ($boots.Count -lt 2) { RLog "logon: boot history unreadable -> not resuming (safe default)"; return }
  $curBoot = $boots[0].TimeCreated; $prevBoot = $boots[1].TimeCreated
  $crash = Get-WinEvent -FilterHashtable @{LogName='System';Id=6008} -MaxEvents 4 -EA SilentlyContinue | Where-Object { $_.TimeCreated -ge $curBoot.AddMinutes(-5) }
  if (-not $crash) { RLog "logon: last shutdown was clean (no crash on this boot) -> normal everyday boot, not resuming"; return }
  $flog = "$rec\follow_log.csv"
  $flogTime = if (Test-Path $flog) { (Get-Item $flog).LastWriteTime } else { [datetime]'1970-01-01' }
  if ($flogTime -lt $prevBoot) { RLog "logon: crashed, but training was NOT running that session (follow_log $flogTime < prev boot $prevBoot) -> not resuming (everyday use)"; return }
  RLog "logon: crash interrupted ACTIVE training (follow_log $flogTime) -> resuming once Forza is up"
}

# ---- (logon) wait for Forza Data-Out telemetry before launching the driver ----
function GameUp {
  $u = $null
  try {
    $u = New-Object System.Net.Sockets.UdpClient
    $u.Client.SetSocketOption([System.Net.Sockets.SocketOptionLevel]::Socket,[System.Net.Sockets.SocketOptionName]::ReuseAddress,$true)
    $u.Client.ReceiveTimeout = 4000
    $u.Client.Bind((New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Any,7777)))
    $ep = New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Any,0)
    $null = $u.Receive([ref]$ep); return $true
  } catch { return $false } finally { if ($u) { $u.Close() } }
}
if ($WaitForGame) {
  $w = 0
  while (-not (GameUp)) { Start-Sleep 10; $w += 10; if ($w % 120 -eq 0) { RLog "  still waiting for Forza telemetry (${w}s)" } }
  RLog "Forza telemetry detected -> launching stack"
}

# ---- kill any stale stack processes ----
Get-CimInstance Win32_Process -Filter "name='python.exe'" | Where-Object { $_.CommandLine -match 'follow\.py|train_residual\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; RLog "killed stale py $($_.ProcessId)" }
Get-CimInstance Win32_Process -Filter "name='pwsh.exe'" | Where-Object { $_.CommandLine -like '*watchdog.ps1*' -and $_.ProcessId -ne $PID } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; RLog "killed stale watchdog $($_.ProcessId)" }
Start-Sleep 2

# ---- (fresh) archive the old run (timestamped -- never clobber a previous archive) + zero the net ----
if ($Fresh) {
  $stamp = (Get-Date).ToString('yyyyMMdd_HHmm')
  if (Test-Path "$root\train_log.csv")    { Move-Item "$root\train_log.csv"    "$root\train_log_archive_$stamp.csv" -Force }
  if (Test-Path "$rec\residual_best.npz") { Move-Item "$rec\residual_best.npz" "$rec\residual_best_archive_$stamp.npz" -Force }
  if (Test-Path "$rec\es_state.json")     { Move-Item "$rec\es_state.json"     "$rec\es_state_archive_$stamp.json" -Force }
  & $py -c "import os; from residual_net import ResidualNet; ResidualNet(8).save(os.path.join(r'$rec','residual_net.npz'))"
  Remove-Item "$rec\residual_mean.npz" -Force -EA SilentlyContinue
  RLog "FRESH: archived train_log/residual_best/es_state as *_archive_$stamp; zeroed residual_net; cleared mean"
}

# ---- launch the follower (hand-built base + bounded residual corrector) ----
$fargs = @("$root\follow.py","--afk","--plan","$rec\refline_plan.npz",
  "--slip-brake","0.0","--understeer-gain","3.0","--kp-thr","0.4","--planner-alat","26","--planner-alat-k","0.0025",
  "--slip-target","1.05","--yaw-rate-sign","-1","--k-counter","0.3","--r-thr","0.2","--understeer-thr","0.55",
  "--slide-deg","7","--k-slide","0.045","--full-slide-deg","22","--k-ff","5.5","--k-head","1.8","--kp","0.4","--ki","0.1",
  "--kd","0.12","--t-ff","0.18","--ld-base","10","--ld-k","0.22","--ld-min","9","--safety","1.0","--max-throttle","1.0",
  "--speed-cap","71","--beta-soft","8","--beta-hard","16","--cte-soft","5","--cte-hard","25","--lowspeed-steer-kmh","8",
  "--launch-cap-kmh","28","--launch-settle-m","70","--shift-up-rpm","7200","--shift-down-rpm","2800","--top-gear","11",
  "--duration","1000000")
$f = Start-Process -FilePath $py -ArgumentList $fargs -WorkingDirectory $root `
     -RedirectStandardOutput "$root\follower_stdout.log" -RedirectStandardError "$root\follower_stderr.log" -WindowStyle Hidden -PassThru
RLog "follower launched PID $($f.Id)"
Start-Sleep 15

# ---- re-add the non-arg tune keys the follower wipes on startup (resid_on=1 turns on the corrector) ----
$addKeys = @{ w_speed=0.08; ff_use_line=1.0; w_merge=6.0; k_d=3.0; head_use_line=0.0; w_len=0.015;
  resid_on=1.0; corner_fcgate=0.52; corner_gutil=0.82; kappa_pct=100.0; S_max=40.0; w_hyst=1.5; w_dev=0.3;
  bc_on=0.0; d0p_max=0.30; brk_ff=1.0; ki_thr=0.5; rejoin_kmin=0.004; rejoin_gain=2.0; scap_on=1.0; ff_loadcomp=0.85; crest_hold=0.85; vtrim_on=1.0; vtrim_up=0.0; vtrim_dn=0.0; vtrim_cut=0.0; vtrim_gutil=0.93; vtrim_hi=1.55; vtrim_netscale=0.0 }
$t = Get-Content $tune -Raw | ConvertFrom-Json
foreach ($k in $addKeys.Keys) { $t | Add-Member -NotePropertyName $k -NotePropertyValue $addKeys[$k] -Force }
$t | ConvertTo-Json | Set-Content $tune
RLog "tune keys re-added (resid_on=1)"

# ---- launch the ES trainer (atomic checkpoints; resumes from es_state.json unless -Fresh) ----
$targs = @("-u","$root\train_residual.py","--hidden","8","--pop","10","--sigma","0.08","--lr","0.04",
  "--settle","33","--measure","680","--w-reset","10","--w-crash","8","--w-over","4","--over-deg","6",
  "--crash-g","6","--w-cte","5","--cte-ok","2.5","--off-pen","40","--dnf","90")
if (-not $Fresh) { $targs += "--resume" }
$tr = Start-Process -FilePath $py -ArgumentList $targs -WorkingDirectory $root `
      -RedirectStandardOutput "$root\train_stdout.log" -RedirectStandardError "$root\train_stderr.log" -WindowStyle Hidden -PassThru
RLog "trainer launched PID $($tr.Id) (resume=$(-not $Fresh))"

# ---- launch the watchdog (restarts the follower if its log goes stale) ----
$wd = Start-Process -FilePath "pwsh.exe" -ArgumentList @("-WindowStyle","Hidden","-File","$root\watchdog.ps1") `
      -WorkingDirectory $root -WindowStyle Hidden -PassThru
RLog "watchdog launched PID $($wd.Id)"

# ---- mark training active (also consumes the logon crash-trigger by refreshing the flag mtime) ----
Set-Content $flag "training active since $((Get-Date).ToString('s'))  follower=$($f.Id) trainer=$($tr.Id) watchdog=$($wd.Id)"
RLog "training_active.flag refreshed; stack up. Done."












