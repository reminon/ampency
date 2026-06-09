use gl;
use std::f32::consts::PI;

// Number of tunnel segments extending into the distance
const TUNNEL_SEGMENTS: usize = 32;
// How far the tunnel extends
const TUNNEL_LENGTH: f32 = 64.0;
// Radius of the octagon
const TUNNEL_RADIUS: f32 = 2.0;
// Number of sides on the octagon
const SIDES: usize = 8;

pub struct Tunnel {
    vao: u32,
    vbo: u32,
    vertex_count: i32,
}

impl Tunnel {
    pub fn new() -> Self {
        let vertices = generate_tunnel_vertices();
        let vertex_count = (vertices.len() / 6) as i32; // x,y,z,r,g,b

        let (mut vao, mut vbo) = (0u32, 0u32);

        unsafe {
            gl::GenVertexArrays(1, &mut vao);
            gl::GenBuffers(1, &mut vbo);

            gl::BindVertexArray(vao);
            gl::BindBuffer(gl::ARRAY_BUFFER, vbo);
            gl::BufferData(
                gl::ARRAY_BUFFER,
                (vertices.len() * std::mem::size_of::<f32>()) as isize,
                vertices.as_ptr() as *const _,
                gl::STATIC_DRAW,
            );

            // Position attribute (location 0)
            gl::VertexAttribPointer(
                0, 3, gl::FLOAT, gl::FALSE,
                6 * std::mem::size_of::<f32>() as i32,
                std::ptr::null(),
            );
            gl::EnableVertexAttribArray(0);

            // Color attribute (location 1)
            gl::VertexAttribPointer(
                1, 3, gl::FLOAT, gl::FALSE,
                6 * std::mem::size_of::<f32>() as i32,
                (3 * std::mem::size_of::<f32>()) as *const _,
            );
            gl::EnableVertexAttribArray(1);

            gl::BindVertexArray(0);
        }

        Tunnel { vao, vbo, vertex_count }
    }

    pub fn draw(&self) {
        unsafe {
            gl::BindVertexArray(self.vao);
            gl::DrawArrays(gl::TRIANGLES, 0, self.vertex_count);
            gl::BindVertexArray(0);
        }
    }
}

impl Drop for Tunnel {
    fn drop(&mut self) {
        unsafe {
            gl::DeleteVertexArrays(1, &self.vao);
            gl::DeleteBuffers(1, &self.vbo);
        }
    }
}

// Colors for each of the 8 walls — matching Frequency's instrument colors
fn wall_color(side: usize) -> (f32, f32, f32) {
    match side {
        0 => (0.8, 0.2, 0.2), // Drums - red
        1 => (0.2, 0.8, 0.2), // Bass - green
        2 => (0.2, 0.2, 0.8), // Guitar - blue
        3 => (0.8, 0.8, 0.2), // Synth - yellow
        4 => (0.8, 0.2, 0.8), // Vocals - magenta
        5 => (0.2, 0.8, 0.8), // Keys - cyan
        6 => (0.8, 0.5, 0.2), // FX - orange
        7 => (0.5, 0.2, 0.8), // Extra - purple
        _ => (1.0, 1.0, 1.0),
    }
}

fn generate_tunnel_vertices() -> Vec<f32> {
    let mut vertices = Vec::new();

    let segment_length = TUNNEL_LENGTH / TUNNEL_SEGMENTS as f32;

    for seg in 0..TUNNEL_SEGMENTS {
        let z_near = -(seg as f32 * segment_length);
        let z_far = -((seg + 1) as f32 * segment_length);

        for side in 0..SIDES {
            let angle1 = (side as f32 / SIDES as f32) * 2.0 * PI;
            let angle2 = ((side + 1) as f32 / SIDES as f32) * 2.0 * PI;

            let x1 = TUNNEL_RADIUS * angle1.cos();
            let y1 = TUNNEL_RADIUS * angle1.sin();
            let x2 = TUNNEL_RADIUS * angle2.cos();
            let y2 = TUNNEL_RADIUS * angle2.sin();

            let (r, g, b) = wall_color(side);

            // Two triangles per wall segment
            // Triangle 1
            vertices.extend_from_slice(&[x1, y1, z_near, r, g, b]);
            vertices.extend_from_slice(&[x2, y2, z_near, r, g, b]);
            vertices.extend_from_slice(&[x1, y1, z_far,  r, g, b]);
            // Triangle 2
            vertices.extend_from_slice(&[x2, y2, z_near, r, g, b]);
            vertices.extend_from_slice(&[x2, y2, z_far,  r, g, b]);
            vertices.extend_from_slice(&[x1, y1, z_far,  r, g, b]);
        }
    }

    vertices
}
