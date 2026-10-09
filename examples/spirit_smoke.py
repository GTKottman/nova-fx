"""Glowing spirit smoke, fresh cyan fading to violet, with motes."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import add, loop, render_settings, start

sc = start(frame_end=150)
system = add("SPIRIT", "spirit_smoke")
render_settings(res=(1280, 720), samples=96)
loop("spirit_smoke", [system], 1, 150 - 4, step=2, width=640, still_at=110)
