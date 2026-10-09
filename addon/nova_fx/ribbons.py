"""Light ribbons: each particle draws a glowing trail through where it was over the last few frames.

The trail comes from the cache, not from extra simulation state: the last N frames are read back and matched by
particle id, so a ribbon is exactly the path the particle took. Written to a companion Curves object
("<system> Ribbons") as smooth Catmull-Rom curves with per-point radius (tapering to the tail) and emission
(fading to the tail), drawn with the system's own particle material.
"""

import os
from collections import OrderedDict

import bpy
import numpy as np

from . import core

_READ = OrderedDict()  # path -> (mtime, data): the last frames, so playback reads each file once


def _read(path):
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return None
    hit = _READ.get(path)
    if hit and hit[0] == mt:
        _READ.move_to_end(path)
        return hit[1]
    try:
        data = core.read_cache(path)
    except (ValueError, OSError):
        return None
    _READ[path] = (mt, data)
    while len(_READ) > 96:
        _READ.popitem(last=False)
    return data


def ribbon_object(sysob, create=True):
    name = sysob.name + " Ribbons"
    ob = bpy.data.objects.get(name)
    if ob is not None and ob.type == "CURVES":
        return ob
    if not create:
        return None
    ob = bpy.data.objects.new(name, bpy.data.hair_curves.new(name))
    for coll in sysob.users_collection:
        coll.objects.link(ob)
    ob.hide_select = True
    return ob


def trails(sysob, frame, path_of):
    """(sizes, positions, head index per curve, t along the trail per point) for the particles alive at frame.
    path_of(frame) -> cache path."""
    n = sysob.nova
    cur = _read(path_of(frame))
    if cur is None or cur["n"] == 0:
        return None
    ids = cur["id"]
    order = np.argsort(ids)
    sid = ids[order]
    K = max(2, n.ribbon_frames)
    pos = np.full((K, len(ids), 3), np.nan, np.float32)
    pos[0] = cur["P"].reshape(-1, 3)
    for b in range(1, K):
        d = _read(path_of(frame - b))
        if d is None or d["n"] == 0:
            break
        # where each current particle was b frames ago (if it existed)
        j = np.searchsorted(sid, d["id"])
        j = np.minimum(j, len(sid) - 1)
        hit = sid[j] == d["id"]
        idx = order[j[hit]]
        pos[b, idx] = d["P"].reshape(-1, 3)[hit]
    alive = ~np.isnan(pos[:, :, 0])  # (K, N)
    # a ribbon runs from now back to the first missing frame
    length = np.where(alive.all(0), K, np.argmin(alive, axis=0))
    keep = length >= 2
    if not keep.any():
        return None
    sel = np.nonzero(keep)[0]
    lens = length[sel]
    # points tail -> head, so the curve's parameter runs along the motion
    pts = []
    tt = []
    for L in np.unique(lens):
        group = sel[lens == L]
        seg = pos[:L, group][::-1].transpose(1, 0, 2)  # (g, L, 3), oldest first
        pts.append((L, group, seg))
    sizes = np.concatenate([np.full(len(g), L, np.int32) for L, g, _ in pts])
    P = np.concatenate([seg.reshape(-1, 3) for _, _, seg in pts])
    T = np.concatenate([np.tile(np.linspace(1.0, 0.0, L, dtype=np.float32), len(g)) for L, g, _ in pts])
    heads = np.concatenate([g for _, g, _ in pts])
    return sizes, P, heads, T, cur


def build(sysob, frame, path_of):
    """Rewrite the ribbons for `frame`. Returns the number of ribbons."""
    rob = ribbon_object(sysob)
    cv = rob.data
    cv.remove_curves()
    out = trails(sysob, frame, path_of)
    if out is None:
        cv.update_tag()
        return 0
    sizes, P, heads, T, cur = out
    n = sysob.nova
    cv.add_curves(sizes.tolist())
    cv.set_types(type="CATMULL_ROM")
    cv.position_data.foreach_set("vector", P.astype(np.float32).ravel())
    per = np.repeat(np.arange(len(sizes)), sizes)
    head = heads[per]
    radius = cur["radius"].astype(np.float32)[head] * n.size_mult * (n.ribbon_taper + (1 - n.ribbon_taper) * (1 - T))
    fade = (1 - T) ** 1.5
    emit = cur["emit"].astype(np.float32)[head] * fade * n.ribbon_glow
    col = cur["Cd"].reshape(-1, 3).astype(np.float32)[head]
    for name, dtype, kind, vals in (("radius", "FLOAT", "value", radius), ("emit", "FLOAT", "value", emit),
                                    ("Cd", "FLOAT_VECTOR", "vector", col.ravel())):
        at = cv.attributes.get(name)
        if at is None or at.data_type != dtype or at.domain != "POINT":
            if at is not None:
                cv.attributes.remove(at)
            at = cv.attributes.new(name, dtype, "POINT")
        at.data.foreach_set(kind, vals)
    if not cv.materials and sysob.data.materials:
        cv.materials.append(sysob.data.materials[0])
    rob.matrix_world = sysob.matrix_world.copy()
    cv.update_tag()
    return len(sizes)
