"""Burn away: a head disintegrates from the chin up. A ragged glowing edge, a charred band, embers and ash
coming off exactly where the surface goes, and flames fed along the edge into the GPU fire solver."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy
from _common import add, loop, nova, render_settings, start

sc = start(frame_end=170)
burn = add("DISINTEGRATE", "burn_away")
presets = nova("presets")
coll = burn.users_collection[0]
# flames on the burning edge: the ember emitter also feeds fuel and heat to a fire grid
presets.domain(coll, burn, (3.6, 2.6, 4.0), (0, 0, 1.7), 128, buoy_heat=2.5, vorticity=0.6, turb_amp=4.0,
               turb_freq=4.0, cool=1.6, cool_rad=0.3, burn_rate=3.0, heat_release=1.4, smoke_yield=0.25,
               expansion=0.3, flame_decay=7.0, smoke_decay=0.4, density_mult=1.5, flame_mult=2.5, heat_mult=1.0)
e = bpy.data.objects["Burning Monkey Ember"].nova_emitter
e.fl_enabled, e.fl_fuel, e.fl_heat, e.fl_noise = True, 0.9, 0.6, 0.7
render_settings(res=(1280, 720), samples=96)
loop("burn_away", [burn], 10, 150, step=2, width=640, still_at=70)
