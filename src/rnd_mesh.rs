//! Amplitude RND Mesh loader.
//! Parses the binary Mesh object format from decompressed RND data blocks.
//!
//! Mesh binary layout:
//!   u32 × 2          header fields
//!   f32 × 16         4×4 transform matrix (row-major)
//!   u32 × 20         padding / unknown fields
//!   u32              mat_name_len + mat_name bytes
//!   u32              mesh_name_len + mesh_name bytes (×2)
//!   u32 × 5          padding
//!   u32              vertex_count
//!   f32 × (count×14) vertex data (56 bytes each)
//!   u32              face_count
//!   u16 × (count×3)  triangle indices
//!   u32              0xDEADDEAD sentinel

use gl;
use std::mem;

#[derive(Debug, Clone)]
pub struct Vertex {
    pub pos:    [f32; 3],
    pub normal: [f32; 3],
    pub color:  [f32; 3],
    pub alpha:  f32,
    pub uv:     [f32; 2],
}

pub struct RndMesh {
    pub name:     String,
    pub material: String,
    pub vertices: Vec<Vertex>,
    pub indices:  Vec<u16>,
    vao: u32,
    vbo: u32,
    ibo: u32,
}

impl RndMesh {
    /// Parse a mesh from a raw block slice (decompressed RND object data).
    pub fn from_block(block: &[u8]) -> Option<Self> {
        let mut pos = 0usize;

        // Skip 2 header u32s
        pos += 8;
        // Skip 4×4 transform matrix (64 bytes)
        pos += 64;
        // Skip 20 unknown u32s (80 bytes)
        pos += 80;

        // Read material name (length-prefixed)
        if pos + 4 > block.len() { return None; }
        let mat_len = u32::from_le_bytes(block[pos..pos+4].try_into().ok()?) as usize;
        pos += 4;
        if pos + mat_len > block.len() { return None; }
        let material = String::from_utf8_lossy(&block[pos..pos+mat_len]).to_string();
        pos += mat_len;

        // Read mesh name ×2 (skip second copy)
        if pos + 4 > block.len() { return None; }
        let name_len = u32::from_le_bytes(block[pos..pos+4].try_into().ok()?) as usize;
        pos += 4;
        if pos + name_len > block.len() { return None; }
        let name = String::from_utf8_lossy(&block[pos..pos+name_len]).to_string();
        pos += name_len;
        // Second copy
        if pos + 4 > block.len() { return None; }
        let name2_len = u32::from_le_bytes(block[pos..pos+4].try_into().ok()?) as usize;
        pos += 4 + name2_len;

        // Skip 5 padding u32s (20 bytes)
        pos += 20;

        // Vertex count
        if pos + 4 > block.len() { return None; }
        let vert_count = u32::from_le_bytes(block[pos..pos+4].try_into().ok()?) as usize;
        pos += 4;

        // Read vertices (56 bytes = 14 f32 each)
        let mut vertices = Vec::with_capacity(vert_count);
        for _ in 0..vert_count {
            if pos + 56 > block.len() { return None; }
            let v: Vec<f32> = (0..14)
                .map(|i| f32::from_le_bytes(block[pos+i*4..pos+i*4+4].try_into().unwrap()))
                .collect();
            vertices.push(Vertex {
                pos:    [v[0],  v[1],  v[2]],
                normal: [v[4],  v[5],  v[6]],
                color:  [v[8],  v[9],  v[10]],
                alpha:  v[11],
                uv:     [v[12], v[13]],
            });
            pos += 56;
        }

        // Face count (number of triangles)
        if pos + 4 > block.len() { return None; }
        let face_count = u32::from_le_bytes(block[pos..pos+4].try_into().ok()?) as usize;
        pos += 4;

        // Read indices (u16, 3 per triangle)
        let mut indices = Vec::with_capacity(face_count * 3);
        for _ in 0..face_count * 3 {
            if pos + 2 > block.len() { return None; }
            let idx = u16::from_le_bytes(block[pos..pos+2].try_into().ok()?);
            indices.push(idx);
            pos += 2;
        }

        // Build OpenGL buffers
        // Interleaved: pos(3) + normal(3) + color(3) + alpha(1) + uv(2) = 12 floats
        let mut flat: Vec<f32> = Vec::with_capacity(vert_count * 12);
        for v in &vertices {
            flat.extend_from_slice(&v.pos);
            flat.extend_from_slice(&v.normal);
            flat.extend_from_slice(&v.color);
            flat.push(v.alpha);
            flat.extend_from_slice(&v.uv);
        }

        let (mut vao, mut vbo, mut ibo) = (0u32, 0u32, 0u32);
        unsafe {
            gl::GenVertexArrays(1, &mut vao);
            gl::GenBuffers(1, &mut vbo);
            gl::GenBuffers(1, &mut ibo);
            gl::BindVertexArray(vao);

            gl::BindBuffer(gl::ARRAY_BUFFER, vbo);
            gl::BufferData(gl::ARRAY_BUFFER,
                (flat.len() * mem::size_of::<f32>()) as isize,
                flat.as_ptr() as *const _,
                gl::STATIC_DRAW);

            gl::BindBuffer(gl::ELEMENT_ARRAY_BUFFER, ibo);
            gl::BufferData(gl::ELEMENT_ARRAY_BUFFER,
                (indices.len() * mem::size_of::<u16>()) as isize,
                indices.as_ptr() as *const _,
                gl::STATIC_DRAW);

            let stride = (12 * mem::size_of::<f32>()) as i32;
            // pos (location 0)
            gl::VertexAttribPointer(0, 3, gl::FLOAT, gl::FALSE, stride,
                std::ptr::null());
            gl::EnableVertexAttribArray(0);
            // normal (location 1) - skip for now, reuse color slot
            // color (location 1)
            gl::VertexAttribPointer(1, 3, gl::FLOAT, gl::FALSE, stride,
                (6 * mem::size_of::<f32>()) as *const _);
            gl::EnableVertexAttribArray(1);

            gl::BindVertexArray(0);
        }

        Some(RndMesh { name, material, vertices, indices, vao, vbo, ibo })
    }

    pub fn draw(&self) {
        unsafe {
            gl::BindVertexArray(self.vao);
            gl::DrawElements(gl::TRIANGLES,
                self.indices.len() as i32,
                gl::UNSIGNED_SHORT,
                std::ptr::null());
            gl::BindVertexArray(0);
        }
    }
}

impl Drop for RndMesh {
    fn drop(&mut self) {
        unsafe {
            gl::DeleteVertexArrays(1, &self.vao);
            gl::DeleteBuffers(1, &self.vbo);
            gl::DeleteBuffers(1, &self.ibo);
        }
    }
}
