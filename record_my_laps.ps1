# One-click human hot-lap recorder (07-14, created after the unrecorded 25.679 PB).
# Run this BEFORE a practice/PB session; drive; Ctrl+C when done.
# Output: recordings\run_<timestamp>.csv (same format as the 06-25 fast runs -> feeds
# refline rebuild, BC dataset, speed profile). Refuses to run while the follower is up
# (they'd fight over UDP 7777 -- concurrent listeners false-negative).
$root = "C:\Users\talon\FH6-AFK-Farm"
# check the PORT itself, not process names (a pythonw/other-project listener ate a session once)
$ep = Get-NetUDPEndpoint -LocalPort 7777 -ErrorAction SilentlyContinue
if ($ep) {
  Write-Host "REFUSING: UDP 7777 is already held - packets would go there, not to you:" -ForegroundColor Red
  $ep | ForEach-Object {
    $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
    $cl = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.OwningProcess)").CommandLine
    Write-Host "  PID $($_.OwningProcess) ($($p.ProcessName)): $cl"
  }
  Write-Host "Kill it (Stop-Process -Id <pid> -Force) or pause the racer/tools, then re-run this."
  exit 1
}
Write-Host "Recording telemetry to recordings\run_<timestamp>.csv -- drive your laps, Ctrl+C to stop." -ForegroundColor Green
& "C:\Users\Talon\myenv\Scripts\python.exe" "$root\fh6_telemetry.py" --port 7777 --out "$root\recordings"
