# Ampency

An open-source clone of Harmonix's *Frequency* and *Amplitude* (PS2, 2001/2003) built in Rust with SDL2 and OpenGL.

> **Status: Early development / research phase.** The file formats have been reverse engineered and asset extraction is working. The renderer is a work in progress.

---

## What Is This?

*Frequency* and *Amplitude* are rhythm games developed by Harmonix (pre-Guitar Hero) for the PlayStation 2. Players navigate a tunnel divided into instrument tracks, capturing note gems to keep each instrument playing. The games are notable for their electronic music focus, reactive visuals, and tight gameplay loop.

Ampency aims to be a faithful open-source reimplementation that can load songs and assets from user-supplied disc images.

---

## Features (Planned)

- [ ] Tunnel renderer (octagonal, 8-track layout)
- [ ] Two visual themes: Frequency (dark industrial) and Amplitude (bright neon)
- [ ] Note gem system with hit detection
- [ ] Custom song loading with stem separation
- [ ] Asset extraction from user-supplied ISOs
- [ ] Controller support (LB/RB/LT scheme)

---

## Building

### Prerequisites

- Rust (stable, 1.70+)
- SDL2 development libraries
- OpenGL 3.3+

On Arch Linux:
```bash
sudo pacman -S sdl2 sdl2_mixer
```

On Ubuntu/Debian:
```bash
sudo apt install libsdl2-dev libsdl2-mixer-dev
```

### Compile

```bash
cargo build --release
```

---

## Asset Extraction

Ampency requires assets from a legally owned copy of *Frequency* (SCUS-971.13)
or *Amplitude* (SCUS-972.58). The `tools/rnd_parse.py` script can extract and
parse RND scene files.

```bash
# Decompress and list objects in an Amplitude RND file
python3 tools/rnd_parse.py path/to/file.rnd
```

See [REVERSE_ENGINEERING.md](REVERSE_ENGINEERING.md) for full documentation of
the file formats discovered during this project.

---

## File Format Summary

### Amplitude RND (reverse engineered)

Amplitude RND files use a gzip-compressed payload with a 216-byte binary header.
They are **not encrypted** despite the high entropy of the raw files.

```python
import zlib, struct

data = open("file.rnd", "rb").read()
header_size = struct.unpack_from("<I", data, 4)[0]  # typically 216
decompressed = zlib.decompress(data[header_size:], 47)
```

The decompressed payload contains a length-prefixed manifest of typed objects
(Tex, Mesh, Mat, View, TransAnim, etc.) followed by their serialized binary data.

---

## Project Structure

```
src/
  main.rs       # OpenGL window + render loop
  shader.rs     # GLSL shader compiler
  tunnel.rs     # Octagonal tunnel geometry
  themes.rs     # Visual theme trait (FrequencyTheme, AmplitudeTheme)

tools/
  rnd_parse.py          # Amplitude RND decompressor + manifest parser
  ArkExtract/           # C# tool for extracting Harmonix ARK archives
  FindRndDecrypt.java   # Ghidra headless script used during RE research

REVERSE_ENGINEERING.md  # Detailed format documentation and EE analysis
```

---

## Technical Stack

| Component | Technology |
|-----------|-----------|
| Language | Rust |
| Windowing / input | SDL2 |
| Audio | SDL2_mixer |
| Graphics | OpenGL 3.3 Core |
| Math | nalgebra |

---

## Legal

This project contains no copyrighted assets from Frequency or Amplitude.
You must supply your own legally obtained disc images to extract assets.

Frequency and Amplitude are trademarks of Harmonix Music Systems.
This project is not affiliated with or endorsed by Harmonix or Sony.

---

## Acknowledgements

- [ghidra-emotionengine-reloaded](https://github.com/chaoticgd/ghidra-emotionengine-reloaded) — R5900 processor support for Ghidra
- [GameArchives](https://github.com/maxton/GameArchives) — Harmonix ARK container library
- [dtab](https://github.com/mtolly/dtab) — Harmonix DTA/DTB format documentation
- The Harmonix modding community for prior ARK format research
