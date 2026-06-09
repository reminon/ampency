// Well, hello there...
mod shader;
mod tunnel;

use sdl2::event::Event;
use sdl2::keyboard::Keycode;
use sdl2::video::GLProfile;
use nalgebra::{Matrix4, Perspective3, Point3, Vector3};

const VERT_SRC: &str = r#"
#version 330 core
layout (location = 0) in vec3 aPos;
layout (location = 1) in vec3 aColor;

out vec3 vColor;

uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;

void main() {
    gl_Position = projection * view * model * vec4(aPos, 1.0);
    vColor = aColor;
}
"#;

const FRAG_SRC: &str = r#"
#version 330 core
in vec3 vColor;
out vec4 FragColor;

void main() {
    FragColor = vec4(vColor, 1.0);
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
        gl::ClearColor(0.0, 0.0, 0.0, 1.0);
        gl::Enable(gl::DEPTH_TEST);
    }

    let shader = shader::Shader::new(VERT_SRC, FRAG_SRC);
    let tunnel = tunnel::Tunnel::new();

    // Camera inside the tunnel looking forward
    let eye = Point3::new(0.0f32, 0.0, 1.5);
    let target = Point3::new(0.0f32, 0.0, -1.0);
    let up = Vector3::new(0.0f32, 1.0, 0.0);
    let view = Matrix4::look_at_rh(&eye, &target, &up);

    let projection = Perspective3::new(
        1280.0 / 720.0, // aspect ratio
        70.0f32.to_radians(), // FOV
        0.1,  // near
        100.0 // far
    ).to_homogeneous();

    let model = Matrix4::<f32>::identity();

    let mut event_pump = sdl_context.event_pump().unwrap();

    'running: loop {
        for event in event_pump.poll_iter() {
            match event {
                Event::Quit { .. }
                | Event::KeyDown {
                    keycode: Some(Keycode::Escape),
                    ..
                } => break 'running,
                _ => {}
            }
        }

        unsafe {
            gl::Clear(gl::COLOR_BUFFER_BIT | gl::DEPTH_BUFFER_BIT);
        }

        shader.use_program();
        shader.set_mat4("model", &model);
        shader.set_mat4("view", &view);
        shader.set_mat4("projection", &projection);

        tunnel.draw();

        window.gl_swap_window();
    }
}
