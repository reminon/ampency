#!/usr/bin/env python3
"""
chart_gen.py — Auto-generate Amplitude MIDI charts from audio files.

Difficulty generation strategy:
1. Detect ALL onsets at maximum sensitivity (expert baseline)
2. Score each onset by strength (amplitude, spectral flux)
3. Thin by difficulty:
   - Hard:   keep top 70%, allow 16th note subdivisions
   - Medium: keep top 45%, allow 8th note subdivisions  
   - Easy:   keep top 25%, quarter notes only
4. Output single MIDI with all difficulty layers (notes 0-47)
   matching Amplitude's format exactly.

Lane unlock timing derived from song energy envelope:
- Detect energy rises to trigger new lane appearances
- Mirrors how Amplitude introduces lanes as songs build

Usage:
    python3 tools/chart_gen.py <audio_file> [--output chart.mid] [--bpm 120]
"""

import sys
import os
import argparse
import numpy as np
import librosa
import mido
from scipy.signal import butter, sosfilt

# ── Amplitude MIDI format ───────────────────────────────────────────────────
# Note encoding: note = difficulty_offset + position
# Easy   = 0-11   (offset 0)
# Medium = 12-23  (offset 12)
# Hard   = 24-35  (offset 24)
# Expert = 36-47  (offset 36)
# Section markers: 96=start, 100=mid, 103=end (always vel=100)

INSTRUMENTS = [
    ('drums',  'D', 1),
    ('bass',   'B', 2),
    ('guitar', 'G', 3),
    ('synth',  'S', 4),
    ('vocal',  'V', 5),
]

DIFF_OFFSET   = {'easy': 0, 'medium': 12, 'hard': 24, 'expert': 36}
DIFF_KEEP     = {'easy': 0.12, 'medium': 0.25, 'hard': 0.45, 'expert': 0.44}
DIFF_MIN_GAP  = {'easy': 1.0,  'medium': 0.5,  'hard': 0.25, 'expert': 0.125}

SECTION_START = 96
SECTION_MID   = 100
SECTION_END   = 103


def bandpass(y, sr, lo, hi):
    nyq = sr / 2
    lo_n = max(lo / nyq, 0.001)
    hi_n = min(hi / nyq, 0.999)
    sos = butter(4, [lo_n, hi_n], btype='band', output='sos')
    return sosfilt(sos, y)


def analyze_audio(path, sr=22050):
    print(f"Loading {path}...")
    y, sr = librosa.load(path, sr=sr, mono=True)
    duration = librosa.get_duration(y=y, sr=sr)
    print(f"Duration: {duration:.1f}s")

    # Tempo and beats
    print("Detecting tempo and beats...")
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units='frames')
    tempo = float(np.atleast_1d(tempo)[0])
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    print(f"Tempo: {tempo:.1f} BPM, {len(beat_times)} beats")

    # Harmonic/percussive separation
    D = librosa.stft(y)
    H, P = librosa.decompose.hpss(D)
    y_harm = librosa.istft(H, length=len(y))
    y_perc = librosa.istft(P, length=len(y))

    # Per-band onset detection with strength scoring
    bands = {
        'drums':  (y_perc, 20,   200),
        'bass':   (y_harm, 80,   500),
        'guitar': (y_harm, 300,  3000),
        'synth':  (y_harm, 800,  8000),
        'vocal':  (y_harm, 150,  3500),
    }

    print("Detecting onsets per band...")
    onsets = {}
    for name, (src, lo, hi) in bands.items():
        band = bandpass(src, sr, lo, hi)
        # Get onset frames AND strength
        onset_env = librosa.onset.onset_strength(y=band, sr=sr)
        onset_frames = librosa.onset.onset_detect(
            onset_envelope=onset_env, sr=sr,
            pre_max=2, post_max=2, pre_avg=5, post_avg=5,
            delta=0.03, wait=2
        )
        times  = librosa.frames_to_time(onset_frames, sr=sr)
        strengths = onset_env[onset_frames]
        onsets[name] = list(zip(times, strengths))
        print(f"  {name}: {len(onsets[name])} onsets")

    # Song energy envelope for lane unlock timing
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
    rms_times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=512)

    return tempo, beat_times, onsets, duration, rms_times, rms


def time_to_beat(t, beat_times):
    if len(beat_times) < 2:
        return t * 2.0
    idx = np.searchsorted(beat_times, t)
    if idx == 0: return 0.0
    if idx >= len(beat_times):
        dt = beat_times[-1] - beat_times[-2]
        return (len(beat_times) - 1) + (t - beat_times[-1]) / dt
    t0, t1 = beat_times[idx-1], beat_times[idx]
    return (idx - 1) + (t - t0) / (t1 - t0)


def quantize(beat, subdivisions):
    step = 1.0 / subdivisions
    return round(beat / step) * step


def thin_onsets(onsets_with_strength, keep_frac, min_gap_beats, beat_times, subdivisions):
    """
    Keep the strongest `keep_frac` fraction of onsets,
    enforcing minimum gap and quantizing to subdivisions.
    """
    if not onsets_with_strength:
        return []

    # Sort by strength descending, pick top fraction
    sorted_by_strength = sorted(onsets_with_strength, key=lambda x: -x[1])
    keep_n = max(1, int(len(sorted_by_strength) * keep_frac))
    candidates = sorted_by_strength[:keep_n]

    # Convert to beats and quantize
    beat_onsets = []
    for t, strength in candidates:
        beat = quantize(time_to_beat(t, beat_times), subdivisions)
        beat_onsets.append((beat, strength))

    # Sort by beat, enforce minimum gap
    beat_onsets.sort(key=lambda x: x[0])
    result = []
    last_beat = -999.0
    for beat, strength in beat_onsets:
        if beat - last_beat >= min_gap_beats:
            result.append(beat)
            last_beat = beat

    return result


def detect_lane_unlocks(rms_times, rms, beat_times, num_lanes=5):
    """
    Detect energy inflection points to determine when new lanes unlock.
    Returns list of beat positions where each additional lane unlocks.
    Lanes 1-2 start active, lanes 3-5 unlock progressively.
    """
    # Smooth RMS
    from scipy.ndimage import uniform_filter1d
    rms_smooth = uniform_filter1d(rms.astype(float), size=20)

    # Find significant energy increases
    diff = np.diff(rms_smooth)
    threshold = np.percentile(diff[diff > 0], 70)
    rises = np.where(diff > threshold)[0]

    # Convert to beat positions, deduplicate (min 8 beats apart)
    unlock_beats = []
    last_beat = 0.0
    for frame in rises:
        if frame >= len(rms_times): continue
        beat = time_to_beat(rms_times[frame], beat_times)
        if beat - last_beat >= 8.0:
            unlock_beats.append(round(beat))
            last_beat = beat
        if len(unlock_beats) >= num_lanes - 2:  # first 2 lanes start active
            break

    return unlock_beats


def generate_midi(tempo, beat_times, onsets, duration, rms_times, rms, output, beat_offset=0.0):
    tpb = 480
    tempo_us = int(60_000_000 / tempo)
    total_beats = time_to_beat(duration, beat_times)

    mid = mido.MidiFile(type=1, ticks_per_beat=tpb)

    # Master track
    master = mido.MidiTrack()
    master.name = 'Master Track'
    mid.tracks.append(master)
    master.append(mido.MetaMessage('set_tempo', tempo=tempo_us, time=0))
    master.append(mido.MetaMessage('time_signature',
                                   numerator=4, denominator=4,
                                   clocks_per_click=24,
                                   notated_32nd_notes_per_beat=8, time=0))
    master.append(mido.MetaMessage('end_of_track', time=0))

    # Detect lane unlock timings
    unlock_beats = detect_lane_unlocks(rms_times, rms, beat_times)
    print(f"\nLane unlock beats: {unlock_beats}")

    # Per-instrument tracks with all difficulty layers
    for track_num, (instr_name, instr_code, _) in enumerate(INSTRUMENTS, 1):
        track = mido.MidiTrack()
        track.name = f"T{track_num} PITCH:D:{instr_code}:{instr_name.upper()}"
        mid.tracks.append(track)

        events = []  # (tick, note, on, velocity)

        # Section markers every 16 beats
        beat = max(0.0, beat_offset)
        phase = 0
        while beat < total_beats + beat_offset:
            marker = [SECTION_START, SECTION_MID, SECTION_END][phase % 3]
            tick = int(beat * tpb)
            events.append((tick, marker, True, 100))
            events.append((tick + tpb * 2, marker, False, 0))
            beat += 16.0
            phase += 1

        # Generate gems for each difficulty
        inst_onsets = onsets.get(instr_name, [])
        subdiv_map = {'easy': 4, 'medium': 8, 'hard': 16, 'expert': 16}

        gem_counts = {}
        for diff in ['easy', 'medium', 'hard', 'expert']:
            gems = thin_onsets(
                inst_onsets,
                keep_frac=DIFF_KEEP[diff],
                min_gap_beats=DIFF_MIN_GAP[diff],
                beat_times=beat_times,
                subdivisions=subdiv_map[diff]
            )
            offset = DIFF_OFFSET[diff]
            gem_counts[diff] = len(gems)

            for i, gem_beat in enumerate(gems):
                note = offset + (i % 12)
                tick = int((gem_beat + beat_offset) * tpb)
                dur  = max(tpb // 8, int(tpb * 0.1))
                events.append((tick,       note, True,  100))
                events.append((tick + dur, note, False, 0))

        print(f"  {instr_name}: easy={gem_counts['easy']} med={gem_counts['medium']} "
              f"hard={gem_counts['hard']} exp={gem_counts['expert']}")

        # Sort and write delta times
        events.sort(key=lambda e: (e[0], not e[2]))
        prev_tick = 0
        for tick, note, on, vel in events:
            delta = tick - prev_tick
            prev_tick = tick
            if on:
                track.append(mido.Message('note_on',  channel=0,
                                          note=note, velocity=vel, time=delta))
            else:
                track.append(mido.Message('note_off', channel=0,
                                          note=note, velocity=0, time=delta))

        track.append(mido.MetaMessage('end_of_track', time=0))

    # WORLD track for lane unlock events
    world = mido.MidiTrack()
    world.name = 'WORLD'
    mid.tracks.append(world)
    prev_tick = 0
    for i, unlock_beat in enumerate(unlock_beats):
        tick = int(unlock_beat * tpb)
        delta = tick - prev_tick
        prev_tick = tick
        # Use note number = lane index (3,4,5,6,7) for unlock events
        world.append(mido.Message('note_on', channel=0,
                                  note=i+3, velocity=100, time=delta))
        world.append(mido.Message('note_off', channel=0,
                                  note=i+3, velocity=0, time=tpb))
    world.append(mido.MetaMessage('end_of_track', time=0))

    mid.save(output)
    print(f"\nSaved: {output}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('audio', help='Audio file (FLAC, MP3, OGG, WAV)')
    ap.add_argument('--output', '-o', default=None)
    ap.add_argument('--bpm', type=float, default=None,
                    help='Override BPM detection')
    ap.add_argument('--start-offset', type=float, default=0.0, dest='start_offset',
                    help='Shift beat times by this many seconds to align with chart')
    ap.add_argument('--intro-beats', type=float, default=16.0, dest='intro_beats',
                    help='Number of beats before first gem (default: 16, matches Amplitude)')
    args = ap.parse_args()

    if not os.path.exists(args.audio):
        print(f"Error: {args.audio} not found"); sys.exit(1)

    if args.output is None:
        base = os.path.splitext(os.path.basename(args.audio))[0]
        args.output = f"{base}_chart.mid"

    tempo, beat_times, onsets, duration, rms_times, rms = analyze_audio(args.audio)

    if args.start_offset != 0.0:
        print(f"Applying start offset: {args.start_offset:+.3f}s")
        # Shift beat times
        beat_times = beat_times + args.start_offset
        beat_times = beat_times[beat_times >= 0]
        # Shift all onset times
        for name in onsets:
            onsets[name] = [(t + args.start_offset, s) for t, s in onsets[name]
                           if t + args.start_offset >= 0]
        rms_times = rms_times + args.start_offset

    if args.bpm:
        print(f"BPM override: {args.bpm}")
        tempo = args.bpm
        # Recompute beat_times with fixed BPM
        beat_times = np.arange(0, duration, 60.0/tempo)

    # Compute beat offset: how many beats to add to align audio with chart
    # Positive = audio starts before chart beat 0
    beat_offset = args.start_offset * tempo / 60.0 + args.intro_beats
    print(f"Beat offset: {beat_offset:.2f} beats (includes {args.intro_beats} intro beats)")
    print(f"\nGenerating chart for all difficulties...")
    generate_midi(tempo, beat_times, onsets, duration,
                  rms_times, rms, args.output, beat_offset=beat_offset)


if __name__ == '__main__':
    main()
