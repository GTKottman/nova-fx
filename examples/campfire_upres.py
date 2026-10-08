"""Campfire close-up with upres: the fire is simulated at 96 cells and written three times finer. The detail
rides the simulated flow plus turbulence, and is held to the simulation at its own scale."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy
from _common import add, look_at, loop, render_settings, start

sc = start(frame_end=150)
fire = add("CAMPFIRE", "campfire_upres")
fl = fire.nova.fluid
fl.resolution, fl.upres, fl.upres_strength = 96, 3, 1.3
cam = sc.camera
cam.location = (0.0, -1.9, 0.75)
look_at(cam, (0, 0, 0.62))
cam.data.lens = 50
render_settings(res=(1280, 720), samples=96)
loop("campfire_upres", [fire], 60, 140, step=2, width=640, still_at=120)
