# One-click human hot-lap recorder (07-14, created after the unrecorded 25.679 PB).
# Run this BEFORE a practice/PB session; drive; Ctrl+C when done.
# Output: recordings\run_<timestamp>.csv (same format as the 06-25 fast runs -> feeds
# refline rebuild, BC dataset, speed profile). Refuses to run while the follower is up
# (they'd fight over UDP 7777 -- concurrent listeners false-negative).
$root = "C:\Users\talon\FH6-AFK-Farm"
$follower = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
            Where-Object { $_.CommandLine -like '*follow.py*' }
if ($follower) {
  Write-Host "REFUSING: the follower is running (would conflict on UDP 7777)." -ForegroundColor Red
  Write-Host "Pause the racer first, then re-run this."
  exit 1
}
Write-Host "Recording telemetry to recordings\run_<timestamp>.csv -- drive your laps, Ctrl+C to stop." -ForegroundColor Green
& "C:\Users\Talon\myenv\Scripts\python.exe" "$root\fh6_telemetry.py" --port 7777 --out "$root\recordings"
