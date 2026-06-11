#!/usr/bin/env python3
"""
Amplitude MIDI chart parser.

Track naming: T{n} {TYPE}:{DIFFICULTY}:{INSTRUMENT}
  TYPE: PITCH, VOX
  DIFFICULTY: D=default, E=easy, M=medium, H=hard, X=expert  
  INSTRUMENT: D=Drums, B=Bass, V=Vocal, S=Synth, G=Guitar

Pitch encoding (PITCH tracks):
  0-47:  gem positions within the bar
  96:    section start marker (vel=100)
  100:   section mid marker (vel=100)
  103:   section end marker (vel=100)

Usage:
  python3 tools/midi_parse.py <song_dir>
"""

import struct, sys, os
from collections import defaultdict

SECTION_MARKERS = {96, 100, 103}

INSTRUMENT_CODES = {
    'D': 'drums',
    'B': 'bass', 
    'V': 'vocal',
    'S': 'synth',
    'G': 'guitar',
    'F': 'fx',
}

def read_varint(data, pos):
    val = 0
    while True:
        b = data[pos]; pos += 1
        val = (val << 7) | (b & 0x7f)
        if not (b & 0x80): break
    return val, pos

def parse_midi(path):
    with open(path, 'rb') as f:
        data = f.read()
    
    if data[:4] != b'MThd':
        raise ValueError("Not a MIDI file")
    
    fmt = struct.unpack_from('>HHH', data, 8)
    ticks_per_beat = fmt[2]
    
    # Parse all tracks
    tracks = []
    pos = 14
    while pos < len(data) - 8:
        chunk_type = data[pos:pos+4]
        chunk_len = struct.unpack_from('>I', data, pos+4)[0]
        if chunk_type != b'MTrk':
            pos += 8 + chunk_len
            continue
        
        track_end = pos + 8 + chunk_len
        tp = pos + 8
        tick = 0
        last_status = 0
        name = ''
        tempo = 500000  # default 120 BPM
        notes = []  # (tick, note, vel, duration_ticks)
        active = {}  # note -> start_tick
        
        while tp < track_end:
            delta, tp = read_varint(data, tp)
            tick += delta
            
            if tp >= track_end: break
            
            if data[tp] & 0x80:
                last_status = data[tp]; tp += 1
            status = last_status
            
            if status == 0xff:
                if tp >= track_end: break
                meta_type = data[tp]; tp += 1
                meta_len, tp = read_varint(data, tp)
                meta_data = data[tp:tp+meta_len]; tp += meta_len
                if meta_type == 0x03:
                    name = meta_data.decode('ascii', errors='replace')
                elif meta_type == 0x51:
                    tempo = struct.unpack('>I', b'\x00' + meta_data[:3])[0]
                elif meta_type == 0x2f:
                    break
            elif (status & 0xf0) == 0x90:
                note = data[tp]; tp += 1
                vel = data[tp]; tp += 1
                if vel > 0:
                    active[note] = tick
                else:
                    if note in active:
                        dur = tick - active.pop(note)
                        notes.append((active.get(note, tick), note, vel, dur))
            elif (status & 0xf0) == 0x80:
                note = data[tp]; tp += 1
                vel = data[tp]; tp += 1
                if note in active:
                    dur = tick - active.pop(note)
                    notes.append((tick, note, vel, dur))
            elif (status & 0xf0) in (0xa0, 0xb0, 0xe0):
                tp += 2
            elif (status & 0xf0) in (0xc0, 0xd0):
                tp += 1
            elif status in (0xf0, 0xf7):
                slen, tp2 = read_varint(data, tp)
                tp = tp2 + slen
            
        tracks.append({
            'name': name,
            'tempo': tempo,
            'notes': sorted(notes),
            'ticks_per_beat': ticks_per_beat,
        })
        pos += 8 + chunk_len
    
    return tracks, ticks_per_beat

def parse_track_name(name):
    """Parse 'T1 PITCH:D:DRUMS' into components."""
    parts = name.split(' ', 1)
    if len(parts) < 2: return None
    track_num = parts[0].lstrip('T')
    rest = parts[1].split(':')
    if len(rest) < 2: return None
    return {
        'num': track_num,
        'type': rest[0],
        'difficulty': rest[1],
        'instrument': INSTRUMENT_CODES.get(rest[2][0], rest[2].lower()) if len(rest) > 2 and rest[2] else 'unknown',
    }

def ticks_to_seconds(ticks, ticks_per_beat, tempo):
    return ticks * tempo / (ticks_per_beat * 1_000_000)

def extract_gems(track, ticks_per_beat):
    """Extract gem events from a PITCH track."""
    gems = []
    sections = []
    tempo = track['tempo']
    
    for tick, note, vel, dur in track['notes']:
        beat = tick / ticks_per_beat
        seconds = ticks_to_seconds(tick, ticks_per_beat, tempo)
        
        if note in SECTION_MARKERS:
            sections.append({'tick': tick, 'beat': beat, 'marker': note})
        else:
            # Note 0-47: gem position
            # Lower notes (0-11 or 0-23) seem to be the primary gem lane
            # Higher notes (32-47) may be a parallel difficulty layer
            gems.append({
                'tick': tick,
                'beat': beat,
                'seconds': seconds,
                'note': note,
                'velocity': vel,
                'duration_ticks': dur,
            })
    
    return gems, sections

def main():
    if len(sys.argv) < 2:
        print("Usage: midi_parse.py <song_dir_or_mid_file>")
        sys.exit(1)
    
    path = sys.argv[1]
    if os.path.isdir(path):
        mid_files = [f for f in os.listdir(path) if f.endswith('.mid')]
    else:
        mid_files = [path]
        path = os.path.dirname(path)
    
    for mid_file in sorted(mid_files):
        mid_path = os.path.join(path, mid_file) if os.path.isdir(sys.argv[1]) else mid_file
        print(f"\n=== {mid_file} ===")
        
        try:
            tracks, tpb = parse_midi(mid_path)
        except Exception as e:
            print(f"Error: {e}")
            continue
        
        for track in tracks:
            info = parse_track_name(track['name'])
            if not info: continue
            if track['name'].startswith('T') and 'PITCH' in track['name']:
                gems, sections = extract_gems(track, tpb)
                bpm = 60_000_000 // track['tempo']
                print(f"\n  {track['name']} ({bpm} BPM)")
                print(f"  {len(gems)} gems, {len(sections)} section markers")
                print(f"  Gem note range: {min(g['note'] for g in gems) if gems else 'n/a'}"
                      f" - {max(g['note'] for g in gems) if gems else 'n/a'}")
                print(f"  First 5 gems:")
                for g in gems[:5]:
                    print(f"    beat={g['beat']:7.3f} note={g['note']:3d} vel={g['velocity']}")

if __name__ == '__main__':
    main()
