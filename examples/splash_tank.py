"""Splash tank: a FLIP liquid dam break. A column of water falls, wraps around a stone ball and sloshes
against the far wall. The water is the system's Liquid particle type; its surface is meshed from the
particles (signed distance grid, Laplacian smoothing) in Geometry Nodes."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy
from _common import add, loop, render_settings, start

sc = start(frame_end=150)
tank = add("LIQUID", "splash_tank")
tank.nova.fluid.resolution = 96  # finer than the preset's 64 for the gallery
render_settings(res=(1280, 720), samples=128)
loop("splash_tank", [tank], 1, 140, step=2, width=640, still_at=34)
