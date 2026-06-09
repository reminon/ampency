#!/usr/bin/env python3
"""Amplitude RND file decompressor and manifest parser."""
import struct, zlib, sys, os

def read_str(data, pos):
    length = struct.unpack_from('<I', data, pos)[0]
    pos += 4
    s = data[pos:pos+length].decode('ascii', errors='replace')
    return s, pos + length

def decompress_rnd(path):
    with open(path, 'rb') as f:
        data = f.read()
    magic = struct.unpack_from('<I', data, 0)[0]
    if magic not in (0xCCBEDEAF, 0xCABEDEAF):
        return data  # already uncompressed
    header_size = struct.unpack_from('<I', data, 4)[0]
    return zlib.decompress(data[header_size:], 47)

def parse_manifest(data):
    version = struct.unpack_from('<I', data, 0)[0]
    obj_count = struct.unpack_from('<I', data, 4)[0]
    pos = 8
    objects = []
    for _ in range(obj_count):
        type_name, pos = read_str(data, pos)
        obj_name, pos = read_str(data, pos)
        objects.append((type_name, obj_name))
    return version, objects, pos

if __name__ == '__main__':
    path = sys.argv[1]
    data = decompress_rnd(path)
    version, objects, data_offset = parse_manifest(data)
    print(f'Version: {version}, Objects: {len(objects)}, Data offset: {data_offset}')
    for i, (t, n) in enumerate(objects):
        print(f'  [{i:4d}] {t:20s} {n}')
