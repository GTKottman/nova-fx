"""Run inside Blender (background): music sync end to end.
blender -b --factory-startup --python tests/blender_music.py"""
import importlib.util, math, os, sys, tempfile, wave

import addon_utils
import bpy
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("test_music", os.path.join(HERE, "test_music.py"))
tm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tm)

mod = "bl_ext.user_default.nova_fx"
bpy.ops.wm.read_factory_settings(use_empty=True)
addon_utils.enable(mod, default_set=True)
sim = sys.modules[mod + ".sim"]
core = sys.modules[mod + ".core"]
sc = bpy.context.scene
sc.frame_start, sc.frame_end = 1, 300
sc.render.fps = 24
ok = True


def check(cond, what):
    global ok
    print(("ok   " if cond else "FAIL ") + what)
    ok &= bool(cond)


work = tempfile.mkdtemp(prefix="nova_music_")
x, rate, kicks, hats = tm.drum_loop(bars=4)  # kicks every 0.5 s from 0.05 s, hats on the off-beats
wav = os.path.join(work, "loop.wav")
with wave.open(wav, "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
    w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
mid = os.path.join(work, "loop.mid")
ev = []
for i, k in enumerate(kicks):  # the same kicks as MIDI note 36 on channel 10 (120 bpm, 480 ticks per beat)
    tk = int(round((k - 0.05) * 960)) + 48
    ev += [(tk, bytes([0x99, 36, 110])), (tk + 60, bytes([0x89, 36, 0]))]
tm.write_midi(mid, [("Drums", ev)])

m = sc.nova_music
m.audio, m.start_frame = wav, 100
kick_frames = [100 + k * 24 for k in kicks]

# ---- fireworks: one launcher's shells burst on the kicks
bpy.ops.nova.add_preset(preset="FIREWORKS")
fw = bpy.context.object
fw.nova.cache_dir = os.path.join(work, "cache") + "/"
fw.nova.live = False  # the test steps the simulation itself
for ob in sc.objects:
    if ob.nova_emitter.enabled:
        ob.nova_emitter.rate = 0
peony = bpy.data.objects["Launcher Peony"]
mt = peony.nova_emitter.music
mt.enabled, mt.source, mt.count, mt.land, mt.every = True, "LOW", 1, True, 2
bpy.ops.nova.music_sync()
hit_frames = [h.frame for h in mt.hits]
check(len(hit_frames) == 8 and all(abs(a - b) < 0.15 for a, b in zip(hit_frames, kick_frames[::2])),
      f"8 hits on every other kick (frames {hit_frames[0]:.2f} ... {hit_frames[-1]:.2f})")
check(sc.sequence_editor and sc.sequence_editor.strips.get("Nova Music") is not None, "song added to the sequencer")
check("bpm" in m.info and "120" in m.info, f"info: {m.info}")

names = [k.name for k in fw.nova.kinds]
star = names.index("Peony Star")
shell = names.index("Shell Peony")
dg = bpy.context.evaluated_depsgraph_get()
births, launches = [], []
seen_star, seen_shell = set(), set()  # ids: the cache stores age as a fraction of life, so births by id
for f in range(1, 230):
    sc.frame_set(f)
    sim.step(sc, fw, f, dg)
    d = core.read_cache(sim.particle_path(fw, f))
    ids = d["id"]
    st, sh = set(ids[d["kind"] == star].tolist()), set(ids[d["kind"] == shell].tolist())
    if st - seen_star:
        births.append(f)
    if sh - seen_shell:
        launches.append(f)
    seen_star |= st
    seen_shell |= sh
expect = [math.ceil(h) for h in hit_frames if h < 230]
check(births == expect, f"stars burst on the hit frames: {births} (expected {expect})")
check(launches and launches[0] < expect[0] - 60, f"shells launch a lifetime early (first at {launches[0]})")

# ---- the same with MIDI notes, burst on the hit (no landing)
m.midi = mid
mt.source, mt.notes, mt.channel, mt.land, mt.every = "MIDI", "C2", 10, False, 1
bpy.ops.nova.music_sync()
check(len(mt.hits) == 16 and abs(mt.hits[3].frame - kick_frames[3]) < 0.01, f"MIDI C2 ch10: {len(mt.hits)} hits")
mt.notes = "D2"
bpy.ops.nova.music_sync()
check(len(mt.hits) == 0, "a note that never plays gives no hits")

# ---- rate by loudness
mt.mode, mt.source = "RATE", "LOW"
bpy.ops.nova.music_sync()
mod_sync = sys.modules[mod + ".music_sync"]
on = mod_sync.level_at(mt, kick_frames[4] + 1)
off = mod_sync.level_at(mt, kick_frames[4] + 10)
check(len(mt.hits) > 200 and on > 0.4 and off < on * 0.5, f"rate level {on:.2f} on a kick, {off:.2f} between")

# ---- drive the system turbulence with pulses on the hats
bpy.context.view_layer.objects.active = fw
bpy.ops.nova.music_drive_add()
d = m.drives[0]
d.shape, d.source, d.low, d.high, d.release = "PULSE", "HIGH", 0.5, 4.0, 0.1
bpy.ops.nova.music_sync()
vals = []
for f in (round(100 + hats[2] * 24) + 1, round(100 + hats[2] * 24) + 8):
    sc.frame_set(f)
    vals.append(fw.nova.turb_amp)
check(vals[0] > 2.5 and vals[1] < 1.2, f"turbulence pulses on a hat: {vals[0]:.2f} then {vals[1]:.2f}")

# ---- lightning: one bolt per hit, resync replaces them
bpy.ops.nova.add_preset(preset="LIGHTNING")
bolt = bpy.context.object
lt = bolt.nova_lightning
lt.music.enabled, lt.music.source, lt.music.every = True, "LOW", 4
bpy.ops.nova.music_sync()
bolts = [o for o in sc.objects if o.type == "CURVES" and o.nova_lightning.enabled]
frames = sorted(o.nova_lightning.strike_frame for o in bolts)
check(len(bolts) == 4 and frames == [round(f) for f in kick_frames[::4]], f"4 strikes at {frames}")
impacts = {o.nova_lightning.impact.name for o in bolts if o.nova_lightning.impact}
check(len(impacts) == 4, "each strike has its own impact emitter")
check(len({o.nova_lightning.seed for o in bolts}) == 4, "each strike has its own shape")
lights_before = len(bpy.data.lights)
lt.music.every = 8
bpy.ops.nova.music_sync()
bolts = [o for o in sc.objects if o.type == "CURVES" and o.nova_lightning.enabled]
check(len(bolts) == 2 and len(bpy.data.lights) == lights_before - 4, f"resync leaves 2 strikes and no stray lights")
lt.music.enabled = False
bpy.ops.nova.music_sync()
check(len([o for o in sc.objects if o.type == "CURVES" and o.nova_lightning.enabled]) == 1,
      "turning music off removes the copies")

# ---- the panel code: every property it draws exists, in every mode
class Stub:
    def __init__(self):
        self.drawn = []
    def prop(self, data, name, **kw):
        assert hasattr(data, name), name
        self.drawn.append(name)
    def row(self, **kw): return self
    def column(self, **kw): return self
    def label(self, **kw): pass
    def operator(self, *a, **kw): return type("Op", (), {})()

ui = sys.modules[mod + ".ui"]
drawn = set()
for mode in ("BURST", "RATE"):
    for src in ("LOW", "MIDI"):
        for land in (False, True):
            mt.mode, mt.source, mt.land = mode, src, land
            st = Stub()
            ui.draw_trigger(st, mt, emitter=True)
            drawn |= set(st.drawn)
st = Stub()
ui.draw_trigger(st, bolt.nova_lightning.music)
check({"source", "notes", "threshold", "mode", "count", "land", "release", "every"} <= drawn,
      f"trigger panel draws {len(drawn)} settings across modes")

print("ALL OK" if ok else "SOME CHECKS FAILED")
sys.exit(0 if ok else 1)
