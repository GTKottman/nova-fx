"""A blizzard: snow driven sideways by a strong gusting wind."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import add, loop, render_settings, start

sc = start(frame_end=120)
system = add("BLIZZARD", "blizzard")
render_settings(res=(1280, 720), samples=96)
loop("blizzard", [system], 1, 120 - 4, step=2, width=640, still_at=96)
