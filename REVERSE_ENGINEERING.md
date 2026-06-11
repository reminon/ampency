# Reverse Engineering Notes

Documentation of Frequency/Amplitude PS2 file format research conducted for Ampency.

## Tools Used

- **Ghidra 12.1.2** with [ghidra-emotionengine-reloaded](https://github.com/chaoticgd/ghidra-emotionengine-reloaded) v2.1.36 (R5900 processor)
- **GameArchives** (C#) — ARK container extraction
- **jPSXdec v2.1** — PS2 media extraction
- Python scripts for entropy analysis, format parsing, decryption attempts

---

## ARK Container Format

Harmonix games use `.ark` files as their primary asset container.

### Amplitude ARK v2 (`gen/main.ark`)

Single self-contained file — no separate `.hdr`. Layout:

```
[0x00] u32 version = 2
[0x04] u32 num_records        # 20-byte records (unknown purpose, not the file table)
[0x08] records x 20 bytes
[records_end] u32 string_table_size
[+4]   string blob (null-terminated strings concatenated)
[+4+string_table_size] u32 num_ptr_entries
[+4]   ptr_table: num_ptr_entries x u32 (byte offsets into string blob)
[ptr_table_end] u32 num_files
[+4]   file_table: num_files x 20 bytes
```

File table entry (20 bytes):

```
u32 ark_offset   # byte offset of file data within this .ark
u32 name_ptr_id  # index into ptr_table -> string blob -> filename
u32 dir_ptr_id   # index into ptr_table -> string blob -> directory path
u32 size         # file size in bytes
u32 flags        # 0 for most files
```

No per-file compression at the ARK level — files are stored raw.

### Frequency ARK (magic `ARK` / 0x4B5241)

Uses a completely different header format identified by the 3-byte ASCII magic
`ARK`. Has block-based compression with `blockSize` and `compressedSize` fields
per file entry. GameArchives handles this format separately.

---

## RND File Format

RND files are Harmonix's serialized scene/object files used by their proprietary
`Rnd` engine. Frequency and Amplitude use different versions.

### Frequency RND (version 6)

Plain binary, uncompressed, little-endian.

```
[0x00] u32 version = 6
[0x04] u32 object_count
[0x08] objects: for each object:
         null-terminated type string  (e.g. "TransAnim\0")
         null-terminated name string  (e.g. "tunnel path\0")
         ... raw object binary data (type-specific, no size header)
```

Entropy: ~5.6 bits/byte. Unambiguously structured binary.

### Amplitude RND (version 10)

Gzip compressed with a fixed-size binary header. Little-endian.

```
[0x00] u32 magic             = 0xCCBEDEAF  (standard variant)
                             | 0xCABEDEAF  (alternate variant)
[0x04] u32 header_size       # byte offset where gzip payload begins (typically 216 = 0xD8)
[0x08] u32 version           = 10
[0x0C] u32 uncompressed_size
[0x10] u32 compressed_size   # = file_size - header_size
[0x14] ... pointer fixup table (header_size - 0x14 bytes, used by PS2 runtime only)
[header_size] gzip payload   # magic bytes: 1f 8b 08 ...
```

**Decompression:**

```python
import zlib, struct

data = open("file.rnd", "rb").read()
header_size = struct.unpack_from("<I", data, 4)[0]
decompressed = zlib.decompress(data[header_size:], 47)
```

The `47` wbits parameter (`16 + 31`) tells zlib to auto-detect gzip format.

**Important:** The raw file has entropy ~7.98 bits/byte, which strongly resembles
encryption. It is gzip compression. The pointer fixup table at bytes 8-216 has
low entropy (~3.76 bits/byte) and is the diagnostic tell. The magic `0xCCBEDEAF`
is a file signature, not a cipher key. No encryption is present.

#### Decompressed Payload Structure

```
[0x00] u32 version       = 10
[0x04] u32 object_count
[0x08] manifest: for each of object_count objects:
         u32 type_len
         u8[type_len] type_string    (e.g. "Tex", no null terminator)
         u32 name_len
         u8[name_len] name_string    (e.g. "panel rendered interference.bmp", no null)
[manifest_end] raw object binary data (contiguous, no per-object size headers)
```

No null terminators anywhere. All strings are u32 length-prefixed with no terminator.
The data section is a flat binary blob — each object type has its own internal
serialization format with no size wrapper.

#### Object Types (from tunnel_new.rnd, 366 objects)

| Type | Count | Description |
|------|-------|-------------|
| Mat | 81 | Material |
| View | 79 | Scene view / render group |
| Tex | 45 | Texture reference |
| MatAnim | 38 | Material animation |
| Mesh | 22 | Geometry mesh |
| ParticleSys | 22 | Particle system |
| Cam | 20 | Camera |
| TransAnim | 19 | Transform animation |
| Font | 10 | Bitmap font |
| Text | 10 | Text object |
| MultiMesh | 9 | Multi-part mesh |
| Line | 4 | Line geometry |
| Light | 3 | Light source |
| Environ | 2 | Environment settings |
| Movie | 1 | IPU video reference |
| LightAnim | 1 | Light animation |

---

## Rnd Engine Class Hierarchy

Recovered from strings in SCUS_972.58:

```
RndObject
├── RndAnimatable
├── RndDrawable
├── RndTransformable
├── RndCollideable
├── RndLoader
├── RndManager
├── RndRenderer
├── RndMesh
├── RndMat
├── RndTex
├── RndView
├── RndTransAnim
├── RndParticleSys
├── RndLightAnim
├── RndCam
└── RndEnviron
```

---

## EE Executable Analysis (SCUS_972.58)

- **Format:** MIPS ELF 32-bit LSB, statically linked, stripped
- **Load address:** 0x100000
- **File offset formula:** `vaddr = file_offset - 0x1000 + 0x100000`
- **Processor:** R5900 (PS2 Emotion Engine), little-endian

### Key Functions

| Address | Description |
|---------|-------------|
| `0x001628d0` | Arena RND loader — formats `Metagame/Arena/%s.rnd`, calls RND object adder |
| `0x00238e98` | RND object adder — adds object to scene at ARK manager `0x43c798` |
| `0x0022c6a0` | RndLoader constructor — sets vtable to `0x3d7060`, allocates buffers |
| `0x0022c988` | RndLoader::Load — allocates 0x124-byte file stream, calls FileInit |
| `0x002952a0` | File stream initializer — reads header (0xD8 bytes) via IOP |
| `0x0028ec20` | File reader — opens file via IOP RPC, reads 4-byte magic |
| `0x00295b70` | RND header writer — writes `0xCCBEDEAF` magic and `0xD8` header size |
| `0x0022ce90` | Deserialization loop — reads objects via `FUN_00294468`, dispatches by type |
| `0x00294468` | Stream reader — reads u32 size then that many bytes via vtable |
| `0x00293f28` | Endian swap — byte-swaps 2/4/8/16-byte values for big-endian compat |
| `0x00237e00` | Object lookup — binary tree search by string key in object registry |
| `0x0028deb0` | ARK opener — opens `gen/main.ark` via `FUN_0028e158` |
| `0x00289330` | File stream opener — dispatches to IOP or in-memory ARK stream |
| `0x0031ab98` | IOP file read — sceSifCallRpc equivalent, sends read RPC to IOP |
| `0x0031a558` | IOP file open |
| `0x0031b610` | IOP file stat / size query |

### Global ARK Manager

ARK manager object lives at `0x43c798`. All RND loading passes through this.

### File Loading Call Chain

```
FUN_001628d0  (Arena loader)
  └─ FUN_00238e98  (RND object adder)
       └─ FUN_0022c6a0  (RndLoader ctor, vtable = 0x3d7060)
            └─ FUN_0022c988  (RndLoader::Load)
                 └─ FUN_002952a0  (file stream init, reads 0xD8 header bytes)
                      └─ FUN_0028ec20  (file reader, reads magic u32)
                           └─ FUN_0031ab98  (IOP RPC file read)
```

### Vtable at 0x3d7060 (RndLoader, 8-byte stride due to R5900 alignment)

| Offset | Function | Description |
|--------|----------|-------------|
| +0x04 | `0x3ab708` | Type info getter |
| +0x0C | `0x29ead8` | Destructor |
| +0x14 | `0x29eb48` | Read dispatch |
| +0x24 | `0x3ab790` | (unknown) |
| +0x2C | `0x29f9c8` | (unknown) |
| +0x34 | `0x29fe68` | (unknown) |
| +0x3C | `0x3305d0` | Abort / no-op |
| +0x44 | `0x2a0120` | (unknown) |

---

## What Was Ruled Out

During the reverse engineering process the following were investigated and
eliminated before the gzip solution was found:

| Hypothesis | Result |
|-----------|--------|
| Old PS2 DTB LCG cipher (`0x41C64E6D` / `0x3039`) | Constants not present in EE executable |
| Rock Band LCG cipher (`0x1F31D` / `0x41A7`) | Constants not present in EE executable |
| AES-128 CTR (Rock Band era) | EE executable predates Rock Band; no AES code present |
| Custom IOP decryption IRX module | No custom IRX in ARK; only standard Sony modules loaded |
| `0x4F1A7EC8` as cipher key | This is a function pointer in the RndLoader vtable chain |
| `0xCCBEDEAF` as cipher key | This is the file magic / signature |
| Byte-swapping + zlib | No valid zlib stream found after any byte-swap arrangement |
| Per-file ARK compression | ARK v2 stores files raw; no compressed size field in file table |

The decisive evidence: gzip magic bytes `1f 8b 08` appear at byte offset
`header_size` (value stored at file byte 4) in every Amplitude RND file.

---

## Ghidra Headless Setup Notes

Three bugs to work around when scripting Ghidra 12.x headless on Linux:

### 1. Felix OSGi Wildcard Import Failure

Scripts fail to compile with `cannot find symbol` for classes from wildcard
imports like `import ghidra.program.model.symbol.*`. The Apache Felix OSGi
classloader used by Ghidra headless does not reliably resolve wildcards.

**Fix:** Use explicit absolute imports for every class:
```java
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceManager;
```

### 2. Cache Ghosting

When a script fails to compile, Ghidra silently falls back to the last
successfully compiled `.class` file for the same script name. This creates the
illusion that your updated script is running but producing stale results.

**Fix:** Delete the compiled bundle cache and rename the script file:
```bash
rm -rf ~/.config/ghidra/ghidra_12.x.x_DEV/osgi/compiled-bundles/<bundle-hash>/
```
Renaming the script forces a new bundle hash and a guaranteed fresh compile.

### 3. R5900 Processor Plugin Install

The ghidra-emotionengine-reloaded extension ships only a `.slaspec` source file.
Ghidra requires a compiled `.sla` file. The plugin also cannot be loaded from
the user extensions directory in headless mode — it must be installed directly
into Ghidra's Processors directory.

**Fix:**
```bash
# Extract and compile the slaspec
mkdir -p ~/ee_ext
unzip ghidra_12.1.2_PUBLIC_*_ghidra-emotionengine-reloaded.zip -d ~/ee_ext
/opt/ghidra/support/sleigh \
  ~/ee_ext/ghidra-emotionengine-reloaded/data/languages/r5900.slaspec

# Install into Ghidra's processor directory
sudo mkdir -p /opt/ghidra/Ghidra/Processors/R5900/data/languages
sudo cp ~/ee_ext/ghidra-emotionengine-reloaded/data/languages/* \
  /opt/ghidra/Ghidra/Processors/R5900/data/languages/
sudo chmod 644 /opt/ghidra/Ghidra/Processors/R5900/data/languages/r5900.sla

# Import with the correct processor ID
analyzeHeadless ~/project AmplitudePS2 \
  -import SCUS_972.58 \
  -processor "r5900:LE:32:default"
```

---

## DTB / DTA Script Format

Amplitude uses compiled binary DTA (`.txt.bin`) files in place of Frequency's
Python scripts. These are Harmonix's cross-game data format, also used in
Guitar Hero and Rock Band.

### File Structure

```
[0x00] u8  version        = 0x02
[0x01] u32 num_files      = 1 (always 1 in Amplitude)
[0x05] u32 filename_len
[0x09] u8[filename_len]   source .txt filename (e.g. "arenas/factory/triggers_p1.txt")
[0x09+filename_len] DTA tree
```

### DTA Tree Structure

```
u16 child_count
u32 node_id
[variable] node ID lookup table (filled with 0xFFFFFFFF sentinels, variable length)
[child_count x] DTA chunks
```

The node ID lookup table between the tree header and chunk data has variable
length. Its end is not explicitly marked — parsers must find the start of valid
chunk data empirically.

### DTA Chunk Encoding

Each chunk is encoded as a u32 type tag followed by type-specific data:

| Type ID | Name | Data |
|---------|------|------|
| `0x00` | Int | u32 value (signed) |
| `0x01` | Float | f32 value |
| `0x02` | Var | u32 len + bytes |
| `0x05` | Symbol | u32 len + bytes |
| `0x06` | Unhandled | u32 (skip 4 bytes) |
| `0x07` | IfDef | u32 len + bytes |
| `0x08` | Else | u32 (skip 4 bytes) |
| `0x09` | EndIf | u32 (skip 4 bytes) |
| `0x10` | Parens `()` | DTA tree (array) |
| `0x11` | Braces `{}` | DTA tree |
| `0x12` | String | u32 len + bytes |
| `0x13` | Brackets `[]` | DTA tree |
| `0x20` | Define | u32 len + bytes |
| `0x21` | Include | u32 len + bytes |
| `0x22` | Merge | u32 len + bytes |
| `0x23` | IfNDef | u32 len + bytes |
| `0x24` | Autorun | u32 (skip 4 bytes) |
| `0x25` | Undef | u32 len + bytes |

All strings are NOT null-terminated. They use a u32 length prefix with raw bytes.

### Trigger Script Format

The `triggers_*.txt.bin` files per arena/phase are event scripts that control
health-reactive animations and game events. They replace Frequency's Python
scripts with compiled DTA.

Each trigger entry is a `()` array containing:

```scheme
(
  beat <float>              ; beat position in song
  conditions
    (not <condition>)       ; optional condition
  actions
    (animate <rnd_object> <float>)   ; play animation at speed
    (set_mat <material> ...)         ; set material properties
    (begin ...)             ; sequential action block
)
```

Example decoded from `arenas/factory/gen/triggers_p1.txt.bin`:
```scheme
(beat 0.0
  (conditions (not note))
  (actions
    (animate "harvester_mouth_01.tnm" 720.0)
    (animate "harvester_mouth_02.tnm" 720.0)))
(beat 61.0
  (conditions (begin))
  (actions
    (animate "World_beat.view" ...)
    (set_mat "harvester_room.mat"
      (base_color 0.4 0.4 0.6))))
```

### Files of Interest

| File | Size | Description |
|------|------|-------------|
| `gen/freq2_config.txt.bin` | 376 KB | Main game configuration |
| `gen/default_config.txt.bin` | 81 KB | Default settings |
| `gen/english_songs.txt.bin` | 20 KB | Song metadata (names, artists, credits) |
| `gen/english_messages.txt.bin` | 88 KB | UI strings |
| `gen/english_screens.txt.bin` | 52 KB | Screen text |
| `arenas/*/gen/triggers_*.txt.bin` | 3-11 KB | Per-phase event scripts |
| `gen/version.txt.bin` | 54 bytes | Build version (`Build: 210203RC4`) |

### Relationship to Frequency Python Scripts

Frequency used Python scripts (e.g. `blue.py`) with a custom `hx` module API:
```python
hx.anim_speed("boundary flash", health * 2.0)
```

Amplitude replaced these with compiled DTA trigger scripts that express the same
concepts (beat-triggered actions, health-reactive animations) in a platform-
independent binary format. The trigger system is functionally equivalent but
compiled rather than interpreted.

### DTB Encryption

Standard DTB files (Guitar Hero, Rock Band) are XOR-encrypted using a 4-byte
key stored at the start of the file. Amplitude's `.txt.bin` files appear to use
an unencrypted variant — the source filename is visible in plaintext immediately
after the version byte, and known strings (`beat`, `conditions`, `actions`,
`animate`) are readable without decryption.

---

## Mesh Object Binary Format

Cracked via PINE memory inspection and static analysis of decompressed RND files.

### Cam Object Struct

The `Cam` object stores projection parameters (position comes from a linked
TransAnim, not the Cam itself):

```
+0x00  f32[4]   padding / flags (zeros)
+0x10  f32[3]   RGB color (0.7, 0.7, 0.7) — fog or ambient
+0x1c  u32      reference pointer
+0x20  f32      FOV horizontal = 0.7854 (π/4 = 45°)
+0x24  f32      FOV vertical   = 0.7854
+0x28  f32      far plane  = 1000.0
+0x2c  f32      near plane = 1.0
+0x30  ...      zeros
+0x38  u32      0xDEADDEAD sentinel
```

**Confirmed camera values for Amplitude tunnel:**
- FOV = 45° (π/4 radians)
- Near plane = 1.0
- Far plane = 1000.0

### Mesh Object Struct

```
[transform]  4×4 identity matrix (64 bytes) — f32, row-major
             1 0 0 0 / 0 1 0 0 / 0 0 1 0 / 0 0 0 1
[material]   u32 len + material name string (e.g. "grid line mat")
[mesh name]  u32 len + mesh name string (e.g. "grid4.mesh") ×2
             (appears twice: once as object name, once as material ref)
[padding]    alignment bytes
u32          vertex_count
[vertices]   vertex_count × 56 bytes
u32          face_index_count
[indices]    face_index_count × u32
u32          0xDEADDEAD sentinel
```

**Note:** After the variable-length name strings, vertex data is NOT 4-byte
aligned. A 10-byte name like "grid4.mesh" shifts subsequent data to mod-4 = 2
alignment. Parsers must track byte position exactly, not assume alignment.

#### Vertex Format (56 bytes = 14 × f32)

```
+0x00  f32[3]   position   (x, y, z)
+0x0c  f32      padding (0.0)
+0x10  f32[3]   normal     (nx, ny, nz)
+0x1c  f32      padding (0.0)
+0x20  f32[3]   color RGB  (r, g, b)
+0x2c  f32      alpha      (a)
+0x30  f32[2]   UV         (u, v)
```

Example from `grid4.mesh` (one lane quad, 0.6 units wide):
```
v0: pos(-0.3, 0.0,  0.03)  normal(0,0,-1)  rgb(1,1,1)  a=0.8  uv(0,0)
v1: pos(-0.3, 0.0, -0.03)  normal(0,0,-1)  rgb(1,1,1)  a=0.8  uv(0,1)
v2: pos( 0.3, 0.0, -0.03)  normal(0,0,-1)  rgb(1,1,1)  a=0.8  uv(1,1)
v3: pos( 0.3, 0.0,  0.03)  normal(0,0,-1)  rgb(1,1,1)  a=0.8  uv(1,0)
```

Indices follow as u32 values (e.g. `0,1,2, 0,2,3` for two triangles forming
the quad), terminated by the `0xDEADDEAD` sentinel.

### PINE Memory Inspection Method

PCSX2 2.7+ exposes a PINE IPC server (Settings → Advanced → Enable PINE,
default port 28011). On Linux it's a Unix domain socket at
`/run/user/<uid>/pcsx2.sock`.

PINE wire format (little-endian):
```
Request:  u32 total_length (incl. self) | u8 opcode | [args]
Response: u32 total_length | u8 status (0=ok) | [data]

Opcodes:  MsgRead8=0, MsgRead16=1, MsgRead32=2, MsgRead64=3,
          MsgWrite8=4 ... MsgWrite64=7
```

Read32 example:
```python
payload = struct.pack('<B', 2) + struct.pack('<I', addr)
msg = struct.pack('<I', len(payload) + 4) + payload
sock.sendall(msg)
resp = sock.recv(64)
value = struct.unpack_from('<I', resp, 5)[0]  # if resp[4] == 0
```

Object name strings are stored in a packed string table in EE RAM (found around
`0x003fb3f8` for tunnel objects). The object registry binary tree root is at
`*(0x0043c79c)`. Object data blocks are scattered in the heap and reference the
string table by content, not pointer.

---

## Complete Mesh Binary Layout (grid4.mesh, 474 bytes)

```
[0x00] u32 = 14          header field (flags/type?)
[0x04] u32 = 5           header field
[0x08] f32[16]           4x4 transform matrix (row-major, identity for grid4)
[0x48] u32 = 0           padding
[0x4c] u32 = 0           padding
[0x50] u32 = 0           padding  
[0x54] u32 = 0           padding
[0x58] u32 = 0           padding
[0x5c] u32 = 0           padding
[0x60] u32 = 0           padding
[0x64] u32 = 0           padding
[0x68] u32 = 0           padding
[0x6c] u32 = 0           padding
[0x70] u32 = 0           padding
[0x74] u32 = 0           padding
[0x78] u32 = 0           padding
[0x7c] u32 = 0           padding
[0x80] u32 = 1           (unknown — render flags?)
[0x84] u32 = 0           padding
[0x88] u32 = 0           padding
[0x8c] u32 = 0           padding
[0x90] u32 = 1           (unknown)
[0x94] u32 mat_name_len
[0x98] u8[mat_name_len]  material name (e.g. "gridline mat")
[...]  u32 mesh_name_len
[...]  u8[mesh_name_len]  mesh name (e.g. "grid4.mesh") ×2
[...]  u32 = 0 ×5        padding/alignment
[...]  u32 vertex_count
[...]  f32[vertex_count × 14]  vertex data (56 bytes each, see vertex format)
[...]  u32 face_count
[...]  u16[face_count × 3]     triangle indices
[...]  u32 = 0xDEADDEAD        sentinel
```

### grid4.mesh Geometry

4 vertices, 2 triangles forming a single quad (one lane segment):
```
Indices: (0,2,3), (0,1,2)

v0: pos(-0.3,  0.0,  0.03)  normal(0,0,-1)  rgb(1,1,1)  a=0.8  uv(0,0)
v1: pos(-0.3,  0.0, -0.03)  normal(0,0,-1)  rgb(1,1,1)  a=0.8  uv(0,1)
v2: pos( 0.3,  0.0, -0.03)  normal(0,0,-1)  rgb(1,1,1)  a=0.8  uv(1,1)
v3: pos( 0.3,  0.0,  0.03)  normal(0,0,-1)  rgb(1,1,1)  a=0.8  uv(1,0)
```

Lane width = 0.6 units (x: -0.3 to 0.3)
Lane depth = 0.06 units (z: -0.03 to 0.03) — single segment, tiled along tunnel

### Important Dimensions

| Parameter | Value | Source |
|-----------|-------|--------|
| Lane width | 0.6 units | grid4.mesh vertices |
| Lane count | 6 | tunnel_new.rnd manifest |
| Total track width | 3.8 units | 6×0.6 + 5×0.04 dividers |
| Tunnel wall radius | ~4.0 units | fake panel mesh extents |
| Track Y position | 0.0 | grid4.mesh Y=0 |
| Tunnel center Y | -0.611 | computed from wall mesh |
| Camera Y | -0.2 | tnl cam1 transform matrix |
| Camera FOV | 45° (π/4) | Cam object data |
| Camera far plane | 1000.0 | Cam object data |
| Fog start | 20.0 | estimated |
| Fog end | 56.0 | tunnel solo.env |
| Ambient color | (0.2, 0.2, 0.2) | tunnel solo.env |

---

## Scene Graph (from tnl.view)

```
tnl.view (master)
├── realtime.view          — live gameplay objects
├── panel intro 1-4.mnm    — lane intro animations
├── streakarrow.view       — lane switch arrow indicator
├── seeker_g/p/r/y/s.mnm  — ship model per lane color
├── panel ckpt.mnm         — checkpoint panels
├── fake panel.mesh        — stage clear plasma fire (lane 1)
├── fake panel1-5.mesh     — stage clear plasma fire (lanes 2-6)
├── fake panel pass 1/2    — two-pass additive blend for fire
├── tunnel track color.lit — dynamic track lighting
├── tunnel rotating.lit    — rotating tunnel light
├── tunnel light1.lit      — static tunnel light
├── fire0/1.view           — fire particle systems
├── fire fs0-5.view        — per-lane fire fullscreen effects
├── tnl cam1               — camera reference
├── tnl opaque             — opaque render pass
│   └── gem_free/neut/slow/mult/bump/auto/crip meshes
└── tnl transparent        — transparent/additive render pass
    ├── gem_miss mesh
    ├── gem_bass/drum/guitar/fx/synth/vox/flash particle systems
    ├── sabre_g/r/y/p.str  — laser beam streak effects
    └── gem_glow 0-3 particle systems
```

### Render Passes

The game uses a two-pass rendering system:
- **Opaque pass** (`tnl opaque`): Standard depth-tested geometry — gem meshes
- **Transparent pass** (`tnl transparent`): Additive/alpha-blended effects — particles, glows, streaks

---

## Instrument Colors (from freq2_config.txt.bin)

### Lane Colors (inst_bg_color — panel background)

| Instrument | Lane Color | RGB |
|-----------|-----------|-----|
| Drum | Red | 0.550, 0.000, 0.000 |
| Bass | Blue | 0.000, 0.200, 0.650 |
| Vocal | Green | 0.000, 0.550, 0.000 |
| Synth | Yellow | 0.700, 0.600, 0.000 |
| Guitar | Orange | 0.800, 0.350, 0.000 |

### Instrument UI Colors (inst_color — foreground/text)

| Instrument | Color | RGB |
|-----------|-------|-----|
| Drum | Red | 0.700, 0.000, 0.000 |
| Bass | Blue | 0.100, 0.650, 1.000 (note: bg has 0.000, 0.100, 0.650) |
| Synth | Green | 0.000, 0.900, 0.000 |
| Guitar | Dark Green | 0.000, 0.500, 0.000 |
| Vocal | Green | 0.000, 0.700, 0.000 |

### Track Color Config Keys

| Key | Dim Color | Bright Color |
|-----|-----------|-------------|
| track_color_r (Red) | 0.500, 0.050, 0.050 | 0.800, 0.150, 0.150 |
| track_color_p (Purple) | 0.450, 0.100, 0.470 | 0.800, 0.250, 0.900 |
| track_color_y (Yellow) | 0.450, 0.450, 0.020 | 0.900, 0.900, 0.100 |
| track_color_neutral | 0.200, 0.200, 0.400 | — |
| track_color_g_streak | — | 0.150, 0.750, 0.150 |

---

## Gameplay Notes

### Lane System
- Songs start with 2-3 lanes active (song-defined in freq2_config)
- Clearing a lane unlocks adjacent locked lanes
- Lane layout is dynamic — new lanes appear as song progresses
- Lane positions shift to stay centered as count changes

### Stage Clear Animation
- On lane clear: fake panel mesh becomes visible over the lane
- Plasma fire effect (lane color) via two-pass additive blending
- Effect scrolls away from player along Z axis (down the tunnel)
- Rails remain visible during clear — track returns after set duration
- Driven by `stageClear.matAnim` objects triggered in DTB scripts

### Streakarrow
- `streakarrow.mesh` + `streakarrow.tnm` — the large arrow indicator
- Appears above the nearest capturable lane
- Points toward the target lane in the player's travel direction
- Not a lane-switch trail — it's a "go here next" indicator

### DTB Trigger System
- Per-song trigger scripts: `triggers_p1.txt.bin` through `triggers_p4.txt.bin`
- Beat-triggered events: `animate`, `set_mat`, `set_anim`, `show`, `hide`
- Conditions: `note`, `gem_pos`, `game_state`, `path_exists`, `path_unlocked`
- Arena phases: each `.txt.bin` corresponds to one song in the arena
