use gl;
use std::ffi::CString;

pub struct Shader {
    pub id: u32,
}

impl Shader {
    pub fn new(vertex_src: &str, fragment_src: &str) -> Self {
        unsafe {
            // Compile vertex shader
            let vertex = gl::CreateShader(gl::VERTEX_SHADER);
            let c_str = CString::new(vertex_src).unwrap();
            gl::ShaderSource(vertex, 1, &c_str.as_ptr(), std::ptr::null());
            gl::CompileShader(vertex);
            check_compile_errors(vertex, "VERTEX");

            // Compile fragment shader
            let fragment = gl::CreateShader(gl::FRAGMENT_SHADER);
            let c_str = CString::new(fragment_src).unwrap();
            gl::ShaderSource(fragment, 1, &c_str.as_ptr(), std::ptr::null());
            gl::CompileShader(fragment);
            check_compile_errors(fragment, "FRAGMENT");

            // Link program
            let id = gl::CreateProgram();
            gl::AttachShader(id, vertex);
            gl::AttachShader(id, fragment);
            gl::LinkProgram(id);
            check_compile_errors(id, "PROGRAM");

            gl::DeleteShader(vertex);
            gl::DeleteShader(fragment);

            Shader { id }
        }
    }

    pub fn use_program(&self) {
        unsafe { gl::UseProgram(self.id); }
    }

    pub fn set_mat4(&self, name: &str, mat: &nalgebra::Matrix4<f32>) {
        unsafe {
            let c_name = CString::new(name).unwrap();
            let loc = gl::GetUniformLocation(self.id, c_name.as_ptr());
            gl::UniformMatrix4fv(loc, 1, gl::FALSE, mat.as_ptr());
        }
    }

    pub fn set_vec3(&self, name: &str, x: f32, y: f32, z: f32) {
        unsafe {
            let c_name = CString::new(name).unwrap();
            let loc = gl::GetUniformLocation(self.id, c_name.as_ptr());
            gl::Uniform3f(loc, x, y, z);
        }
    }
}

fn check_compile_errors(shader: u32, shader_type: &str) {
    unsafe {
        let mut success = gl::FALSE as i32;
        let mut info_log = vec![0u8; 1024];
        if shader_type != "PROGRAM" {
            gl::GetShaderiv(shader, gl::COMPILE_STATUS, &mut success);
            if success != gl::TRUE as i32 {
                gl::GetShaderInfoLog(
                    shader, 1024, std::ptr::null_mut(),
                    info_log.as_mut_ptr() as *mut i8,
                );
                eprintln!("Shader compile error [{}]: {}", shader_type,
                    String::from_utf8_lossy(&info_log));
            }
        } else {
            gl::GetProgramiv(shader, gl::LINK_STATUS, &mut success);
            if success != gl::TRUE as i32 {
                gl::GetProgramInfoLog(
                    shader, 1024, std::ptr::null_mut(),
                    info_log.as_mut_ptr() as *mut i8,
                );
                eprintln!("Program link error: {}",
                    String::from_utf8_lossy(&info_log));
            }
        }
    }
}
