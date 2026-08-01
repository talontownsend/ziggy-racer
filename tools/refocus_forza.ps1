# Bring Forza Horizon 6 to the foreground and CONFIRM it got there.
#
# RUN THIS AT THE END OF EVERY COMPUTER-USE SESSION, and after any PowerShell/screenshot
# burst. FH6 only accepts the bot's virtual-gamepad input while it is the FOREGROUND
# window; when Claude's own app (or a console, or a notification) takes focus the game
# pauses, the follower silently stops driving and logging, and the watchdog reads that as a
# hang and restarts it -- which destroys the vpad, raises a "Controller Disconnected"
# dialog, and costs another minute of recovery. Focus is load-bearing.
#
# SetForegroundWindow ALONE IS NOT ENOUGH. Windows' foreground lock refuses it whenever
# another process currently owns the foreground (measured 2026-08-01: "FH6 did NOT take
# focus" while a Bash/PowerShell call was active). The reliable sequence attaches our input
# queue to the current foreground window's thread first, so Windows treats us as the same
# input context and allows the switch; an ALT tap additionally releases the lock.
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class FzFocus {
  [DllImport("user32.dll")] public static extern bool   SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool   ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern uint   GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool   AttachThreadInput(uint a, uint b, bool attach);
  [DllImport("user32.dll")] public static extern bool   BringWindowToTop(IntPtr h);
  [DllImport("user32.dll")] public static extern bool   SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  [DllImport("user32.dll")] public static extern void   keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
}
"@ -ErrorAction SilentlyContinue

$p = Get-Process forzahorizon6 -ErrorAction SilentlyContinue
if (-not $p) { Write-Host "FH6 is not running"; exit 1 }
$h = $p.MainWindowHandle
if ($h -eq [IntPtr]::Zero) { Write-Host "FH6 has no main window yet"; exit 1 }

for ($try = 1; $try -le 3; $try++) {
  # ALT priming: Windows releases the foreground lock for a process that just saw key input.
  [FzFocus]::keybd_event(0x12, 0, 0, [UIntPtr]::Zero)      # ALT down
  [FzFocus]::keybd_event(0x12, 0, 2, [UIntPtr]::Zero)      # ALT up

  [FzFocus]::ShowWindow($h, 9) | Out-Null                  # SW_RESTORE (can't front a minimized window)
  Start-Sleep -Milliseconds 250

  # Attach our input queue to whoever owns the foreground, so the switch is permitted.
  $fgPid = [uint32]0
  $fg = [FzFocus]::GetForegroundWindow()
  $fgThread = [FzFocus]::GetWindowThreadProcessId($fg, [ref]$fgPid)
  $meThread = [FzFocus]::GetCurrentThreadId()
  $attached = $false
  if ($fgThread -ne 0 -and $fgThread -ne $meThread) {
    $attached = [FzFocus]::AttachThreadInput($meThread, $fgThread, $true)
  }
  [FzFocus]::BringWindowToTop($h) | Out-Null
  [FzFocus]::SetForegroundWindow($h) | Out-Null
  [FzFocus]::SetWindowPos($h, [IntPtr](-1), 0,0,0,0, 0x0043) | Out-Null   # HWND_TOPMOST
  [FzFocus]::SetWindowPos($h, [IntPtr](-2), 0,0,0,0, 0x0043) | Out-Null   # HWND_NOTOPMOST
  if ($attached) { [FzFocus]::AttachThreadInput($meThread, $fgThread, $false) | Out-Null }

  Start-Sleep -Milliseconds 700
  if ([FzFocus]::GetForegroundWindow() -eq $h) {
    Write-Host "FH6 is foreground - bot can drive (attempt $try)"
    exit 0
  }
}
Write-Host "WARNING: FH6 did NOT take focus after 3 attempts; the bot will not drive."
exit 2
