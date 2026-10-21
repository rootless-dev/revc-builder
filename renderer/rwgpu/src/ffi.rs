//! The exported C functions declared in `include/rwgpu.h` (design §4.3).
//!
//! Every function locks the single renderer. Calls other than `rwgpu_abi_version`,
//! `rwgpu_last_error` and `rwgpu_init` do nothing (and return 0) without a renderer.

use std::ffi::{CStr, CString, c_char, c_void};
use std::slice;
use std::sync::Mutex;

use crate::abi::*;
use crate::renderer::Renderer;

static RENDERER: Mutex<Option<Renderer>> = Mutex::new(None);
static LAST_ERROR: Mutex<Option<CString>> = Mutex::new(None);

fn set_error(message: impl Into<String>) {
    let message = message.into();
    eprintln!("rwgpu: {message}");
    *LAST_ERROR.lock().unwrap() = CString::new(message.replace('\0', " ")).ok();
}

fn with<R>(default: R, f: impl FnOnce(&mut Renderer) -> R) -> R {
    let mut guard = RENDERER.lock().unwrap_or_else(|e| e.into_inner());
    match guard.as_mut() {
        Some(r) => f(r),
        None => default,
    }
}

unsafe fn matrix<'a>(m: *const f32) -> Option<&'a [f32; 16]> {
    if m.is_null() {
        None
    } else {
        Some(unsafe { &*(m as *const [f32; 16]) })
    }
}

unsafe fn vec4(v: *const f32) -> [f32; 4] {
    if v.is_null() {
        [0.0; 4]
    } else {
        unsafe { *(v as *const [f32; 4]) }
    }
}

unsafe fn bytes<'a>(p: *const c_void, len: usize) -> &'a [u8] {
    if p.is_null() || len == 0 {
        &[]
    } else {
        unsafe { slice::from_raw_parts(p as *const u8, len) }
    }
}

unsafe fn indices<'a>(p: *const u16, n: u32) -> Option<&'a [u16]> {
    if p.is_null() {
        None
    } else {
        Some(unsafe { slice::from_raw_parts(p, n as usize) })
    }
}

// --- lifecycle ----------------------------------------------------------------------------

#[unsafe(no_mangle)]
pub extern "C" fn rwgpu_abi_version() -> u32 {
    ABI_VERSION
}

/// # Safety
/// `desc` must point to a valid `RwgpuWindowDesc` whose handles outlive the renderer.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rwgpu_init(desc: *const RwgpuWindowDesc) -> u32 {
    if desc.is_null() {
        set_error("rwgpu_init: no window description");
        return 0;
    }
    match unsafe { Renderer::new(&*desc) } {
        Ok(r) => {
            *RENDERER.lock().unwrap_or_else(|e| e.into_inner()) = Some(r);
            1
        }
        Err(e) => {
            set_error(format!("rwgpu_init: {e}"));
            0
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn rwgpu_shutdown() {
    let renderer = RENDERER.lock().unwrap_or_else(|e| e.into_inner()).take();
    drop(renderer);
}

/// The message of the last failure, or an empty string; valid until the next failure.
#[unsafe(no_mangle)]
pub extern "C" fn rwgpu_last_error() -> *const c_char {
    static EMPTY: &CStr = c"";
    match LAST_ERROR.lock().unwrap().as_ref() {
        Some(s) => s.as_ptr(),
        None => EMPTY.as_ptr(),
    }
}

/// # Safety
/// `out` must be null or point to writable memory for an `RwgpuCaps`.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rwgpu_get_caps(out: *mut RwgpuCaps) {
    if let Some(out) = unsafe { out.as_mut() } {
        *out = with(RwgpuCaps::default(), |r| r.caps());
    }
}

// --- frame ----------------------------------------------------------------------------------

#[unsafe(no_mangle)]
pub extern "C" fn rwgpu_resize(width: u32, height: u32) {
    with((), |r| r.resize(width, height));
}

#[unsafe(no_mangle)]
pub extern "C" fn rwgpu_present(vsync: u32) {
    with((), |r| r.present(vsync != 0));
}

/// # Safety
/// `out` must be null or point to writable memory for an `RwgpuStats`.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rwgpu_get_stats(out: *mut RwgpuStats) {
    if let Some(out) = unsafe { out.as_mut() } {
        *out = with(RwgpuStats::default(), |r| r.stats());
    }
}

// --- cameras and targets ----------------------------------------------------------------------

/// # Safety
/// Pointers must be valid: `target`, 16-float `view` and `proj`, 2-float `gl_depth_row`.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rwgpu_begin_camera(
    target: *const RwgpuTarget,
    view: *const f32,
    proj: *const f32,
    fog_start: f32,
    fog_end: f32,
    gl_depth_row: *const f32,
) {
    let (Some(target), Some(view), Some(proj)) = (unsafe { target.as_ref() }, unsafe { matrix(view) }, unsafe {
        matrix(proj)
    }) else {
        return;
    };
    let gl = if gl_depth_row.is_null() {
        [0.0; 2]
    } else {
        unsafe { *(gl_depth_row as *const [f32; 2]) }
    };
    with((), |r| r.begin_camera(target, view, proj, fog_start, fog_end, gl));
}

#[unsafe(no_mangle)]
pub extern "C" fn rwgpu_end_camera() {
    with((), |r| r.end_camera());
}

/// # Safety
/// `target` and the 4-float `rgba` must be valid.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rwgpu_clear(target: *const RwgpuTarget, rgba: *const f32, mode: u32) {
    let Some(target) = (unsafe { target.as_ref() }) else {
        return;
    };
    let rgba = unsafe { vec4(rgba) };
    with((), |r| r.clear(target, rgba, mode));
}

#[unsafe(no_mangle)]
pub extern "C" fn rwgpu_copy_main_to_texture(tex: u32, dst_x: i32, dst_y: i32, width: u32, height: u32) {
    with((), |r| r.copy_main_to_texture(tex, dst_x, dst_y, width, height));
}

/// Copies the main target as top-down RGB8 into `out` (`size` bytes); returns the bytes
/// written, or 0 when `size` is smaller than width × height × 3.
///
/// # Safety
/// `out` must be valid for `size` bytes.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rwgpu_read_main(out: *mut c_void, size: u32) -> u32 {
    if out.is_null() {
        return 0;
    }
    with(0, |r| {
        let (_, _, rgb) = r.read_main();
        if rgb.len() > size as usize {
            return 0;
        }
        unsafe { std::ptr::copy_nonoverlapping(rgb.as_ptr(), out as *mut u8, rgb.len()) };
        rgb.len() as u32
    })
}

// --- textures ----------------------------------------------------------------------------------

#[unsafe(no_mangle)]
pub extern "C" fn rwgpu_texture_create(format: u32, width: u32, height: u32, levels: u32, flags: u32) -> u32 {
    with(0, |r| r.texture_create(format, width, height, levels, flags))
}

/// # Safety
/// `data` must be valid for `size` bytes.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rwgpu_texture_upload(
    tex: u32,
    level: u32,
    src_format: u32,
    data: *const c_void,
    size: u32,
) -> u32 {
    let data = unsafe { bytes(data, size as usize) };
    with(0, |r| r.texture_upload(tex, level, src_format, data) as u32)
}

/// Reads a level back, tightly packed in the texture's format; returns the bytes written,
/// or 0 when `size` is too small or the level does not exist.
///
/// # Safety
/// `out` must be valid for `size` bytes.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rwgpu_texture_read(tex: u32, level: u32, out: *mut c_void, size: u32) -> u32 {
    if out.is_null() {
        return 0;
    }
    with(0, |r| match r.texture_read(tex, level) {
        Some(data) if data.len() <= size as usize => {
            unsafe { std::ptr::copy_nonoverlapping(data.as_ptr(), out as *mut u8, data.len()) };
            data.len() as u32
        }
        _ => 0,
    })
}

#[unsafe(no_mangle)]
pub extern "C" fn rwgpu_texture_destroy(tex: u32) {
    with((), |r| r.texture_destroy(tex));
}

#[unsafe(no_mangle)]
pub extern "C" fn rwgpu_depth_create(width: u32, height: u32) -> u32 {
    with(0, |r| r.depth_create(width, height))
}

#[unsafe(no_mangle)]
pub extern "C" fn rwgpu_depth_destroy(depth: u32) {
    with((), |r| r.depth_destroy(depth));
}

// --- render state ---------------------------------------------------------------------------------

#[unsafe(no_mangle)]
pub extern "C" fn rwgpu_set_render_state(state: u32, value: u32) {
    with((), |r| r.state.set(state, value));
}

#[unsafe(no_mangle)]
pub extern "C" fn rwgpu_get_render_state(state: u32) -> u32 {
    with(0, |r| r.state.get(state))
}

#[unsafe(no_mangle)]
pub extern "C" fn rwgpu_set_raster(stage: u32, tex: u32, flags: u32) {
    with((), |r| r.state.set_raster(stage as usize, tex, flags));
}

#[unsafe(no_mangle)]
pub extern "C" fn rwgpu_set_texture(
    stage: u32,
    tex: u32,
    flags: u32,
    filter: u32,
    address_u: u32,
    address_v: u32,
    max_anisotropy: u32,
) {
    with((), |r| {
        r.state
            .set_texture(stage as usize, tex, flags, filter, address_u, address_v, max_anisotropy)
    });
}

// --- per object / mesh --------------------------------------------------------------------------------

/// # Safety
/// `m` must point to 16 floats.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rwgpu_set_world_matrix(m: *const f32) {
    if let Some(m) = unsafe { matrix(m) } {
        with((), |r| r.set_world_matrix(m));
    }
}

/// # Safety
/// `ambient` must point to 4 floats and `lights` to `count` lights.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rwgpu_set_lights(ambient: *const f32, lights: *const RwgpuLight, count: u32) {
    let ambient = unsafe { vec4(ambient) };
    let lights = if lights.is_null() {
        &[][..]
    } else {
        unsafe { slice::from_raw_parts(lights, count as usize) }
    };
    with((), |r| r.set_lights(ambient, lights));
}

/// # Safety
/// `color` and `surface_props` must point to 4 floats each.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rwgpu_set_material(color: *const f32, surface_props: *const f32) {
    let (color, props) = unsafe { (vec4(color), vec4(surface_props)) };
    with((), |r| r.set_material(color, props));
}

/// # Safety
/// `matrices` must point to `count` × 16 floats.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rwgpu_set_bones(matrices: *const f32, count: u32) {
    if matrices.is_null() {
        return;
    }
    let m = unsafe { slice::from_raw_parts(matrices as *const [f32; 16], count.min(MAX_BONES as u32) as usize) };
    with((), |r| r.set_bones(m));
}

/// # Safety
/// `tex_matrix` must point to 16 floats, the others to 4 floats each.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rwgpu_set_matfx_env(
    tex_matrix: *const f32,
    fx_params: *const f32,
    color_clamp: *const f32,
    env_color: *const f32,
) {
    let Some(m) = (unsafe { matrix(tex_matrix) }) else {
        return;
    };
    let (fx, clamp, env) = unsafe { (vec4(fx_params), vec4(color_clamp), vec4(env_color)) };
    with((), |r| r.set_matfx_env(m, fx, clamp, env));
}

// --- meshes --------------------------------------------------------------------------------------------

/// # Safety
/// `vertices` must be valid for `vertex_bytes` bytes and `indices` for `index_count` indices.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rwgpu_mesh_create(
    layout: u32,
    vertices: *const c_void,
    vertex_bytes: u32,
    indices: *const u16,
    index_count: u32,
) -> u32 {
    let v = unsafe { bytes(vertices, vertex_bytes as usize) };
    let i = unsafe { indices_or_empty(indices, index_count) };
    with(0, |r| r.mesh_create(layout, v, i))
}

unsafe fn indices_or_empty<'a>(p: *const u16, n: u32) -> &'a [u16] {
    unsafe { indices(p, n) }.unwrap_or(&[])
}

/// # Safety
/// `vertices` must be valid for `bytes` bytes.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rwgpu_mesh_update_vertices(mesh: u32, vertices: *const c_void, vertex_bytes: u32) {
    let v = unsafe { bytes(vertices, vertex_bytes as usize) };
    with((), |r| r.mesh_update_vertices(mesh, v));
}

#[unsafe(no_mangle)]
pub extern "C" fn rwgpu_mesh_destroy(mesh: u32) {
    with((), |r| r.mesh_destroy(mesh));
}

#[unsafe(no_mangle)]
pub extern "C" fn rwgpu_draw_mesh(mesh: u32, shader: u32, prim: u32, first_index: u32, index_count: u32) {
    with((), |r| r.draw_mesh(mesh, shader, prim, first_index, index_count));
}

// --- immediate mode ------------------------------------------------------------------------------------------

/// # Safety
/// `vertices` must hold `num_vertices` `RwgpuIm2DVertex`; `indices` is null or holds `num_indices` indices.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rwgpu_im2d_draw(
    prim: u32,
    vertices: *const RwgpuIm2DVertex,
    num_vertices: u32,
    indices: *const u16,
    num_indices: u32,
) {
    let v = unsafe { bytes(vertices as *const c_void, num_vertices as usize * 28) };
    let i = unsafe { self::indices(indices, num_indices) };
    with((), |r| r.im2d_draw(prim, v, 28, num_vertices, i, false));
}

/// # Safety
/// As `rwgpu_im2d_draw`, with `RwgpuIm2DVertexUV2` vertices.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rwgpu_im2d_uv2_draw(
    prim: u32,
    vertices: *const RwgpuIm2DVertexUV2,
    num_vertices: u32,
    indices: *const u16,
    num_indices: u32,
) {
    let v = unsafe { bytes(vertices as *const c_void, num_vertices as usize * 36) };
    let i = unsafe { self::indices(indices, num_indices) };
    with((), |r| r.im2d_draw(prim, v, 36, num_vertices, i, true));
}

/// Compiles an Im2D override fragment shader; returns its handle, or 0 on error.
///
/// # Safety
/// `wgsl` must be a valid NUL-terminated string.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rwgpu_im2d_shader_create(wgsl: *const c_char) -> u32 {
    if wgsl.is_null() {
        return 0;
    }
    let Ok(source) = unsafe { CStr::from_ptr(wgsl) }.to_str() else {
        set_error("rwgpu_im2d_shader_create: the source is not UTF-8");
        return 0;
    };
    with(0, |r| r.im2d_shader_create(source))
}

/// # Safety
/// `params` must be null or point to 16 floats.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rwgpu_im2d_set_override(shader: u32, params: *const f32) {
    let p = if params.is_null() {
        [0.0; 16]
    } else {
        unsafe { *(params as *const [f32; 16]) }
    };
    with((), |r| r.im2d_set_override(shader, &p));
}

/// # Safety
/// `vertices` must hold `num_vertices` `RwgpuIm3DVertex`; `world` is null or 16 floats.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rwgpu_im3d_transform(
    vertices: *const RwgpuIm3DVertex,
    num_vertices: u32,
    world: *const f32,
    lit: u32,
) {
    const IDENTITY: [f32; 16] = [1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.];
    let v = unsafe { bytes(vertices as *const c_void, num_vertices as usize * 36) };
    let world = unsafe { matrix(world) }.copied().unwrap_or(IDENTITY);
    with((), |r| r.im3d_transform(v, num_vertices, &world, lit != 0));
}

/// # Safety
/// `indices` is null (draw the transformed vertices in order) or holds `num_indices` indices.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rwgpu_im3d_draw(prim: u32, indices: *const u16, num_indices: u32) {
    let i = unsafe { self::indices(indices, num_indices) };
    with((), |r| r.im3d_draw(prim, i));
}

#[unsafe(no_mangle)]
pub extern "C" fn rwgpu_im3d_end() {
    with((), |r| r.im3d_end());
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn calls_without_a_renderer_do_nothing() {
        assert_eq!(rwgpu_abi_version(), ABI_VERSION);
        assert_eq!(rwgpu_texture_create(FORMAT_RGBA8, 4, 4, 1, 0), 0);
        assert_eq!(rwgpu_get_render_state(SRCBLEND), 0);
        rwgpu_present(1);
        let mut caps = RwgpuCaps {
            bc_supported: 9,
            ..Default::default()
        };
        unsafe { rwgpu_get_caps(&mut caps) };
        assert_eq!(caps, RwgpuCaps::default());
    }

    #[test]
    fn init_failure_leaves_a_message() {
        assert_eq!(unsafe { rwgpu_init(std::ptr::null()) }, 0);
        let msg = unsafe { CStr::from_ptr(rwgpu_last_error()) }.to_str().unwrap();
        assert!(msg.contains("rwgpu_init"), "{msg}");
    }
}
