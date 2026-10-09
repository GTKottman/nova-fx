"""Motes draw a turning spell circle on the ground and lights rise from it."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import add, loop, render_settings, start

sc = start(frame_end=150)
system = add("SPELL", "spell_circle")
render_settings(res=(1280, 720), samples=96)
loop("spell_circle", [system], 1, 150 - 4, step=2, width=640, still_at=100)
