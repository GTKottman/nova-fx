"""Big wet snowflakes, six-armed crystals that rock and tumble down and lie where they land."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import add, loop, render_settings, start

sc = start(frame_end=150)
system = add("WETSNOW", "wet_snow")
render_settings(res=(1280, 720), samples=96)
loop("wet_snow", [system], 1, 150 - 4, step=2, width=640, still_at=120)
