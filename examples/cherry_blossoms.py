"""Cherry blossom petals drift and flutter on the breeze and gather on the grass."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import add, loop, render_settings, start

sc = start(frame_end=180)
system = add("SAKURA", "cherry_blossoms")
render_settings(res=(1280, 720), samples=96)
loop("cherry_blossoms", [system], 1, 180 - 4, step=2, width=640, still_at=150)
