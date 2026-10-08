"""Music sync: emitters, lightning and any animatable property follow a song.

A song is an audio file (onsets and loudness per frequency band), a MIDI file (exact notes), or both. Sync
turns them into data stored in the .blend, so simulating and rendering never need the song again:
  - emitter triggers: hit list (frame, strength) for bursts, or a per-frame level for the emission rate
  - lightning: one bolt per hit (copies of the bolt, each with its own seed and impact)
  - drives: keyframes on any numeric property (turbulence, fuel, light power ...)

A burst can also *land* on the hit: the particles are emitted one lifetime early with that exact lifetime,
so a firework shell launched on the beat before bursts on the beat.
"""

import math
import os

import bpy
import numpy as np
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty, IntProperty,
                       PointerProperty, StringProperty)

from . import music

SOURCES = [
    ("LOW", "Bass (audio)", "Kick drum and bass onsets, 30-150 Hz"),
    ("MID", "Mids (audio)", "Snare body, vocals and most instruments, 150-2500 Hz"),
    ("HIGH", "Highs (audio)", "Hats, cymbals and snare crack, 5-16 kHz"),
    ("ALL", "Full Mix (audio)", "Onsets across the whole spectrum"),
    ("MIDI", "MIDI Notes", "Note-ons from the MIDI file, filtered by note, channel and track"),
]
COPY_TAG = "nova_music_of"


class NovaHit(bpy.types.PropertyGroup):
    frame: FloatProperty(name="Frame")
    value: FloatProperty(name="Strength", min=0, max=1)


def _trigger_annotations(mode=True):
    ann = dict(
        enabled=BoolProperty(name="Music", default=False, description="Follow the song (press Sync to Music)"),
        source=EnumProperty(name="Listen To", items=SOURCES, default="LOW"),
        notes=StringProperty(name="Notes", default="",
                             description="MIDI notes: 36, 36-38, C2, F#2-A2 or a comma list (C4 = 60). "
                                         "Empty = every note"),
        channel=IntProperty(name="Channel", default=0, min=0, max=16, description="MIDI channel, 0 = any"),
        track=StringProperty(name="Track", default="",
                             description="MIDI track number or part of its name, empty = any"),
        threshold=FloatProperty(name="Sensitivity Threshold", default=0.3, min=0, max=1,
                                description="Audio: 0 picks every bump, 1 only the biggest hits"),
        min_gap=FloatProperty(name="Min Gap", default=0.08, min=0, soft_max=2, unit="TIME_ABSOLUTE",
                              description="Ignore hits closer than this to the previous one (seconds)"),
        every=IntProperty(name="Every", default=1, min=1, max=64,
                          description="Use every Nth hit (several emitters can take turns with Offset)"),
        offset=IntProperty(name="Offset", default=0, min=0, max=63, description="Skip this many hits first"),
        hits=CollectionProperty(type=NovaHit),
    )
    if mode:
        ann.update(
            mode=EnumProperty(name="Mode", items=[
                ("BURST", "Burst per Hit", "Emit a burst on every hit (scaled by how hard it hits)"),
                ("RATE", "Rate by Loudness", "Emission rate follows the loudness (audio) or held notes (MIDI)"),
            ], default="BURST"),
            count=IntProperty(name="Burst", default=50, min=1, soft_max=5000,
                              description="Particles per hit at full strength"),
            response=FloatProperty(name="Velocity Response", default=0.7, min=0, max=1,
                                   description="How much a soft hit shrinks the burst (0 = every hit the same)"),
            land=BoolProperty(name="Land on the Hit", default=False,
                              description="Emit one lifetime early with that exact lifetime, so whatever the "
                                          "particle does on death (a firework burst) happens on the hit"),
            attack=FloatProperty(name="Attack", default=0.01, min=0.001, soft_max=1, unit="TIME_ABSOLUTE"),
            release=FloatProperty(name="Release", default=0.25, min=0.001, soft_max=4, unit="TIME_ABSOLUTE"),
        )
    return ann


NovaMusicTrigger = type("NovaMusicTrigger", (bpy.types.PropertyGroup,),
                        {"__annotations__": _trigger_annotations(True)})


class NovaDrive(bpy.types.PropertyGroup):
    """Keyframes one numeric property from the song."""
    target: PointerProperty(name="Object", type=bpy.types.Object)
    path: StringProperty(name="Property", default="nova.turb_amp",
                         description="Data path from the object: nova.turb_amp, nova.fluid.turb_amp, "
                                     "nova_emitter.rate, data.energy, location[2] ...")
    low: FloatProperty(name="Quiet", default=0.0, description="Value when the band is silent")
    high: FloatProperty(name="Loud", default=1.0, description="Value at the song's loud parts or on a hit")
    shape: EnumProperty(name="Shape", items=[
        ("LEVEL", "Loudness", "Follows the band's loudness (audio) or held notes (MIDI)"),
        ("PULSE", "Pulse per Hit", "Jumps on every hit and decays with Release"),
    ], default="LEVEL")
    source: EnumProperty(name="Listen To", items=SOURCES, default="LOW")
    notes: StringProperty(name="Notes", default="")
    channel: IntProperty(name="Channel", default=0, min=0, max=16)
    track: StringProperty(name="Track", default="")
    threshold: FloatProperty(name="Sensitivity Threshold", default=0.3, min=0, max=1)
    min_gap: FloatProperty(name="Min Gap", default=0.08, min=0, soft_max=2, unit="TIME_ABSOLUTE")
    every: IntProperty(name="Every", default=1, min=1, max=64)
    offset: IntProperty(name="Offset", default=0, min=0, max=63)
    attack: FloatProperty(name="Attack", default=0.01, min=0.001, soft_max=1, unit="TIME_ABSOLUTE")
    release: FloatProperty(name="Release", default=0.25, min=0.001, soft_max=4, unit="TIME_ABSOLUTE")


class NovaMusic(bpy.types.PropertyGroup):
    audio: StringProperty(name="Audio", subtype="FILE_PATH",
                          description="Song audio (wav, mp3, flac, ogg ...): onsets and loudness, and the sound "
                                      "you hear on playback")
    midi: StringProperty(name="MIDI", subtype="FILE_PATH",
                         description="Optional MIDI of the same song: exact notes for triggers")
    start_frame: IntProperty(name="Song Starts", default=1, description="Scene frame where the song begins")
    sound_strip: BoolProperty(name="Play Along", default=True,
                              description="Put the audio in the sequencer so playback has sound")
    drives: CollectionProperty(type=NovaDrive)
    drives_index: IntProperty(default=0)
    info: StringProperty(default="")


# ------------------------------------------------------------------ song loading (cached)

_CACHE = {}


def _key(path):
    p = bpy.path.abspath(path)
    return (p, os.path.getmtime(p)) if path and os.path.isfile(p) else None


def song(scene):
    """(notes or None, Analysis or None) for the scene's song files."""
    m = scene.nova_music
    out = []
    for path, loader in ((m.midi, music.read_midi), (m.audio, _analyze)):
        k = _key(path)
        if k is None:
            out.append(None)
            continue
        if k not in _CACHE:
            _CACHE[k] = loader(k[0])
        out.append(_CACHE[k])
    return tuple(out)


def _analyze(path):
    samples, rate = music.read_audio(path)
    return music.Analysis(samples, rate)


def fps(scene):
    return scene.render.fps / scene.render.fps_base


def to_frame(scene, t):
    return scene.nova_music.start_frame + t * fps(scene)


def hits_of(trig, notes, ana):
    """Hits (seconds, strength) for a trigger or drive, or raises ValueError explaining what is missing."""
    if trig.source == "MIDI":
        if notes is None:
            raise ValueError("listens to MIDI notes but there is no MIDI file")
        sel = music.filter_notes(notes, music.parse_notes(trig.notes), trig.channel, trig.track)
        hits = music.note_hits(sel, trig.min_gap)
    else:
        if ana is None:
            raise ValueError("listens to audio but there is no audio file")
        hits = ana.onsets(trig.source, trig.threshold, trig.min_gap)
    return hits[trig.offset::trig.every]


def level_of(trig, notes, ana, times):
    if trig.source == "MIDI":
        if notes is None:
            raise ValueError("listens to MIDI notes but there is no MIDI file")
        sel = music.filter_notes(notes, music.parse_notes(trig.notes), trig.channel, trig.track)
        return music.note_envelope(sel, times, trig.release)
    if ana is None:
        raise ValueError("listens to audio but there is no audio file")
    return ana.envelope(trig.source, times, trig.attack, trig.release)


def pulse(hits, times, release):
    out = np.zeros(len(times))
    for t, v in hits:
        after = times >= t
        out[after] = np.maximum(out[after], v * np.exp(-(times[after] - t) / max(release, 1e-3)))
    return out


def song_frames(scene, notes, ana):
    """Scene frames the song covers (clipped to the scene range)."""
    dur = 0.0
    if ana is not None:
        dur = ana.duration
    if notes:
        dur = max(dur, max(n["end"] for n in notes))
    f0 = max(scene.frame_start, scene.nova_music.start_frame)
    f1 = min(scene.frame_end, int(math.ceil(to_frame(scene, dur))))
    return np.arange(f0, f1 + 1)


# ------------------------------------------------------------------ applying

def sync_emitter(scene, ob, notes, ana):
    t = ob.nova_emitter.music
    t.hits.clear()
    if t.mode == "RATE":
        frames = song_frames(scene, notes, ana)
        lv = level_of(t, notes, ana, (frames - scene.nova_music.start_frame) / fps(scene))
        for f, v in zip(frames, lv):
            h = t.hits.add()
            h.frame, h.value = float(f), float(v)
        return f"{ob.name}: rate follows {len(frames)} frames"
    hits = hits_of(t, notes, ana)
    for s, v in hits:
        h = t.hits.add()
        h.frame, h.value = to_frame(scene, s), v
    return f"{ob.name}: {len(hits)} hits"


def _lightning_settings(lt):
    skip = {"rna_type", "name", "enabled", "impact", "music", "music_spread"}
    return {p.identifier: getattr(lt, p.identifier) for p in lt.bl_rna.properties
            if p.identifier not in skip and not p.is_readonly}


def remove_copies(ob):
    for o in [o for o in bpy.data.objects if o.get(COPY_TAG) == ob.name]:
        data = o.data
        mats = list(data.materials) if hasattr(data, "materials") and data else []
        if o.type == "CURVES":
            for suffix in ("Cloud Flash", "Flash"):
                lob = bpy.data.objects.get(f"{o.name} {suffix}")
                if lob is not None:
                    ldata = lob.data
                    bpy.data.objects.remove(lob)
                    if ldata and ldata.users == 0:
                        bpy.data.lights.remove(ldata)
        bpy.data.objects.remove(o)
        if data is not None and data.users == 0:
            if isinstance(data, bpy.types.Curves):
                bpy.data.hair_curves.remove(data)
        for m in mats:
            if m and m.users == 0:
                bpy.data.materials.remove(m)


def sync_lightning(context, scene, ob, notes, ana):
    from . import lightning
    lt = ob.nova_lightning
    t = lt.music
    remove_copies(ob)
    t.hits.clear()
    hits = hits_of(t, notes, ana)
    if not hits:
        return f"{ob.name}: no hits"
    for s, v in hits:
        h = t.hits.add()
        h.frame, h.value = to_frame(scene, s), v
    rng = np.random.default_rng(lt.seed * 977 + 3)
    base = ob.matrix_world.translation.copy()
    settings = _lightning_settings(lt)
    coll = ob.users_collection[0] if ob.users_collection else scene.collection
    lt.strike_frame = int(round(t.hits[0].frame))
    for i, h in enumerate(t.hits[1:], 1):
        st = dict(settings, seed=lt.seed + 101 * i, strike_frame=int(round(h.frame)),
                  brightness=lt.brightness * (0.6 + 0.4 * h.value))
        a, r = rng.uniform(0, 2 * math.pi), lt.music_spread * math.sqrt(rng.uniform())
        loc = base + type(base)((r * math.cos(a), r * math.sin(a), 0))
        impact = None
        if lt.impact is not None:
            impact = lt.impact.copy()
            impact[COPY_TAG] = ob.name
            for c in lt.impact.users_collection:
                c.objects.link(impact)
            impact.nova_emitter.music.enabled = False
            st["impact"] = impact
        new = lightning.add(context, coll, loc, name=f"{ob.name} Strike", **st)
        new[COPY_TAG] = ob.name
    return f"{ob.name}: {len(t.hits)} strikes"


def _fcurve(owner, prop, index):
    """The F-curve that animates owner.prop[index], created if needed (layered actions in 4.4+)."""
    owner.keyframe_insert(prop, index=index, frame=0)
    idb = owner.id_data
    adt = idb.animation_data
    path = owner.path_from_id(prop)
    act = adt.action
    try:
        from bpy_extras import anim_utils
        bag = anim_utils.action_get_channelbag_for_slot(act, adt.action_slot)
        curves = bag.fcurves if bag else []
    except (ImportError, AttributeError):
        curves = act.fcurves
    return next(fc for fc in curves if fc.data_path == path and fc.array_index == max(index, 0))


def sync_drive(scene, d, notes, ana):
    if d.target is None:
        raise ValueError("has no object")
    path, index = d.path.strip(), -1
    if path.endswith("]"):
        path, idx = path[:-1].rsplit("[", 1)
        index = int(idx)
    if "." in path:
        owner_path, prop = path.rsplit(".", 1)
        owner = d.target.path_resolve(owner_path)
    else:
        owner, prop = d.target, path
    if not hasattr(owner, prop):
        raise ValueError(f"has no property {d.path!r}")
    frames = song_frames(scene, notes, ana)
    times = (frames - scene.nova_music.start_frame) / fps(scene)
    if d.shape == "PULSE":
        lv = pulse(hits_of(d, notes, ana), times, d.release)
    else:
        lv = level_of(d, notes, ana, times)
    vals = d.low + (d.high - d.low) * lv
    fc = _fcurve(owner, prop, index)
    fc.keyframe_points.clear()
    fc.keyframe_points.add(len(frames))
    co = np.empty(2 * len(frames), np.float32)
    co[0::2], co[1::2] = frames, vals
    fc.keyframe_points.foreach_set("co", co)
    fc.keyframe_points.foreach_set("interpolation", [bpy.types.Keyframe.bl_rna.properties["interpolation"]
                                   .enum_items["LINEAR"].value] * len(frames))
    fc.update()
    return f"{d.target.name}.{d.path}: {len(frames)} keys"


def sound_strip(scene):
    m = scene.nova_music
    path = bpy.path.abspath(m.audio) if m.audio else ""
    se = scene.sequence_editor
    if se is not None:
        old = se.strips.get("Nova Music")
        if old is not None:
            se.strips.remove(old)
    if not (m.sound_strip and path and os.path.isfile(path)):
        return
    se = scene.sequence_editor or scene.sequence_editor_create()
    st = se.strips.new_sound("Nova Music", path, 1, m.start_frame)
    st.name = "Nova Music"
    scene.sync_mode = "AUDIO_SYNC"


def sync_all(context):
    """Sync every music-driven thing in the scene. Returns (messages, errors)."""
    scene = context.scene
    notes, ana = song(scene)
    msgs, errs = [], []
    if notes is None and ana is None:
        return msgs, ["Set an audio or MIDI file first"]
    # by name: removing a bolt's copies also removes their lights, which may be later in this list
    for name in [o.name for o in scene.objects if not o.get(COPY_TAG)]:  # copies are rebuilt, never synced
        ob = bpy.data.objects.get(name)
        if ob is None:
            continue
        jobs = []
        if ob.nova_emitter.enabled and ob.nova_emitter.music.enabled:
            jobs.append(lambda ob=ob: sync_emitter(scene, ob, notes, ana))
        if ob.type == "CURVES" and ob.nova_lightning.enabled:
            if ob.nova_lightning.music.enabled:
                jobs.append(lambda ob=ob: sync_lightning(context, scene, ob, notes, ana))
            elif any(o.get(COPY_TAG) == ob.name for o in scene.objects):
                remove_copies(ob)
        for job in jobs:
            try:
                msgs.append(job())
            except ValueError as e:
                errs.append(f"{ob.name} {e}")
    for d in scene.nova_music.drives:
        try:
            msgs.append(sync_drive(scene, d, notes, ana))
        except (ValueError, KeyError) as e:
            errs.append(f"Drive {d.target.name if d.target else '?'} {e}")
    sound_strip(scene)
    info = []
    if ana is not None:
        bpm = music.tempo(ana.onsets("LOW"))
        info.append(f"{ana.duration:.0f} s audio" + (f" · ~{bpm:.0f} bpm" if bpm else ""))
    if notes is not None:
        tracks = sorted({(n["track"], n["track_name"]) for n in notes})
        info.append(f"{len(notes)} MIDI notes in {len(tracks)} tracks")
    scene.nova_music.info = " · ".join(info)
    return msgs, errs


# ------------------------------------------------------------------ emission (called from sim.emit_frame)

def hits_in(trig, frame, lead=0.0):
    """Hits whose emission moment (hit frame - lead) falls in (frame-1, frame]: list of (t in (0, 1], value),
    t = the moment's position inside the frame."""
    out = []
    lo, hi = frame - 1, frame
    for h in trig.hits:
        e = h.frame - lead
        if lo < e <= hi:
            out.append((e - lo, h.value))
    return out


def level_at(trig, frame):
    n = len(trig.hits)
    if n == 0:
        return 1.0
    f0 = trig.hits[0].frame
    i = int(round(frame - f0))
    if 0 <= i < n:
        return trig.hits[i].value
    return 0.0


# ------------------------------------------------------------------ operators

class NOVA_OT_music_sync(bpy.types.Operator):
    """Analyze the song and update every emitter, bolt and drive that follows it"""
    bl_idname = "nova.music_sync"
    bl_label = "Sync to Music"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            msgs, errs = sync_all(context)
        except (OSError, music.MidiError, ValueError) as e:
            self.report({"ERROR"}, f"Nova FX: {e}")
            return {"CANCELLED"}
        for m in msgs:
            print("Nova FX music:", m)
        for e in errs:
            self.report({"WARNING"}, e)
        if not msgs and not errs:
            self.report({"WARNING"}, "Nothing follows the music yet: turn on Music on an emitter, a bolt or "
                                     "add a drive")
        elif msgs:
            self.report({"INFO"}, "Synced: " + "; ".join(msgs[:4]) + (" ..." if len(msgs) > 4 else ""))
        # cached frames came from the old timing: restart the live simulation from the start (it only
        # starts there, so staying on the current frame would leave playback with nothing to show)
        from . import sim
        systems = sim.systems(context.scene)
        for sysob in systems:
            sim._RT.pop(sysob.name, None)
        if systems:
            context.scene.frame_set(min(s.nova.frame_start for s in systems))
        return {"FINISHED"}


class NOVA_OT_music_drive_add(bpy.types.Operator):
    """Drive a property of the active object from the music"""
    bl_idname = "nova.music_drive_add"
    bl_label = "Add Drive"
    bl_options = {"UNDO"}

    def execute(self, context):
        m = context.scene.nova_music
        d = m.drives.add()
        ob = context.object
        if ob is not None:
            d.target = ob
            if ob.nova.is_system:
                d.path, d.low, d.high = "nova.turb_amp", ob.nova.turb_amp, max(1.0, ob.nova.turb_amp * 3)
            elif ob.nova_emitter.enabled:
                d.path, d.low, d.high = "nova_emitter.rate", 0.0, max(1.0, ob.nova_emitter.rate)
            elif ob.type == "LIGHT":
                d.path, d.low, d.high = "data.energy", 0.0, ob.data.energy
        m.drives_index = len(m.drives) - 1
        return {"FINISHED"}


class NOVA_OT_music_drive_remove(bpy.types.Operator):
    """Remove the selected drive (its keyframes stay)"""
    bl_idname = "nova.music_drive_remove"
    bl_label = "Remove Drive"
    bl_options = {"UNDO"}

    def execute(self, context):
        m = context.scene.nova_music
        if m.drives:
            m.drives.remove(m.drives_index)
            m.drives_index = max(0, min(m.drives_index, len(m.drives) - 1))
        return {"FINISHED"}


TYPES = (NovaHit, NovaMusicTrigger, NovaDrive, NovaMusic)
CLASSES = (NOVA_OT_music_sync, NOVA_OT_music_drive_add, NOVA_OT_music_drive_remove)


def register_types():
    for c in TYPES:
        bpy.utils.register_class(c)
    bpy.types.Scene.nova_music = PointerProperty(type=NovaMusic)


def unregister_types():
    del bpy.types.Scene.nova_music
    for c in reversed(TYPES):
        bpy.utils.unregister_class(c)
