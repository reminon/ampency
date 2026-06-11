#!/usr/bin/env python3
"""
chart_gen.py — Auto-generate Amplitude MIDI charts from audio files.

Difficulty generation strategy:
1. Compute beat-synchronous spectral flux per frequency band (16th note grid)
2. Use adaptive thresholding to detect chartable events per instrument
3. Generate all 4 difficulty layers in one pass:
   - Expert: full density (offset 36-47)
   - Hard:   70% density (offset 24-35)
   - Medium: 45% density (offset 12-23)
   - Easy:   25% density (offset 0-11)
4. Output single MIDI with all difficulty layers matching Amplitude format

Phase detection: cross-correlates onset envelope with fixed-BPM beat grid
to find the optimal beat phase, then uses intro-beats offset to align
the chart with Amplitude's convention (first gem at beat 16).

Usage:
    python3 tools/chart_gen.py <audio_file> [options]

Options:
    --output, -o        Output MIDI file (default: <audio>_chart.mid)
    --bpm               Override BPM detection
    --start-offset      Audio time offset in seconds for beat phase alignment
    --intro-beats       Beats before first gem (default: 16.0)

Example:
    python3 tools/chart_gen.py song.flac --bpm 128 --start-offset 0.232 --intro-beats 13.26
"""

import sys
import os
import argparse
import numpy as np
import librosa
import mido
from scipy.signal import butter, sosfilt
from scipy.ndimage import uniform_filter1d

# ── Amplitude MIDI format constants ────────────────────────────────────────
INSTRUMENTS = [
    ('drums',  'D', 1),
    ('bass',   'B', 2),
    ('guitar', 'G', 3),
    ('synth',  'S', 4),
    ('vocal',  'V', 5),
]

DIFF_OFFSET  = {'easy': 0, 'medium': 12, 'hard': 24, 'expert': 36}
DIFF_WINDOWS = {'easy': 64, 'medium': 48, 'hard': 32, 'expert': 24}
DIFF_THRESH  = {'easy': 2.5, 'medium': 1.8, 'hard': 1.3, 'expert': 1.0}
DIFF_GAP     = {'easy': 4,   'medium': 2,   'hard': 1,   'expert': 1}

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

    # Tempo detection
    print("Detecting tempo and beats...")
    tempo_arr, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units='frames')
    tempo = float(np.atleast_1d(tempo_arr)[0])
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    print(f"Tempo: {tempo:.1f} BPM, {len(beat_times)} beats")

    # Harmonic/percussive separation
    D = librosa.stft(y)
    H, P = librosa.decompose.hpss(D)
    y_harm = librosa.istft(H, length=len(y))
    y_perc = librosa.istft(P, length=len(y))

    # Frequency bands per instrument
    band_defs = {
        'drums':  (y_perc, 20,   200),
        'bass':   (y_harm, 80,   500),
        'guitar': (y_harm, 300,  3000),
        'synth':  (y_harm, 800,  8000),
        'vocal':  (y_harm, 200,  3500),
    }

    # Compute spectral flux on 16th-note grid
    print("Computing spectral flux per band...")
    hop = 512
    S = np.abs(librosa.stft(y, hop_length=hop))
    freqs = librosa.fft_frequencies(sr=sr)

    beat_period = 60.0 / tempo
    subdiv_step = beat_period / 4  # 16th notes
    flux_grid = np.arange(0, duration, subdiv_step)  # in seconds

    def band_flux(src, lo, hi):
        band_y = bandpass(src, sr, lo, hi)
        S_band = np.abs(librosa.stft(band_y, hop_length=hop))
        flux = np.sum(np.maximum(0, np.diff(S_band, axis=1)), axis=0)
        flux = np.concatenate([[0], flux])
        if flux.max() > 0:
            flux = flux / flux.max()
        # Sample at grid points
        result = []
        for t in flux_grid:
            f = int(t * sr / hop)
            result.append(float(flux[min(f, len(flux) - 1)]))
        return np.array(result)

    fluxes = {}
    for name, (src, lo, hi) in band_defs.items():
        fluxes[name] = band_flux(src, lo, hi)
        print(f"  {name}: {len(flux_grid)} grid points")

    # RMS energy for lane unlock detection
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
    rms_times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=512)

    return tempo, beat_times, duration, rms_times, rms, flux_grid, fluxes, subdiv_step


def detect_lane_unlocks(rms_times, rms, beat_times, tempo, num_lanes=5):
    rms_smooth = uniform_filter1d(rms.astype(float), size=20)
    diff = np.diff(rms_smooth)
    threshold = np.percentile(diff[diff > 0], 70)
    rises = np.where(diff > threshold)[0]

    unlock_beats = []
    last_beat = 0.0
    for frame in rises:
        if frame >= len(rms_times):
            continue
        t = rms_times[frame]
        idx = np.searchsorted(beat_times, t)
        beat = float(idx)
        if beat - last_beat >= 8.0:
            unlock_beats.append(round(beat))
            last_beat = beat
        if len(unlock_beats) >= num_lanes - 2:
            break
    return unlock_beats


def generate_midi(tempo, beat_times, duration, rms_times, rms,
                  flux_grid, fluxes, subdiv_step, output, beat_offset=0.0):
    tpb = 480
    tempo_us = int(60_000_000 / tempo)
    total_beats = duration * tempo / 60.0

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

    # Lane unlock track
    unlock_beats = detect_lane_unlocks(rms_times, rms, beat_times, tempo)
    print(f"Lane unlock beats: {unlock_beats}")

    world = mido.MidiTrack()
    world.name = 'WORLD'
    mid.tracks.append(world)
    prev = 0
    for i, ub in enumerate(unlock_beats):
        tick = int((ub + beat_offset) * tpb)
        if tick < 0:
            continue
        delta = tick - prev
        prev = tick
        world.append(mido.Message('note_on', channel=0, note=i+3, velocity=100, time=delta))
        world.append(mido.Message('note_off', channel=0, note=i+3, velocity=0, time=tpb))
    world.append(mido.MetaMessage('end_of_track', time=0))

    # Instrument tracks
    for instr_name, instr_code, _ in INSTRUMENTS:
        track = mido.MidiTrack()
        track.name = f"T PITCH:D:{instr_code}:{instr_name.upper()}"
        mid.tracks.append(track)

        events = []

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

        # Gems per difficulty using spectral flux
        flux = fluxes.get(instr_name, np.zeros(len(flux_grid)))
        gem_counts = {}

        for diff in ['easy', 'medium', 'hard', 'expert']:
            offset = DIFF_OFFSET[diff]
            local_mean = uniform_filter1d(flux.astype(float), size=DIFF_WINDOWS[diff])
            mask = flux > (local_mean * DIFF_THRESH[diff] + 0.01)

            gem_indices = []
            last = -999
            for ii, m in enumerate(mask):
                if m and ii - last >= DIFF_GAP[diff]:
                    gem_indices.append(ii)
                    last = ii

            # flux_grid is in seconds; convert to beats then add offset
            gems_beats = [flux_grid[ii] * tempo / 60.0 for ii in gem_indices]
            gem_counts[diff] = len(gems_beats)

            for i, gem_beat in enumerate(gems_beats):
                note = offset + (i % 12)
                tick = int((gem_beat + beat_offset) * tpb)
                if tick < 0:
                    continue
                dur = max(tpb // 8, int(tpb * 0.1))
                events.append((tick,       note, True,  100))
                events.append((tick + dur, note, False, 0))

        print(f"  {instr_name}: easy={gem_counts['easy']} "
              f"med={gem_counts['medium']} "
              f"hard={gem_counts['hard']} "
              f"exp={gem_counts['expert']}")

        # Write delta times
        events.sort(key=lambda e: (e[0], not e[2]))
        prev_tick = 0
        for tick, note, on, vel in events:
            delta = tick - prev_tick
            prev_tick = tick
            if on:
                track.append(mido.Message('note_on', channel=0,
                                          note=note, velocity=vel, time=delta))
            else:
                track.append(mido.Message('note_off', channel=0,
                                          note=note, velocity=0, time=delta))
        track.append(mido.MetaMessage('end_of_track', time=0))

    mid.save(output)
    print(f"\nSaved: {output}")


def main():
    ap = argparse.ArgumentParser(
        description='Generate Amplitude MIDI charts from audio')
    ap.add_argument('audio', help='Audio file (FLAC, MP3, OGG, WAV)')
    ap.add_argument('--output', '-o', default=None)
    ap.add_argument('--bpm', type=float, default=None,
                    help='Override BPM detection')
    ap.add_argument('--start-offset', type=float, default=0.0, dest='start_offset',
                    help='Audio time offset in seconds for beat phase alignment')
    ap.add_argument('--intro-beats', type=float, default=16.0, dest='intro_beats',
                    help='Beats before first gem (default: 16.0)')
    args = ap.parse_args()

    if not os.path.exists(args.audio):
        print(f"Error: {args.audio} not found")
        sys.exit(1)

    if args.output is None:
        base = os.path.splitext(os.path.basename(args.audio))[0]
        args.output = f"{base}_chart.mid"

    (tempo, beat_times, duration,
     rms_times, rms, flux_grid, fluxes, subdiv_step) = analyze_audio(args.audio)

    if args.bpm:
        print(f"BPM override: {args.bpm}")
        tempo = args.bpm
        beat_period = 60.0 / tempo
        beat_times = np.arange(0, duration, beat_period)
        # Recompute 16th-note grid at new tempo
        subdiv_step = beat_period / 4
        flux_grid = np.arange(0, duration, subdiv_step)

    if args.start_offset != 0.0:
        print(f"Applying audio offset: {args.start_offset:+.3f}s")
        beat_times = beat_times + args.start_offset
        beat_times = beat_times[beat_times >= 0]

    beat_offset = args.start_offset * tempo / 60.0 + args.intro_beats
    print(f"Beat offset: {beat_offset:.2f} beats "
          f"(includes {args.intro_beats:.2f} intro beats)")

    print(f"\nGenerating chart...")
    generate_midi(tempo, beat_times, duration, rms_times, rms,
                  flux_grid, fluxes, subdiv_step,
                  args.output, beat_offset=beat_offset)


if __name__ == '__main__':
    main()
