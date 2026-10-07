"""Shared helpers for the example scenes. Every example runs headless:

    blender -b --factory-startup --python examples/<name>.py -- [--quick] [--out DIR]

and writes a still (.jpg) and a short loop (.webp) to docs/examples/ (or --out)."""
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time

import addon_utils
import bpy
from mathutils import Vector

MOD = "bl_ext.user_default.nova_fx"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
QUICK = "--quick" in ARGS
OUT = ARGS[ARGS.index("--out") + 1] if "--out" in ARGS else os.path.join(ROOT, "docs", "examples")
# caches and frames go to disk, not tempfile.gettempdir(): /tmp is often RAM-backed and a 128^3 fire
# writes gigabytes of VDBs
WORK = os.path.join(os.path.expanduser("~"), ".cache", "nova-fx-examples")


def start(frame_end=250, fps=24):
    """Empty scene with Nova FX enabled."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    addon_utils.enable(MOD, default_set=True)
    sc = bpy.context.scene
    sc.frame_start, sc.frame_end = 1, frame_end
    sc.render.fps = fps
    return sc


def nova(name):
    """Import a Nova FX module (sim, presets, render ...)."""
    import importlib
    return importlib.import_module(f"{MOD}.{name}")


def add(preset, cache_name):
    """Add a preset with camera, night sky and glow; cache into a temp folder."""
    bpy.ops.nova.add_preset(preset=preset, setup_scene=True)
    so = bpy.context.object
    if not so.nova.is_system:  # Lightning focuses its bolt; the cache belongs to the preset's particle system
        so = next(o for c in so.users_collection for o in c.objects if o.nova.is_system)
    so.nova.cache_dir = os.path.join(WORK, "cache", cache_name) + "/"
    nova("sim").free_cache(so)
    bpy.context.scene.frame_set(so.nova.frame_start)  # restart the live simulation in the new cache
    return so


def material(name, color, rough=0.5, metal=0.0, emit=None, strength=0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    b = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if emit:
        b.inputs["Emission Color"].default_value = (*emit, 1)
        b.inputs["Emission Strength"].default_value = strength
    return mat


def look_at(ob, target):
    d = Vector(target) - ob.location
    ob.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def render_settings(res=(1280, 720), samples=96, dof=None):
    sc = bpy.context.scene
    r = sc.render
    r.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "OPTIX"
    prefs.get_devices()
    for d in prefs.devices:
        d.use = d.type == "OPTIX"
    sc.cycles.device = "GPU"
    sc.cycles.samples = max(16, samples // (3 if QUICK else 1))
    sc.cycles.use_denoising = True
    r.resolution_x, r.resolution_y = (res[0] // 2, res[1] // 2) if QUICK else res
    r.resolution_percentage = 100
    sc.view_settings.view_transform = "AgX"
    try:
        sc.view_settings.look = "AgX - Medium High Contrast"
    except TypeError:
        pass
    cam = sc.camera
    if dof and cam:
        cam.data.dof.use_dof = True
        cam.data.dof.focus_distance = dof[0]
        cam.data.dof.aperture_fstop = dof[1]


def advance(sysobs, frame):
    """Simulate (live) up to `frame`, then make sure volumes on disk are current."""
    sc = bpy.context.scene
    sim = nova("sim")
    while sc.frame_current < frame:
        sc.frame_set(sc.frame_current + 1)
    for so in sysobs:
        sim.wait_vdb(so)
        if so.nova.fluid.volume:
            sim.refresh_volume(so)


def _render(path, percentage):
    sc = bpy.context.scene
    sc.render.resolution_percentage = percentage
    sc.render.filepath = path
    try:
        bpy.ops.render.render(write_still=True)
    except RuntimeError as e:
        if sc.cycles.device != "GPU" or "memory" not in str(e).lower():
            raise
        # other programs hold the GPU: finish this scene on the CPU (same image, slower)
        print("GPU is out of memory; rendering the rest of this scene on the CPU", flush=True)
        sc.cycles.device = "CPU"
        bpy.context.preferences.addons["cycles"].preferences.compute_device_type = "NONE"
        sc.cycles.denoiser = "OPENIMAGEDENOISE"     # the OptiX denoiser needs the GPU too
        if hasattr(sc.cycles, "denoising_use_gpu"):
            sc.cycles.denoising_use_gpu = False
        if hasattr(sc.render, "compositor_device"):
            sc.render.compositor_device = "CPU"
        sc.render.threads_mode = "FIXED"           # leave a few cores for whatever else is running
        sc.render.threads = max(1, (os.cpu_count() or 4) - 4)
        bpy.ops.render.render(write_still=True)
    sc.render.resolution_percentage = 100


def _jpg(src, name):
    out = os.path.join(OUT, f"{name}.jpg")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-q:v", "3", out], check=True)
    return out


def still(name, sysobs, frame):
    """Simulate to `frame` and render one full-size image."""
    os.makedirs(OUT, exist_ok=True)
    advance(sysobs, frame)
    os.makedirs(WORK, exist_ok=True)
    tmp = os.path.join(WORK, f"{name}.png")
    t = time.perf_counter()
    _render(tmp, 100)
    out = _jpg(tmp, name)
    print(f"[{name}] still frame {frame}: {time.perf_counter() - t:.1f}s -> {out}", flush=True)
    return out


def loop(name, sysobs, first, last, step=1, width=640, fps=24, still_at=None):
    """Render first..last (every `step`) at half size into an animated WebP that plays inline on
    GitHub; on frame `still_at` also render a full-size still. Simulation only moves forward, so
    call this once per scene, from the earliest frame you need."""
    os.makedirs(OUT, exist_ok=True)
    sc = bpy.context.scene
    os.makedirs(WORK, exist_ok=True)
    d = tempfile.mkdtemp(prefix=f"{name}_", dir=WORK)
    t = time.perf_counter()
    n = 0
    for f in range(first, last + 1):
        advance(sysobs, f)
        if f == still_at:
            tmp = os.path.join(d, "still.png")
            _render(tmp, 100)
            print(f"[{name}] still frame {f} -> {_jpg(tmp, name)}", flush=True)
        if (f - first) % step:
            continue
        _render(os.path.join(d, f"{n:04d}.png"), 50)
        n += 1
    out = os.path.join(OUT, f"{name}.webp")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(max(1, fps // step)), "-i",
                    os.path.join(d, "%04d.png"), "-vf", f"scale={width}:-2:flags=lanczos", "-c:v", "libwebp_anim",
                    "-quality", "75", "-compression_level", "6", "-loop", "0", out], check=True)
    shutil.rmtree(d, ignore_errors=True)
    print(f"[{name}] loop {first}-{last} ({n} frames): {time.perf_counter() - t:.1f}s -> {out} "
          f"({os.path.getsize(out) / 1e6:.1f} MB)", flush=True)
    return out
