"""A shaken snow globe: flakes swirl inside the glass and settle on the little scene inside."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import add, loop, render_settings, start

sc = start(frame_end=150)
system = add("GLOBE", "snow_globe")
render_settings(res=(1280, 720), samples=96)
loop("snow_globe", [system], 1, 150 - 4, step=2, width=640, still_at=60)
