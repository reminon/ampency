#!/usr/bin/env python3
"""
decode_stems.py - Decode Amplitude NSE audio stems to WAV.

Run once per song to cache decoded stems locally.
NSE files are PS2 SPU ADPCM encoded, 22050Hz mono.

Usage:
    python3 tools/decode_stems.py <song_dir> [--output-dir <dir>]
"""

import sys, os, struct, wave, array, argparse, math

FILTER_POS = [0.0, 0.9375, 1.796875, 1.53125, 1.90625]
FILTER_NEG = [0.0, 0.0,   -0.8125,  -0.859375, -0.9375]

def decode_nse(path, sr=22050):
    with open(path, 'rb') as f:
        data = f.read()
    samples = []
    p1 = p2 = 0.0
    pos = 0
    while pos + 16 <= len(data):
        block = data[pos:pos+16]
        shift = max(0, 12 - (block[0] & 0x0f))
        filt  = min((block[0] >> 4) & 0x07, 4)
        flags = block[1]
        f0, f1 = FILTER_POS[filt], FILTER_NEG[filt]
        for j in range(2, 16):
            for nibble in [block[j] & 0x0f, (block[j] >> 4) & 0x0f]:
                s = (nibble-16 if nibble>=8 else nibble) * (1<<shift)
                s = int(s + f0*p1 + f1*p2)
                s = max(-32768, min(32767, s))
                samples.append(s)
                p2, p1 = p1, float(s)
        pos += 16
        if flags & 0x01:
            p1 = p2 = 0.0  # reset at sample boundaries
    return samples, sr

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('song_dir')
    ap.add_argument('--output-dir', '-o', default=None)
    args = ap.parse_args()

    out_dir = args.output_dir or os.path.join(args.song_dir, 'wav')
    os.makedirs(out_dir, exist_ok=True)

    nse_files = sorted([f for f in os.listdir(args.song_dir)
                        if f.endswith('.nse') and '_s_1' in f])
    if not nse_files:
        print(f"No NSE stem files in {args.song_dir}"); sys.exit(1)

    print(f"Decoding {len(nse_files)} stems -> {out_dir}/")
    for nse in nse_files:
        samples, sr = decode_nse(os.path.join(args.song_dir, nse))
        out = os.path.join(out_dir, nse.replace('.nse', '.wav'))
        with wave.open(out, 'w') as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sr)
            wf.writeframes(array.array('h', samples).tobytes())
        dur = len(samples)/sr
        rms = math.sqrt(sum(s*s for s in samples)/len(samples)) if samples else 0
        print(f"  {nse}: {dur:.1f}s RMS={rms:.0f}")
    print("Done.")

if __name__ == '__main__':
    main()
