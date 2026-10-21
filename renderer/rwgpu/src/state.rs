//! librw's render-state cache with the semantics of its GL3 backend (design §5.3).
//!
//! Adapted from librw's `src/gl/gl3device.cpp` (Copyright (c) 2014 aap, MIT licence).
//! Only the bookkeeping is here; turning the result into wgpu state is `pipeline.rs`.

use crate::abi::*;

/// GL3's per-stage cache (`rwStateCache.texstage`): what `getRenderState` reports.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Stage {
    /// Texture handle; 0 samples the white texture.
    pub texture: u32,
    /// `RASTER_*` flags of the bound raster.
    pub flags: u32,
    pub filter: u32,
    pub address_u: u32,
    pub address_v: u32,
}

/// GL3's per-texture-object sampling state (`Gl3Raster` filter/address/anisotropy):
/// what sampling actually uses. GL's defaults are filter 0, address 0.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct TextureSampling {
    pub filter: u32,
    pub address_u: u32,
    pub address_v: u32,
    pub max_anisotropy: u32,
}

impl Default for TextureSampling {
    fn default() -> Self {
        TextureSampling {
            filter: 0,
            address_u: 0,
            address_v: 0,
            max_anisotropy: 1,
        }
    }
}

/// How a stage samples: its bound texture with that texture's own state.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Sampling {
    pub texture: u32,
    pub flags: u32,
    pub state: TextureSampling,
}

/// The depth state GL3 would have set: `test` false means no depth test and no writes.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct DepthState {
    pub test: bool,
    /// `true`: compare `Always` (depth test was switched off while writes stay on).
    pub always: bool,
    pub write: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct StencilState {
    pub enable: bool,
    pub fail: u32,
    pub zfail: u32,
    pub pass: u32,
    pub func: u32,
    pub reference: u32,
    pub mask: u32,
    pub write_mask: u32,
}

#[derive(Clone, Debug)]
pub struct RenderState {
    vertex_alpha: bool,
    texture_alpha: bool,
    blend_enable: bool,
    alpha_test_enable: bool,
    /// The function the application asked for (`ALPHATESTFUNC`).
    alpha_func: u32,
    /// The function the shader applies: `alpha_func`, or `ALPHAALWAYS` when the test is off.
    shader_alpha_func: u32,
    alpha_ref: u32,
    src_blend: u32,
    dst_blend: u32,
    zwrite: bool,
    ztest: bool,
    depth_test: bool,
    depth_always: bool,
    cull: u32,
    stencil: StencilState,
    fog_enable: bool,
    fog_color: u32,
    gs_alpha: bool,
    gs_alpha_ref: u32,
    stages: [Stage; MAX_STAGES],
    textures: std::collections::HashMap<u32, TextureSampling>,
}

impl Default for RenderState {
    /// GL3's `resetRenderState`.
    fn default() -> Self {
        RenderState {
            vertex_alpha: false,
            texture_alpha: false,
            blend_enable: false,
            alpha_test_enable: false,
            alpha_func: ALPHAGREATEREQUAL,
            shader_alpha_func: ALPHAALWAYS,
            alpha_ref: 10,
            src_blend: BLENDSRCALPHA,
            dst_blend: BLENDINVSRCALPHA,
            zwrite: true,
            ztest: true,
            depth_test: true,
            depth_always: false,
            cull: CULLNONE,
            stencil: StencilState {
                enable: false,
                fail: STENCILKEEP,
                zfail: STENCILKEEP,
                pass: STENCILKEEP,
                func: STENCILALWAYS,
                reference: 0,
                mask: 0xFFFF_FFFF,
                write_mask: 0xFFFF_FFFF,
            },
            fog_enable: false,
            fog_color: 0xFFFF_FFFF,
            gs_alpha: false,
            gs_alpha_ref: 128,
            stages: [Stage::default(); MAX_STAGES],
            textures: std::collections::HashMap::new(),
        }
    }
}

/// One draw of a mesh under the PS2 alpha-test emulation (`drawInst_GSemu`).
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct GsPass {
    pub alpha_range: [f32; 2],
    pub depth: DepthState,
}

impl RenderState {
    // --- setters with GL3 semantics ---------------------------------------------------

    pub fn set(&mut self, state: u32, value: u32) {
        match state {
            TEXTUREADDRESS => {
                self.set_address_u(0, value);
                self.set_address_v(0, value);
            }
            TEXTUREADDRESSU => self.set_address_u(0, value),
            TEXTUREADDRESSV => self.set_address_v(0, value),
            TEXTUREFILTER => self.set_filter_mode(0, value, 1),
            VERTEXALPHA => self.set_vertex_alpha(value != 0),
            SRCBLEND => self.src_blend = value,
            DESTBLEND => self.dst_blend = value,
            ZTESTENABLE => self.set_depth_test(value != 0),
            ZWRITEENABLE => self.set_depth_write(value != 0),
            FOGENABLE => self.fog_enable = value != 0,
            FOGCOLOR => self.fog_color = value,
            CULLMODE => self.cull = value,
            STENCILENABLE => self.stencil.enable = value != 0,
            STENCILFAIL => self.stencil.fail = value,
            STENCILZFAIL => self.stencil.zfail = value,
            STENCILPASS => self.stencil.pass = value,
            STENCILFUNCTION => self.stencil.func = value,
            STENCILFUNCTIONREF => self.stencil.reference = value,
            STENCILFUNCTIONMASK => self.stencil.mask = value,
            STENCILFUNCTIONWRITEMASK => self.stencil.write_mask = value,
            ALPHATESTFUNC => self.set_alpha_test_function(value),
            ALPHATESTREF => self.alpha_ref = value,
            GSALPHATEST => self.gs_alpha = value != 0,
            GSALPHATESTREF => self.gs_alpha_ref = value,
            // TEXTURERASTER carries a pointer; the driver uses `set_raster` instead (§4.3).
            _ => {}
        }
    }

    pub fn get(&self, state: u32) -> u32 {
        let stage = &self.stages[0];
        match state {
            TEXTUREADDRESS => {
                if stage.address_u == stage.address_v {
                    stage.address_u
                } else {
                    0
                }
            }
            TEXTUREADDRESSU => stage.address_u,
            TEXTUREADDRESSV => stage.address_v,
            TEXTUREFILTER => stage.filter,
            VERTEXALPHA => self.vertex_alpha as u32,
            SRCBLEND => self.src_blend,
            DESTBLEND => self.dst_blend,
            ZTESTENABLE => self.ztest as u32,
            ZWRITEENABLE => self.zwrite as u32,
            FOGENABLE => self.fog_enable as u32,
            FOGCOLOR => self.fog_color,
            CULLMODE => self.cull,
            STENCILENABLE => self.stencil.enable as u32,
            STENCILFAIL => self.stencil.fail,
            STENCILZFAIL => self.stencil.zfail,
            STENCILPASS => self.stencil.pass,
            STENCILFUNCTION => self.stencil.func,
            STENCILFUNCTIONREF => self.stencil.reference,
            STENCILFUNCTIONMASK => self.stencil.mask,
            STENCILFUNCTIONWRITEMASK => self.stencil.write_mask,
            ALPHATESTFUNC => self.alpha_func,
            ALPHATESTREF => self.alpha_ref,
            GSALPHATEST => self.gs_alpha as u32,
            GSALPHATESTREF => self.gs_alpha_ref,
            _ => 0,
        }
    }

    /// `TEXTURERASTER`: GL3's `setRasterStage`.
    pub fn set_raster(&mut self, stage: usize, texture: u32, flags: u32) {
        if stage >= MAX_STAGES || self.stages[stage].texture == texture {
            return;
        }
        self.stages[stage].texture = texture;
        self.stages[stage].flags = flags;
        if texture != 0 {
            let cache = self.stages[stage];
            let native = self.textures.entry(texture).or_default();
            native.filter = cache.filter;
            native.address_u = cache.address_u;
            native.address_v = cache.address_v;
        }
        self.texture_alpha_changed(stage, texture, flags);
    }

    /// GL3's `setRasterStageOnly`: binds and copies the texture's state into the cache.
    fn set_raster_stage_only(&mut self, stage: usize, texture: u32, flags: u32) {
        if self.stages[stage].texture == texture {
            return;
        }
        let native = *self.textures.entry(texture).or_default();
        let cache = &mut self.stages[stage];
        cache.texture = texture;
        cache.flags = flags;
        cache.filter = native.filter;
        cache.address_u = native.address_u;
        cache.address_v = native.address_v;
        self.texture_alpha_changed(stage, texture, flags);
    }

    fn texture_alpha_changed(&mut self, stage: usize, texture: u32, flags: u32) {
        if stage != 0 {
            return;
        }
        let alpha = texture != 0 && flags & RASTER_HAS_ALPHA != 0;
        if alpha != self.texture_alpha {
            self.texture_alpha = alpha;
            if !self.vertex_alpha {
                self.blend_enable = alpha;
                self.set_alpha_test(alpha);
            }
        }
    }

    /// GL3's `setTexture`.
    #[allow(clippy::too_many_arguments)]
    pub fn set_texture(
        &mut self,
        stage: usize,
        texture: u32,
        flags: u32,
        filter: u32,
        address_u: u32,
        address_v: u32,
        max_anisotropy: u32,
    ) {
        if stage >= MAX_STAGES {
            return;
        }
        if texture == 0 {
            self.set_raster(stage, 0, 0);
            return;
        }
        self.set_raster_stage_only(stage, texture, flags);
        self.set_filter_mode(stage, filter, max_anisotropy);
        self.set_address_u(stage, address_u);
        self.set_address_v(stage, address_v);
    }

    /// GL3's `setFilterMode`: the bound texture follows the stage's filter changes.
    fn set_filter_mode(&mut self, stage: usize, filter: u32, max_anisotropy: u32) {
        let cache = &mut self.stages[stage];
        if cache.filter == filter {
            return;
        }
        cache.filter = filter;
        let texture = cache.texture;
        if texture != 0 {
            let native = self.textures.entry(texture).or_default();
            native.filter = filter;
            native.max_anisotropy = max_anisotropy;
        }
    }

    /// GL3's `setAddressU`: only the cache changes (GL3 tests `==` where `!=` is meant,
    /// so the bound texture keeps its addressing).
    fn set_address_u(&mut self, stage: usize, address: u32) {
        self.stages[stage].address_u = address;
    }

    fn set_address_v(&mut self, stage: usize, address: u32) {
        self.stages[stage].address_v = address;
    }

    /// Forgets a destroyed texture (GL3's `evictRaster` unbinds it everywhere).
    pub fn forget_texture(&mut self, texture: u32) {
        for stage in 0..MAX_STAGES {
            if self.stages[stage].texture == texture {
                self.set_raster(stage, 0, 0);
            }
        }
        self.textures.remove(&texture);
    }

    pub fn sampling(&self, stage: usize) -> Sampling {
        let cache = self.stages[stage];
        let state = self.textures.get(&cache.texture).copied().unwrap_or_default();
        Sampling {
            texture: cache.texture,
            flags: cache.flags,
            state,
        }
    }

    fn set_vertex_alpha(&mut self, enable: bool) {
        if self.vertex_alpha != enable {
            if !self.texture_alpha {
                self.blend_enable = enable;
                self.set_alpha_test(enable);
            }
            self.vertex_alpha = enable;
        }
    }

    fn set_alpha_test(&mut self, enable: bool) {
        if self.alpha_test_enable != enable {
            self.alpha_test_enable = enable;
            self.shader_alpha_func = if enable { self.alpha_func } else { ALPHAALWAYS };
        }
    }

    fn set_alpha_test_function(&mut self, function: u32) {
        if self.alpha_func != function {
            self.alpha_func = function;
            self.shader_alpha_func = if self.alpha_test_enable { function } else { ALPHAALWAYS };
        }
    }

    fn set_depth_test(&mut self, enable: bool) {
        if self.ztest != enable {
            self.ztest = enable;
            if self.zwrite && !enable {
                // Writes still wanted: keep the test on but let everything pass.
                self.depth_test = true;
                self.depth_always = true;
            } else {
                self.depth_test = enable;
                self.depth_always = false;
            }
        }
    }

    fn set_depth_write(&mut self, enable: bool) {
        if self.zwrite != enable {
            self.zwrite = enable;
            if enable && !self.ztest {
                self.depth_test = true;
                self.depth_always = true;
            }
        }
    }

    // --- derived state ----------------------------------------------------------------

    /// `Some((source, destination))` librw blend functions when blending is on.
    pub fn blend(&self) -> Option<(u32, u32)> {
        self.blend_enable.then_some((self.src_blend, self.dst_blend))
    }

    pub fn depth(&self) -> DepthState {
        DepthState {
            test: self.depth_test,
            always: self.depth_always,
            write: self.depth_test && self.zwrite,
        }
    }

    pub fn cull(&self) -> u32 {
        self.cull
    }

    pub fn stencil(&self) -> StencilState {
        self.stencil
    }

    /// `(low, high)`: the shader discards alpha `< low` or `>= high` (GL3's `u_alphaRef`).
    pub fn alpha_range(&self) -> [f32; 2] {
        alpha_range(self.shader_alpha_func, self.alpha_ref)
    }

    pub fn fog_enabled(&self) -> bool {
        self.fog_enable
    }

    /// Fog colour as RGBA floats; `FOGCOLOR` is packed as R in the lowest byte.
    pub fn fog_color(&self) -> [f32; 4] {
        let c = self.fog_color;
        [c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF, c >> 24].map(|v| v as f32 / 255.0)
    }

    /// The draws `drawInst` makes for one mesh: one, or two under the PS2 alpha-test
    /// emulation. The render state is left as it was.
    pub fn mesh_passes(&mut self) -> Vec<GsPass> {
        let current = GsPass {
            alpha_range: self.alpha_range(),
            depth: self.depth(),
        };
        if !self.gs_alpha || !self.blend_enable {
            return vec![current];
        }
        let alpha_func = self.get(ALPHATESTFUNC);
        if self.zwrite {
            let alpha_ref = self.get(ALPHATESTREF);
            self.set(ALPHATESTFUNC, ALPHAGREATEREQUAL);
            self.set(ALPHATESTREF, self.gs_alpha_ref);
            let first = GsPass {
                alpha_range: self.alpha_range(),
                depth: self.depth(),
            };
            self.set(ALPHATESTFUNC, ALPHALESS);
            self.set(ZWRITEENABLE, 0);
            let second = GsPass {
                alpha_range: self.alpha_range(),
                depth: self.depth(),
            };
            self.set(ZWRITEENABLE, 1);
            self.set(ALPHATESTFUNC, alpha_func);
            self.set(ALPHATESTREF, alpha_ref);
            vec![first, second]
        } else {
            self.set(ALPHATESTFUNC, ALPHAALWAYS);
            let only = GsPass {
                alpha_range: self.alpha_range(),
                depth: self.depth(),
            };
            self.set(ALPHATESTFUNC, alpha_func);
            vec![only]
        }
    }
}

pub fn alpha_range(function: u32, reference: u32) -> [f32; 2] {
    let r = reference as f32 / 255.0;
    match function {
        ALPHAGREATEREQUAL => [r, 1000.0],
        ALPHALESS => [-1000.0, r],
        _ => [-1000.0, 1000.0],
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const ALWAYS: [f32; 2] = [-1000.0, 1000.0];

    #[test]
    fn starts_like_gl3_reset_render_state() {
        let s = RenderState::default();
        assert_eq!(s.blend(), None);
        assert_eq!(s.alpha_range(), ALWAYS);
        assert_eq!(
            s.depth(),
            DepthState {
                test: true,
                always: false,
                write: true
            }
        );
        assert_eq!(s.cull(), CULLNONE);
        assert_eq!(s.get(SRCBLEND), BLENDSRCALPHA);
        assert_eq!(s.get(DESTBLEND), BLENDINVSRCALPHA);
        assert_eq!(s.get(ALPHATESTFUNC), ALPHAGREATEREQUAL);
        assert_eq!(s.get(ALPHATESTREF), 10);
        assert_eq!(s.get(GSALPHATESTREF), 128);
        assert!(!s.fog_enabled());
        assert_eq!(s.fog_color(), [1.0; 4]);
    }

    #[test]
    fn texture_alpha_turns_on_blending_and_alpha_test() {
        let mut s = RenderState::default();
        s.set_raster(0, 7, RASTER_HAS_ALPHA);
        assert_eq!(s.blend(), Some((BLENDSRCALPHA, BLENDINVSRCALPHA)));
        assert_eq!(s.alpha_range(), [10.0 / 255.0, 1000.0]);
        s.set_raster(0, 8, 0);
        assert_eq!(s.blend(), None);
        assert_eq!(s.alpha_range(), ALWAYS);
    }

    #[test]
    fn texture_alpha_is_ignored_while_vertex_alpha_is_on() {
        let mut s = RenderState::default();
        s.set(VERTEXALPHA, 1);
        assert!(s.blend().is_some());
        s.set_raster(0, 7, RASTER_HAS_ALPHA);
        s.set_raster(0, 8, 0);
        // GL3 leaves blending alone when texture alpha changes under vertex alpha.
        assert!(s.blend().is_some());
        s.set(VERTEXALPHA, 0);
        assert!(s.blend().is_none());
    }

    #[test]
    fn vertex_alpha_is_ignored_while_texture_alpha_is_on() {
        let mut s = RenderState::default();
        s.set_raster(0, 7, RASTER_HAS_ALPHA);
        s.set(VERTEXALPHA, 1);
        s.set(VERTEXALPHA, 0);
        assert!(s.blend().is_some());
    }

    #[test]
    fn only_stage_zero_drives_alpha() {
        let mut s = RenderState::default();
        s.set_raster(1, 7, RASTER_HAS_ALPHA);
        assert!(s.blend().is_none());
    }

    #[test]
    fn depth_test_off_with_writes_on_compares_always() {
        let mut s = RenderState::default();
        s.set(ZTESTENABLE, 0);
        assert_eq!(
            s.depth(),
            DepthState {
                test: true,
                always: true,
                write: true
            }
        );
        s.set(ZWRITEENABLE, 0);
        assert!(!s.depth().write);
        s.set(ZTESTENABLE, 1);
        assert_eq!(
            s.depth(),
            DepthState {
                test: true,
                always: false,
                write: false
            }
        );
    }

    #[test]
    fn depth_test_and_writes_off_disable_depth() {
        let mut s = RenderState::default();
        s.set(ZWRITEENABLE, 0);
        s.set(ZTESTENABLE, 0);
        assert_eq!(
            s.depth(),
            DepthState {
                test: false,
                always: false,
                write: false
            }
        );
        s.set(ZWRITEENABLE, 1);
        assert_eq!(
            s.depth(),
            DepthState {
                test: true,
                always: true,
                write: true
            }
        );
    }

    #[test]
    fn alpha_function_applies_only_while_the_test_is_on() {
        let mut s = RenderState::default();
        s.set(ALPHATESTFUNC, ALPHALESS);
        s.set(ALPHATESTREF, 51);
        assert_eq!(s.alpha_range(), ALWAYS);
        s.set(VERTEXALPHA, 1);
        assert_eq!(s.alpha_range(), [-1000.0, 51.0 / 255.0]);
        assert_eq!(s.get(ALPHATESTREF), 51);
    }

    #[test]
    fn set_texture_reports_the_texture_state_through_the_stage() {
        let mut s = RenderState::default();
        s.set_texture(0, 3, 0, FILTERLINEAR, ADDRESSCLAMP, ADDRESSWRAP, 4);
        assert_eq!(s.get(TEXTUREFILTER), FILTERLINEAR);
        assert_eq!(s.get(TEXTUREADDRESSU), ADDRESSCLAMP);
        assert_eq!(s.get(TEXTUREADDRESS), 0, "U and V differ");
        let sampling = s.sampling(0);
        assert_eq!(sampling.texture, 3);
        // The filter reaches the texture, with its anisotropy ...
        assert_eq!(sampling.state.filter, FILTERLINEAR);
        assert_eq!(sampling.state.max_anisotropy, 4);
        // ... but GL3's setAddressU bug leaves the texture repeating.
        assert_eq!((sampling.state.address_u, sampling.state.address_v), (0, 0));
    }

    #[test]
    fn texture_raster_applies_the_stage_addressing_to_a_newly_bound_texture() {
        let mut s = RenderState::default();
        s.set(TEXTUREADDRESS, ADDRESSCLAMP);
        s.set(TEXTUREFILTER, FILTERLINEAR);
        s.set_raster(0, 5, 0);
        let state = s.sampling(0).state;
        assert_eq!(
            (state.filter, state.address_u, state.address_v),
            (FILTERLINEAR, ADDRESSCLAMP, ADDRESSCLAMP)
        );
        // Changing addressing while the texture stays bound does not reach it.
        s.set(TEXTUREADDRESS, ADDRESSWRAP);
        assert_eq!(s.sampling(0).state.address_u, ADDRESSCLAMP);
        assert_eq!(s.get(TEXTUREADDRESS), ADDRESSWRAP);
        // Rebinding the same raster changes nothing either; another one picks it up.
        s.set_raster(0, 5, 0);
        assert_eq!(s.sampling(0).state.address_u, ADDRESSCLAMP);
        s.set_raster(0, 6, 0);
        assert_eq!(s.sampling(0).state.address_u, ADDRESSWRAP);
        // The texture keeps its own state when it comes back.
        s.set(TEXTUREADDRESS, ADDRESSMIRROR);
        s.set_texture(0, 5, 0, FILTERLINEAR, ADDRESSWRAP, ADDRESSWRAP, 1);
        assert_eq!(s.sampling(0).state.address_u, ADDRESSCLAMP);
        assert_eq!(s.get(TEXTUREADDRESSU), ADDRESSWRAP);
    }

    #[test]
    fn texture_filter_state_resets_anisotropy() {
        let mut s = RenderState::default();
        s.set_texture(0, 3, 0, FILTERLINEARMIPLINEAR, 1, 1, 8);
        assert_eq!(s.sampling(0).state.max_anisotropy, 8);
        s.set(TEXTUREFILTER, FILTERLINEAR);
        assert_eq!(s.sampling(0).state.max_anisotropy, 1);
        // Same filter again: GL3 skips the update, anisotropy included.
        s.set_texture(0, 4, 0, FILTERLINEAR, 1, 1, 8);
        s.set_texture(0, 3, 0, FILTERLINEAR, 1, 1, 8);
        assert_eq!(s.sampling(0).state.max_anisotropy, 1);
    }

    #[test]
    fn forgetting_a_texture_unbinds_it() {
        let mut s = RenderState::default();
        s.set_raster(0, 7, RASTER_HAS_ALPHA);
        s.set_raster(1, 7, 0);
        s.forget_texture(7);
        assert_eq!(s.sampling(0).texture, 0);
        assert_eq!(s.sampling(1).texture, 0);
        assert!(s.blend().is_none());
    }

    #[test]
    fn fog_color_unpacks_red_in_the_low_byte() {
        let mut s = RenderState::default();
        s.set(FOGCOLOR, 0x80_40_20_FF);
        assert_eq!(s.get(FOGCOLOR), 0x80_40_20_FF);
        assert_eq!(s.fog_color(), [1.0, 32.0 / 255.0, 64.0 / 255.0, 128.0 / 255.0]);
    }

    #[test]
    fn gs_emulation_with_depth_writes_draws_twice_and_restores() {
        let mut s = RenderState::default();
        s.set(GSALPHATEST, 1);
        s.set(GSALPHATESTREF, 128);
        s.set(VERTEXALPHA, 1);
        let passes = s.mesh_passes();
        assert_eq!(passes.len(), 2);
        assert_eq!(passes[0].alpha_range, [128.0 / 255.0, 1000.0]);
        assert!(passes[0].depth.write);
        assert_eq!(passes[1].alpha_range, [-1000.0, 128.0 / 255.0]);
        assert!(!passes[1].depth.write);
        assert_eq!(s.get(ALPHATESTFUNC), ALPHAGREATEREQUAL);
        assert_eq!(s.get(ALPHATESTREF), 10);
        assert_eq!(s.get(ZWRITEENABLE), 1);
    }

    #[test]
    fn gs_emulation_without_depth_writes_draws_once_without_alpha_test() {
        let mut s = RenderState::default();
        s.set(GSALPHATEST, 1);
        s.set(VERTEXALPHA, 1);
        s.set(ZWRITEENABLE, 0);
        let passes = s.mesh_passes();
        assert_eq!(passes.len(), 1);
        assert_eq!(passes[0].alpha_range, ALWAYS);
        assert_eq!(s.get(ALPHATESTFUNC), ALPHAGREATEREQUAL);
    }

    #[test]
    fn gs_emulation_needs_blending() {
        let mut s = RenderState::default();
        s.set(GSALPHATEST, 1);
        assert_eq!(s.mesh_passes().len(), 1);
    }
}
