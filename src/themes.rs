// Visual theme system for Ampency
// Two themes are planned:
//   - FrequencyTheme: darker industrial aesthetic, hard edges, electronica feel
//   - AmplitudeTheme: bright neon dreamlike aesthetic, smoother effects
//
// Each theme implements the VisualTheme trait and provides its own:
//   - Tunnel shaders and color palette
//   - Note gem appearance
//   - Particle effects
//   - UI style
//   - Background environments

pub trait VisualTheme {
    fn name(&self) -> &str;
    fn wall_color(&self, side: usize) -> (f32, f32, f32);
    fn background_color(&self) -> (f32, f32, f32);
}
