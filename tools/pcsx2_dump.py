#!/usr/bin/env python3
"""
Amplitude RND object dumper via PCSX2 PINE.
Sets a conceptual breakpoint by polling the stream reader function return address.

Usage: Run while Amplitude is loading a level in PCSX2.
Dumps first occurrence of each object type to dumps/ directory.
"""

import socket, struct, os, time, zlib

SOCK_PATH = '/run/user/1000/pcsx2.sock'
DUMP_DIR  = 'dumps/object_structs'

# From Ghidra: FUN_00294468 = stream reader
# a1 (register $a1 = $5) = dest buffer ptr
# a2 (register $a2 = $6) = size
# PC register offset in PINE: we poll EPC (current PC)

# EE register indices for PINE MsgRead (using memory reads of EE register file)
# EE register file is at PINE address 0x10000000+ in some builds,
# but more reliably we read from the known stack/context

# Simpler approach: poll the known global that changes during loading
# ARK manager object count at 0x43c7a0
ARK_OBJ_COUNT = 0x0043c7a0

# Pre-loaded manifest from tunnel_new.rnd (object order)
MANIFEST = [
    ('Tex', 'panel rendered interference.bmp'),
    ('Tex', 'panel rendered scale.bmp'),
    ('Tex', 'snow.bmp'),
    # ... (we'll load this dynamically)
]

def r32(sock, addr):
    payload = struct.pack('<B', 2) + struct.pack('<I', addr)
    msg = struct.pack('<I', len(payload) + 4) + payload
    sock.sendall(msg)
    resp = sock.recv(64)
    if len(resp) >= 9 and resp[4] == 0:
        return struct.unpack_from('<I', resp, 5)[0]
    return None

def read_block(sock, addr, size):
    result = bytearray()
    for i in range(0, size, 4):
        v = r32(sock, addr + i)
        result += struct.pack('<I', v if v else 0)
    return bytes(result[:size])

def load_manifest(rnd_path):
    with open(rnd_path, 'rb') as f:
        raw = f.read()
    header_size = struct.unpack_from('<I', raw, 4)[0]
    dec = zlib.decompress(raw[header_size:], 47)
    obj_count = struct.unpack_from('<I', dec, 4)[0]
    pos = 8
    manifest = []
    for _ in range(obj_count):
        tlen = struct.unpack_from('<I', dec, pos)[0]; pos += 4
        t = dec[pos:pos+tlen].decode(); pos += tlen
        nlen = struct.unpack_from('<I', dec, pos)[0]; pos += 4
        n = dec[pos:pos+nlen].decode(); pos += nlen
        manifest.append((t, n))
    return manifest

def main():
    os.makedirs(DUMP_DIR, exist_ok=True)

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(SOCK_PATH)
    sock.settimeout(5)
    print('Connected to PCSX2 PINE')

    manifest = load_manifest(
        'extracted/amplitude/tunnel/tunnel_new.rnd')
    print(f'Loaded manifest: {len(manifest)} objects')

    # Poll object count — when it starts incrementing, loading has begun
    print('Waiting for level load...')
    last_count = 0
    seen_types = set()

    while True:
        count = r32(sock, ARK_OBJ_COUNT)
        if count and count != last_count:
            print(f'Object count: {count}')
            last_count = count
        time.sleep(0.1)

if __name__ == '__main__':
    main()
