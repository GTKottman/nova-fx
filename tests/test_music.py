"""Music analysis without Blender: MIDI parsing with tempo changes, onset timing on a synthetic drum loop.
Run: python3 tests/test_music.py"""
import importlib.util, os, struct, sys, tempfile, time, wave
import numpy as np

_p = os.path.join(os.path.dirname(__file__), "..", "addon", "nova_fx", "music.py")
_spec = importlib.util.spec_from_file_location("nova_music", _p)
music = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(music)


def vlq(v):
    out = [v & 0x7F]
    v >>= 7
    while v:
        out.append(0x80 | (v & 0x7F))
        v >>= 7
    return bytes(reversed(out))


def write_midi(path, tracks, div=480):
    """tracks: list of (name, [(tick, bytes)])"""
    data = b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), div)
    for name, evs in tracks:
        body, last = vlq(0) + b"\xff\x03" + vlq(len(name)) + name.encode(), 0
        for tick, ev in sorted(evs, key=lambda e: e[0]):
            body += vlq(tick - last) + ev
            last = tick
        body += vlq(0) + b"\xff\x2f\x00"
        data += b"MTrk" + struct.pack(">I", len(body)) + body
    open(path, "wb").write(data)


def test_midi():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "t.mid")
    # 120 bpm for 2 beats, then 60 bpm. kicks every beat on ch10, a held pad on ch1 using running status
    tempo = [(0, b"\xff\x51\x03" + (500000).to_bytes(3, "big")), (960, b"\xff\x51\x03" + (1000000).to_bytes(3, "big"))]
    drums = []
    for b in range(4):
        drums += [(b * 480, bytes([0x99, 36, 100 + b * 5])), (b * 480 + 60, bytes([0x89, 36, 0]))]
    drums += [(480, bytes([0x99, 42, 50])), (540, bytes([0x99, 42, 0]))]  # hat, note-off as vel 0
    pad = [(0, bytes([0x90, 60, 64])), (0, bytes([64, 64])), (1920, bytes([0x80, 60, 0])), (1920, bytes([64, 0]))]
    write_midi(p, [("Tempo", tempo), ("Drums", drums), ("Pad", pad)])
    notes = music.read_midi(p)
    kicks = music.filter_notes(notes, music.parse_notes("C2"), channel=10)
    t = [round(n["start"], 4) for n in kicks]
    assert t == [0.0, 0.5, 1.0, 2.0], t  # beat 3 starts at 1.0 s, beat 4 one second later (60 bpm)
    assert abs(kicks[0]["end"] - 0.0625) < 1e-6 and abs(kicks[-1]["velocity"] - 115 / 127) < 1e-6
    pad_notes = music.filter_notes(notes, track="pad")
    assert len(pad_notes) == 2 and abs(pad_notes[0]["end"] - 3.0) < 1e-6, pad_notes
    assert music.filter_notes(notes, music.parse_notes("42"), track="1")[0]["start"] == 0.5
    assert music.parse_notes("36-38,F#2") == {36, 37, 38, 42} and music.parse_notes("") is None
    hits = music.note_hits(music.filter_notes(notes, channel=10))
    assert [round(h[0], 3) for h in hits] == [0.0, 0.5, 1.0, 2.0], hits  # kick + hat at 0.5 s count once
    env = music.note_envelope(pad_notes, np.array([0.5, 2.9, 3.4]), release=0.1)
    assert env[0] == env[1] == 64 / 127 and env[2] < 0.1 * 64 / 127
    print("midi ok: tempo change, running status, note-off as velocity 0, track/channel/note filters")


def drum_loop(rate=44100, bpm=120, bars=4, seed=0, first=0.05):
    rng = np.random.default_rng(seed)
    beat = 60 / bpm
    n = int(rate * beat * 4 * bars) + rate
    x = np.zeros(n, np.float32)
    kicks, hats = [], []
    t = np.arange(int(0.25 * rate)) / rate
    kick = np.sin(2 * np.pi * (50 + 80 * np.exp(-t * 30)) * t) * np.exp(-t * 12)
    th = np.arange(int(0.05 * rate)) / rate
    for b in range(4 * bars):
        k0 = b * beat + first
        kicks.append(k0)
        i = int(k0 * rate)
        x[i:i + len(kick)] += 0.8 * kick
        h0 = k0 + beat / 2
        hats.append(h0)
        i = int(h0 * rate)
        hp = np.diff(rng.normal(size=len(th) + 1)).astype(np.float32)
        x[i:i + len(th)] += 0.3 * hp * np.exp(-th * 80)
    x += 0.003 * rng.normal(size=n).astype(np.float32)  # noise floor
    return x, rate, kicks, hats


def test_onsets():
    x, rate, kicks, hats = drum_loop()
    t0 = time.perf_counter()
    a = music.Analysis(x, rate)
    ms = (time.perf_counter() - t0) * 1000
    for band, truth in (("LOW", kicks), ("HIGH", hats)):
        hits = a.onsets(band, threshold=0.3)
        got = np.array([h[0] for h in hits])
        err = [np.min(np.abs(got - t)) for t in truth]
        assert len(hits) == len(truth), (band, len(hits), len(truth))
        assert max(err) < 0.008, (band, max(err))
        print(f"{band}: {len(hits)}/{len(truth)} onsets, worst timing error {max(err) * 1000:.1f} ms")
    # write it as a WAV and read it back through the no-Blender path
    p = os.path.join(tempfile.mkdtemp(), "loop.wav")
    with wave.open(p, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(rate)
        s = (np.clip(x, -1, 1) * 32767).astype("<i2")
        w.writeframes(np.stack([s, s], 1).tobytes())
    y, r = music.read_audio(p)
    assert r == rate and len(y) == len(x) and np.abs(y - np.clip(x, -1, 1)).max() < 1e-3
    env = a.envelope("LOW", np.array([kicks[2] + 0.03, kicks[2] + 0.45]))
    assert env[0] > 0.3 and env[1] < env[0] * 0.3, env
    x0, _r, k0, _h = drum_loop(first=0.0)  # a hit on the very first sample still counts
    first = music.Analysis(x0, rate).onsets("LOW")
    assert len(first) == len(k0) and first[0][0] < 0.005, first[:2]
    bpm = music.tempo(a.onsets("LOW"))
    assert abs(bpm - 120) < 2, bpm
    print(f"analysis of {len(x) / rate:.1f} s in {ms:.0f} ms; tempo {bpm} bpm; envelope rises on kicks and decays")


if __name__ == "__main__":
    test_midi()
    test_onsets()
    print("all music tests passed")
