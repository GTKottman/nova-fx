"""A wall of water crashes over a breakwater: spray off the crest, foam riding the surface, bubbles rising."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import add, loop, render_settings, start

sc = start(frame_end=140)
system = add("WHITEWATER", "whitewater")
render_settings(res=(1280, 720), samples=96)
loop("whitewater", [system], 1, 140 - 4, step=2, width=640, still_at=40)
