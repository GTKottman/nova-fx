"""Mesh (SDF) collider vs analytic sphere: same drop, positions should agree; plus bake timing."""
import bpy, addon_utils, time, tempfile, numpy as np, bmesh
from importlib import import_module
mod = "bl_ext.user_default.nova_fx"
bpy.ops.wm.read_factory_settings(use_empty=True)
addon_utils.enable(mod, default_set=True)
sim = import_module(mod + ".sim")
sc = bpy.context.scene
def run(shape, res=64):
    for ob in list(bpy.data.objects): bpy.data.objects.remove(ob)
    bpy.ops.nova.add_preset(preset="EMPTY")
    so = bpy.context.object
    so.nova.cache_dir = tempfile.mkdtemp(dir="/tmp/claude-1000") + "/"
    k = so.nova.kinds[0]; k.collide = "BOUNCE"; k.bounce = 0.0; k.friction = 0.5; k.life_min = k.life_max = 10
    em = bpy.data.objects["Nova Emitter"]; e = em.nova_emitter
    e.shape = "SPHERE"; e.radius = 0.8; e.rate = 0; e.burst = 4000; e.burst_frame = 1; e.speed = 0; e.direction = "RANDOM"
    em.location = (0, 0, 2.5)
    me = bpy.data.meshes.new("ball"); bm = bmesh.new(); bmesh.ops.create_uvsphere(bm, u_segments=64, v_segments=32, radius=1.0); bm.to_mesh(me); bm.free()
    ball = bpy.data.objects.new("ball", me); sc.collection.objects.link(ball)
    ball.nova_collider.enabled = True; ball.nova_collider.shape = shape; ball.nova_collider.sdf_res = res
    t = time.perf_counter(); sc.frame_set(1); t1 = time.perf_counter() - t
    for f in range(2, 49): sc.frame_set(f)
    P = np.empty(len(so.data.points) * 3, np.float32); so.data.attributes["position"].data.foreach_get("vector", P)
    return P.reshape(-1, 3), t1
A, _ = run("SPHERE")
B, tb = run("MESH", 64)
r = np.linalg.norm(B, axis=1)
inside = (r < 0.99).mean()
print(f"mesh collider bake + first frame: {tb*1000:.0f} ms (64 cells)")
print(f"particles resting on ball: analytic r mean {np.linalg.norm(A,axis=1)[np.linalg.norm(A,axis=1)<1.2].mean():.3f}, "
      f"mesh r mean {r[r<1.2].mean():.3f}; inside the mesh: {inside*100:.2f}%")
print(f"mean |pos diff| analytic vs mesh: {np.linalg.norm(A-B,axis=1).mean():.3f} m (n={len(A)})")
