"""A spray of blood drops breaks up in flight and stains the wall and floor, each stain lying flat on what it hit."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import add, loop, render_settings, start

sc = start(frame_end=90)
system = add("SPLATTER", "blood_splatter")
render_settings(res=(1280, 720), samples=96)
loop("blood_splatter", [system], 1, 90 - 4, step=2, width=640, still_at=40)
