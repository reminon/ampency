//! Amplitude song chart: parsed MIDI data with beat-to-world-Z conversion.
//!
//! Coordinate convention:
//!   - Player is at Z=0, gems scroll toward Z=0 from negative Z
//!   - A gem at beat B, with current_beat C, scroll_speed S units/beat:
//!     gem_z = -(B - C) * S
//!   - Gem is visible when -TUNNEL_LENGTH < gem_z < 2.0

use std::collections::HashMap;

pub const SCROLL_SPEED: f32 = 8.0; // units per beat — tune to feel right

/// A single gem event on a track
#[derive(Debug, Clone)]
pub struct Gem {
    pub beat:       f32,    // absolute beat position in song
    pub note:       u8,     // raw MIDI note (0-47)
    pub velocity:   u8,
    pub difficulty: u8,     // 0=easy, 1=medium, 2=hard, 3=expert
    pub position:   u8,     // 0-11, gem slot within bar
}

/// A section marker (beat boundary)
#[derive(Debug, Clone)]
pub struct Section {
    pub beat:   f32,
    pub marker: u8,  // 96=start, 100=mid, 103=end
}

/// One instrument track from the MIDI
#[derive(Debug, Clone)]
pub struct Track {
    pub instrument: String,  // "drums", "bass", "guitar", "synth", "vocal", "fx"
    pub gems:       Vec<Gem>,
    pub sections:   Vec<Section>,
}

/// Full parsed chart for one song
#[derive(Debug)]
pub struct Chart {
    pub song_name:      String,
    pub bpm:            f32,
    pub ticks_per_beat: u32,
    pub tracks:         Vec<Track>,
}

impl Chart {
    /// Load and parse a MIDI file
    pub fn from_midi(path: &str) -> Option<Self> {
        let data = std::fs::read(path).ok()?;
        if &data[0..4] != b"MThd" { return None; }

        let fmt         = u16::from_be_bytes(data[8..10].try_into().ok()?);
        let ticks_per_beat = u16::from_be_bytes(data[12..14].try_into().ok()?) as u32;

        let mut tracks = Vec::new();
        let mut global_tempo = 500_000u32; // 120 BPM default
        let mut pos = 14usize;

        while pos + 8 <= data.len() {
            let chunk_type = &data[pos..pos+4];
            let chunk_len  = u32::from_be_bytes(data[pos+4..pos+8].try_into().ok()?) as usize;
            pos += 8;
            if chunk_type != b"MTrk" { pos += chunk_len; continue; }

            let (name, tempo, note_ons) = parse_track_events(&data, pos, chunk_len);
            if tempo > 0 { global_tempo = tempo; }

            if let Some(track) = parse_instrument_track(&name, &note_ons, ticks_per_beat) {
                tracks.push(track);
            }
            pos += chunk_len;
        }

        let bpm = 60_000_000.0 / global_tempo as f32;
        let song_name = std::path::Path::new(path)
            .file_stem()?.to_string_lossy().to_string();

        Some(Chart { song_name, bpm, ticks_per_beat, tracks })
    }

    /// Convert a beat position to world Z at the current playback beat
    pub fn beat_to_z(&self, gem_beat: f32, current_beat: f32) -> f32 {
        -(gem_beat - current_beat) * SCROLL_SPEED
    }

    /// Get all visible gems across all tracks at current_beat
    pub fn visible_gems(&self, current_beat: f32, difficulty: u8)
        -> Vec<(&Track, &Gem, f32)>
    {
        let look_ahead = 60.0 / SCROLL_SPEED; // beats visible ahead
        let look_behind = 2.0 / SCROLL_SPEED;  // beats behind player

        let mut result = Vec::new();
        for track in &self.tracks {
            for gem in &track.gems {
                if gem.difficulty != difficulty { continue; }
                let delta = gem.beat - current_beat;
                if delta < -look_behind || delta > look_ahead { continue; }
                let z = self.beat_to_z(gem.beat, current_beat);
                result.push((track, gem, z));
            }
        }
        result
    }

    /// Get track by instrument name
    pub fn track(&self, instrument: &str) -> Option<&Track> {
        self.tracks.iter().find(|t| t.instrument == instrument)
    }
}

const SECTION_MARKERS: &[u8] = &[96, 100, 103];

fn read_varint(data: &[u8], pos: usize) -> (u32, usize) {
    let mut val = 0u32;
    let mut p = pos;
    loop {
        let b = data[p]; p += 1;
        val = (val << 7) | (b & 0x7f) as u32;
        if b & 0x80 == 0 { break; }
    }
    (val, p)
}

fn parse_track_events(data: &[u8], start: usize, len: usize)
    -> (String, u32, Vec<(u32, u8, u8)>) // (name, tempo, note_ons: tick/note/vel)
{
    let end = start + len;
    let mut pos = start;
    let mut tick = 0u32;
    let mut last_status = 0u8;
    let mut name = String::new();
    let mut tempo = 0u32;
    let mut note_ons = Vec::new();

    while pos < end {
        let (delta, np) = read_varint(data, pos); pos = np;
        tick += delta;
        if pos >= end { break; }

        if data[pos] & 0x80 != 0 { last_status = data[pos]; pos += 1; }
        let status = last_status;

        match status {
            0xff => {
                if pos + 1 >= end { break; }
                let meta = data[pos]; pos += 1;
                let (mlen, np) = read_varint(data, pos); pos = np;
                let mend = pos + mlen as usize;
                if meta == 0x03 {
                    name = String::from_utf8_lossy(&data[pos..mend]).to_string();
                } else if meta == 0x51 && mlen >= 3 {
                    tempo = u32::from_be_bytes([0, data[pos], data[pos+1], data[pos+2]]);
                } else if meta == 0x2f {
                    break;
                }
                pos = mend;
            }
            s if s & 0xf0 == 0x90 => {
                if pos + 1 >= end { break; }
                let note = data[pos]; pos += 1;
                let vel  = data[pos]; pos += 1;
                if vel > 0 { note_ons.push((tick, note, vel)); }
            }
            s if s & 0xf0 == 0x80 => { pos += 2; }
            s if s & 0xf0 == 0xa0 || s & 0xf0 == 0xb0 || s & 0xf0 == 0xe0 => { pos += 2; }
            s if s & 0xf0 == 0xc0 || s & 0xf0 == 0xd0 => { pos += 1; }
            0xf0 | 0xf7 => {
                let (slen, np) = read_varint(data, pos);
                pos = np + slen as usize;
            }
            _ => break,
        }
    }
    (name, tempo, note_ons)
}

fn parse_instrument_track(name: &str, note_ons: &[(u32, u8, u8)], tpb: u32) -> Option<Track> {
    // Name format: "T1 PITCH:D:DRUMS" or "T3 VOX:V:VOCAL"
    let parts: Vec<&str> = name.splitn(2, ' ').collect();
    if parts.len() < 2 { return None; }
    let colon_parts: Vec<&str> = parts[1].split(':').collect();
    if colon_parts.len() < 2 { return None; }

    let instrument = if colon_parts.len() >= 3 {
        match colon_parts[2].chars().next().unwrap_or('?') {
            'D' => "drums",
            'B' => "bass",
            'V' => "vocal",
            'S' => "synth",
            'G' => "guitar",
            'F' => "fx",
            _   => return None,
        }
    } else { return None; };

    let mut gems = Vec::new();
    let mut sections = Vec::new();

    for &(tick, note, vel) in note_ons {
        let beat = tick as f32 / tpb as f32;
        if SECTION_MARKERS.contains(&note) {
            sections.push(Section { beat, marker: note });
        } else {
            let difficulty = note / 12;
            let position   = note % 12;
            gems.push(Gem { beat, note, velocity: vel, difficulty, position });
        }
    }

    gems.sort_by(|a,b| a.beat.partial_cmp(&b.beat).unwrap());
    Some(Track { instrument: instrument.to_string(), gems, sections })
}
