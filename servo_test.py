"""Standalone two-servo test on Pi 4; kernel PWM only; no AI, camera, or pump.

Run: ./venv/bin/python servo_test.py
Preview without GPIO: python servo_test.py --dry-run
"""

import argparse
import math
import subprocess
import sys
import time


PINS = {"pan": 18, "tilt": 19}  # Physical header pins 12 and 35.
FREQUENCY = 50


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("all", "pan", "tilt", "both"), default="both")
    parser.add_argument("--hold", type=float, default=1.5, help="Seconds per position (0.5-5).")
    parser.add_argument("--min-us", type=int, default=500, help="Pulse at 0 degrees.")
    parser.add_argument("--max-us", type=int, default=2400, help="Pulse at 180 degrees.")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without touching GPIO.")
    parser.add_argument("--yes", action="store_true", help="Start without the Enter prompt.")
    args = parser.parse_args()
    if not math.isfinite(args.hold) or not 0.5 <= args.hold <= 5:
        parser.error("--hold must be between 0.5 and 5 seconds")
    if not 500 <= args.min_us < args.max_us <= 2500:
        parser.error("Pulse limits must satisfy 500 <= min-us < max-us <= 2500")
    return args


def positions(mode):
    for section in (("pan", "tilt", "both") if mode == "all" else (mode,)):
        axes = tuple(PINS) if section == "both" else (section,)
        for angle in (90, 75, 105, 90):
            yield section, {axis: angle for axis in axes}


def main():
    args = parse_args()
    servos = {}
    print("PAN: BCM18 / physical pin12; TILT: BCM19 / physical pin35", flush=True)
    print(f"50 Hz; pulse range {args.min_us}-{args.max_us} us; {args.hold}s/position; kernel PWM sysfs.")
    print("External 5V supply; servo supply GND must connect to Pi GND.")
    try:
        if not args.dry_run:
            if sys.platform != "linux":
                raise RuntimeError("GPIO mode requires Raspberry Pi Linux; use --dry-run here.")
            running = subprocess.run(
                ["pgrep", "-f", "[p]ython.*web_server.py"], capture_output=True, check=False
            )
            if running.returncode == 0:
                raise RuntimeError("Stop web_server.py with Ctrl+C before testing servos.")
            from actuators import _SysfsPWMServo

            if not args.yes:
                input("Watch both servos. Enter starts the test; Ctrl+C cancels: ")
            axes = PINS if args.mode in ("all", "both") else (args.mode,)
            for axis in axes:
                servo = _SysfsPWMServo(
                    PINS[axis],
                    min_pulse_width=args.min_us / 1_000_000,
                    max_pulse_width=args.max_us / 1_000_000,
                )
                servos[axis] = servo
                print(f"{axis}: GPIO{PINS[axis]} -> {servo.pwm_path}", flush=True)

        for section, angles in positions(args.mode):
            for axis, angle in angles.items():
                pulse = round(args.min_us + angle / 180 * (args.max_us - args.min_us))
                print(f"[{section}] {axis}: GPIO{PINS[axis]} -> {angle} deg, {pulse} us", flush=True)
                if axis in servos:
                    servo = servos[axis]
                    servo.angle = angle
                    from pathlib import Path
                    pwm = Path(servo.pwm_path)
                    actual = {k: (pwm / k).read_text().strip()
                              for k in ("enable", "period", "duty_cycle")}
                    print(f"  PWM readback: {actual}", flush=True)
                    expected = int(round((args.min_us + angle / 180 *
                                          (args.max_us - args.min_us)) * 1000))
                    if actual != {"enable": "1", "period": "20000000",
                                  "duty_cycle": str(expected)}:
                        raise RuntimeError(f"Unexpected PWM output for {axis}: {actual}")
            if servos:
                time.sleep(args.hold)
        print("Command sequence completed. Check actual servo motion.", flush=True)
        return 0
    except KeyboardInterrupt:
        print("\nTest interrupted.", flush=True)
        return 130
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr, flush=True)
        return 1
    finally:
        for axis, servo in reversed(list(servos.items())):
            try:
                servo.close()
            except Exception as error:
                print(f"{axis} cleanup failed: {error}", file=sys.stderr)



if __name__ == "__main__":
    raise SystemExit(main())
