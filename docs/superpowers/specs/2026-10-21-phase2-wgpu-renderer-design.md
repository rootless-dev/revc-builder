# Phase 2 — wgpu Renderer for reVC

Date: 2026-10-21
Status: implemented on 2026-10-21 on branch `phase2-wgpu-renderer` (not committed); notes
from the implementation are in §13

## 1. Goal

Replace librw's OpenGL 3 backend, which reVC Builder (Phase 1) compiles into `reVC.app`,
with a new librw backend whose rendering is implemented in Rust on `wgpu` (Metal on
macOS; the same Rust code is meant to run on Vulkan and DX12 later). reVC's game logic
and librw's object model stay C++.

Decisions taken before this design (not revisited here):

| # | Decision |
|---|---|
| D1 | End users never build Rust. CI builds the renderer as a universal (arm64 + x86_64, `lipo`) static library plus a C header and publishes it as a release asset; `sources.lock` pins its URL and SHA-256; the Builder downloads and verifies it like any other pinned source and links it into reVC, which is still compiled on the user's Mac. A development override points the Builder at a locally built library instead. |
| D2 | A thin C++ librw driver (new librw platform `WGPU`) implements librw's `Device` callbacks, rasters and textures, and the default, skin and matfx object pipelines by forwarding to a Rust crate over a C ABI. Device and surface, buffers, textures, render targets, the render-state → pipeline-state mapping, WGSL shaders and draw submission live in Rust. `wgpu-native` is not used. |
| D3 | librw and reVC changes live in this repository as source files we own plus small patches, copied and applied at build time like `patches/`. No GitHub fork or repository is created. |
| D4 | Validation is macOS only. The Rust code stays platform-neutral (Metal-only APIs only behind `cfg`). |
| D5 | GL3 stays available as reference and fallback through a CLI option `--renderer gl3\|wgpu`; the GUI has no toggle. The default becomes `wgpu` only once §10 passes (§10 adds one condition this design needs: the pinned library must be a published one). |

### 1.1 Non-goals

- reVC's Neo pipelines (vehicle reflections, world lightmaps, road gloss, rim light) and
  its `NEW_RENDERER` world renderer are off by default and are not ported; with `RW_WGPU`
  the Neo options render as GL3 does with them off, and the new renderer stays off
  (§8.3).
- Multisampling. GL3 requests it through a GLFW window hint; it is off by default
  (`MultiSampling=0`) and the WGPU platform reports one sample level.
- Linux, Windows or Android builds of the renderer (D4).

## 2. Facts this design relies on

Verified by reading the pinned reVC commit `a26fff4` and librw commit `0ad67ee`
(reference clones, nothing executed):

- **G1** librw selects its backend at compile time: `LIBRW_PLATFORM` (chosen from
  `LIBRW_PLATFORMS` in librw's top-level `CMakeLists.txt`; macOS falls in its final
  `else()` branch, shared with Linux) makes `src/CMakeLists.txt` define `RW_<PLATFORM>`
  publicly; `rwbase.h` maps `RW_GL3` to
  `RW_OPENGL` and `RWDEVICE gl3`; `base.cpp` sets `rw::platform`; `engine.cpp` picks the
  `Device` and calls `gl3::registerPlatformPlugins()`; `texture.cpp`, `geoplg.cpp`,
  `raster.cpp` dispatch on `PLATFORM_*` ids, and `skin.cpp` and `matfx.cpp` call every
  backend's `initSkin`/`initMatFX`. The ids end at `PLATFORM_GL3 = 12`, followed by
  `NUM_PLATFORMS`, which sizes per-platform arrays (`Engine::driver`,
  `Driver::s_plglist`, `matFXGlobals.pipelines`, `skinGlobals.pipelines`).
  `texture.cpp`'s `getMaxSupportedMaxAnisotropy` returns the device maximum under
  `RW_D3D9` and `RW_GL3` and 1 otherwise; reVC applies it to textures (`ANISOTROPIC_FILTERING`). All backends'
  sources are always compiled; a backend that is not selected compiles to stubs.
- **G2** The GL3 window is created by librw itself (`startGLFW`, on `DEVICEINIT`) from the
  `EngineOpenParams` reVC's GLFW skeleton passes (`GLFWwindow **window`, size, title).
  reVC's skeleton issues no OpenGL call of its own.
- **G3** GL3 keeps textures bottom-up (rows flipped by `rasterFromImage`/`rasterToImage`;
  DXT blocks flipped by `flipDXT` when D3D textures are converted) and samples at `(u, 1-v)`; its device depth range is `zNear=-1, zFar=1`.
  D3D9 keeps textures top-down with `zNear=0, zFar=1` and a projection whose depth maps
  to `[0, 1]`.
- **G4** In the GL3 backend, vertex attributes a geometry lacks are disabled, so the
  shader reads OpenGL's default `(0, 0, 0, 1)`: geometry without prelight colours has
  colour `(0, 0, 0, 1)` and without normals has normal `(0, 0, 0)`.
- **G5** `reVC.ini` and saves are found through `$HOME` (`GetMacOSUserFilesFolder`), so
  starting the executable with another `HOME` isolates them.
- **G6** With `LIBRW` reVC turns on `EXTENDED_COLOURFILTER`, `EXTENDED_PIPELINES`,
  `SCREEN_DROPLETS` and `NEW_RENDERER` (`src/core/config.h`). Runtime defaults:
  colour filter `POSTFX_NORMAL` (on), screen droplets enabled, vehicle pipeline
  `VEHICLEPIPE_MATFX`, Neo lightmaps / gloss / rim light off, `gbNewRenderer` false.
- **G7** reVC code behind `RW_GL3`, `RW_OPENGL` or `rw::gl3::` (40 lines whose text matches
  `RW_GL3` or `RW_OPENGL`: 38 in 16 source files — including `skel/sdl2`, which is only
  built with SDL2 and not used here — and 2 in `src/CMakeLists.txt`, the Android
  definition list and a `LIBRW_GL3_GFXLIB` test, neither relevant on macOS; `rw::gl3::` appears in four of
  those files) is of three kinds: (a) the GLFW skeleton and input (`skel/glfw`, `crossplatform.h`,
  `ControllerConfig`, `config.h`, `Frontend.cpp`, `MenuScreensCustom.cpp`, `main.cpp`'s
  mouse centring and version string), which only needs GLFW; (b) data layout:
  `Radar.cpp` writes RGBA byte order into a raster, `TexRead.cpp` decides the `txd.img`
  conversion (`CanVideoCardDoDXT`, `GPUcaps`, `needToReadBackTextures`); (c) rendering:
  `postfx.cpp` (colour filter shaders), `screendroplets.cpp` (droplet shader, an Im2D
  vertex with two UV sets, texture stage 1), `custompipes_gl.cpp` (Neo pipelines and the
  `NEW_RENDERER` world renderer), `custompipes.cpp` (registration), `RwHelper.cpp`
  (debug groups).
- **G8** reVC's colour filter and droplets copy the current frame into a camera texture
  with `RwRasterRenderFast` (GL3: `glCopyTexSubImage2D` from the bound framebuffer).
- **G9** `CStreaming::Init` converts all textures once into `models/txd.img` when
  `CanVideoCardDoDXT()` is false (GL3) and records `rw::platform` in `data/CAPS.DAT`;
  a different platform id makes it convert again.
- **G10** On a camera size change reVC destroys and recreates the camera's `CAMERA` and
  `ZBUFFER` rasters (`CameraSize`, `RwHelper.cpp`); the GLFW framebuffer-size callback
  sets the camera size in framebuffer pixels, so on Retina the game renders at 2×.
- **G11** GL3 binds a 1×1 white texture to every stage that has no raster
  (`whitetex`), so untextured draws show their vertex colour; its `rasterToImage` and
  `rasterFromImage` flip rows because its rasters are bottom-up.

## 3. Repository layout

```
renderer/                         Rust workspace (ours, MIT)
├── rust-toolchain.toml           pinned toolchain 1.96.1, targets aarch64 + x86_64 apple-darwin
├── Cargo.toml, Cargo.lock        committed; wgpu pinned to =30.0.1
├── include/rwgpu.h               the C ABI (hand-written; tests keep it in sync, §4.4)
├── link-libs.txt                 the system libraries the static library needs; shipped in the archive (§6.1)
├── collect-licenses.py           writes THIRD_PARTY_LICENSES.txt from `cargo metadata` and the registry sources
├── check-link-libs.py            CI: link-libs.txt covers `rustc --print native-static-libs`
├── rwgpu/                        the crate: staticlib + rlib
│   ├── src/  lib.rs abi.rs ffi.rs renderer.rs state.rs pipeline.rs convert.rs dump.rs shaders.rs shaders/*.wgsl
│   └── tests/abi_check.c         compiled by a Rust test (§4.4)
└── build-universal.sh            builds both slices, lipo, packages the release archive
renderers/                        per-renderer overlays applied by the Builder (§7)
├── gl3/librw/patches/            GL3 frame dump and frame statistics (§9)
└── wgpu/
    ├── librw/files/src/wgpu/     the C++ librw driver (ours, MIT; adapted from librw's GL3 backend, MIT)
    ├── librw/patches/            librw build and platform-id patches
    ├── revc/files/src/extras/    custompipes_wgpu.cpp (ours, MIT); shaders/wgpu/*.wgsl.inc (reVC shader translations, §8.2)
    └── revc/patches/             reVC guard and extras patches
patches/                          unchanged: reVC patches for every renderer
tools/capture/                    development-only reVC patch for deterministic captures (§10)
```

No reVC source file enters the repository. reVC changes are patches, as in Phase 1
(patches carry reVC context lines and are small). The colour filter and droplet
fragment shaders are reVC's (about 20 lines each); their WGSL translations are small
include files copied into the reVC checkout next to the patched code, which hands them to
the renderer at run time (§4.3, §8.2), so they are not part of the Rust crate. The other
new file added to reVC, `custompipes_wgpu.cpp`, is code written for this project:
pipelines whose render callbacks call the driver's default, skin and matfx callbacks. The C++ driver is adapted from librw's GL3 backend, which is
MIT-licensed: its files keep librw's copyright notice next to ours. The app ships
`renderers/` as it already ships `patches/`, so it carries this librw-derived code and
reVC excerpts (patch context and the shader translations); `THIRD_PARTY_NOTICES.md` is
updated to say so and to name librw's licence (MIT) and reVC's (`LICENSE.md` in the reVC
repository: MIT with an added condition), replacing its current statement that the app
contains nothing from reVC or librw.

## 4. The C ABI (`renderer/include/rwgpu.h`)

### 4.1 Principles

- Plain C, `extern "C"`, prefix `rwgpu_`. Only fixed-width integers, `float`, pointers
  and `#[repr(C)]` structs. Objects are `uint32_t` handles; `0` means "none", except in
  `RwgpuTarget.color`, where `0` is the main frame (§5.1). A texture stage set to `0`
  samples a 1×1 opaque white texture, as GL3 does (G11). Index buffers are `uint16_t`,
  as in librw.
- The library is single-threaded: every call comes from the thread that called
  `rwgpu_init` (reVC's main thread). Rust keeps its state in one global behind a mutex.
  `rwgpu_abi_version`, `rwgpu_last_error` and `rwgpu_init` work at any time; any other
  call made before a successful `rwgpu_init` or after `rwgpu_shutdown` is ignored and
  returns 0 where it returns a value.
- Calls that can fail return `0`; `rwgpu_init` (and a shader source that is not UTF-8)
  also leave a message for `rwgpu_last_error()`, the others log to stderr. Uncaptured wgpu errors (validation and others) are counted
  (`rwgpu_get_stats`) and the first 20 are logged to stderr with the prefix `rwgpu:`; they do not abort, because `rwgpu_init`
  installs `Device::on_uncaptured_error` (wgpu's default handler panics, which
  `panic = "abort"` would turn into a crash). `rwgpu_im2d_shader_create` compiles inside
  a validation error scope and returns 0 when the WGSL is rejected. Panics abort the process
  (`panic = "abort"`) after printing.
- `RWGPU_ABI_VERSION` (starting at 1) is defined in the header and returned by
  `rwgpu_abi_version()`; the driver refuses to start when they differ, so a library
  that does not match the header the driver was compiled with is reported, not
  misused. The header comes with the library (same archive or override directory), so
  the driver also states the ABI version it was written for, `RWGPU_DRIVER_ABI` in
  `rwwgpu.h`, and its private header `rwwgpuimpl.h` (included only by the driver's
  `.cpp` files, which see `RWGPU_INCLUDE_DIR`) stops the compile with `#error` unless it
  equals `rwgpu.h`'s `RWGPU_ABI_VERSION`: a driver in `renderers/wgpu` and a pinned
  library for different ABIs fail at compile time.
- Enumerations reuse librw's numbering where librw has one (render states, blend,
  stencil, cull, filter and addressing modes, primitive types, clear flags), so the
  driver forwards values unchanged. Tests assert the numbering (§4.4).

### 4.2 Structures

| Struct | Size | Layout |
|---|---|---|
| `RwgpuWindowDesc` | 48 | `uint32 kind` (1 = AppKit), `uint32 width, height` (framebuffer pixels), `uint32 vsync`, `void *handle[4]` (AppKit: `[0]` = `NSView*`) |
| `RwgpuStats` | 32 | `uint64 frames`, `uint64 validation_errors`, `uint32 pipelines`, `uint32 textures`, `uint32 meshes`, `uint32 reserved` |
| `RwgpuCaps` | 16 | `uint32 bc_supported`, `float max_anisotropy`, `uint32 max_texture_size`, `uint32 reserved` |
| `RwgpuTarget` | 24 | `uint32 color` (0 = the main frame), `uint32 depth` (0 = none), `int32 x, y, w, h` (viewport in target pixels, top-left origin) |
| `RwgpuLight` | 64 | `float type, radius, minus_cos_angle, hard_spot; float position[4]; float direction[4]; float color[4]` (type 1 directional, 2 point, 3 spot; `set_lights` uses the first `count` entries, at most 8) |
| `RwgpuIm2DVertex` | 28 | `float x, y, z, w; uint8 r, g, b, a; float u, v` (identical to `gl3::Im2DVertex`) |
| `RwgpuIm2DVertexUV2` | 36 | `RwgpuIm2DVertex` + `float u2, v2` |
| `RwgpuIm3DVertex` | 36 | `float pos[3], normal[3]; uint8 r, g, b, a; float u, v` (identical to `gl3::Im3DVertex`) |
| mesh vertex, layout `MESH` | 44 | `float pos[3]` @0, `float normal[3]` @12, `uint8 rgba[4]` @24, `float uv0[2]` @28, `float uv1[2]` @36 |
| mesh vertex, layout `SKIN` | 64 | `MESH` + `float weights[4]` @44, `uint8 indices[4]` @60 |

Matrices are 16 floats in librw's `RawMatrix` order (the order GL3 uploads).

### 4.3 Functions

| Group | Functions |
|---|---|
| Lifecycle | `rwgpu_abi_version`, `rwgpu_init(const RwgpuWindowDesc*)`, `rwgpu_shutdown`, `rwgpu_last_error`, `rwgpu_get_caps(RwgpuCaps*)` |
| Frame | `rwgpu_resize(w, h)`, `rwgpu_present(vsync)`, `rwgpu_get_stats(RwgpuStats*)` |
| Cameras and targets | `rwgpu_begin_camera(const RwgpuTarget*, const float view[16], const float proj[16], float fog_start, float fog_end, const float gl_depth_row[2])`, `rwgpu_end_camera`, `rwgpu_clear(const RwgpuTarget*, const float rgba[4], uint32 mode)`, `rwgpu_copy_main_to_texture(tex, dst_x, dst_y, w, h)`, `rwgpu_read_main(void *rgb, uint32 size)` |
| Textures | `rwgpu_texture_create(format, w, h, levels, flags)`, `rwgpu_texture_upload(tex, level, src_format, data, size)`, `rwgpu_texture_read(tex, level, out, size)`, `rwgpu_texture_destroy(tex)`, `rwgpu_depth_create(w, h)`, `rwgpu_depth_destroy(depth)` |
| Render state | `rwgpu_set_render_state(state, value)`, `rwgpu_get_render_state(state)`, `rwgpu_set_raster(stage, tex, flags)`, `rwgpu_set_texture(stage, tex, flags, filter, address_u, address_v, max_anisotropy)` |
| Per object / mesh | `rwgpu_set_world_matrix(m)`, `rwgpu_set_lights(ambient[4], const RwgpuLight*, count)`, `rwgpu_set_material(color[4], surface_props[4])`, `rwgpu_set_bones(matrices, count)`, `rwgpu_set_matfx_env(tex_matrix[16], fx_params[4], color_clamp[4], env_color[4])` |
| Meshes | `rwgpu_mesh_create(layout, vertices, vertex_bytes, indices, index_count)`, `rwgpu_mesh_update_vertices(mesh, vertices, bytes)`, `rwgpu_mesh_destroy(mesh)`, `rwgpu_draw_mesh(mesh, shader, prim, first_index, index_count)` |
| Immediate mode | `rwgpu_im2d_draw(prim, vertices, num_vertices, indices, num_indices)` (indices may be NULL), `rwgpu_im2d_uv2_draw(prim, vertices, num_vertices, indices, num_indices)` (UV2 vertices), `rwgpu_im2d_shader_create(const char *wgsl)`, `rwgpu_im2d_set_override(shader, const float params[16])`, `rwgpu_im3d_transform(vertices, n, world[16], lit)`, `rwgpu_im3d_draw(prim, indices, num_indices)` (indices may be NULL: draws the transformed vertices in order), `rwgpu_im3d_end` |

Texture formats: `RGBA8 = 1`, `BC1 = 2`, `BC2 = 3`, `BC3 = 4`; a BC texture's width and
height must be multiples of 4 (`rwgpu_texture_create` returns 0 otherwise). Upload
source formats: `SRC_NATIVE = 0` (the texture's own format, tightly packed),
`SRC_RGB8 = 1` (RGB8 rows, expanded to RGBA8 with alpha 255; RGBA8 textures only).
Texture flags: `RENDER_TARGET = 1`, `AUTO_MIPMAP = 2` (uploading level 0 of an RGBA8
texture regenerates levels 1 to `levels − 1` with a 2×2 box filter). The driver does not
use `AUTO_MIPMAP`: GL3 gives `MIPMAP|AUTOMIPMAP` rasters one level and
`GL_TEXTURE_MAX_LEVEL` 0, so they are sampled at level 0 only, and the driver creates
them with one level for parity. Raster flags passed with `set_raster`/`set_texture`: `HAS_ALPHA = 1`,
`FORCE_OPAQUE = 2`. The driver sets `FORCE_OPAQUE` on every raster without alpha:
sampled alpha is then 1, as with GL3, which stores such rasters as `GL_RGB8` or
`GL_COMPRESSED_RGB_S3TC_DXT1`. It matters for DXT1 textures without alpha and for screen
copies into camera textures created without alpha (reVC's colour-filter buffers), whose
RGBA8 storage receives the main target's alpha. `TEXTURERASTER` is never passed to `rwgpu_set_render_state` (which ignores it): its
value is a `Raster*`, so the driver keeps the pointer and calls `rwgpu_set_raster(0, …)`.
Sampling state follows GL3 exactly (§5.3): `rwgpu_set_raster` is GL3's
`setRasterStage`, `rwgpu_set_texture` is GL3's `setTexture`, and the `TEXTURE*` render
states go through GL3's `setFilterMode`/`setAddressU`/`setAddressV`.
Shaders for `draw_mesh`: `DEFAULT = 0`,
`SKIN = 1`, `MATFX_ENV = 2`. Mesh layouts: `MESH = 0`, `SKIN = 1`.

`rwgpu_im2d_shader_create` takes a WGSL fragment entry point `fs_main(in: Im2DOut) ->
@location(0) vec4f`; the renderer prepends a fixed prelude declaring `Im2DOut`
(`color`, `tex0`, `tex1`, `fog`), the texture bindings `tex0/samp0/tex1/samp1`, the Draw
block as `override_draw`, and helpers: `param(i)` returns the `i`-th `vec4f` of the 16
floats of `set_override`, and `sample0`/`sample1` sample a stage the way the built-in
shaders do (alpha 1 for rasters without alpha). While an override is set,
Im2D draws use it instead of the built-in fragment stage. This mirrors the
fragment half of GL3's `im2dOverrideShader` and lets reVC's patch supply its own
shaders. GL3's override replaces the vertex stage too, with reVC's `im2d.vert`, which
sets `w = 1` and takes fog from `z`; here the vertex stage stays librw's Im2D one. For
the shaders reVC uses this changes nothing: they ignore fog, and every vertex of their
quads has the same `w`, so interpolation is the same.

### 4.4 Keeping the contract

- Rust unit tests assert `size_of`/`offset_of` of every `#[repr(C)]` struct against the
  numbers in §4.2.
- A Rust test compiles `tests/abi_check.c` with the system C compiler
  (`cc -fsyntax-only`); it includes `rwgpu.h` and `_Static_assert`s the same sizes and
  offsets and the enum values that mirror librw.
- `abi_check.c` also asserts the header's librw-mirroring values against librw's
  numbering, and the C++ driver `static_assert`s that every `RWGPU_*` constant that
  mirrors librw equals librw's enumerator, so the header cannot drift from librw either.
- A Rust test reads `include/rwgpu.h` and `src/ffi.rs` (where every exported function
  lives) and fails unless the set of `rwgpu_*` functions declared in the header equals the
  set of `extern "C" fn rwgpu_*` defined there.

## 5. Rendering design (Rust)

### 5.1 Device, surface and frames

- `rwgpu_init` builds a `RawWindowHandle` (AppKit: the `NSView` from
  `glfwGetCocoaView`) and calls `Instance::create_surface_unsafe`, then requests a
  high-performance adapter compatible with the surface and a device with
  `TEXTURE_COMPRESSION_BC` and `ADDRESS_MODE_CLAMP_TO_BORDER` when the adapter has them.
  The surface is configured with `CompositeAlphaMode::Opaque`, so destination-alpha
  blending never makes the window translucent. The window stays owned by GLFW.
- Rendering goes to an offscreen **main colour target** (`Rgba8Unorm`, framebuffer
  size, usable as render attachment, copy source/destination and texture), not to the
  swap chain; `rwgpu_resize` recreates it and reconfigures the surface. `rwgpu_present`
  ends the open pass, optionally writes a frame dump (§9),
  blits the main target to the surface texture with a full-screen triangle (the surface
  uses a non-sRGB format, like GL3's default framebuffer), submits and presents.
  This makes frame copies (G8), frame dumps and `rwgpu_read_main` simple and keeps the
  main target's contents across frames.
- Present mode: `Fifo` when `vsync` is set, else `Immediate` (`AutoNoVsync` if
  unsupported); the surface is reconfigured only when the mode or size changes. A lost
  or outdated surface is reconfigured and that frame is not shown; a timeout, an occluded
  window or any other acquisition failure also only skips showing it. In every case the
  recorded commands are still submitted, and the frame still counts for dump and
  statistics numbering (§9), so frame numbers do not depend on the window.
- At most one `CommandEncoder` and one `RenderPass<'static>` (`forget_lifetime`) are
  open at a time. The pass ends when the target changes, a full-target clear restarts it
  (§5.2), a copy is recorded, the
  recorded commands are submitted (at present, and mid-frame in the cases of §5.4) or the
  frame is presented; a submit finishes the encoder and the next command opens a new
  one. Whenever the pass has ended, the next draw reopens it on the current target with
  `LoadOp::Load` and re-applies the viewport and stencil reference. Resources stay alive while referenced
  because wgpu objects are reference counted.

### 5.2 Targets, cameras and clears

- A target is `(colour, depth, viewport)`. Colour `0` is the main target; otherwise a
  texture created with `RENDER_TARGET` (a librw `CAMERATEXTURE`). Depth handles come
  from `ZBUFFER` rasters; each is a `Depth24PlusStencil8` texture that is recreated at
  the colour target's size when attached to a target of another size (G10). `rwgpu_clear` and `rwgpu_begin_camera` each name their target (reVC clears a
  camera before it begins it), and the driver checks the framebuffer size in both, so a
  clear after a window resize already goes to the resized main target. A pass is begun
  lazily at the first draw, or by a clear. `end_camera` keeps the
  target, so draws after it still go to the last camera's target, as in GL3, which
  leaves its framebuffer bound.
- `begin_camera` stores view, projection, fog start/end and the Im2D transform
  `(2/w, -2/h, -1, 1)` for the viewport size (GL3 uses the camera raster's size; for the
  main camera reVC keeps that equal to the framebuffer size, G10, so the two differ only
  between a resize and reVC's camera-size handler), and sets the viewport (subrasters give a
  viewport offset; origin top-left).
- `rwgpu_clear`: when the viewport covers the whole target, the pass is restarted with
  `LoadOp::Clear` for the requested aspects (colour, depth 1.0, stencil 0) and `Load`
  for the others; otherwise a quad is drawn inside the viewport with the clear values
  (depth `Always` + write, stencil `Replace`, colour writes masked per mode). Clears
  ignore the current depth-write state, as GL3 does.
- `rwgpu_copy_main_to_texture` ends the pass, records `copy_texture_to_texture` from the
  main target at `(0, 0, w, h)` to `(dst_x, dst_y)` of the texture (clamped to both
  sizes) and lets the next draw reopen the pass with `Load`. This is
  `rasterRenderFast` from a `CAMERA` raster.

### 5.3 Render state and pipelines

Rust holds librw's render-state cache and reproduces GL3's semantics (`gl3device.cpp`):
the interplay of vertex alpha and texture alpha that switches blending and alpha test
(`setVertexAlpha`, `setRasterStage`), depth test off with depth write on becoming
compare `Always` with writes, `CULLBACK`/`CULLFRONT`, stencil, alpha function and
reference, fog enable and colour, and the PS2 alpha-test emulation (`drawInst_GSemu`:
when `GSALPHATEST` is set and blending is on, a mesh draw with depth writes on becomes
two draws — alpha test `ALPHAGREATEREQUAL` against `GSALPHATESTREF`, then `ALPHALESS`
with depth writes off — and with depth writes off one draw with alpha test `ALPHAALWAYS`;
the previous alpha function, reference and depth write are restored afterwards). It lives in `state.rs` and
is tested without a GPU.

A **pipeline key** is: vertex stage (`default`, `skin`, `matfx_env`, `im3d`, `im2d`,
`im2d_uv2`, `clear`; a lit Im3D draw uses `default` with the `IM3D` layout, as GL3 uses
its default shader for it), fragment stage (`simple`, `matfx_env`, `override(handle)`,
`clear`), vertex layout (`MESH`, `SKIN`, `IM3D`, `IM2D`, `IM2D_UV2`), topology (point
list, line list, line strip, triangle list, triangle strip; fans are converted to lists
on the CPU), blend (`None` or source/destination factors, equation add), depth (compare
`LessEqual` or `Always`, write on/off; absent when the target has no depth), cull mode
(front face counter-clockwise, as GL3), stencil (compare, fail/depth-fail/pass ops,
read and write masks; the reference is dynamic state), colour target format and colour
write mask. Pipelines are created on first use and cached in a `HashMap` for the whole
run (the set is small and bounded by the state space the game uses). Alpha test and fog
are uniforms, not pipeline variants: alpha test is `discard if a < ref_low || a >=
ref_high`, with `(-1000, 1000)` for "always", as GL3.

Blend factors map one to one (`ZERO, ONE, SRCCOLOR, INVSRCCOLOR, SRCALPHA, INVSRCALPHA,
DESTALPHA, INVDESTALPHA, DESTCOLOR, INVDESTCOLOR, SRCALPHASAT`); stencil operations
`KEEP, ZERO, REPLACE, INCRSAT, DECRSAT, INVERT, INCR (wrap), DECR (wrap)`; stencil
functions `NEVER, LESS, EQUAL, LESSEQUAL, GREATER, NOTEQUAL, GREATEREQUAL, ALWAYS`.

**Sampling state.** GL3 keeps two sets of sampling state, and Rust keeps both: a cache
per stage (raster, filter, address U/V; what `getRenderState` reports) and the state of
each texture object (filter, address U/V, anisotropy; what sampling uses), which starts
at filter 0, address 0 (GL's defaults: linear magnification, nearest-mipmap-linear
minification, repeat) and anisotropy 1. They are updated as in `gl3device.cpp`:

- `set_raster` (`setRasterStage`): when the raster differs from the stage's, the stage
  takes it, and the texture's filter and addressing are set to the stage's where they
  differ (anisotropy is untouched).
- `set_texture` (`setTexture`): when the raster differs, the stage takes it and copies
  the texture's filter and addressing into the stage cache (`setRasterStageOnly`); then
  `setFilterMode` with the texture's filter and anisotropy, then `setAddressU/V` with its
  addressing. A raster of 0 is `setRasterStage(0)`.
- `setFilterMode(filter, anisotropy)` (also `TEXTUREFILTER`, with anisotropy 1): when
  the stage's filter differs, the stage and the bound texture take the new filter, and the
  texture takes the new anisotropy.
- `setAddressU/V` (also `TEXTUREADDRESS*`): when the stage's address differs, the stage
  takes it; the texture's address does not change (GL3 tests `==` where `!=` is meant).

So a texture's addressing changes only when it is bound with `TEXTURERASTER` under
different stage addressing; textures drawn only through `setTexture` keep `repeat`. This
reproduces GL3's behaviour, including its addressing bug, because GL3 is the reference
of §10. A destroyed texture is unbound from every stage with `setRasterStage(stage, 0)`, as
GL3's `evictRaster` does, so on stage 0 the texture-alpha interplay runs (blending and
alpha test follow). Filter or address 0 set after a non-zero value is a GL error in GL3
that keeps the previous value; here 0 maps to GL's default state; the case is not known
to occur.

Samplers are cached by `(filter, address U, address V, anisotropy)`; filter modes map to
min/mag/mipmap filters as GL3's tables do. `NEAREST` and `LINEAR` use a non-mipmapped
minification filter in GL3 even on a texture with mipmaps, so only level 0 is sampled;
their samplers set `lod_max_clamp = 0`. wgpu accepts an anisotropy above 1 only when
the minification, magnification and mipmap filters are all linear, so anisotropy is
applied with `LINEARMIPLINEAR` and clamped to 1 with every other filter (GL3 applies it
under any filter; with nearest filtering its effect is driver-defined); `BORDER` addressing becomes `ClampToBorder`
with transparent black when the device supports it, else `ClampToEdge`. Texture bind
groups (`tex0, samp0, tex1, samp1`) are cached by those four keys and dropped when a
texture is destroyed.

### 5.4 Uniforms and buffers

- Uniform blocks: **Camera** (projection, view, fog start/end/range, Im2D transform,
  GL depth row for skin fog),
  **Object** (world matrix, ambient, 8 lights, env-map matrix), **Draw** (material
  colour, surface properties, alpha-test range, fog colour, fog disable, raster flags,
  matfx parameters, override parameters), **Bones** (64 matrices). Each is appended to
  a per-frame uniform arena only when it changed, at 256-byte-aligned offsets, and bound
  with dynamic offsets (one bind group per arena buffer). After an arena restart (below)
  every block counts as changed, so the next draw appends all four again.
- Im2D/Im3D vertices and indices go to per-frame vertex and index arenas the same way.
  Every arena allocation starts at a multiple of 4 bytes and is written padded to a
  multiple of 4 bytes, as `Queue::write_buffer` requires (an odd number of `uint16_t`
  indices gets two zero bytes).
  All arenas are written with `Queue::write_buffer` at offsets that never repeat within
  a submission; when one is full, the frame's commands so far are submitted and the
  arenas restart at zero (queue order guarantees the earlier commands read the old
  data first). A single request larger than an arena replaces that arena with one of at
  least twice the needed size (the next power of two, doubled) before it is written, so
  every request fits.
- Readbacks (`rwgpu_read_main`, `rwgpu_texture_read`) submit the commands recorded so
  far and wait for them, so they see every earlier draw, as `glReadPixels` does.
- Textures: `Queue::write_texture` also takes effect before every command of the
  submission it lands in. Each texture records whether a command recorded since the last
  submission samples it or renders to it; an upload to such a texture first submits the
  commands recorded so far (ending the pass), so earlier draws keep the old contents, as
  in GL3.
- Meshes own a vertex and an index buffer. `rwgpu_mesh_update_vertices` creates a new
  vertex buffer instead of writing in place, so draws already recorded in the frame keep
  the old vertices (GL3's `glBufferData` behaves the same way).

### 5.5 Shaders (WGSL)

Translated from librw's GLSL (`src/gl/shaders`, MIT): `default.vert`, `skin.vert`,
`matfx_env.vert/.frag`, `im2d.vert`, `im3d.vert`, `simple.frag`, `header.vert/.frag`
(lighting, fog, alpha test). Changes from the GLSL:

- Textures are sampled at `(u, v)`, not `(u, 1-v)`, because every texture, including
  render targets, is top-down in wgpu (G3).
- The projection is D3D-style (depth in `[0, 1]`), so the device reports
  `zNear = 0, zFar = 1`, like D3D9 (G3).
- One vertex shader per kind handles all light types; a `light_mask` uniform reproduces
  GL3's `DIRECTIONALS/POINTLIGHTS/SPOTLIGHTS` variants (with no lights the loop ends at
  once, which is what GL3's unlit variant computes).
- GL3's skin shader computes fog from clip-space `z` where every other shader uses `w`;
  with GL's projection that `z` is `2n(z_view − f)/(f − n)` away from `w` for a
  perspective camera (`−2n` at the near plane, `0` at the far plane). The skin shader
  reproduces it, because GL3 is the reference A2 is measured against: the camera block
  carries GL's depth row (`(f+n)/(f−n)` and `−2fn/(f−n)` for perspective,
  `2/(f−n)` and `−(f+n)/(f−n)` for parallel), and the skin shader takes fog from
  `z_view` mapped through it.
- When fog is disabled the fog factor is `1` without evaluating the formula (GL3's
  `clamp(x, 1, 1)`), which also avoids a division by zero when fog start equals fog end.

Every WGSL module is parsed and validated by `naga` in a unit test (`naga` is a
dev-dependency pinned to the version wgpu 30.0.1 uses, `=30.0.1`), including reVC's
override shaders (§8.2) with the prelude prepended.

## 6. The C++ librw driver (`renderers/wgpu/librw/files/src/wgpu`)

Namespace `rw::wgpu`, compiled when `RW_WGPU` is defined. Adapted from librw's GL3
backend (MIT) with the OpenGL calls replaced by `rwgpu_*` calls:

- `wgpudevice.cpp` — `Device renderdevice` (`zNear 0`, `zFar 1`); a `static_assert`
  for every librw enumerator the ABI mirrors (§4.4); GLFW monitor and video
  mode handling copied from GL3; `DEVICEINIT` creates the window with
  `GLFW_CLIENT_API = GLFW_NO_API`, takes `glfwGetCocoaView` and the framebuffer size and
  calls `rwgpu_init`; `beginUpdate` on a `CAMERA` raster reads `glfwGetFramebufferSize`
  and calls `rwgpu_resize` when it changed, then builds the view matrix as GL3 does and a D3D-style
  projection, fills `cam->devView`/`devProj`, computes GL3's depth row for skin fog
  (§5.5), and calls `rwgpu_begin_camera`;
  `clearCamera`, `showRaster` (`FLIPWAITVSYNCH` → vsync), `rasterRenderFast`,
  `setRenderState`/`getRenderState` (the `TEXTURERASTER` pointer is kept on the C++ side
  for `getRenderState`).
- `wgpuraster.cpp` — the native raster plugin (`WgpuRaster`: texture or depth handle,
  `hasAlpha`, `isCompressed`, `numLevels`, `autogenMipmap`, a CPU backing store while
  `needToReadBackTextures` is set), lock/unlock, image conversion, native texture
  stream read/write, DXT allocation. CPU layout is top-down: `C8888` and `C1555` rasters
  are RGBA8 (4 bytes per pixel, like GL3 on GLES), `C888` is RGB8 (uploaded with
  `SRC_RGB8`). `MIPMAP|AUTOMIPMAP` rasters, compressed or not, have one level, as in GL3 (§4.3). Locking a
  level for reading without a backing store reads the texture back from the GPU (RGBA8;
  converted to RGB8 for `C888`). DXT rasters whose width or height is not a multiple of
  4 are not kept compressed; they take librw's generic conversion through an `Image`.
  A `CAMERA` raster has no texture and maps to the main target; locking it reads the
  main target (`rwgpu_read_main`, RGB8, top row first — GL3 returns the bottom row
  first). Because rasters are top-down, `rasterFromImage` and `rasterToImage` copy rows
  in order, without GL3's flip (G11), and `rasterToImage` makes a 32-bit image from
  every 4-byte raster, including `C1555`, so screenshots (`psGrabScreen`) come out
  upright.

  **Native texture stream** (`PLATFORM_WGPU`, written into `txd.img`): GL3's layout with
  the platform id 13. After the chunk header: `platform`, `filterAddressing`, `name[32]`,
  `mask[32]`, then `format`, `width`, `height`, `depth`, `numLevels`, a reserved `0`
  (GL3's `subplatform`), `flags` (1 = has alpha, 2 = compressed) and `compression`
  (0, or 1/3/5 for DXT1/3/5), each 32-bit little-endian; then per level a 32-bit size
  and the level's bytes in the CPU layout above (RGBA8, RGB8 or BC blocks, top-down).
  Reading a compressed texture on a device without BC support fails like GL3's reader
  (`ERR_FORMAT_UNSUPPORTED`); in practice it does not happen, because `CAPS.DAT` records
  BC support and reVC converts again when it changes (G9).
- `wgpu.cpp` — driver plugin registration (`registerPlatformPlugins`).
- `wgpupipe.cpp`, `wgpuskin.cpp`, `wgpumatfx.cpp`, `wgpuimmed.cpp` —
  instancing into the `MESH`/`SKIN` layouts (missing attributes get G4's defaults),
  lighting (`World::enumerateLights` → `RwgpuLight`), the default, skin and matfx render
  callbacks, Im2D/Im3D forwarding (`im2dOverrideShader` becomes
  `rwgpu_im2d_set_override`).
- `rwwgpu.h` — public header for reVC: `EngineOpenParams` (same fields as GL3 with GLFW),
  `Im2DVertex`/`Im3DVertex` with GL3's accessors, the pipeline and raster API the
  extras use (`setTexture`, `setWorldMatrix`, `lightingCB`, `defaultRenderCB`,
  `skinRenderCB`, `matfxRenderCB`, `drawInst`, `setLights`, `setMaterial`, `ObjPipeline`,
  `defaultInstanceCB`, `skinInstanceCB`, `InstanceDataHeader`, the native raster
  extension `WgpuRaster` with `nativeRasterOffset`, `caps` (`dxtSupported`,
  `maxAnisotropy`), `needToReadBackTextures`, `im2DCreateShader`, `im2DSetOverride`,
  `im2DRenderIndexedPrimitiveUV2`).

### 6.1 librw patches (`renderers/wgpu/librw/patches`)

1. `PLATFORM_WGPU = 13` inserted after `PLATFORM_GL3` and before `NUM_PLATFORMS` (which
   becomes 14, so every array it sizes has a slot for it), and `ID_RASTERWGPU` in
   `rwbase.h`, `RW_WGPU` → `RWDEVICE wgpu`; `rw::platform`
   (`base.cpp`), device and plugin registration (`engine.cpp`), native texture
   read/write/size dispatch (`texture.cpp`), native data destruction (`geoplg.cpp`),
   skin and matfx init (`skin.cpp`, `matfx.cpp`; calls guarded by `RW_WGPU`, since the
   driver's sources are only compiled for that platform), DXT pass-through from D3D and
   Xbox rasters when the device supports BC (`rw::wgpu::caps.dxtSupported`; GL3 checks this
   for D3D rasters only) and width and height are multiples of 4, copying the blocks
   without GL3's `flipDXT` because the rasters are top-down (`raster.cpp`), the maximum
   anisotropy from `rw::wgpu::caps` (`texture.cpp`), `rw.h` includes `rwwgpu.h`, and so do the generic files that include
   `gl/rwgl3.h` directly instead of `rw.h` (`charset.cpp`, which uses
   `RWDEVICE::Im2DVertex`, and `engine.cpp`, `geoplg.cpp`, `raster.cpp`, `skin.cpp`,
   `matfx.cpp`, `texture.cpp`).
2. CMake: `WGPU` added to `LIBRW_PLATFORMS` in the final `else()` branch (it fails at
   configure time on anything but Apple); with it, the `src/wgpu/*.cpp` sources
   are compiled, `glfw` is linked publicly as for GL3, and the static library named by
   `RWGPU_LIBRARY` is linked, with its header directory `RWGPU_INCLUDE_DIR` as a private
   include of librw (reVC uses the driver's `rwwgpu.h`, never `rwgpu.h`), plus the system
   libraries the Rust static library needs. That list travels with the library:
   `renderer/link-libs.txt` (for wgpu 30.0.1: the `Metal`, `QuartzCore`,
   `CoreGraphics`, `Foundation` and `CoreFoundation` frameworks and `objc`, `iconv`, `c`,
   `m`, as `rustc --print native-static-libs` reports) is copied into the archive as
   `lib/link-libs.txt`; the Builder reads it and passes it as `RWGPU_LINK_LIBS`, which the
   patch links. CI fails when the reported list gains an entry missing from
   `link-libs.txt` (§11). OpenGL is not linked.

## 7. Builder integration

### 7.1 Renderer selection

- `vcbuilder/renderers.py` defines the renderers `gl3` and `wgpu`: overlay directory,
  extra CMake definitions, whether the prebuilt library is needed, and the CMake build
    directory (`build/reVC` for `gl3`, the Phase 1 path; `build/reVC-wgpu` for `wgpu`).
  `Locations.revc_build` becomes `Locations.revc_build_for(renderer)`, and its users
  `BuildContext.built_app` and `stage_compile` pass the context's renderer
  (`tests/test_platform.py`, which also reads it, is updated; so is
  `tests/test_sources.py`, which expects exactly three archives in the lock). Both renderers install the
  same `reVC.app`: building with the other renderer replaces it. `DEFAULT_RENDERER = "gl3"` until §10 holds (D5).
- CLI: `--renderer {gl3,wgpu}`; `--rwgpu-dir DIR` (or the environment variable
  `VCBUILDER_RWGPU_DIR`) uses `DIR/lib/librwgpu.a` and `DIR/include/rwgpu.h` instead of
  the pinned download and logs that a development override is active. The GUI uses the
  default renderer.
- `BuildSession(renderer=..., rwgpu_dir=...)` passes both to `BuildContext`.

### 7.2 Pinned prebuilt library

A new `sources.lock` archive entry:

```toml
[sources.rwgpu]
type = "archive"
renderer = "wgpu"          # fetched only for this renderer
platform = "macos"         # selected by Platform.lock_platform
version = "0.1.0"
urls = ["https://github.com/rootless-dev/revc-builder/releases/download/rwgpu-v0.1.0/rwgpu-0.1.0-macos-universal.tar.gz"]
sha256 = "0000000000000000000000000000000000000000000000000000000000000000"
placeholder = true          # until the first release exists; the SHA-256 is then all zeros
```

`renderer` and `platform` are optional; entries without them are fetched for every
build, as today. An entry with `placeholder = true` is never downloaded: a build that
needs it without the development override stops with "The prebuilt renderer has not
been published yet" (new `RendererUnavailableError`). The archive has one top
directory `rwgpu-<version>/` with `lib/librwgpu.a` (universal), `lib/link-libs.txt`,
`include/rwgpu.h`, `LICENSE` and `THIRD_PARTY_LICENSES.txt`; a development override
directory has the same layout (`build-universal.sh` produces both). Stage 3 extracts it like the other archives;
stage 5 checks that `lib/librwgpu.a`, `lib/link-libs.txt` and `include/rwgpu.h` exist
there or, with the development override, in the override directory. The network test
(`tests/test_network.py`) skips placeholder entries, which have nothing to download.

### 7.3 Stages

- **fetch** skips archives whose `renderer` differs from the build's renderer or whose
  `platform` differs from the host platform's, and skips the renderer library entirely
  when the development override is set.
- **compile** restores the checkout as today, applies `patches/`, then the renderer's
  overlay: copies `renderers/<r>/librw/files/` into `vendor/librw/`, applies
  `renderers/<r>/librw/patches/*.patch` inside `vendor/librw`, copies
  `renderers/<r>/revc/files/` into the checkout and applies
  `renderers/<r>/revc/patches/*.patch` (each group in file-name order; missing groups
  are skipped). The restore's `git clean -f -d` removes copied files on a retry. CMake
  gets `LIBRW_PLATFORM` plus, for `wgpu`, `RWGPU_LIBRARY`, `RWGPU_INCLUDE_DIR` and
  `RWGPU_LINK_LIBS`.
- **verify** additionally requires, through `Platform.verify_renderer(app, renderer)`,
  that the executable links Metal and not OpenGL (`wgpu`) or links OpenGL (`gl3`).
- `resources.py` locates `renderers/` like `patches/` (source tree or wheel data); the
  wheel and the PyInstaller spec include it.

Platform seam: the library file name (`librwgpu.a`), the lock platform name, the
frameworks to verify and the renderer check are `Platform` methods implemented in
`macos.py`; everything else above is platform-neutral.

## 8. reVC changes (`renderers/wgpu/revc`)

### 8.1 Guards and data layout

`RW_GL3` becomes `RW_GL3 || RW_WGPU` where it means "the GLFW skeleton" (G7 a) and in
`Radar.cpp`'s RGBA byte order; negated tests become `!(RW_GL3 || RW_WGPU)`
(`main.cpp`'s mouse centring, `Frontend.cpp`'s DirectInput branch,
`ControllerConfig.h`, `config.h`). In `TexRead.cpp`, `CanVideoCardDoDXT` returns false for
`RW_WGPU` (keeps GL3's `txd.img` conversion, G9), `GetGPUcaps` records
`rw::wgpu::caps.dxtSupported`, and `needToReadBackTextures` is set and cleared as for
GL3. `main.cpp`'s version string gains "wgpu".

### 8.2 Colour filter and droplets

`postfx.cpp` and `screendroplets.cpp` get `RW_WGPU` branches. The WGSL translations of
`colourfilterVC.frag`, `contrast.frag` and `screenDroplet.frag` (sampling at `(u, v)`
where the GLSL samples `(u, 1-v)`, for the reason in §5.5) are raw string literals in
`renderers/wgpu/revc/files/src/extras/shaders/wgpu/*.wgsl.inc`, copied into the checkout
and `#include`d by the patched files, so the Rust tests can validate them; they are created with the driver's `im2DCreateShader` and selected with
`im2DSetOverride` (which call `rwgpu_im2d_shader_create` and `rwgpu_im2d_set_override`);
their uniforms become override parameters; droplets draw with the driver's
`im2DRenderIndexedPrimitiveUV2` and bind the screen copy on texture stage 1 with
`setTexture`.

### 8.3 Custom pipelines

`custompipes_wgpu.cpp` (new, ours) creates the vehicle, world, gloss and rim pipelines
with render callbacks that do what the GL3 ones do when the Neo options are off:
vehicle → matfx, world and gloss → default, rim → default or skin. `custompipes.cpp`
registers it under `RW_WGPU`. `NEW_RENDERER` is not ported: under `RW_WGPU` the patch
compiles out `re3.cpp`'s `NewRenderer` ini read, ini write and debug-menu toggle, so
`gbNewRenderer` keeps its initial `false` and a `NewRenderer` value in `reVC.ini` that a
GL3 build wrote is left as it was; and `custompipes_wgpu.cpp` defines
the `WorldRender` symbols the rest of reVC references: the three functions as empty
stubs, which are then never called, and the array `numBlendInsts`, which
`CRenderer::ClearForFrame` references (it is only called when `gbNewRenderer` is set,
but the reference must still link). `RwHelper.cpp`'s debug groups stay GL/D3D only.

## 9. Frame dumps and statistics (both renderers)

Both are part of the builds users get, not development-only patches, so the builds
measured in §10 differ from the shipped ones only by the capture patch, which changes
timing, the random seed and scripted input, not rendering. They do nothing unless their
environment variables are set (the cost is reading three environment variables once).

Environment variables read by both renderers:

- `REVC_FRAME_DUMP_DIR` — directory for dumps; dumping is off when unset.
- `REVC_FRAME_DUMP_FRAMES` — comma-separated frame numbers (1 = first presented frame);
  frame `N` is written as `frame-NNNNNN.png` (RGB, top row first) before it is presented.
- `REVC_FRAME_STATS` — when set to `N > 0`, every `N` presented frames one line goes to
  stderr: `frame-stats: frames=<total> avg_ms=<mean wall-clock time between presents over
  the last N frames> fps=<1000/avg_ms>`.

`wgpu`: in `rwgpu_present` (readback of the main target, `png` crate). `gl3`: a librw
patch in `renderers/gl3/librw/patches` reads the back buffer with `glReadPixels`
in `showRaster` before `glfwSwapBuffers`, flips it, and encodes it with librw's bundled
`lodepng`. Neither reads the screen through macOS, so no screen-recording permission is
needed.

## 10. Acceptance

All on the owner's Mac, comparing a GL3 build and a wgpu build of the same pins. Each
renderer has its own Builder `--home`, so its own copy of the game data, `txd.img` and
`CAPS.DAT` (G9), its own `reVC.ini` (G5) and its own `Applications` folder (the CLI
installs into `HOME/Applications` with `--home`), so `/Applications/reVC.app` is not
touched. Before each run the capture script writes the same settings into both
`reVC.ini` files — windowed, the same width and height, `NewRenderer` 0, and
`VSync`/`FrameLimiter` 0 for timing runs. A
warm-up run of each build performs the one-time texture conversion (one presented frame
per TXD slot), so the capture runs that follow start without it and their frame
numbers mean the same thing for both renderers.

**Capture harness.** `tools/capture/` holds a development-only reVC patch, never applied
by the Builder: its script runs the whole Builder pipeline for each renderer in that renderer's
`--home` (which copies the game data there and writes that home's `reVC.ini`), applies
the patch to the Builder's reVC checkout with `git apply`, rebuilds the build directory
with `cmake --build`, and starts the rebuilt `reVC.app` from the build directory with
`HOME` set to that renderer's home. The patch makes runs reproducible: with `REVC_CAPTURE=1` the game clock
advances a fixed 1/30 s per frame, the random seed is fixed, and
`REVC_CAPTURE_NEWGAME=<frame>` starts a new game at that frame the way the menu's
"Start Game" does, and `REVC_CAPTURE_SKIPCUTSCENE=<frame>` skips the running cutscene at
that frame the way the skip key does (`CCutsceneMgr`). The script then runs the scenes,
collects the dumps outside the repository, and computes the metrics. Scenes: the main
menu (no input); the start of a new game (the opening cutscene); the street scene
(frames after the opening cutscene has been skipped and the player is in control). The frame numbers
are fixed in the script and identical for both renderers.

| # | Criterion |
|---|---|
| A1 | `--renderer wgpu` with the development override builds and verifies `reVC.app` (Metal linked, OpenGL not); `--renderer gl3` still does. |
| A2 | Image parity on three scenes — main menu, start of a new game, a street scene — at the same frame numbers: per scene the mean absolute error over RGB channels (0–255), the share of pixels whose largest channel difference exceeds 16, and PSNR, plus side-by-side and difference images. Pass: main menu MAE < 1.0 and > 16 on < 0.5 % of pixels; in-game scenes MAE < 4.0 and > 16 on < 5 % of pixels. |
| A3 | Frame rate in the street scene, vsync and frame limiter off, same resolution: wgpu's mean frame time is no more than 10 % above GL3's. |
| A4 | Stability: a 5-minute wgpu run in the street scene without a crash or a wgpu validation error, with resident memory after minute 5 within 10 % of the value after minute 1. |
| A5 | `pytest` and `cargo test` pass. |

The default renderer becomes `wgpu` only when A1–A5 pass **and** `sources.lock` pins a
published library (not a placeholder): a default that needs a placeholder would break
every GUI build. Until then `DEFAULT_RENDERER` stays `gl3` and the report says which
condition is missing.

## 11. CI and releases

New job **wgpu renderer** (macOS): `cargo test`, `renderer/build-universal.sh` (deployment
targets 11.0 for arm64 and 10.15 for x86_64, the floors the Builder uses for the
dependencies; reVC's own x86_64 floor is 10.12, so the Intel link warns about a newer
deployment target, which is harmless because the Builder requires macOS 13), check both architectures with `lipo -archs`, upload the archive as an artifact. On tags
`rwgpu-v*` (added to the workflow's tag filter, which today matches only `v*`) a release
job publishes the archive as a release asset, created with `--latest=false` so that
`/releases/latest`, which the README sends users to for the Builder, keeps pointing at
the newest Builder release. The existing test, pins and package jobs
have no tag condition and also run for such a tag (harmless); the Builder `release` job
stays gated on `v*`. The job also compares `rustc --print native-static-libs` with
`renderer/link-libs.txt` (§6.1) and fails when the former has an entry the latter lacks. A second new job
builds reVC with `--renderer wgpu --rwgpu-dir` pointing at that archive's contents and
stops after `verify`. Publishing a renderer version: tag `rwgpu-vX.Y.Z`, wait for the
release, then put its URL and SHA-256 into `sources.lock` (dropping `placeholder`) in a
commit before tagging a Builder release `v*`.

## 12. Testing

- **Rust (no GPU):** render-state semantics (§5.3) including GL3's alpha interplay, GS
  alpha emulation and GL3's two-level sampling state (stage cache and per-texture state,
  including the addressing bug);
  sampler keys, including anisotropy clamped to 1 unless the filter is `LINEARMIPLINEAR`; pipeline-key mapping tables; fan → list conversion; raster format
  conversions (RGB8 → RGBA8, mip chains, BC level sizes); frame-dump configuration
  parsing and PNG encoding; uniform block layouts; WGSL validation with `naga`; the ABI
  checks of §4.4.
- **Python:** lock parsing of `renderer`, `platform` and `placeholder`; the network
  test skipping placeholders; reading `link-libs.txt` into `RWGPU_LINK_LIBS`; fetch filtering;
  the placeholder error; the override, including that fetch then skips the renderer
  library; `revc_build_for` per renderer; overlay application on a test git repository
  (copy + patches, twice); configure definitions per renderer; `verify_renderer`; CLI `--renderer`/`--rwgpu-dir`; overlays apply to the
  real cache checkout when one exists (skipped otherwise, like Phase 1's patch test).
- **End to end:** §10.

## 13. Implementation notes

- **M1 spike.** A GLFW window created with `GLFW_NO_API`, its `NSView` from
  `glfwGetCocoaView` and `Instance::create_surface_unsafe` work as designed: wgpu (through
  raw-window-metal) makes the view layer-backed and adds a `CAMetalLayer` that tracks the
  view's size and scale. On the owner's M3 Pro the adapter offers BC compression,
  clamp-to-border, `Fifo` and `Immediate`. The main menu rendered on the first run.
- **Window size.** reVC sizes its window from the framebuffer size it is told (G10), so
  the framebuffer reVC ends up with depends on which screen macOS puts the window on.
  The capture harness therefore moves the window to the primary monitor and gives it a
  fixed size (`REVC_CAPTURE_WINDOW`); both renderers then render 1920×1080 on the owner's
  Mac. The harness also accepts `REVC_CAPTURE_WEATHER=<frame>:<weather>` to force rain
  for the screen droplets.
- **Generic librw files.** `charset.cpp`, `engine.cpp`, `geoplg.cpp`, `raster.cpp`,
  `skin.cpp`, `matfx.cpp` and `texture.cpp` include `gl/rwgl3.h` directly instead of
  `rw.h`; the librw patch adds `wgpu/rwwgpu.h` next to it (§6.1).
- **Crate modules.** CPU conversions live in `convert.rs` and the WGSL sources in
  `shaders.rs` (§3 lists the final set).
- **Release library.** Built without debug information; the universal archive is about
  35 MB (100 MB static library).

- **Acceptance (2026-10-21, owner's M3 Pro, 1920×1080, capture harness).**
  - A1: both renderers build and verify through the Builder (`--renderer wgpu` with the
    development override, Metal linked and OpenGL not; `--renderer gl3`, OpenGL linked).
  - A2: main menu (frame 150) MAE 0.000, 0.000 % of pixels > 16; opening cutscene
    (frame 1500) MAE 0.007, 0.004 %; street scene (frame 4000) MAE 0.217, 0.420 %,
    PSNR 40.3 dB. A rain scene (forced weather, screen droplets) is within the in-game
    limits too (MAE 0.28–2.31, 0.42–1.79 %); the droplets' positions differ between
    runs. The remaining street-scene difference is slightly sharper texture sampling on
    some surfaces under wgpu; disabling anisotropy makes it worse (MAE 1.10).
  - A3: street scene without vsync or frame limiter, mean frame time over 16 windows of
    500 frames: GL3 2.653 ms, wgpu 2.746 ms (+3.5 %).
  - A4: 330 s, 43,200 frames, no crash, no wgpu error; resident memory 130 MiB at
    minute 1 and 140 MiB at minute 5 (+7.7 %).
  - A5: `pytest` and `cargo test` pass.
  - The default stays `gl3`: A1–A5 pass, but `sources.lock` pins a placeholder, so the
    second condition of §10 is not met until an `rwgpu-v0.1.0` release exists and is
    pinned.
