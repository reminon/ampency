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
