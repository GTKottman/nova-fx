import bpy

from . import presets, sim
from .ops import system_of
from .params import KIND_GROUPS, KIND_SPEC
from .props import FLUID_BOOL_SPEC, FLUID_INT_SPEC, FLUID_SPEC


class NOVA_UL_kinds(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_prop, index=0):
        icons = {"BLACKBODY": "LIGHT_SUN", "GRADIENT": "COLOR", "FIXED": "SHADING_SOLID"}
        layout.prop(item, "name", text="", emboss=False, icon=icons.get(item.color_mode, "DOT"))


class _Panel:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Nova FX"


def _sys(context):
    return system_of(context.object)


class NOVA_PT_main(_Panel, bpy.types.Panel):
    bl_label = "Nova FX"

    def draw(self, context):
        layout = self.layout
        layout.operator_menu_enum("nova.add_preset", "preset", text="Add Effect", icon="ADD")
        ob = context.object
        if ob is None:
            return
        sysob = _sys(context)
        if ob.nova.is_system or ob.nova_lightning.enabled:
            return
        col = layout.column(align=True)
        row = col.row(align=True)
        row.operator("nova.make", text="Emitter", icon="PARTICLES",
                     depress=ob.nova_emitter.enabled).role = "EMITTER"
        row.operator("nova.make", text="Collider", icon="MOD_PHYSICS",
                     depress=ob.nova_collider.enabled).role = "COLLIDER"
        row.operator("nova.make", text="Force", icon="FORCE_FORCE", depress=ob.nova_force.enabled).role = "FORCE"
        if ob.nova_emitter.enabled or ob.nova_collider.enabled or ob.nova_force.enabled:
            col.operator("nova.make", text="Clear Roles", icon="X").role = "CLEAR"
        if ob.type == "MESH" and not ob.nova_dissolve.enabled:
            layout.operator("nova.dissolve_setup", icon="MOD_EXPLODE")
        if sysob and ob.nova_emitter.enabled:
            layout.operator("nova.select_system", text=f"System: {sysob.name}", icon="RESTRICT_SELECT_OFF")


class NOVA_PT_system(_Panel, bpy.types.Panel):
    bl_label = "Simulation"

    @classmethod
    def poll(cls, context):
        ob = context.object
        return ob is not None and ob.nova.is_system

    def draw(self, context):
        layout = self.layout
        sysob = _sys(context)
        n = sysob.nova
        layout.use_property_split = True
        layout.use_property_decorate = False
        row = layout.row(align=True)
        row.scale_y = 1.4
        row.operator("nova.bake", icon="RENDER_ANIMATION")
        row.operator("nova.free_cache", text="", icon="TRASH")
        row.operator("nova.reset", text="", icon="FILE_REFRESH")
        layout.prop(n, "live")
        col = layout.column(align=True)
        col.prop(n, "frame_start", text="Frames")
        col.prop(n, "frame_end", text="End")
        layout.prop(n, "substeps")
        layout.prop(n, "time_scale")
        layout.prop(n, "max_particles")
        layout.prop(n, "seed")
        layout.prop(n, "cache_dir")
        st = sim.stats(sysob)
        cached = len(sim.cached_frames(sysob))
        box = layout.box()
        box.use_property_split = False
        c = box.column(align=True)
        c.label(text=f"{st.get('count', 0):,} particles · {cached} frames cached", icon="INFO")
        if st:
            c.label(text=f"Particles {st['particle_ms']:.1f} ms · frame {st['frame_ms']:.0f} ms")
            if st.get("device"):
                c.label(text=st["device"], icon="CHECKMARK" if st["device"].startswith("GPU:") else "INFO")
            if st.get("cells"):
                c.label(text=f"Fluid {st['fluid_ms']:.0f} ms · {st['cg_iters']} pressure iterations")
                if st.get("upres"):
                    c.label(text=st["upres"], icon="ERROR" if "skipped" in st["upres"] else "MOD_REMESH")
                where = "on the GPU" if str(st.get("device", "")).startswith("GPU:") else "on the CPU"
                if n.fluid.sparse:
                    c.label(text=f"{st['active'] * 100:.0f}% of {st['cells'] / 1e6:.2f}M cells active {where} (sparse)")
                else:
                    c.label(text=f"{st['cells'] / 1e6:.2f}M cells {where} (dense)")


class NOVA_PT_types(_Panel, bpy.types.Panel):
    bl_label = "Particle Types"

    @classmethod
    def poll(cls, context):
        ob = context.object
        return ob is not None and ob.nova.is_system

    def draw(self, context):
        layout = self.layout
        n = _sys(context).nova
        row = layout.row()
        row.template_list("NOVA_UL_kinds", "", n, "kinds", n, "kinds_index", rows=4)
        col = row.column(align=True)
        col.operator("nova.kind_add", text="", icon="ADD").duplicate = False
        col.operator("nova.kind_add", text="", icon="DUPLICATE").duplicate = True
        col.operator("nova.kind_remove", text="", icon="REMOVE")
        if not n.kinds:
            return
        k = n.kinds[min(n.kinds_index, len(n.kinds) - 1)]
        layout.use_property_split = True
        layout.use_property_decorate = False
        for gid, label, icon in KIND_GROUPS:
            header, body = layout.panel(f"nova_kind_{gid}", default_closed=gid not in {"life", "color"})
            header.label(text=label, icon=icon)
            if body is None:
                continue
            draw_kind_group(body, k, n, gid)


def draw_kind_group(layout, k, n, gid):
    cm = k.color_mode
    for name, t, _d, o in KIND_SPEC:
        if o["group"] != gid:
            continue
        if gid == "color":
            if name in {"temp0", "temp_var", "cool", "cool_rad"} and cm != "BLACKBODY":
                continue
            if name in {"color", "color_var", "hue_random"} and cm == "BLACKBODY":
                continue
            if name in {"color2", "color_curve"} and cm != "GRADIENT":
                continue
            if name == "twinkle_amt" and k.twinkle_freq <= 0:
                continue
        ref = {"death": "death_kind", "trail": "trail_kind", "split": "split_kind"}.get(gid)
        if ref and name != ref and not getattr(k, ref):
            continue
        if gid == "life" and name == "size_curve" and n.display == "SHAPES":
            layout.prop(k, name, text="Size Curve")
            layout.prop(k, "shape_object")
            row = layout.row()
            row.prop(k, "shape_align")
            if k.shape_align == "TUMBLE":
                layout.prop(k, "shape_spin")
            layout.prop(k, "shape_scale")
            continue
        if gid == "liquid" and name != "liquid" and not k.liquid:
            continue
        if gid == "collide" and name != "collide" and k.collide == "NONE":
            continue
        if name in {"hit_count", "hit_speed"} and not k.hit_kind:
            continue
        if name == "death_shape":
            if k.death_pattern == "SHAPE":
                layout.prop(k, name, text="Shape")
                if k.death_shape:
                    draw_shape(layout, k.death_shape)
                    if k.death_kind and k.death_kind in n.kinds:
                        star = n.kinds[k.death_kind]
                        if star.drag_lin > 0:
                            layout.label(text=f"Shape size ≈ {k.death_speed / star.drag_lin:.1f} m "
                                              f"(speed / {k.death_kind} linear drag)", icon="INFO")
                        else:
                            layout.label(text=f"Give {k.death_kind} linear drag so the stars stop in the shape",
                                         icon="ERROR")
            continue
        label = name.replace("_", " ").title()
        if t == "K":
            layout.prop_search(k, name, n, "kinds", text=label.replace(" Kind", ""), icon="PARTICLES")
        else:
            layout.prop(k, name, text=label)


class NOVA_PT_forces(_Panel, bpy.types.Panel):
    bl_label = "World Forces"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        ob = context.object
        return ob is not None and ob.nova.is_system

    def draw(self, context):
        layout = self.layout
        n = _sys(context).nova
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(n, "gravity")
        layout.prop(n, "wind")
        col = layout.column(align=True)
        col.prop(n, "turb_amp")
        col.prop(n, "turb_freq")
        col.prop(n, "turb_speed")
        col.prop(n, "turb_octaves")
        layout.prop(n, "t_ambient")


class NOVA_PT_fluid(_Panel, bpy.types.Panel):
    bl_label = "Fire & Smoke"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        ob = context.object
        return ob is not None and ob.nova.is_system

    def draw_header(self, context):
        self.layout.prop(_sys(context).nova.fluid, "enabled", text="")

    def draw(self, context):
        layout = self.layout
        fl = _sys(context).nova.fluid
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.active = fl.enabled
        layout.prop(fl, "mode", expand=True)
        layout.prop(fl, "domain")
        layout.prop(fl, "resolution")
        if fl.mode == "LIQUID":
            layout.prop(fl, "look")
            layout.prop(fl, "flip")
            layout.prop(fl, "walls")
            col = layout.column(align=True)
            col.prop(fl, "surface_radius")
            col.prop(fl, "surface_smooth")
            if not any(k.liquid for k in _sys(context).nova.kinds):
                layout.label(text="Mark a particle type as Liquid (Motion)", icon="ERROR")
            header, body = layout.panel("nova_liquid_solver", default_closed=True)
            header.label(text="Solver")
            if body:
                body.prop(fl, "cfl")
                body.prop(fl, "max_sub")
                body.prop(fl, "visc_couple")
                body.prop(fl, "visc_iter")
                body.prop(fl, "cg_tol")
            return
        layout.prop(fl, "device", expand=True)
        if fl.domain:
            try:
                res, dx, _o = sim.fluid_layout(_sys(context))
                layout.label(text=f"{res[0]}×{res[1]}×{res[2]} cells · {dx * 100:.1f} cm voxels")
            except Exception:
                pass
        for gid, label in (("physics", "Gas"), ("fire", "Combustion"), ("solver", "Solver")):
            header, body = layout.panel(f"nova_fluid_{gid}", default_closed=gid == "solver")
            header.label(text=label)
            if body is None:
                continue
            for name, _d, _l, _kw, g, _desc in FLUID_SPEC:
                if g == gid:
                    body.prop(fl, name)
            if gid == "physics":
                body.prop(fl, "wind")
            if gid == "solver":
                for name, *_ in FLUID_INT_SPEC:
                    body.prop(fl, name)
                for name, *_ in FLUID_BOOL_SPEC:
                    body.prop(fl, name)
        header, body = layout.panel("nova_fluid_upres", default_closed=fl.upres <= 1)
        header.label(text="Upres")
        if body:
            body.prop(fl, "upres", text="Factor")
            sub = body.column()
            sub.active = fl.upres > 1
            sub.prop(fl, "upres_strength")
            sub.prop(fl, "upres_scale")
            sub.prop(fl, "upres_speed")
            if fl.upres > 1 and fl.domain:
                try:
                    res, dx, _o = sim.fluid_layout(_sys(context))
                    body.label(text=f"Voxels {dx * 100 / fl.upres:.2f} cm · at most "
                                    f"{res[0] * res[1] * res[2] * fl.upres ** 3 * 32 / 1e9:.1f} GB "
                                    f"if the fire fills the domain", icon="INFO")
                except Exception:
                    pass
        header, body = layout.panel("nova_fluid_look", default_closed=False)
        header.label(text="Look")
        if body:
            body.prop(fl, "gas_look")
            if fl.gas_look == "SPIRIT":
                body.prop(fl, "spirit_color")
                body.prop(fl, "spirit_color2")
            if fl.gas_look == "INK":
                body.prop(fl, "ink_color")
            for name in ("density_mult", "smoke_color", "flame_mult", "heat_mult", "temp_scale", "write_velocity"):
                body.prop(fl, name)


class NOVA_PT_display(_Panel, bpy.types.Panel):
    bl_label = "Display & Render"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        ob = context.object
        return ob is not None and ob.nova.is_system

    def draw(self, context):
        layout = self.layout
        n = _sys(context).nova
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(n, "display")
        if n.display == "STREAKS":
            layout.prop(n, "streak_length")
        if n.display == "RIBBONS":
            layout.prop(n, "ribbon_frames")
            layout.prop(n, "ribbon_taper")
            layout.prop(n, "ribbon_glow")
            layout.prop(n, "ribbon_heads")
        layout.prop(n, "shading")
        layout.prop(n, "size_mult")
        layout.prop(n, "emission_mult")
        layout.prop(n, "viewport_pct")
        layout.operator("nova.glow", icon="LIGHT_SUN")


class NOVA_PT_emitter(_Panel, bpy.types.Panel):
    bl_label = "Emitter"

    @classmethod
    def poll(cls, context):
        ob = context.object
        return ob is not None and ob.nova_emitter.enabled

    def draw(self, context):
        layout = self.layout
        e = context.object.nova_emitter
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(e, "system")
        if e.system:
            layout.prop_search(e, "kind", e.system.nova, "kinds", icon="PARTICLES")
        layout.prop(e, "shape")
        if e.system and e.kind in e.system.nova.kinds and e.system.nova.kinds[e.kind].liquid:
            layout.prop(e, "nozzle")
        if e.shape == "DISSOLVE":
            layout.prop(e, "dissolve_source")
            src = e.dissolve_source or context.object
            if not (src.type == "MESH" and src.nova_dissolve.enabled):
                layout.label(text="Pick an object with Disintegrate on", icon="ERROR")
        if e.shape == "SPHERE":
            layout.prop(e, "radius")
        if e.shape in {"SURFACE", "VERTS"}:
            layout.prop(e, "deforming")
        col = layout.column(align=True)
        col.prop(e, "rate")
        col.prop(e, "random_timing")
        col = layout.column(align=True)
        col.prop(e, "burst")
        col.prop(e, "burst_frame")
        col = layout.column(align=True)
        col.prop(e, "frame_start", text="Active From")
        col.prop(e, "frame_end", text="To")
        layout.prop(e, "direction")
        col = layout.column(align=True)
        col.prop(e, "speed")
        col.prop(e, "speed_var")
        if e.direction != "RANDOM":
            layout.prop(e, "spread")
        layout.prop(e, "inherit")
        layout.prop(e, "seed")
        header, body = layout.panel("nova_emitter_music", default_closed=not e.music.enabled)
        header.prop(e.music, "enabled", text="Music")
        if body:
            body.active = e.music.enabled
            draw_trigger(body, e.music, emitter=True)
            if e.music.mode == "BURST" and e.rate > 0:
                body.label(text="Rate still emits between hits", icon="INFO")
        header, body = layout.panel("nova_emitter_fluid", default_closed=not e.fl_enabled)
        header.prop(e, "fl_enabled", text="Fluid Source")
        if body:
            body.active = e.fl_enabled
            for name in ("fl_fuel", "fl_heat", "fl_density", "fl_speed", "fl_radius", "fl_noise", "fl_points"):
                body.prop(e, name)


class NOVA_PT_collider(_Panel, bpy.types.Panel):
    bl_label = "Collider"

    @classmethod
    def poll(cls, context):
        ob = context.object
        return ob is not None and ob.nova_collider.enabled

    def draw(self, context):
        c = context.object.nova_collider
        self.layout.prop(c, "shape")
        if c.shape == "MESH":
            self.layout.prop(c, "sdf_res")
            self.layout.prop(c, "deforming")


class NOVA_PT_force(_Panel, bpy.types.Panel):
    bl_label = "Force"

    @classmethod
    def poll(cls, context):
        ob = context.object
        return ob is not None and ob.nova_force.enabled

    def draw(self, context):
        layout = self.layout
        f = context.object.nova_force
        layout.use_property_split = True
        layout.prop(f, "type")
        layout.prop(f, "system")
        if f.type == "HEAT":
            layout.prop(f, "temperature")
            layout.prop(f, "heat_rate")
            layout.prop(f, "radius")
            layout.prop(f, "falloff")
            return
        if f.type == "FORM":
            layout.prop(f, "target")
            target = f.target or context.object
            if target.type in {"MESH", "CURVE", "FONT", "SURFACE", "META", "CURVES"}:
                draw_shape(layout, target)
            else:
                layout.label(text="Pick a mesh, text or curve to form", icon="ERROR")
            layout.prop(f, "pull")
            layout.prop(f, "snap")
            layout.prop(f, "damping")
            return
        layout.prop(f, "strength")
        layout.prop(f, "radius")
        layout.prop(f, "falloff")
        if f.type == "TURBULENCE":
            layout.prop(f, "freq")


def draw_shape(layout, ob):
    s = ob.nova_shape
    col = layout.column(align=True)
    col.prop(s, "mode")
    col.prop(s, "points")


def draw_trigger(layout, t, emitter=False):
    """The shared music trigger settings (emitters and bolts)."""
    layout.prop(t, "source")
    if t.source == "MIDI":
        layout.prop(t, "notes")
        row = layout.row(align=True)
        row.prop(t, "channel")
        row.prop(t, "track")
    elif not (emitter and t.mode == "RATE"):
        layout.prop(t, "threshold")
    if emitter:
        layout.prop(t, "mode")
    if not (emitter and t.mode == "RATE"):
        col = layout.column(align=True)
        col.prop(t, "min_gap")
        col.prop(t, "every")
        col.prop(t, "offset")
    if emitter and t.mode == "BURST":
        col = layout.column(align=True)
        col.prop(t, "count")
        col.prop(t, "response")
        layout.prop(t, "land")
    elif emitter:
        col = layout.column(align=True)
        if t.source != "MIDI":
            col.prop(t, "attack")
        col.prop(t, "release")
    n = len(t.hits)
    if emitter and t.mode == "RATE":
        msg = f"Rate follows {n} frames" if n else "Not synced yet"
    else:
        msg = f"{n} hits, first at frame {t.hits[0].frame:.1f}" if n else "Not synced yet"
    row = layout.row()
    row.label(text=msg, icon="CHECKMARK" if n else "INFO")
    row.operator("nova.music_sync", text="", icon="FILE_REFRESH")


class NOVA_PT_lightning(_Panel, bpy.types.Panel):
    bl_label = "Lightning"

    @classmethod
    def poll(cls, context):
        ob = context.object
        return ob is not None and ob.nova_lightning.enabled

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        ob = context.object
        lt = ob.nova_lightning
        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator("nova.lightning_regrow", icon="FILE_REFRESH").new_seed = False
        row.operator("nova.lightning_regrow", text="New Seed", icon="SHADERFX").new_seed = True
        if "nova_strike" in ob:
            x, y, z = ob["nova_strike"]
            layout.label(text=f"Strikes at {x:.1f}, {y:.1f}, {z:.1f}", icon="CHECKMARK")
        else:
            layout.label(text="Never reaches the ground: raise Directness", icon="ERROR")
        header, body = layout.panel("nova_lightning_shape", default_closed=False)
        header.label(text="Shape")
        if body:
            for prop in ("seed", "ground", "target", "branching", "field", "segment", "prune", "detail",
                         "roughness", "radius"):
                body.prop(lt, prop)
        header, body = layout.panel("nova_lightning_timing", default_closed=False)
        header.label(text="Timing")
        if body:
            for prop in ("strike_frame", "leader_frames", "strokes", "stroke_gap", "afterglow"):
                body.prop(lt, prop)
        header, body = layout.panel("nova_lightning_look", default_closed=True)
        header.label(text="Look")
        if body:
            for prop in ("brightness", "branch_glow", "temperature", "light_power", "impact"):
                body.prop(lt, prop)
        header, body = layout.panel("nova_lightning_music", default_closed=not lt.music.enabled)
        header.prop(lt.music, "enabled", text="Strike on the Music")
        if body:
            body.active = lt.music.enabled
            draw_trigger(body, lt.music)
            body.prop(lt, "music_spread")


class NOVA_PT_dissolve(_Panel, bpy.types.Panel):
    bl_label = "Disintegrate"

    @classmethod
    def poll(cls, context):
        ob = context.object
        return ob is not None and ob.type == "MESH" and ob.nova_dissolve.enabled

    def draw_header(self, context):
        self.layout.prop(context.object.nova_dissolve, "enabled", text="")

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        d = context.object.nova_dissolve
        layout.prop(d, "front")
        layout.prop(d, "mode", expand=True)
        layout.label(text="Move the front along its arrow" if d.mode == "PLANE" else "Scale the front up",
                     icon="INFO")
        col = layout.column(align=True)
        col.prop(d, "noise")
        col.prop(d, "noise_scale")
        col.prop(d, "detail")
        col = layout.column(align=True)
        col.prop(d, "edge")
        col.prop(d, "char")
        col.prop(d, "fine")
        col = layout.column(align=True)
        col.prop(d, "temperature")
        col.prop(d, "glow")


class NOVA_UL_drives(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_prop, index=0):
        name = item.target.name if item.target else "(no object)"
        layout.label(text=f"{name} · {item.path}", icon="SOUND")


class NOVA_PT_music(_Panel, bpy.types.Panel):
    bl_label = "Music"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        m = context.scene.nova_music
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(m, "audio")
        layout.prop(m, "midi")
        layout.prop(m, "start_frame")
        layout.prop(m, "sound_strip")
        row = layout.row()
        row.scale_y = 1.4
        row.operator("nova.music_sync", icon="SOUND")
        if m.info:
            layout.label(text=m.info, icon="INFO")
        header, body = layout.panel("nova_music_drives", default_closed=not m.drives)
        header.label(text="Drive Properties")
        if body is None:
            return
        row = body.row()
        row.template_list("NOVA_UL_drives", "", m, "drives", m, "drives_index", rows=3)
        col = row.column(align=True)
        col.operator("nova.music_drive_add", text="", icon="ADD")
        col.operator("nova.music_drive_remove", text="", icon="REMOVE")
        if not m.drives:
            body.label(text="Select an object, then +", icon="INFO")
            return
        d = m.drives[min(m.drives_index, len(m.drives) - 1)]
        body.prop(d, "target")
        body.prop(d, "path")
        row = body.row(align=True)
        row.prop(d, "low")
        row.prop(d, "high")
        body.prop(d, "shape", expand=True)
        body.prop(d, "source")
        if d.source == "MIDI":
            body.prop(d, "notes")
            row = body.row(align=True)
            row.prop(d, "channel")
            row.prop(d, "track")
        elif d.shape == "PULSE":
            body.prop(d, "threshold")
        if d.shape == "PULSE":
            body.prop(d, "every")
        elif d.source != "MIDI":
            body.prop(d, "attack")
        body.prop(d, "release")


class NOVA_MT_add(bpy.types.Menu):
    bl_label = "Nova FX"
    bl_idname = "NOVA_MT_add"

    def draw(self, context):
        for key, label, _d, _f in presets.PRESETS:
            op = self.layout.operator("nova.add_preset", text=label)
            op.preset = key


def menu_add(self, context):
    self.layout.menu("NOVA_MT_add", icon="PARTICLES")


CLASSES = (NOVA_UL_kinds, NOVA_PT_main, NOVA_PT_system, NOVA_PT_types, NOVA_PT_forces, NOVA_PT_fluid,
           NOVA_PT_display, NOVA_PT_emitter, NOVA_PT_collider, NOVA_PT_force, NOVA_PT_lightning, NOVA_PT_dissolve,
           NOVA_UL_drives,
           NOVA_PT_music, NOVA_MT_add)
