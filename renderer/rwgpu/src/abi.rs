//! Types and constants shared with C through `include/rwgpu.h` (design §4).
//!
//! Enumerations that mirror librw keep librw's numbering, so the C++ driver forwards
//! values unchanged. Every `#[repr(C)]` struct here has a size and layout that tests check
//! against the header and against the numbers in the design.

/// Bumped whenever a function signature, struct layout or constant changes.
pub const ABI_VERSION: u32 = 1;

// --- render states (librw `RenderState`) ---------------------------------------------
pub const TEXTURERASTER: u32 = 0;
pub const TEXTUREADDRESS: u32 = 1;
pub const TEXTUREADDRESSU: u32 = 2;
pub const TEXTUREADDRESSV: u32 = 3;
pub const TEXTUREFILTER: u32 = 4;
pub const VERTEXALPHA: u32 = 5;
pub const SRCBLEND: u32 = 6;
pub const DESTBLEND: u32 = 7;
pub const ZTESTENABLE: u32 = 8;
pub const ZWRITEENABLE: u32 = 9;
pub const FOGENABLE: u32 = 10;
pub const FOGCOLOR: u32 = 11;
pub const CULLMODE: u32 = 12;
pub const STENCILENABLE: u32 = 13;
pub const STENCILFAIL: u32 = 14;
pub const STENCILZFAIL: u32 = 15;
pub const STENCILPASS: u32 = 16;
pub const STENCILFUNCTION: u32 = 17;
pub const STENCILFUNCTIONREF: u32 = 18;
pub const STENCILFUNCTIONMASK: u32 = 19;
pub const STENCILFUNCTIONWRITEMASK: u32 = 20;
pub const ALPHATESTFUNC: u32 = 21;
pub const ALPHATESTREF: u32 = 22;
pub const GSALPHATEST: u32 = 23;
pub const GSALPHATESTREF: u32 = 24;

// --- alpha test functions (librw `AlphaTestFunc`) ---------------------------------------
pub const ALPHAALWAYS: u32 = 0;
pub const ALPHAGREATEREQUAL: u32 = 1;
pub const ALPHALESS: u32 = 2;

// --- stencil operations and functions (librw `StencilOp`, `StencilFunc`) -----------------
pub const STENCILKEEP: u32 = 1;
pub const STENCILZERO: u32 = 2;
pub const STENCILREPLACE: u32 = 3;
pub const STENCILINCSAT: u32 = 4;
pub const STENCILDECSAT: u32 = 5;
pub const STENCILINVERT: u32 = 6;
pub const STENCILINC: u32 = 7;
pub const STENCILDEC: u32 = 8;

pub const STENCILNEVER: u32 = 1;
pub const STENCILLESS: u32 = 2;
pub const STENCILEQUAL: u32 = 3;
pub const STENCILLESSEQUAL: u32 = 4;
pub const STENCILGREATER: u32 = 5;
pub const STENCILNOTEQUAL: u32 = 6;
pub const STENCILGREATEREQUAL: u32 = 7;
pub const STENCILALWAYS: u32 = 8;

// --- cull modes (librw `CullMode`) ---------------------------------------------------------
pub const CULLNONE: u32 = 1;
pub const CULLBACK: u32 = 2;
pub const CULLFRONT: u32 = 3;

// --- blend functions (librw `BlendFunction`) -------------------------------------------------
pub const BLENDZERO: u32 = 1;
pub const BLENDONE: u32 = 2;
pub const BLENDSRCCOLOR: u32 = 3;
pub const BLENDINVSRCCOLOR: u32 = 4;
pub const BLENDSRCALPHA: u32 = 5;
pub const BLENDINVSRCALPHA: u32 = 6;
pub const BLENDDESTALPHA: u32 = 7;
pub const BLENDINVDESTALPHA: u32 = 8;
pub const BLENDDESTCOLOR: u32 = 9;
pub const BLENDINVDESTCOLOR: u32 = 10;
pub const BLENDSRCALPHASAT: u32 = 11;

// --- texture filtering and addressing (librw `Texture::FilterMode`, `Texture::Addressing`) ---
pub const FILTERNEAREST: u32 = 1;
pub const FILTERLINEAR: u32 = 2;
pub const FILTERMIPNEAREST: u32 = 3;
pub const FILTERMIPLINEAR: u32 = 4;
pub const FILTERLINEARMIPNEAREST: u32 = 5;
pub const FILTERLINEARMIPLINEAR: u32 = 6;

pub const ADDRESSWRAP: u32 = 1;
pub const ADDRESSMIRROR: u32 = 2;
pub const ADDRESSCLAMP: u32 = 3;
pub const ADDRESSBORDER: u32 = 4;

// --- primitive types (librw `PrimitiveType`) ------------------------------------------------
pub const PRIMTYPENONE: u32 = 0;
pub const PRIMTYPELINELIST: u32 = 1;
pub const PRIMTYPEPOLYLINE: u32 = 2;
pub const PRIMTYPETRILIST: u32 = 3;
pub const PRIMTYPETRISTRIP: u32 = 4;
pub const PRIMTYPETRIFAN: u32 = 5;
pub const PRIMTYPEPOINTLIST: u32 = 6;

// --- camera clear flags (librw `Camera::CLEAR*`) -------------------------------------------
pub const CLEARIMAGE: u32 = 1;
pub const CLEARZ: u32 = 2;
pub const CLEARSTENCIL: u32 = 4;

// --- our own enumerations ----------------------------------------------------------------
pub const WINDOW_APPKIT: u32 = 1;

pub const FORMAT_RGBA8: u32 = 1;
pub const FORMAT_BC1: u32 = 2;
pub const FORMAT_BC2: u32 = 3;
pub const FORMAT_BC3: u32 = 4;

pub const SRC_NATIVE: u32 = 0;
pub const SRC_RGB8: u32 = 1;

pub const TEXTURE_RENDER_TARGET: u32 = 1;
pub const TEXTURE_AUTO_MIPMAP: u32 = 2;

pub const RASTER_HAS_ALPHA: u32 = 1;
pub const RASTER_FORCE_OPAQUE: u32 = 2;

pub const SHADER_DEFAULT: u32 = 0;
pub const SHADER_SKIN: u32 = 1;
pub const SHADER_MATFX_ENV: u32 = 2;

pub const LAYOUT_MESH: u32 = 0;
pub const LAYOUT_SKIN: u32 = 1;

pub const MAX_LIGHTS: usize = 8;
pub const MAX_BONES: usize = 64;
pub const MAX_STAGES: usize = 8;

#[repr(C)]
#[derive(Clone, Copy, Debug)]
pub struct RwgpuWindowDesc {
    pub kind: u32,
    pub width: u32,
    pub height: u32,
    pub vsync: u32,
    pub handle: [*mut core::ffi::c_void; 4],
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct RwgpuStats {
    pub frames: u64,
    pub validation_errors: u64,
    pub pipelines: u32,
    pub textures: u32,
    pub meshes: u32,
    pub reserved: u32,
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct RwgpuCaps {
    pub bc_supported: u32,
    pub max_anisotropy: f32,
    pub max_texture_size: u32,
    pub reserved: u32,
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
pub struct RwgpuTarget {
    pub color: u32,
    pub depth: u32,
    pub x: i32,
    pub y: i32,
    pub w: i32,
    pub h: i32,
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, bytemuck::Pod, bytemuck::Zeroable)]
pub struct RwgpuLight {
    pub kind: f32,
    pub radius: f32,
    pub minus_cos_angle: f32,
    pub hard_spot: f32,
    pub position: [f32; 4],
    pub direction: [f32; 4],
    pub color: [f32; 4],
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, bytemuck::Pod, bytemuck::Zeroable)]
pub struct RwgpuIm2DVertex {
    pub x: f32,
    pub y: f32,
    pub z: f32,
    pub w: f32,
    pub r: u8,
    pub g: u8,
    pub b: u8,
    pub a: u8,
    pub u: f32,
    pub v: f32,
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, bytemuck::Pod, bytemuck::Zeroable)]
pub struct RwgpuIm2DVertexUV2 {
    pub base: RwgpuIm2DVertex,
    pub u2: f32,
    pub v2: f32,
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, bytemuck::Pod, bytemuck::Zeroable)]
pub struct RwgpuIm3DVertex {
    pub pos: [f32; 3],
    pub normal: [f32; 3],
    pub r: u8,
    pub g: u8,
    pub b: u8,
    pub a: u8,
    pub u: f32,
    pub v: f32,
}

/// Byte stride of a `MESH` layout vertex (design §4.2).
pub const MESH_STRIDE: u64 = 44;
/// Byte stride of a `SKIN` layout vertex (design §4.2).
pub const SKIN_STRIDE: u64 = 64;

#[cfg(test)]
mod tests {
    use super::*;
    use core::mem::{offset_of, size_of};

    #[test]
    fn struct_sizes_match_the_design() {
        assert_eq!(size_of::<RwgpuWindowDesc>(), 48);
        assert_eq!(size_of::<RwgpuStats>(), 32);
        assert_eq!(size_of::<RwgpuCaps>(), 16);
        assert_eq!(size_of::<RwgpuTarget>(), 24);
        assert_eq!(size_of::<RwgpuLight>(), 64);
        assert_eq!(size_of::<RwgpuIm2DVertex>(), 28);
        assert_eq!(size_of::<RwgpuIm2DVertexUV2>(), 36);
        assert_eq!(size_of::<RwgpuIm3DVertex>(), 36);
    }

    #[test]
    fn struct_offsets_match_the_design() {
        assert_eq!(offset_of!(RwgpuWindowDesc, handle), 16);
        assert_eq!(offset_of!(RwgpuStats, pipelines), 16);
        assert_eq!(offset_of!(RwgpuTarget, x), 8);
        assert_eq!(offset_of!(RwgpuLight, position), 16);
        assert_eq!(offset_of!(RwgpuLight, direction), 32);
        assert_eq!(offset_of!(RwgpuLight, color), 48);
        assert_eq!(offset_of!(RwgpuIm2DVertex, r), 16);
        assert_eq!(offset_of!(RwgpuIm2DVertex, u), 20);
        assert_eq!(offset_of!(RwgpuIm2DVertexUV2, u2), 28);
        assert_eq!(offset_of!(RwgpuIm3DVertex, normal), 12);
        assert_eq!(offset_of!(RwgpuIm3DVertex, r), 24);
        assert_eq!(offset_of!(RwgpuIm3DVertex, u), 28);
    }
}
