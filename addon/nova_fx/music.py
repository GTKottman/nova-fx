"""Music analysis: note events from MIDI files, onsets and envelopes from audio. No Blender imports, so the
tests run it standalone.

Everything comes out in seconds from the start of the song. music_sync.py turns that into scene frames.

Audio onsets use spectral flux per frequency band (log-compressed magnitude, positive differences only),
picked with a local-maximum + moving-average threshold (Böck et al. 2012) and a minimum gap. Bands:
  LOW  30-150 Hz    kick drum, bass
  MID  150-2500 Hz  snare body, vocals, most instruments
  HIGH 5-16 kHz     hats, cymbals, the snare's crack
  ALL  everything
"""

import os
import re
import struct
import wave

import numpy as np

BANDS = {"LOW": (30.0, 150.0), "MID": (150.0, 2500.0), "HIGH": (5000.0, 16000.0), "ALL": (30.0, 16000.0)}
NOTE_NAMES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


# ------------------------------------------------------------------ MIDI

class MidiError(ValueError):
    pass


def _vlq(data, i):
    v = 0
    while True:
        if i >= len(data):
            raise MidiError("truncated variable-length number")
        b = data[i]
        i += 1
        v = (v << 7) | (b & 0x7F)
        if not b & 0x80:
            return v, i


def read_midi(path):
    """Notes of a Standard MIDI File (format 0 or 1) as a list of dicts:
    start, end (seconds), pitch, velocity (0-1), channel (1-16), track (index), track_name.
    Tempo changes anywhere in the file apply to every track."""
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:4] != b"MThd":
        raise MidiError(f"not a MIDI file: {os.path.basename(path)}")
    hlen = struct.unpack(">I", data[4:8])[0]
    _fmt, ntrk, div = struct.unpack(">HHH", data[8:14])
    if div & 0x8000:
        raise MidiError("SMPTE time division is not supported (export with ticks per beat)")
    i = 8 + hlen
    tempos = []  # (tick, microseconds per quarter)
    raw = []  # (tick, kind, pitch, velocity, channel, track)
    names = []
    for t in range(ntrk):
        while i + 8 <= len(data) and data[i:i + 4] != b"MTrk":  # skip unknown chunks
            i += 8 + struct.unpack(">I", data[i + 4:i + 8])[0]
        if i + 8 > len(data):
            break
        ln = struct.unpack(">I", data[i + 4:i + 8])[0]
        j, end = i + 8, i + 8 + ln
        i = end
        tick, status, name = 0, 0, ""
        while j < end:
            dt, j = _vlq(data, j)
            tick += dt
            b = data[j]
            if b & 0x80:
                status = b
                j += 1
            elif status == 0:
                raise MidiError("running status without a status byte")
            if status == 0xFF:
                mtype = data[j]
                ml, j = _vlq(data, j + 1)
                body = data[j:j + ml]
                j += ml
                if mtype == 0x51 and ml == 3:
                    tempos.append((tick, (body[0] << 16) | (body[1] << 8) | body[2]))
                elif mtype == 0x03 and not name:
                    name = body.decode("latin-1", errors="replace")
                elif mtype == 0x2F:
                    break
                status = 0
            elif status in (0xF0, 0xF7):
                ml, j = _vlq(data, j)
                j += ml
                status = 0
            else:
                hi, ch = status & 0xF0, status & 0x0F
                if hi in (0xC0, 0xD0):
                    j += 1
                    continue
                d1, d2 = data[j], data[j + 1]
                j += 2
                if hi == 0x90 and d2 > 0:
                    raw.append((tick, 1, d1, d2, ch + 1, t))
                elif hi == 0x80 or (hi == 0x90 and d2 == 0):
                    raw.append((tick, 0, d1, 0, ch + 1, t))
        names.append(name)

    tempos.sort()
    if not tempos or tempos[0][0] > 0:
        tempos.insert(0, (0, 500000))
    # piecewise-linear tick -> seconds
    seg_tick = np.array([tk for tk, _ in tempos], np.float64)
    seg_us = np.array([us for _, us in tempos], np.float64)
    seg_sec = np.zeros(len(tempos))
    for k in range(1, len(tempos)):
        seg_sec[k] = seg_sec[k - 1] + (seg_tick[k] - seg_tick[k - 1]) * seg_us[k - 1] / 1e6 / div

    def sec(tick):
        k = int(np.searchsorted(seg_tick, tick, side="right") - 1)
        return float(seg_sec[k] + (tick - seg_tick[k]) * seg_us[k] / 1e6 / div)

    notes, held = [], {}
    for tick, on, pitch, vel, ch, trk in sorted(raw, key=lambda r: (r[0], r[1])):  # note-offs first per tick
        key = (trk, ch, pitch)
        if on:
            held.setdefault(key, []).append((tick, vel))
        elif held.get(key):
            t0, v = held[key].pop(0)
            notes.append(dict(start=sec(t0), end=sec(tick), pitch=pitch, velocity=v / 127.0, channel=ch,
                              track=trk, track_name=names[trk] if trk < len(names) else ""))
    for (trk, ch, pitch), rest in held.items():  # never released: one beat long
        for t0, v in rest:
            notes.append(dict(start=sec(t0), end=sec(t0 + div), pitch=pitch, velocity=v / 127.0, channel=ch,
                              track=trk, track_name=names[trk] if trk < len(names) else ""))
    notes.sort(key=lambda n: (n["start"], n["pitch"]))
    return notes


def parse_pitch(tok):
    """'36' or a note name with C4 = 60 ('C1', 'F#2', 'Bb3', 'c-1')."""
    tok = tok.strip()
    if re.fullmatch(r"-?\d+", tok):
        return int(tok)
    m = re.fullmatch(r"([A-Ga-g])([#b]?)(-?\d+)", tok)
    if not m:
        raise ValueError(f"not a note: {tok!r}")
    p = NOTE_NAMES[m.group(1).upper()] + {"#": 1, "b": -1, "": 0}[m.group(2)]
    return p + 12 * (int(m.group(3)) + 1)


def parse_notes(spec):
    """'36', '36-38', 'C1,D1', 'F#2-A2' -> set of pitches, or None for any note."""
    spec = (spec or "").strip()
    if not spec:
        return None
    out = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(.+?)\s*-\s*([A-Ga-g][#b]?-?\d+|\d+)", part) if not re.fullmatch(r"-?\d+", part) else None
        if m:
            a, b = parse_pitch(m.group(1)), parse_pitch(m.group(2))
            out.update(range(min(a, b), max(a, b) + 1))
        else:
            out.add(parse_pitch(part))
    return out


def filter_notes(notes, pitches=None, channel=0, track=""):
    """pitches: set or None; channel 0 = any; track: index ('2') or part of the track name, '' = any."""
    track = (track or "").strip()
    out = []
    for n in notes:
        if pitches is not None and n["pitch"] not in pitches:
            continue
        if channel and n["channel"] != channel:
            continue
        if track:
            if track.isdigit():
                if n["track"] != int(track):
                    continue
            elif track.lower() not in n["track_name"].lower():
                continue
        out.append(n)
    return out


def note_hits(notes, min_gap=0.0):
    """Note-ons as (time, strength); chords (onsets within 15 ms) count once at their loudest."""
    hits = []
    for n in notes:
        t, v = n["start"], n["velocity"]
        if hits and t - hits[-1][0] < max(min_gap, 0.015):
            if v > hits[-1][1] and t - hits[-1][0] < 0.015:
                hits[-1] = (hits[-1][0], v)
            continue
        hits.append((t, v))
    return hits


def note_envelope(notes, times, release=0.15):
    """Gate of held notes (loudest velocity), with an exponential release after the note ends."""
    env = np.zeros(len(times))
    for n in notes:
        on = (times >= n["start"]) & (times < n["end"])
        env[on] = np.maximum(env[on], n["velocity"])
        if release > 0:
            after = times >= n["end"]
            tail = n["velocity"] * np.exp(-(times[after] - n["end"]) / release)
            env[after] = np.maximum(env[after], tail)
    return env


# ------------------------------------------------------------------ audio

def read_audio(path):
    """Mono float32 samples and the sample rate. Any format Blender can play (through aud); plain WAV
    without Blender."""
    try:
        import aud
        snd = aud.Sound(path)
        rate = int(snd.specs[0])
        data = np.asarray(snd.data(), np.float32)
        mono = data.mean(axis=1) if data.ndim == 2 else data
        return np.ascontiguousarray(mono, np.float32), rate
    except ImportError:
        pass
    with wave.open(path, "rb") as w:
        ch, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if width == 1:
        a = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128) / 128
    elif width == 2:
        a = np.frombuffer(raw, "<i2").astype(np.float32) / 32768
    elif width == 3:
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
        a = ((b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)) << 8 >> 8).astype(np.float32) / 8388608
    else:
        a = np.frombuffer(raw, "<i4").astype(np.float32) / 2147483648
    return a.reshape(-1, ch).mean(axis=1).astype(np.float32), rate


class Analysis:
    """Per-band spectral flux and energy of a song at ~10 ms resolution."""

    def __init__(self, samples, rate, n_fft=2048):
        hop = max(64, int(round(rate * 0.01)))
        self.rate, self.hop, self.dt = rate, hop, hop / rate
        # a centred window sees a transient before it happens: flux peaks ~0.45 half-windows early
        self.latency = 0.45 * (n_fft / 2) / rate
        self.duration = len(samples) / rate
        # centred frames: frame k is the window around sample k*hop - lead. The lead of silence lets a hit
        # right at the start of the song register as an onset
        lead = int(np.ceil(n_fft / hop)) * hop
        x = np.concatenate([np.zeros(n_fft // 2 + lead, np.float32), samples, np.zeros(n_fft, np.float32)])
        nfr = max(1, (len(x) - n_fft) // hop + 1)
        win = np.hanning(n_fft).astype(np.float32)
        freqs = np.fft.rfftfreq(n_fft, 1.0 / rate)
        masks = {b: (freqs >= lo) & (freqs < hi) for b, (lo, hi) in BANDS.items()}
        flux = {b: np.zeros(nfr, np.float32) for b in BANDS}
        energy = {b: np.zeros(nfr, np.float32) for b in BANDS}
        # per-bin noise floor (20th percentile over a sample of frames): steady hiss and the step from the
        # silent lead-in into a noisy recording are not onsets
        pick = np.arange(0, nfr, max(1, nfr // 400))
        idx = pick[:, None] * hop + np.arange(n_fft)[None, :]
        floor = 2.0 * np.percentile(np.abs(np.fft.rfft(x[idx] * win, axis=1)), 20, axis=0).astype(np.float32)
        prev = None
        chunk = 1024
        for c0 in range(0, nfr, chunk):
            c1 = min(nfr, c0 + chunk)
            idx = (np.arange(c0, c1)[:, None] * hop + np.arange(n_fft)[None, :])
            mag = np.abs(np.fft.rfft(x[idx] * win, axis=1)).astype(np.float32)
            logm = np.log1p(100.0 * np.maximum(0.0, mag - floor))
            first = logm[:1] if prev is None else prev
            diff = np.maximum(0.0, logm - np.concatenate([first, logm[:-1]], axis=0))
            prev = logm[-1:]
            p = mag * mag
            for b, m in masks.items():
                flux[b][c0:c1] = diff[:, m].sum(axis=1)
                energy[b][c0:c1] = np.sqrt(p[:, m].sum(axis=1))
        self.flux, self.energy = flux, energy
        self.times = np.arange(nfr) * self.dt - lead / rate

    def onsets(self, band="ALL", threshold=0.3, min_gap=0.08):
        """(time, strength 0-1) of the band's onsets. threshold: 0 = every bump, 1 = only the biggest hits."""
        f = self.flux[band].astype(np.float64)
        top = np.percentile(f, 99.5) if len(f) else 0.0
        if top <= 1e-9:
            return []
        f = f / top
        n = len(f)
        w_max = max(1, int(round(0.03 / self.dt)))  # local maximum over +-30 ms
        w_avg = max(1, int(round(0.1 / self.dt)))  # moving average over the previous 100 ms
        pad = np.pad(f, w_max, mode="edge")
        win = np.lib.stride_tricks.sliding_window_view(pad, 2 * w_max + 1)
        local_max = win.max(axis=1)
        csum = np.concatenate([[0.0], np.cumsum(f)])
        lo = np.maximum(0, np.arange(n) - w_avg)
        avg = (csum[np.arange(n) + 1] - csum[lo]) / (np.arange(n) + 1 - lo)
        # a hit must stand out from the last 100 ms and reach `threshold` of the song's loud hits
        cand = np.nonzero((f >= local_max - 1e-12) & (f >= avg + 0.05) & (f >= max(threshold, 1e-6)))[0]
        hits, last = [], -1e9
        for k in cand:
            t = self.times[k]
            if t - last < min_gap:
                continue
            # parabolic peak refinement: sub-hop timing
            if 0 < k < n - 1:
                a, b, c = f[k - 1], f[k], f[k + 1]
                den = a - 2 * b + c
                t += (0.5 * (a - c) / den if abs(den) > 1e-12 else 0.0) * self.dt
            hits.append((max(0.0, float(t + self.latency)), float(min(1.0, f[k]))))
            last = t
        return hits

    def envelope(self, band, times, attack=0.01, release=0.2):
        """Band loudness (0-1, 1 = the song's loud parts) at `times`, smoothed with attack/release."""
        e = self.energy[band].astype(np.float64)
        top = np.percentile(e, 98) if len(e) else 0.0
        e = np.clip(e / top, 0, 1) if top > 1e-12 else e * 0
        ka = 1 - np.exp(-self.dt / max(attack, 1e-4))
        kr = 1 - np.exp(-self.dt / max(release, 1e-4))
        out = np.empty_like(e)
        y = 0.0
        for k, v in enumerate(e):
            y += (v - y) * (ka if v > y else kr)
            out[k] = y
        return np.interp(times, self.times, out, left=0.0, right=0.0)


def tempo(hits, lo=60.0, hi=200.0):
    """Rough BPM from onset times (autocorrelation of an impulse train), or 0 if unclear."""
    if len(hits) < 8:
        return 0.0
    dt = 0.01
    t = np.array([h[0] for h in hits])
    train = np.zeros(int(t.max() / dt) + 2)
    np.add.at(train, (t / dt).astype(int), [h[1] for h in hits])
    ac = np.correlate(train, train, "full")[len(train) - 1:]
    lags = np.arange(len(ac)) * dt
    m = (lags >= 60.0 / hi) & (lags <= 60.0 / lo)
    if not m.any() or ac[m].max() <= 0:
        return 0.0
    lag = lags[m][np.argmax(ac[m])]
    return round(60.0 / lag, 1)
