#!/usr/bin/env python3
"""Drag-select a rectangle on screen with a virtual mouse (python-evdev + uinput).

Setup:  pip install evdev   (and /dev/uinput must be writable, see earlier notes)

Examples:
  python3 select_area.py 200 200 800 500 --dry-run     # moves only, never presses
  python3 select_area.py 200 200 800 500               # real drag-select
  python3 select_area.py 200 200 800 500 --screen 2560x1440

Safety: the left button is ALWAYS released in a finally block, so Ctrl+C or an
exception cannot leave the mouse stuck.
"""
import argparse
import sys
import time

from evdev import AbsInfo, UInput, ecodes as e


def make_device(w: int, h: int) -> UInput:
    cap = {
        e.EV_KEY: [e.BTN_LEFT],
        e.EV_ABS: [
            (e.ABS_X, AbsInfo(0, 0, w - 1, 0, 0, 0)),
            (e.ABS_Y, AbsInfo(0, 0, h - 1, 0, 0, 0)),
        ],
    }
    return UInput(cap, name="agent-mouse")


def move(ui: UInput, x: float, y: float) -> None:
    ui.write(e.EV_ABS, e.ABS_X, int(x))
    ui.write(e.EV_ABS, e.ABS_Y, int(y))
    ui.syn()


def glide(ui, x0, y0, x1, y1, steps=40, delay=0.012) -> None:
    """Move in small steps so apps see a real drag, not a teleport."""
    for i in range(1, steps + 1):
        t = i / steps
        move(ui, x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
        time.sleep(delay)


def main() -> int:
    p = argparse.ArgumentParser(description="Drag-select a screen rectangle.")
    p.add_argument("x1", type=int)
    p.add_argument("y1", type=int)
    p.add_argument("x2", type=int)
    p.add_argument("y2", type=int)
    p.add_argument("--screen", default="1920x1080", help="WIDTHxHEIGHT (default 1920x1080)")
    p.add_argument("--steps", type=int, default=40, help="glide steps (default 40)")
    p.add_argument("--countdown", type=int, default=3, help="seconds before starting")
    p.add_argument("--dry-run", action="store_true", help="move the pointer but never press")
    a = p.parse_args()

    try:
        w, h = (int(v) for v in a.screen.lower().split("x"))
    except ValueError:
        print("--screen must look like 1920x1080")
        return 2

    for name, val, lim in (("x1", a.x1, w), ("x2", a.x2, w), ("y1", a.y1, h), ("y2", a.y2, h)):
        if not 0 <= val < lim:
            print(f"{name}={val} is outside the screen (0..{lim - 1})")
            return 2

    ui = make_device(w, h)
    pressed = False
    try:
        time.sleep(1)  # let the desktop register the new device
        for s in range(a.countdown, 0, -1):
            print(f"Starting in {s}... (Ctrl+C to abort)")
            time.sleep(1)

        move(ui, a.x1, a.y1)             # go to the first corner
        time.sleep(0.3)

        if not a.dry_run:
            ui.write(e.EV_KEY, e.BTN_LEFT, 1)   # press
            ui.syn()
            pressed = True
            time.sleep(0.15)

        glide(ui, a.x1, a.y1, a.x2, a.y2, steps=a.steps)
        time.sleep(0.4)                  # hold so the selection box is visible
        print("Done." if not a.dry_run else "Dry run done (no button was pressed).")
    except KeyboardInterrupt:
        print("\nAborted.")
    finally:
        if pressed:                      # ALWAYS release
            ui.write(e.EV_KEY, e.BTN_LEFT, 0)
            ui.syn()
        ui.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())