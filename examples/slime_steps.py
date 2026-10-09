"""A blob of slime drops onto steps and oozes down them."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import add, loop, render_settings, start

sc = start(frame_end=120)
system = add("SLIME", "slime_steps")
render_settings(res=(1280, 720), samples=96)
loop("slime_steps", [system], 1, 120 - 4, step=2, width=640, still_at=80)
