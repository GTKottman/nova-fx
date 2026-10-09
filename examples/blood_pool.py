"""A pool of blood wells up on a tiled floor and creeps across it."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import add, loop, render_settings, start

sc = start(frame_end=160)
system = add("BLOOD", "blood_pool")
render_settings(res=(1280, 720), samples=96)
loop("blood_pool", [system], 1, 160 - 4, step=2, width=640, still_at=140)
