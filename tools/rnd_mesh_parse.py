#!/usr/bin/env python3
"""
rnd_mesh_parse.py — Extract Mesh and Cam objects from Amplitude RND files.

The RND object data section packs objects back-to-back with no per-object
size headers. Object names are length-prefixed strings. After a name string
of non-multiple-of-4 length, subsequent binary data is byte-misaligned, so
this parser tracks byte position exactly rather than assuming 4-byte alignment.

Vertex format (56 bytes):
    pos[3] f32, pad f32, normal[3] f32, pad f32, rgb[3] f32, a f32, uv[2] f32

Usage:
    python3 rnd_mesh_parse.py <file.rnd> [--obj OUTPUT.obj]
"""

import struct
import zlib
import sys
import argparse

DEADDEAD = 0xDEADDEAD


def decompress_rnd(path):
    """Load and decompress an Amplitude RND file. Returns the payload bytes."""
    with open(path, 'rb') as f:
        raw = f.read()
    magic = struct.unpack_from('<I', raw, 0)[0]
    if magic in (0xCCBEDEAF, 0xCABEDEAF):
        header_size = struct.unpack_from('<I', raw, 4)[0]
        return zlib.decompress(raw[header_size:], 47)
    # Frequency v6: uncompressed
    return raw


def parse_manifest(dec):
    """Parse the object manifest. Returns (manifest, data_start_offset)."""
    obj_count = struct.unpack_from('<I', dec, 4)[0]
    pos = 8
    manifest = []
    for _ in range(obj_count):
        tlen = struct.unpack_from('<I', dec, pos)[0]
        pos += 4
        t = dec[pos:pos+tlen].decode('latin-1')
        pos += tlen
        nlen = struct.unpack_from('<I', dec, pos)[0]
        pos += 4
        n = dec[pos:pos+nlen].decode('latin-1')
        pos += nlen
        manifest.append((t, n))
    return manifest, pos


def find_vertices(data, search_start=0):
    """
    Locate vertex blocks in the data section by detecting the 56-byte
    stride quad pattern. Returns a list of (offset, vertex_count, vertices).
    Each vertex is a dict with pos, normal, color, alpha, uv.
    """
    results = []
    i = search_start
    n = len(data)
    while i < n - 56:
        # A vertex block is preceded by a u32 count. Heuristic: try reading
        # a plausible vertex at each byte offset and validate the stride.
        try:
            v0 = read_vertex(data, i)
        except struct.error:
            i += 1
            continue
        # Validate: position components in a reasonable range, normal ~unit
        if is_plausible_vertex(v0):
            block = try_read_block(data, i)
            if block and len(block) >= 3:
                results.append((i, len(block), block))
                # Skip past this block
                i += len(block) * 56
                continue
        i += 1
    return results


def read_vertex(data, off):
    vals = struct.unpack_from('<14f', data, off)
    return {
        'pos':    (vals[0], vals[1], vals[2]),
        'normal': (vals[4], vals[5], vals[6]),
        'color':  (vals[8], vals[9], vals[10]),
        'alpha':  vals[11],
        'uv':     (vals[12], vals[13]),
    }


def is_plausible_vertex(v):
    px, py, pz = v['pos']
    if not all(abs(c) < 1000 for c in (px, py, pz)):
        return False
    nx, ny, nz = v['normal']
    nlen = (nx*nx + ny*ny + nz*nz) ** 0.5
    if not (0.5 < nlen < 1.5):
        return False
    r, g, b = v['color']
    if not all(-0.01 <= c <= 4.0 for c in (r, g, b)):
        return False
    if not (-0.01 <= v['alpha'] <= 4.0):
        return False
    return True


def try_read_block(data, off):
    """Read consecutive plausible vertices at a fixed 56-byte stride."""
    block = []
    i = off
    while i + 56 <= len(data):
        try:
            v = read_vertex(data, i)
        except struct.error:
            break
        if not is_plausible_vertex(v):
            break
        block.append(v)
        i += 56
        if len(block) > 100000:
            break
    return block


def write_obj(meshes, out_path):
    """Write extracted vertices to a Wavefront OBJ file."""
    with open(out_path, 'w') as f:
        f.write("# Extracted from Amplitude RND by rnd_mesh_parse.py\n")
        vbase = 1
        for mi, (off, count, verts) in enumerate(meshes):
            f.write(f"o mesh_{mi}_off{off}\n")
            for v in verts:
                x, y, z = v['pos']
                f.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")
            for v in verts:
                u, vv = v['uv']
                f.write(f"vt {u:.6f} {vv:.6f}\n")
            # Triangulate as a fan (best-effort without index data)
            for k in range(1, count - 1):
                a = vbase
                b = vbase + k
                c = vbase + k + 1
                f.write(f"f {a}/{a} {b}/{b} {c}/{c}\n")
            vbase += count
    print(f"Wrote {out_path} ({len(meshes)} meshes)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rnd')
    ap.add_argument('--obj', help="Write extracted geometry to OBJ file")
    ap.add_argument('--min-verts', type=int, default=3,
                    help="Minimum vertices to report a block")
    args = ap.parse_args()

    dec = decompress_rnd(args.rnd)
    manifest, data_start = parse_manifest(dec)
    data = dec[data_start:]

    mesh_objs = [(i, t, n) for i, (t, n) in enumerate(manifest) if t == 'Mesh']
    cam_objs = [(i, t, n) for i, (t, n) in enumerate(manifest) if t == 'Cam']

    print(f"File: {args.rnd}")
    print(f"Objects: {len(manifest)} total, "
          f"{len(mesh_objs)} Mesh, {len(cam_objs)} Cam")
    print()

    blocks = find_vertices(data)
    blocks = [b for b in blocks if b[1] >= args.min_verts]
    print(f"Found {len(blocks)} vertex blocks:")
    for off, count, verts in blocks[:40]:
        xs = [v['pos'][0] for v in verts]
        ys = [v['pos'][1] for v in verts]
        zs = [v['pos'][2] for v in verts]
        print(f"  +{off:6d}: {count:4d} verts  "
              f"x[{min(xs):6.2f},{max(xs):6.2f}] "
              f"y[{min(ys):6.2f},{max(ys):6.2f}] "
              f"z[{min(zs):6.2f},{max(zs):6.2f}]")

    if args.obj:
        write_obj(blocks, args.obj)


if __name__ == '__main__':
    main()
