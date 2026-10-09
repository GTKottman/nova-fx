"""A spinning ring flings sparks while ribbons of light swirl inside it."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import add, loop, render_settings, start

sc = start(frame_end=120)
system = add("PORTAL", "portal")
render_settings(res=(1280, 720), samples=96)
loop("portal", [system], 1, 120 - 4, step=2, width=640, still_at=60)
