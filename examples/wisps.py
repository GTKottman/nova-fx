"""Will-o'-wisps wander through the dark, drawing faint trails."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import add, loop, render_settings, start

sc = start(frame_end=160)
system = add("WISPS", "wisps")
render_settings(res=(1280, 720), samples=96)
loop("wisps", [system], 1, 160 - 4, step=2, width=640, still_at=90)
