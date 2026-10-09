"""Lava runs down a slope, bright where hot and dark where its crust cools (viscosity that rises as it cools)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import add, loop, render_settings, start

sc = start(frame_end=220)
system = add("LAVA", "lava_flow")
render_settings(res=(1280, 720), samples=96)
loop("lava_flow", [system], 1, 220 - 4, step=2, width=640, still_at=180)
