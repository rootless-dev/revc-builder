//! WGSL sources (design §5.5).

pub const MAIN: &str = include_str!("shaders/main.wgsl");
pub const BLIT: &str = include_str!("shaders/blit.wgsl");
pub const OVERRIDE_PRELUDE: &str = include_str!("shaders/override_prelude.wgsl");

/// The full source of an Im2D override fragment module.
pub fn override_source(fragment: &str) -> String {
    format!("{OVERRIDE_PRELUDE}\n{fragment}\n")
}

#[cfg(test)]
pub(crate) fn validate(source: &str) -> Result<naga::Module, String> {
    let module = naga::front::wgsl::parse_str(source).map_err(|e| e.emit_to_string(source))?;
    naga::valid::Validator::new(naga::valid::ValidationFlags::all(), naga::valid::Capabilities::empty())
        .validate(&module)
        .map_err(|e| e.emit_to_string(source))?;
    Ok(module)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn main_module_is_valid() {
        let module = validate(MAIN).unwrap();
        let names: Vec<_> = module.entry_points.iter().map(|e| e.name.as_str()).collect();
        for name in [
            "vs_default",
            "vs_skin",
            "vs_matfx_env",
            "vs_im3d",
            "vs_im2d",
            "vs_im2d_uv2",
            "fs_simple",
            "fs_matfx_env",
            "vs_clear",
            "fs_clear",
        ] {
            assert!(names.contains(&name), "{name} missing");
        }
    }

    #[test]
    fn blit_module_is_valid() {
        validate(BLIT).unwrap();
    }

    /// reVC's override shaders, which the reVC patch includes as raw string literals
    /// (design §8.2), compile against the prelude.
    #[test]
    fn revc_override_shaders_are_valid() {
        let dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../renderers/wgpu/revc/files/src/extras/shaders/wgpu");
        let mut checked = 0;
        for entry in std::fs::read_dir(&dir).unwrap() {
            let path = entry.unwrap().path();
            let text = std::fs::read_to_string(&path).unwrap();
            let body = text
                .trim()
                .strip_prefix("R\"wgsl(")
                .and_then(|t| t.strip_suffix(")wgsl\""))
                .unwrap_or_else(|| panic!("{} is not a R\"wgsl(...)wgsl\" literal", path.display()));
            validate(&override_source(body)).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
            checked += 1;
        }
        assert_eq!(checked, 3);
    }

    #[test]
    fn override_prelude_accepts_a_fragment() {
        let src = override_source(
            "@fragment fn fs_main(in: Im2DOut) -> @location(0) vec4f { return textureSample(tex0, samp0, in.tex0) * param(0); }",
        );
        validate(&src).unwrap();
    }
}
