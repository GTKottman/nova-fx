"""Red, orange and yellow leaves tumble down on the wind and settle."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import add, loop, render_settings, start

sc = start(frame_end=200)
system = add("AUTUMN", "autumn_leaves")
render_settings(res=(1280, 720), samples=96)
loop("autumn_leaves", [system], 1, 200 - 4, step=2, width=640, still_at=170)
