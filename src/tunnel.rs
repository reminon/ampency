// Amplitude tunnel renderer
// Circular tunnel with 6 flat lane panels at the bottom.

use gl;
use std::f32::consts::PI;

const TUNNEL_SEGMENTS: usize = 48;
const TUNNEL_LENGTH: f32 = 80.0;
const TUNNEL_RADIUS: f32 = 4.0;
const SIDES: usize = 32; // circular approximation
const LANE_COUNT: usize = 6;
const LANE_WIDTH: f32 = 0.60;
const LANE_DIVIDER: f32 = 0.04;
const TRACK_Y: f32 = 0.0;
const RING_COUNT: usize = 50;

pub mod palette {
    // Lane colors left to right
        pub const LANES: [[f32; 3]; 6] = [
        [0.550, 0.000, 0.000], // Lane 1 - Red    (Drum bg)
        [0.000, 0.200, 0.650], // Lane 2 - Blue   (Bass bg)
        [0.000, 0.550, 0.000], // Lane 3 - Green  (Vocal bg)
        [0.700, 0.600, 0.000], // Lane 4 - Yellow (Synth bg)
        [0.800, 0.350, 0.000], // Lane 5 - Orange (Guitar bg)
        [0.550, 0.000, 0.000], // Lane 6 - Red    (Drum bg)
    ];
    pub const WALL_DARK:  [f32; 3] = [0.08, 0.01, 0.01]; // dark red-black
    pub const WALL_RING:  [f32; 3] = [1.0,  0.2,  0.2 ]; // red glow ring
    pub const DIVIDER:    [f32; 3] = [0.05, 0.05, 0.05]; // dark divider
    pub const BORDER:     [f32; 3] = [0.08, 0.08, 0.08]; // outer border panels
}

pub struct Tunnel {
    vao: u32,
    vbo: u32,
    vertex_count: i32,
    pub scroll_offset: f32,
    pub active_lane: usize,
}

impl Tunnel {
    pub fn new() -> Self {
        let vertices = generate_vertices(0);
        let vertex_count = (vertices.len() / 6) as i32;
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
            gl::VertexAttribPointer(0, 3, gl::FLOAT, gl::FALSE,
                6 * std::mem::size_of::<f32>() as i32, std::ptr::null());
            gl::EnableVertexAttribArray(0);
            gl::VertexAttribPointer(1, 3, gl::FLOAT, gl::FALSE,
                6 * std::mem::size_of::<f32>() as i32,
                (3 * std::mem::size_of::<f32>()) as *const _);
            gl::EnableVertexAttribArray(1);
            gl::BindVertexArray(0);
        }
        Tunnel { vao, vbo, vertex_count, scroll_offset: 0.0, active_lane: 0 }
    }

    pub fn update(&mut self, dt: f32) {
        self.scroll_offset += dt * 6.0;
        let seg_len = TUNNEL_LENGTH / RING_COUNT as f32;
        if self.scroll_offset >= seg_len {
            self.scroll_offset -= seg_len;
        }
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

fn push_quad(v: &mut Vec<f32>, p: [[f32; 3]; 4], color: [f32; 3]) {
    let [r, g, b] = color;
    v.extend_from_slice(&[p[0][0],p[0][1],p[0][2], r,g,b]);
    v.extend_from_slice(&[p[1][0],p[1][1],p[1][2], r,g,b]);
    v.extend_from_slice(&[p[2][0],p[2][1],p[2][2], r,g,b]);
    v.extend_from_slice(&[p[0][0],p[0][1],p[0][2], r,g,b]);
    v.extend_from_slice(&[p[2][0],p[2][1],p[2][2], r,g,b]);
    v.extend_from_slice(&[p[3][0],p[3][1],p[3][2], r,g,b]);
}

fn circle_pt(i: usize, total: usize, radius: f32) -> (f32, f32) {
    let angle = (i as f32 / total as f32) * 2.0 * PI - PI * 0.5;
    (radius * angle.cos(), radius * angle.sin())
}

fn generate_vertices(_active_lane: usize) -> Vec<f32> {
    let mut v = Vec::new();
    let seg_len = TUNNEL_LENGTH / TUNNEL_SEGMENTS as f32;

    // Circular tunnel walls
    for seg in 0..TUNNEL_SEGMENTS {
        let z_n = -(seg as f32 * seg_len);
        let z_f = -((seg + 1) as f32 * seg_len);
        for side in 0..SIDES {
            let (x1, y1) = circle_pt(side,     SIDES, TUNNEL_RADIUS);
            let (x2, y2) = circle_pt(side + 1, SIDES, TUNNEL_RADIUS);
            // Darken bottom panels, lighter on top
            let t = (y1 + TUNNEL_RADIUS) / (2.0 * TUNNEL_RADIUS);
            let shade = 0.3 + t * 0.4;
            let [wr, wg, wb] = palette::WALL_DARK;
            push_quad(&mut v, [
                [x1, y1, z_n], [x2, y2, z_n],
                [x2, y2, z_f], [x1, y1, z_f],
            ], [wr * shade, wg * shade * 0.3, wb * shade * 0.3]);
        }
    }

    // Red glowing rings
    let ring_seg = TUNNEL_LENGTH / RING_COUNT as f32;
    let rt = 0.06f32;
    let ring_inner = TUNNEL_RADIUS - 0.25;
    for ring in 0..RING_COUNT {
        let z = -(ring as f32 * ring_seg);
        for side in 0..SIDES {
            let (x1, y1) = circle_pt(side,     SIDES, TUNNEL_RADIUS);
            let (x2, y2) = circle_pt(side + 1, SIDES, TUNNEL_RADIUS);
            let (x1i, y1i) = circle_pt(side,     SIDES, ring_inner);
            let (x2i, y2i) = circle_pt(side + 1, SIDES, ring_inner);
            push_quad(&mut v, [
                [x1,  y1,  z - rt],
                [x2,  y2,  z - rt],
                [x2i, y2i, z + rt],
                [x1i, y1i, z + rt],
            ], palette::WALL_RING);
        }
    }

    // Track surface - 6 lanes + borders
    let total_track_width = LANE_COUNT as f32 * LANE_WIDTH
        + (LANE_COUNT - 1) as f32 * LANE_DIVIDER;
    let track_start_x = -total_track_width * 0.5;
    let ty = TRACK_Y;
    let z0 = 2.5f32;
    let z1 = -TUNNEL_LENGTH;

    // Outer border left
    let border_w = 0.3f32;
    push_quad(&mut v, [
        [track_start_x - border_w, ty, z0],
        [track_start_x,            ty, z0],
        [track_start_x,            ty, z1],
        [track_start_x - border_w, ty, z1],
    ], palette::BORDER);

    // 6 lane panels
    for lane in 0..LANE_COUNT {
        let x0 = track_start_x + lane as f32 * (LANE_WIDTH + LANE_DIVIDER);
        let x1 = x0 + LANE_WIDTH;
        let color = palette::LANES[lane];
        let dim = [color[0] * 0.45, color[1] * 0.45, color[2] * 0.45];

        // Lane panel (dimmed base)
        push_quad(&mut v, [
            [x0, ty, z0], [x1, ty, z0],
            [x1, ty, z1], [x0, ty, z1],
        ], dim);

        // Bright center strip
        let cx = (x0 + x1) * 0.5;
        let sw = 0.05f32;
        push_quad(&mut v, [
            [cx - sw, ty + 0.001, z0], [cx + sw, ty + 0.001, z0],
            [cx + sw, ty + 0.001, z1], [cx - sw, ty + 0.001, z1],
        ], color);

        // Divider after lane (except last)
        if lane < LANE_COUNT - 1 {
            let dx = x1;
            push_quad(&mut v, [
                [dx,                  ty, z0],
                [dx + LANE_DIVIDER,   ty, z0],
                [dx + LANE_DIVIDER,   ty, z1],
                [dx,                  ty, z1],
            ], palette::DIVIDER);
        }
    }

    // Outer border right
    let track_end_x = track_start_x + total_track_width;
    push_quad(&mut v, [
        [track_end_x,            ty, z0],
        [track_end_x + border_w, ty, z0],
        [track_end_x + border_w, ty, z1],
        [track_end_x,            ty, z1],
    ], palette::BORDER);

    v
}
