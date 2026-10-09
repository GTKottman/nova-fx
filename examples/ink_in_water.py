"""Ink dropped into still water sinks in curling, billowing tendrils, backlit on white."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import add, loop, render_settings, start

sc = start(frame_end=180)
system = add("INK", "ink_in_water")
render_settings(res=(1280, 720), samples=96)
loop("ink_in_water", [system], 1, 180 - 4, step=2, width=640, still_at=70)
