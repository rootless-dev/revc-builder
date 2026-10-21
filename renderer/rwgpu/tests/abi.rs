//! The header `include/rwgpu.h` and the crate agree (design §4.4).

use std::collections::BTreeSet;
use std::path::PathBuf;
use std::process::Command;

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn header() -> String {
    std::fs::read_to_string(root().join("../include/rwgpu.h")).unwrap()
}

/// Identifiers `rwgpu_*` followed by `(` in `text`.
fn functions(text: &str, prefix_filter: impl Fn(&str) -> bool) -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    for line in text.lines().filter(|l| prefix_filter(l)) {
        let mut rest = line;
        while let Some(i) = rest.find("rwgpu_") {
            let tail = &rest[i..];
            let end = tail
                .find(|c: char| !(c.is_ascii_alphanumeric() || c == '_'))
                .unwrap_or(tail.len());
            if tail[end..].starts_with('(') {
                out.insert(tail[..end].to_string());
            }
            rest = &tail[end..];
        }
    }
    out
}

#[test]
fn header_declares_exactly_the_exported_functions() {
    let declared = functions(&header(), |l| {
        !l.trim_start().starts_with('*') && !l.trim_start().starts_with("/*")
    });
    let source = std::fs::read_to_string(root().join("src/ffi.rs")).unwrap();
    let exported = functions(&source, |l| l.contains("extern \"C\" fn"));
    assert!(!exported.is_empty());
    assert_eq!(declared, exported);
}

#[test]
fn header_compiles_with_the_expected_layouts() {
    let status = Command::new("cc")
        .args(["-fsyntax-only", "-std=c11", "-Wall", "-Werror"])
        .arg(format!("-DEXPECTED_ABI_VERSION={}", rwgpu::abi::ABI_VERSION))
        .arg("-I")
        .arg(root().join("../include"))
        .arg(root().join("tests/abi_check.c"))
        .status()
        .expect("a C compiler (cc) is needed for this test");
    assert!(status.success());
}

#[test]
fn header_constants_match_the_crate() {
    use rwgpu::abi::*;
    let h = header();
    let value = |name: &str| -> u32 {
        let at = h
            .find(&format!("RWGPU_{name} = "))
            .unwrap_or_else(|| panic!("{name} not in header"));
        let rest = &h[at + name.len() + 9..];
        rest[..rest.find(|c: char| !c.is_ascii_digit()).unwrap()]
            .parse()
            .unwrap()
    };
    let expected = [
        ("TEXTURERASTER", TEXTURERASTER),
        ("TEXTUREFILTER", TEXTUREFILTER),
        ("VERTEXALPHA", VERTEXALPHA),
        ("CULLMODE", CULLMODE),
        ("STENCILENABLE", STENCILENABLE),
        ("ALPHATESTFUNC", ALPHATESTFUNC),
        ("GSALPHATESTREF", GSALPHATESTREF),
        ("ALPHALESS", ALPHALESS),
        ("CULLFRONT", CULLFRONT),
        ("BLENDSRCALPHASAT", BLENDSRCALPHASAT),
        ("STENCILDEC", STENCILDEC),
        ("STENCILALWAYS", STENCILALWAYS),
        ("FILTERLINEARMIPLINEAR", FILTERLINEARMIPLINEAR),
        ("ADDRESSBORDER", ADDRESSBORDER),
        ("PRIMTYPEPOINTLIST", PRIMTYPEPOINTLIST),
        ("CLEARSTENCIL", CLEARSTENCIL),
        ("FORMAT_BC3", FORMAT_BC3),
        ("SRC_RGB8", SRC_RGB8),
        ("TEXTURE_AUTO_MIPMAP", TEXTURE_AUTO_MIPMAP),
        ("RASTER_FORCE_OPAQUE", RASTER_FORCE_OPAQUE),
        ("SHADER_MATFX_ENV", SHADER_MATFX_ENV),
        ("LAYOUT_SKIN", LAYOUT_SKIN),
        ("WINDOW_APPKIT", WINDOW_APPKIT),
    ];
    for (name, v) in expected {
        assert_eq!(value(name), v, "{name}");
    }
}
