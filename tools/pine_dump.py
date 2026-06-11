#!/usr/bin/env python3
"""
PINE-based Amplitude RND object data dumper.
Connects to PCSX2 via PINE protocol and reads live object data from PS2 RAM.
"""

import struct
import socket
import zlib

PINE_HOST = 'localhost'
PINE_PORT = 28011

# PINE opcodes
MsgRead8   = 0
MsgRead16  = 1
MsgRead32  = 2
MsgRead64  = 3
MsgWrite8  = 4
MsgWrite16 = 5
MsgWrite32 = 6
MsgWrite64 = 7
MsgGetGameID = 17

def pine_send(sock, commands):
    """Send a batch of PINE commands."""
    buf = bytearray()
    for cmd, addr in commands:
        buf += struct.pack('<BII', cmd, addr, 0)
    # Prepend total length
    msg = struct.pack('<I', len(buf) + 4) + bytes(buf)
    sock.sendall(msg)

def pine_read32(sock, addr):
    """Read a 32-bit value from PS2 memory."""
    cmd = struct.pack('<I', 9) + struct.pack('<B', MsgRead32) + struct.pack('<I', addr)
    sock.sendall(cmd)
    resp = sock.recv(1024)
    if len(resp) >= 8:
        return struct.unpack_from('<I', resp, 4)[0]
    return None

def pine_read_bytes(sock, addr, length):
    """Read a block of bytes from PS2 memory using multiple Read8 calls."""
    result = bytearray()
    for i in range(length):
        cmd = struct.pack('<I', 9) + struct.pack('<B', MsgRead8) + struct.pack('<I', addr + i)
        sock.sendall(cmd)
        resp = sock.recv(1024)
        if len(resp) >= 5:
            result.append(struct.unpack_from('<B', resp, 4)[0])
        else:
            result.append(0)
    return bytes(result)

def get_game_id(sock):
    cmd = struct.pack('<I', 5) + struct.pack('<B', MsgGetGameID)
    sock.sendall(cmd)
    resp = sock.recv(1024)
    if len(resp) > 5:
        return resp[5:].decode('ascii', errors='replace').rstrip('\x00')
    return None

def main():
    sock = socket.create_connection((PINE_HOST, PINE_PORT), timeout=5)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    
    print("Connected to PCSX2 PINE")
    
    game_id = get_game_id(sock)
    print(f"Game ID: {game_id}")
    
    # ARK manager is at 0x43c798 in EE virtual memory
    # PS2 EE RAM starts at 0x00000000 in PINE addressing
    ark_manager = 0x0043c798
    
    print(f"\nReading ARK manager at 0x{ark_manager:08x}...")
    val = pine_read32(sock, ark_manager)
    print(f"  Value: 0x{val:08x}" if val else "  Failed to read")
    
    # Read 64 bytes around the ARK manager
    print(f"\nDumping 64 bytes at ARK manager:")
    data = pine_read_bytes(sock, ark_manager, 64)
    for i in range(0, 64, 16):
        hex_part = ' '.join(f'{b:02x}' for b in data[i:i+16])
        asc_part = ''.join(chr(b) if 32<=b<127 else '.' for b in data[i:i+16])
        print(f"  {ark_manager+i:08x}: {hex_part:<48}  {asc_part}")
    
    sock.close()

if __name__ == '__main__':
    main()
