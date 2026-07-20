#!/usr/bin/env python3
"""
Virtual Xbox pad sanity test (Stage 1 plumbing) -- INJECTS INPUT.

Creates a virtual Xbox 360 controller via ViGEmBus and runs a slow, scripted
sequence so you can confirm FH6 sees it and learn which axis/trigger maps to
what. Run this with FH6 in FREE ROAM (sitting still in an open area) so you can
watch the car react. It does NOT touch menus.

Prereqs (already done): vgamepad installed into Python312, ViGEmBus driver active.

Run (with FH6 open):
    & "C:\\Users\\talon\\AppData\\Local\\Programs\\Python\\Python312\\python.exe" .\\pad_test.py
Then immediately ALT-TAB into FH6 (free roam, car stopped in an open area) during the
6-second countdown so the game is the focused window when input starts.

Watch for:
    - Does the car STEER left then right?  (confirms left-stick X -> steering, and the sign)
    - Does it ACCELERATE on "throttle"?     (confirms right trigger -> throttle)
    - Does it BRAKE/reverse on "brake"?     (confirms left trigger -> brake)
    - When the pad connects, FH6 should switch its on-screen prompts to controller.
Note the answers -- they calibrate the controller's output mapping.
"""
import time

try:
    import vgamepad as vg
except ImportError:
    raise SystemExit(
        "vgamepad not installed. Run:\n"
        '  & "C:\\Users\\talon\\workspace\\myenv\\Scripts\\python.exe" -m pip install vgamepad'
    )


def banner(msg):
    print(f"\n>>> {msg}")
    time.sleep(0.4)


def main():
    gp = vg.VX360Gamepad()
    print("Virtual Xbox 360 pad created.")
    print(">>> ALT-TAB INTO FH6 NOW (free roam, car stopped). Starting in 6 seconds...\n")
    for k in range(6, 0, -1):
        print(f"  {k}...")
        time.sleep(1.0)

    # Neutral
    gp.left_joystick_float(x_value_float=0.0, y_value_float=0.0)
    gp.right_trigger_float(value_float=0.0)
    gp.left_trigger_float(value_float=0.0)
    gp.update()

    banner("STEER LEFT (left stick X = -1.0) for 1.5s")
    gp.left_joystick_float(x_value_float=-1.0, y_value_float=0.0)
    gp.update(); time.sleep(1.5)

    banner("STEER RIGHT (left stick X = +1.0) for 1.5s")
    gp.left_joystick_float(x_value_float=1.0, y_value_float=0.0)
    gp.update(); time.sleep(1.5)

    banner("CENTER steering")
    gp.left_joystick_float(x_value_float=0.0, y_value_float=0.0)
    gp.update(); time.sleep(1.0)

    banner("THROTTLE 60% (right trigger) for 2s -- car should pull forward")
    gp.right_trigger_float(value_float=0.6)
    gp.update(); time.sleep(2.0)
    gp.right_trigger_float(value_float=0.0)
    gp.update(); time.sleep(1.0)

    banner("BRAKE 80% (left trigger) for 1.5s -- should brake / reverse")
    gp.left_trigger_float(value_float=0.8)
    gp.update(); time.sleep(1.5)
    gp.left_trigger_float(value_float=0.0)
    gp.update(); time.sleep(0.5)

    banner("Tap A button (menu confirm) -- watch for a UI 'select' reaction")
    gp.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_A)
    gp.update(); time.sleep(0.15)
    gp.release_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_A)
    gp.update()

    # Reset everything
    gp.reset()
    gp.update()
    print("\nDone. The virtual pad will disconnect when this script exits.")


if __name__ == "__main__":
    main()
