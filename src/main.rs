// Well, hello there...
mod shader;
mod tunnel;
mod themes;

use sdl2::event::Event;
use sdl2::keyboard::Keycode;
use sdl2::video::GLProfile;
use nalgebra::{Matrix4, Perspective3, Point3, Vector3};

const VERT_SRC: &str = r#"
#version 330 core
layout (location = 0) in vec3 aPos;
layout (location = 1) in vec3 aColor;
out vec3 vColor;
out float vDepth;
uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
void main() {
    vec4 viewPos = view * model * vec4(aPos, 1.0);
    gl_Position = projection * viewPos;
    vColor = aColor;
    vDepth = -viewPos.z;
}
"#;

const FRAG_SRC: &str = r#"
#version 330 core
in vec3 vColor;
in float vDepth;
out vec4 FragColor;

uniform float fogStart;
uniform float fogEnd;
uniform vec3 fogColor;

void main() {
    float fogFactor = clamp((fogEnd - vDepth) / (fogEnd - fogStart), 0.0, 1.0);
    vec3 color = mix(fogColor, vColor, fogFactor);
    FragColor = vec4(color, 1.0);
}
"#;

fn main() {
    let sdl_context = sdl2::init().unwrap();
    let video_subsystem = sdl_context.video().unwrap();

    let gl_attr = video_subsystem.gl_attr();
    gl_attr.set_context_profile(GLProfile::Core);
    gl_attr.set_context_version(3, 3);

    let window = video_subsystem
        .window("Ampency", 1280, 720)
        .position_centered()
        .opengl()
        .build()
        .unwrap();

    let _gl_context = window.gl_create_context().unwrap();
    gl::load_with(|s| video_subsystem.gl_get_proc_address(s) as *const _);

    unsafe {
        gl::ClearColor(0.01, 0.01, 0.03, 1.0);
        gl::Enable(gl::DEPTH_TEST);
        gl::Enable(gl::POLYGON_OFFSET_FILL);
        gl::PolygonOffset(1.0, 1.0);
    }

    let shader = shader::Shader::new(VERT_SRC, FRAG_SRC);
    let mut tunnel = tunnel::Tunnel::new();

    // Camera: behind ship on lane 3 (green, center), looking forward
    let eye    = Point3::new(0.0f32, -3.6,  0.8);
    let target = Point3::new(0.0f32, -4.0, -20.0);
    let up     = Vector3::new(0.0f32, 1.0,  0.0);
    let view   = Matrix4::look_at_rh(&eye, &target, &up);

    let projection = Perspective3::new(
        1280.0 / 720.0,
        45.0f32.to_radians(),
        0.1,
        200.0,
    ).to_homogeneous();

    let mut event_pump = sdl_context.event_pump().unwrap();
    let mut last_ticks = sdl_context.timer().unwrap().ticks();
    let mut active_lane: i32 = 2; // start on lane 3 (center-left)
    let mut cam_x: f32 = -0.320; // lane 3 center X
    let lane_centers = [-1.600f32, -0.960, -0.320, 0.320, 0.960, 1.600];

    'running: loop {
        let timer = sdl_context.timer().unwrap();
        let now = timer.ticks();
        let dt = (now - last_ticks) as f32 / 1000.0;
        last_ticks = now;

        for event in event_pump.poll_iter() {
            match event {
                Event::KeyDown { keycode: Some(Keycode::Left), .. } => {
                    active_lane = (active_lane - 1).max(0);
                }
                Event::KeyDown { keycode: Some(Keycode::Right), .. } => {
                    active_lane = (active_lane + 1).min(5);
                }
                Event::Quit { .. }
                | Event::KeyDown { keycode: Some(Keycode::Escape), .. } => {
                    break 'running;
                }
                _ => {}
            }
        }

        tunnel.update(dt);
        let scroll_z = tunnel.scroll_offset;
        let model = Matrix4::new_translation(&Vector3::new(0.0, 0.0, scroll_z));

        // Smooth camera follow
        let target_x = lane_centers[active_lane as usize];
        cam_x += (target_x - cam_x) * (dt * 8.0).min(1.0);

        unsafe {
            gl::Clear(gl::COLOR_BUFFER_BIT | gl::DEPTH_BUFFER_BIT);
        }

        let eye_dyn    = Point3::new(cam_x, -0.2f32, 1.5);
        let target_dyn = Point3::new(cam_x, 3.272f32, -18.196);
        let view_dyn   = Matrix4::look_at_rh(&eye_dyn, &target_dyn, &up);

        shader.use_program();
        shader.set_mat4("model", &model);
        shader.set_mat4("view", &view_dyn);
        shader.set_float("fogStart", 20.0);
        shader.set_float("fogEnd", 56.0);
        shader.set_vec3("fogColor", 0.02, 0.02, 0.06);
        shader.set_mat4("projection", &projection);
        tunnel.draw();

        window.gl_swap_window();
    }
}
