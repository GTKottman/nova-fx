"""Fireworks to music: every launcher follows one part of a beat, and the shells *land* on it (launched one
lifetime early, so the burst happens on the hit). Writes fireworks_music.mp4 with the sound, plus the usual
silent loop and still. The beat is synthesized here (a plain drum pattern as test material): point
Music > Audio at any song instead."""
import os, sys, wave
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy
import numpy as np
from _common import WORK, add, look_at, loop, render_settings, start

BPM, BARS, RATE = 120, 4, 44100
SONG_START = 80  # scene frame where the beat starts: the first shells launch about 70 frames before


def beat(path):
    """Kick on every beat, snare on 2 and 4, hats on the eighths, a crash on bar 4 beat 1."""
    rng = np.random.default_rng(1)
    spb = 60 / BPM
    n = int(RATE * (spb * 4 * BARS + 3))
    x = np.zeros(n, np.float32)

    def put(t0, sig):
        sig = sig * np.minimum(1.0, np.linspace(5.0, 0.0, len(sig)))  # fade the tail: no click at the end
        i = int(t0 * RATE)
        x[i:i + len(sig)] += sig[:max(0, n - i)]

    t = np.arange(int(0.35 * RATE)) / RATE
    kick = 0.9 * np.sin(2 * np.pi * (45 + 90 * np.exp(-t * 28)) * t) * np.exp(-t * 9)
    ts = np.arange(int(0.25 * RATE)) / RATE
    snare = (0.35 * rng.normal(size=len(ts)) * np.exp(-ts * 18) +
             0.4 * np.sin(2 * np.pi * 190 * ts) * np.exp(-ts * 25))
    th = np.arange(int(0.06 * RATE)) / RATE
    tc = np.arange(int(2.0 * RATE)) / RATE
    for b in range(4 * BARS):
        t0 = b * spb
        put(t0, kick)
        if b % 2 == 1:
            put(t0, snare)
        for h in (0.0, 0.5):
            hat = np.diff(rng.normal(size=len(th) + 1)) * np.exp(-th * 70) * (0.12 if h == 0 else 0.2)
            put(t0 + h * spb, hat)
    put(3 * 4 * spb, 0.25 * np.diff(rng.normal(size=len(tc) + 1)) * np.exp(-tc * 1.8))
    x /= max(1.0, np.abs(x).max() / 0.9)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
        w.writeframes((x * 32767).astype("<i2").tobytes())


sc = start(frame_end=SONG_START + int(BARS * 4 * 60 / BPM * 24) + 60)
os.makedirs(WORK, exist_ok=True)
wav = os.path.join(WORK, "fireworks_music_beat.wav")
beat(wav)
show = add("FIREWORKS", "fireworks_music")
m = sc.nova_music
m.audio, m.start_frame = wav, SONG_START

# who plays what: (launcher, band, every, offset, x position)
parts = {
    "Peony": ("LOW", 4, 0, -30), "Chrysanthemum": ("LOW", 4, 2, 30),   # kicks, alternating sides
    "Ring": ("LOW", 4, 1, -10), "Heart": ("LOW", 4, 3, 10),
    "Crackle": ("MID", 2, 0, -45), "Crossette": ("MID", 2, 1, 45),    # snares
    "Strobe": ("HIGH", 8, 3, 0),                                        # a few hats
}
for ob in list(sc.objects):
    e = ob.nova_emitter
    if not e.enabled:
        continue
    e.rate = 0
    name = ob.name.replace("Launcher ", "")
    if name not in parts:
        continue
    band, every, offset, x = parts[name]
    ob.location.x = x
    t = e.music
    t.enabled, t.source, t.every, t.offset = True, band, every, offset
    t.count, t.response, t.land = 1, 0.0, True
    t.threshold = 0.4
bpy.ops.nova.music_sync()

cam = sc.camera
cam.location = (0, -150, 6)
look_at(cam, (0, 0, 55))
cam.data.lens = 24
render_settings(res=(1280, 720), samples=64)
first = SONG_START - 4
last = sc.frame_end - 20
loop("fireworks_music", [show], first, last, step=1, width=640, still_at=SONG_START + 60, audio=(wav, SONG_START))
