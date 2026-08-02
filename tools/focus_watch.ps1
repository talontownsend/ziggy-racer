# Log WHO owns the foreground window, continuously, alongside whether the farm log is growing.
#
# Built 2026-08-01 to settle a question I got wrong: I claimed TextInputHost.exe was stealing
# the foreground and pausing FH6. But every observation of that was made in a session where
# computer use was ACTIVE (screenshots, permission dialogs, the Claude app coming back to the
# front when a session starts or stops), so "TextInputHost was in front" could equally have been
# a SYMPTOM of that activity rather than an independent cause. TextInputHost is resident from
# 24 s after boot on this machine and normally idle.
#
# This samples the real foreground owner every few seconds and pairs it with follow_log growth,
# so focus loss can be attributed to a named process with a timestamp instead of inferred.
# It only observes - it kills nothing.
param(
  [int]$IntervalSec = 5,
  [string]$Out = "C:\Users\talon\FH6-AFK-Farm\focus_watch.log"
)
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class FgProbe {
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, System.Text.StringBuilder s, int n);
}
"@ -ErrorAction SilentlyContinue

$log = "C:\Users\talon\FH6-AFK-Farm\recordings\follow_log.csv"
$lastLen = -1
$lastGrow = Get-Date
$prevKey = ""
"# started $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') interval=${IntervalSec}s" | Add-Content $Out

while ($true) {
  $h = [FgProbe]::GetForegroundWindow()
  $fgPid = [uint32]0
  [void][FgProbe]::GetWindowThreadProcessId($h, [ref]$fgPid)
  $proc = (Get-Process -Id $fgPid -ErrorAction SilentlyContinue).ProcessName
  $sb = New-Object System.Text.StringBuilder 256
  [void][FgProbe]::GetWindowTextW($h, $sb, 256)
  $title = $sb.ToString()

  $li = Get-Item $log -ErrorAction SilentlyContinue
  $len = if ($li) { $li.Length } else { 0 }
  if ($len -ne $lastLen) { $lastLen = $len; $lastGrow = Get-Date }
  $stall = [int]((Get-Date) - $lastGrow).TotalSeconds

  # log every sample where the foreground OWNER changed, plus a heartbeat when the farm is stalled
  $key = "$proc|$fgPid"
  if ($key -ne $prevKey -or $stall -gt 30) {
    $ts = Get-Date -Format 'HH:mm:ss'
    "$ts  fg=$proc (pid $fgPid) stall=${stall}s  title='$title'" | Add-Content $Out
    $prevKey = $key
  }
  Start-Sleep -Seconds $IntervalSec
}
