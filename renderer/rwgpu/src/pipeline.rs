//! Render state → wgpu pipeline and sampler state (design §5.3).

use crate::abi::*;
use crate::state::{DepthState, StencilState};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum VertexStage {
    Default,
    Skin,
    MatfxEnv,
    Im3D,
    Im2D,
    Im2DUv2,
    Clear,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum FragmentStage {
    Simple,
    MatfxEnv,
    /// An Im2D override shader (handle from `rwgpu_im2d_shader_create`).
    Override(u32),
    Clear,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Layout {
    Mesh,
    Skin,
    Im3D,
    Im2D,
    Im2DUv2,
    /// No vertex buffer (clears).
    None,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct PipelineKey {
    pub vertex: VertexStage,
    pub fragment: FragmentStage,
    pub layout: Layout,
    pub topology: wgpu::PrimitiveTopology,
    /// librw blend functions, `None` when blending is off.
    pub blend: Option<(u32, u32)>,
    /// `None` when the target has no depth attachment.
    pub depth: Option<DepthKey>,
    pub cull: u32,
    pub color_write: bool,
    pub color_format: wgpu::TextureFormat,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct DepthKey {
    pub compare: wgpu::CompareFunction,
    pub write: bool,
    /// `(fail, depth fail, pass, function, read mask, write mask)` when stencil is on.
    pub stencil: Option<(u32, u32, u32, u32, u32, u32)>,
}

pub fn depth_key(depth: DepthState, stencil: StencilState) -> DepthKey {
    let compare = if !depth.test || depth.always {
        wgpu::CompareFunction::Always
    } else {
        wgpu::CompareFunction::LessEqual
    };
    let stencil = stencil.enable.then_some((
        stencil.fail,
        stencil.zfail,
        stencil.pass,
        stencil.func,
        stencil.mask,
        stencil.write_mask,
    ));
    DepthKey {
        compare,
        write: depth.write,
        stencil,
    }
}

pub fn blend_factor(f: u32) -> wgpu::BlendFactor {
    use wgpu::BlendFactor as B;
    match f {
        BLENDZERO => B::Zero,
        BLENDONE => B::One,
        BLENDSRCCOLOR => B::Src,
        BLENDINVSRCCOLOR => B::OneMinusSrc,
        BLENDSRCALPHA => B::SrcAlpha,
        BLENDINVSRCALPHA => B::OneMinusSrcAlpha,
        BLENDDESTALPHA => B::DstAlpha,
        BLENDINVDESTALPHA => B::OneMinusDstAlpha,
        BLENDDESTCOLOR => B::Dst,
        BLENDINVDESTCOLOR => B::OneMinusDst,
        BLENDSRCALPHASAT => B::SrcAlphaSaturated,
        // GL3 maps 0 ("invalid") to GL_ZERO.
        _ => B::Zero,
    }
}

pub fn blend_state(blend: Option<(u32, u32)>) -> Option<wgpu::BlendState> {
    blend.map(|(src, dst)| {
        let component = wgpu::BlendComponent {
            src_factor: blend_factor(src),
            dst_factor: blend_factor(dst),
            operation: wgpu::BlendOperation::Add,
        };
        wgpu::BlendState {
            color: component,
            alpha: component,
        }
    })
}

pub fn stencil_operation(op: u32) -> wgpu::StencilOperation {
    use wgpu::StencilOperation as S;
    match op {
        STENCILZERO => S::Zero,
        STENCILREPLACE => S::Replace,
        STENCILINCSAT => S::IncrementClamp,
        STENCILDECSAT => S::DecrementClamp,
        STENCILINVERT => S::Invert,
        STENCILINC => S::IncrementWrap,
        STENCILDEC => S::DecrementWrap,
        _ => S::Keep,
    }
}

pub fn stencil_compare(func: u32) -> wgpu::CompareFunction {
    use wgpu::CompareFunction as C;
    match func {
        STENCILLESS => C::Less,
        STENCILEQUAL => C::Equal,
        STENCILLESSEQUAL => C::LessEqual,
        STENCILGREATER => C::Greater,
        STENCILNOTEQUAL => C::NotEqual,
        STENCILGREATEREQUAL => C::GreaterEqual,
        STENCILALWAYS => C::Always,
        _ => C::Never,
    }
}

pub fn cull_mode(cull: u32) -> Option<wgpu::Face> {
    match cull {
        CULLBACK => Some(wgpu::Face::Back),
        CULLFRONT => Some(wgpu::Face::Front),
        _ => None,
    }
}

/// wgpu topology for a librw primitive type; fans are drawn as lists after conversion.
pub fn topology(prim: u32) -> wgpu::PrimitiveTopology {
    use wgpu::PrimitiveTopology as T;
    match prim {
        PRIMTYPELINELIST => T::LineList,
        PRIMTYPEPOLYLINE => T::LineStrip,
        PRIMTYPETRISTRIP => T::TriangleStrip,
        PRIMTYPEPOINTLIST => T::PointList,
        _ => T::TriangleList,
    }
}

pub fn depth_stencil_state(key: DepthKey) -> wgpu::DepthStencilState {
    let stencil = match key.stencil {
        Some((fail, zfail, pass, func, mask, write_mask)) => {
            let face = wgpu::StencilFaceState {
                compare: stencil_compare(func),
                fail_op: stencil_operation(fail),
                depth_fail_op: stencil_operation(zfail),
                pass_op: stencil_operation(pass),
            };
            wgpu::StencilState {
                front: face,
                back: face,
                read_mask: mask,
                write_mask,
            }
        }
        None => wgpu::StencilState::default(),
    };
    wgpu::DepthStencilState {
        format: DEPTH_FORMAT,
        depth_write_enabled: Some(key.write),
        depth_compare: Some(key.compare),
        stencil,
        bias: wgpu::DepthBiasState::default(),
    }
}

pub const DEPTH_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Depth24PlusStencil8;
pub const COLOR_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Rgba8Unorm;

// --- samplers --------------------------------------------------------------------------

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct SamplerKey {
    pub filter: u32,
    pub address_u: u32,
    pub address_v: u32,
    pub anisotropy: u16,
}

impl SamplerKey {
    /// wgpu allows anisotropy only with all-linear filtering, so other filters get 1.
    pub fn new(filter: u32, address_u: u32, address_v: u32, max_anisotropy: u32) -> Self {
        let anisotropy = if filter == FILTERLINEARMIPLINEAR {
            max_anisotropy.clamp(1, 16) as u16
        } else {
            1
        };
        SamplerKey {
            filter,
            address_u,
            address_v,
            anisotropy,
        }
    }
}

/// `(mag, min, mipmap, uses mipmaps)` for a librw filter mode, as GL3's tables.
/// Filter 0 is GL's default texture state: linear magnification, nearest-mipmap-linear
/// minification.
pub fn filters(filter: u32) -> (wgpu::FilterMode, wgpu::FilterMode, wgpu::MipmapFilterMode, bool) {
    use wgpu::FilterMode::{Linear as L, Nearest as N};
    use wgpu::MipmapFilterMode::{Linear as ML, Nearest as MN};
    match filter {
        FILTERNEAREST => (N, N, MN, false),
        FILTERLINEAR => (L, L, MN, false),
        FILTERMIPNEAREST => (N, N, MN, true),
        FILTERMIPLINEAR => (L, L, MN, true),
        FILTERLINEARMIPNEAREST => (N, N, ML, true),
        FILTERLINEARMIPLINEAR => (L, L, ML, true),
        _ => (L, N, ML, true),
    }
}

pub fn address_mode(address: u32, border_supported: bool) -> wgpu::AddressMode {
    match address {
        ADDRESSMIRROR => wgpu::AddressMode::MirrorRepeat,
        ADDRESSCLAMP => wgpu::AddressMode::ClampToEdge,
        ADDRESSBORDER if border_supported => wgpu::AddressMode::ClampToBorder,
        ADDRESSBORDER => wgpu::AddressMode::ClampToEdge,
        _ => wgpu::AddressMode::Repeat,
    }
}

pub fn sampler_descriptor(key: SamplerKey, border_supported: bool) -> wgpu::SamplerDescriptor<'static> {
    let (mag, min, mip, mipmapped) = filters(key.filter);
    let border = address_mode(key.address_u, border_supported) == wgpu::AddressMode::ClampToBorder
        || address_mode(key.address_v, border_supported) == wgpu::AddressMode::ClampToBorder;
    wgpu::SamplerDescriptor {
        label: Some("rwgpu sampler"),
        address_mode_u: address_mode(key.address_u, border_supported),
        address_mode_v: address_mode(key.address_v, border_supported),
        address_mode_w: wgpu::AddressMode::Repeat,
        mag_filter: mag,
        min_filter: min,
        mipmap_filter: mip,
        lod_min_clamp: 0.0,
        // Without a mipmapped filter GL samples level 0 only.
        lod_max_clamp: if mipmapped { 32.0 } else { 0.0 },
        compare: None,
        anisotropy_clamp: key.anisotropy,
        border_color: border.then_some(wgpu::SamplerBorderColor::TransparentBlack),
    }
}

// --- vertex layouts ------------------------------------------------------------------------

pub fn vertex_layout(layout: Layout) -> Option<wgpu::VertexBufferLayout<'static>> {
    use wgpu::VertexFormat as F;
    const MESH: [wgpu::VertexAttribute; 5] = wgpu::vertex_attr_array![
        0 => Float32x3, 1 => Float32x3, 2 => Unorm8x4, 3 => Float32x2, 4 => Float32x2
    ];
    const SKIN: [wgpu::VertexAttribute; 7] = [
        wgpu::VertexAttribute {
            format: F::Float32x3,
            offset: 0,
            shader_location: 0,
        },
        wgpu::VertexAttribute {
            format: F::Float32x3,
            offset: 12,
            shader_location: 1,
        },
        wgpu::VertexAttribute {
            format: F::Unorm8x4,
            offset: 24,
            shader_location: 2,
        },
        wgpu::VertexAttribute {
            format: F::Float32x2,
            offset: 28,
            shader_location: 3,
        },
        wgpu::VertexAttribute {
            format: F::Float32x2,
            offset: 36,
            shader_location: 4,
        },
        wgpu::VertexAttribute {
            format: F::Float32x4,
            offset: 44,
            shader_location: 5,
        },
        wgpu::VertexAttribute {
            format: F::Uint8x4,
            offset: 60,
            shader_location: 6,
        },
    ];
    const IM3D: [wgpu::VertexAttribute; 4] = [
        wgpu::VertexAttribute {
            format: F::Float32x3,
            offset: 0,
            shader_location: 0,
        },
        wgpu::VertexAttribute {
            format: F::Float32x3,
            offset: 12,
            shader_location: 1,
        },
        wgpu::VertexAttribute {
            format: F::Unorm8x4,
            offset: 24,
            shader_location: 2,
        },
        wgpu::VertexAttribute {
            format: F::Float32x2,
            offset: 28,
            shader_location: 3,
        },
    ];
    const IM2D: [wgpu::VertexAttribute; 3] = [
        wgpu::VertexAttribute {
            format: F::Float32x4,
            offset: 0,
            shader_location: 0,
        },
        wgpu::VertexAttribute {
            format: F::Unorm8x4,
            offset: 16,
            shader_location: 2,
        },
        wgpu::VertexAttribute {
            format: F::Float32x2,
            offset: 20,
            shader_location: 3,
        },
    ];
    const IM2D_UV2: [wgpu::VertexAttribute; 4] = [
        wgpu::VertexAttribute {
            format: F::Float32x4,
            offset: 0,
            shader_location: 0,
        },
        wgpu::VertexAttribute {
            format: F::Unorm8x4,
            offset: 16,
            shader_location: 2,
        },
        wgpu::VertexAttribute {
            format: F::Float32x2,
            offset: 20,
            shader_location: 3,
        },
        wgpu::VertexAttribute {
            format: F::Float32x2,
            offset: 28,
            shader_location: 4,
        },
    ];
    let (stride, attributes): (u64, &'static [wgpu::VertexAttribute]) = match layout {
        Layout::Mesh => (MESH_STRIDE, &MESH),
        Layout::Skin => (SKIN_STRIDE, &SKIN),
        Layout::Im3D => (36, &IM3D),
        Layout::Im2D => (28, &IM2D),
        Layout::Im2DUv2 => (36, &IM2D_UV2),
        Layout::None => return None,
    };
    Some(wgpu::VertexBufferLayout {
        array_stride: stride,
        step_mode: wgpu::VertexStepMode::Vertex,
        attributes,
    })
}

pub fn vertex_entry(stage: VertexStage) -> &'static str {
    match stage {
        VertexStage::Default => "vs_default",
        VertexStage::Skin => "vs_skin",
        VertexStage::MatfxEnv => "vs_matfx_env",
        VertexStage::Im3D => "vs_im3d",
        VertexStage::Im2D => "vs_im2d",
        VertexStage::Im2DUv2 => "vs_im2d_uv2",
        VertexStage::Clear => "vs_clear",
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::state::RenderState;

    #[test]
    fn blend_functions_map_one_to_one() {
        use wgpu::BlendFactor as B;
        let expected = [
            (BLENDZERO, B::Zero),
            (BLENDONE, B::One),
            (BLENDSRCCOLOR, B::Src),
            (BLENDINVSRCCOLOR, B::OneMinusSrc),
            (BLENDSRCALPHA, B::SrcAlpha),
            (BLENDINVSRCALPHA, B::OneMinusSrcAlpha),
            (BLENDDESTALPHA, B::DstAlpha),
            (BLENDINVDESTALPHA, B::OneMinusDstAlpha),
            (BLENDDESTCOLOR, B::Dst),
            (BLENDINVDESTCOLOR, B::OneMinusDst),
            (BLENDSRCALPHASAT, B::SrcAlphaSaturated),
        ];
        for (rw, wgpu) in expected {
            assert_eq!(blend_factor(rw), wgpu);
        }
        assert_eq!(blend_state(None), None);
    }

    #[test]
    fn stencil_tables() {
        use wgpu::CompareFunction as C;
        use wgpu::StencilOperation as S;
        let ops = [
            S::Keep,
            S::Zero,
            S::Replace,
            S::IncrementClamp,
            S::DecrementClamp,
            S::Invert,
            S::IncrementWrap,
            S::DecrementWrap,
        ];
        for (i, op) in ops.iter().enumerate() {
            assert_eq!(stencil_operation(i as u32 + 1), *op);
        }
        let funcs = [
            C::Never,
            C::Less,
            C::Equal,
            C::LessEqual,
            C::Greater,
            C::NotEqual,
            C::GreaterEqual,
            C::Always,
        ];
        for (i, f) in funcs.iter().enumerate() {
            assert_eq!(stencil_compare(i as u32 + 1), *f);
        }
    }

    #[test]
    fn depth_keys_follow_gl3() {
        let mut s = RenderState::default();
        let k = depth_key(s.depth(), s.stencil());
        assert_eq!(
            (k.compare, k.write, k.stencil),
            (wgpu::CompareFunction::LessEqual, true, None)
        );
        s.set(ZTESTENABLE, 0);
        let k = depth_key(s.depth(), s.stencil());
        assert_eq!((k.compare, k.write), (wgpu::CompareFunction::Always, true));
        s.set(ZWRITEENABLE, 0);
        let k = depth_key(s.depth(), s.stencil());
        assert_eq!((k.compare, k.write), (wgpu::CompareFunction::Always, false));
        s.set(STENCILENABLE, 1);
        s.set(STENCILPASS, STENCILREPLACE);
        let k = depth_key(s.depth(), s.stencil());
        assert_eq!(
            k.stencil,
            Some((STENCILKEEP, STENCILKEEP, STENCILREPLACE, STENCILALWAYS, !0, !0))
        );
    }

    #[test]
    fn anisotropy_only_with_linear_mip_linear() {
        assert_eq!(SamplerKey::new(FILTERLINEARMIPLINEAR, 1, 1, 16).anisotropy, 16);
        assert_eq!(SamplerKey::new(FILTERLINEARMIPLINEAR, 1, 1, 0).anisotropy, 1);
        assert_eq!(SamplerKey::new(FILTERLINEAR, 1, 1, 16).anisotropy, 1);
        assert_eq!(SamplerKey::new(FILTERMIPLINEAR, 1, 1, 64).anisotropy, 1);
    }

    #[test]
    fn filters_match_gl3_tables() {
        use wgpu::FilterMode::{Linear, Nearest};
        use wgpu::MipmapFilterMode as M;
        assert_eq!(filters(FILTERNEAREST), (Nearest, Nearest, M::Nearest, false));
        assert_eq!(filters(FILTERLINEAR), (Linear, Linear, M::Nearest, false));
        assert_eq!(filters(FILTERMIPLINEAR), (Linear, Linear, M::Nearest, true));
        assert_eq!(filters(FILTERLINEARMIPNEAREST), (Nearest, Nearest, M::Linear, true));
        let d = sampler_descriptor(SamplerKey::new(FILTERLINEAR, ADDRESSCLAMP, ADDRESSBORDER, 1), true);
        assert_eq!(d.lod_max_clamp, 0.0);
        assert_eq!(d.address_mode_u, wgpu::AddressMode::ClampToEdge);
        assert_eq!(d.address_mode_v, wgpu::AddressMode::ClampToBorder);
        assert_eq!(d.border_color, Some(wgpu::SamplerBorderColor::TransparentBlack));
        let d = sampler_descriptor(SamplerKey::new(FILTERLINEAR, ADDRESSBORDER, 0, 1), false);
        assert_eq!(d.address_mode_u, wgpu::AddressMode::ClampToEdge);
        assert_eq!(d.address_mode_v, wgpu::AddressMode::Repeat);
        assert_eq!(d.border_color, None);
    }

    #[test]
    fn layouts_match_the_abi() {
        let mesh = vertex_layout(Layout::Mesh).unwrap();
        assert_eq!(mesh.array_stride, 44);
        assert_eq!(
            mesh.attributes.iter().map(|a| a.offset).collect::<Vec<_>>(),
            vec![0, 12, 24, 28, 36]
        );
        assert_eq!(vertex_layout(Layout::Skin).unwrap().array_stride, 64);
        assert_eq!(vertex_layout(Layout::Im2D).unwrap().array_stride, 28);
        assert!(vertex_layout(Layout::None).is_none());
    }

    #[test]
    fn primitive_types_map_to_topologies() {
        use wgpu::PrimitiveTopology as T;
        assert_eq!(topology(PRIMTYPELINELIST), T::LineList);
        assert_eq!(topology(PRIMTYPEPOLYLINE), T::LineStrip);
        assert_eq!(topology(PRIMTYPETRILIST), T::TriangleList);
        assert_eq!(topology(PRIMTYPETRISTRIP), T::TriangleStrip);
        assert_eq!(topology(PRIMTYPETRIFAN), T::TriangleList);
        assert_eq!(topology(PRIMTYPEPOINTLIST), T::PointList);
        assert_eq!(cull_mode(CULLNONE), None);
        assert_eq!(cull_mode(CULLBACK), Some(wgpu::Face::Back));
    }
}
