"""Particle logo: thirty thousand motes drift in, assemble into a word, hold, and are released into the
turbulence. The Form force pulls each particle to its own point of the text; its Pull is keyframed."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy
from _common import add, loop, render_settings, start

sc = start(frame_end=200)
logo = add("FORMATION", "particle_logo")
logo.nova.kinds["Mote"].size_start = 0.009
render_settings(res=(1280, 720), samples=64)
loop("particle_logo", [logo], 1, 196, step=2, width=640, still_at=110)
