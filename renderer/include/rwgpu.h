/*
 * rwgpu.h — C ABI of the rwgpu renderer (reVC Builder, MIT licence).
 *
 * The contract between librw's WGPU platform driver (C++) and the Rust renderer, see
 * docs/superpowers/specs/2026-10-21-phase2-wgpu-renderer-design.md, section 4.
 *
 * - Every call comes from the thread that called rwgpu_init.
 * - Objects are uint32_t handles; 0 means "none", except RwgpuTarget.color, where 0 is
 *   the main frame. A texture stage set to 0 samples opaque white.
 * - rwgpu_abi_version, rwgpu_last_error and rwgpu_init work at any time; any other call
 *   made without a successfully initialised renderer is ignored and returns 0.
 * - Enumerations that mirror librw keep librw's values.
 */
#ifndef RWGPU_H
#define RWGPU_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define RWGPU_ABI_VERSION 1

/* Render states (librw RenderState). TEXTURERASTER is set with rwgpu_set_raster. */
enum {
	RWGPU_TEXTURERASTER = 0,
	RWGPU_TEXTUREADDRESS = 1,
	RWGPU_TEXTUREADDRESSU = 2,
	RWGPU_TEXTUREADDRESSV = 3,
	RWGPU_TEXTUREFILTER = 4,
	RWGPU_VERTEXALPHA = 5,
	RWGPU_SRCBLEND = 6,
	RWGPU_DESTBLEND = 7,
	RWGPU_ZTESTENABLE = 8,
	RWGPU_ZWRITEENABLE = 9,
	RWGPU_FOGENABLE = 10,
	RWGPU_FOGCOLOR = 11,
	RWGPU_CULLMODE = 12,
	RWGPU_STENCILENABLE = 13,
	RWGPU_STENCILFAIL = 14,
	RWGPU_STENCILZFAIL = 15,
	RWGPU_STENCILPASS = 16,
	RWGPU_STENCILFUNCTION = 17,
	RWGPU_STENCILFUNCTIONREF = 18,
	RWGPU_STENCILFUNCTIONMASK = 19,
	RWGPU_STENCILFUNCTIONWRITEMASK = 20,
	RWGPU_ALPHATESTFUNC = 21,
	RWGPU_ALPHATESTREF = 22,
	RWGPU_GSALPHATEST = 23,
	RWGPU_GSALPHATESTREF = 24
};

/* Alpha test functions (librw AlphaTestFunc). */
enum { RWGPU_ALPHAALWAYS = 0, RWGPU_ALPHAGREATEREQUAL = 1, RWGPU_ALPHALESS = 2 };

/* Cull modes (librw CullMode). */
enum { RWGPU_CULLNONE = 1, RWGPU_CULLBACK = 2, RWGPU_CULLFRONT = 3 };

/* Blend functions (librw BlendFunction). */
enum {
	RWGPU_BLENDZERO = 1,
	RWGPU_BLENDONE = 2,
	RWGPU_BLENDSRCCOLOR = 3,
	RWGPU_BLENDINVSRCCOLOR = 4,
	RWGPU_BLENDSRCALPHA = 5,
	RWGPU_BLENDINVSRCALPHA = 6,
	RWGPU_BLENDDESTALPHA = 7,
	RWGPU_BLENDINVDESTALPHA = 8,
	RWGPU_BLENDDESTCOLOR = 9,
	RWGPU_BLENDINVDESTCOLOR = 10,
	RWGPU_BLENDSRCALPHASAT = 11
};

/* Stencil operations and functions (librw StencilOp, StencilFunc). */
enum {
	RWGPU_STENCILKEEP = 1, RWGPU_STENCILZERO = 2, RWGPU_STENCILREPLACE = 3,
	RWGPU_STENCILINCSAT = 4, RWGPU_STENCILDECSAT = 5, RWGPU_STENCILINVERT = 6,
	RWGPU_STENCILINC = 7, RWGPU_STENCILDEC = 8
};
enum {
	RWGPU_STENCILNEVER = 1, RWGPU_STENCILLESS = 2, RWGPU_STENCILEQUAL = 3,
	RWGPU_STENCILLESSEQUAL = 4, RWGPU_STENCILGREATER = 5, RWGPU_STENCILNOTEQUAL = 6,
	RWGPU_STENCILGREATEREQUAL = 7, RWGPU_STENCILALWAYS = 8
};

/* Texture filtering and addressing (librw Texture::FilterMode, Texture::Addressing). */
enum {
	RWGPU_FILTERNEAREST = 1, RWGPU_FILTERLINEAR = 2, RWGPU_FILTERMIPNEAREST = 3,
	RWGPU_FILTERMIPLINEAR = 4, RWGPU_FILTERLINEARMIPNEAREST = 5, RWGPU_FILTERLINEARMIPLINEAR = 6
};
enum { RWGPU_ADDRESSWRAP = 1, RWGPU_ADDRESSMIRROR = 2, RWGPU_ADDRESSCLAMP = 3, RWGPU_ADDRESSBORDER = 4 };

/* Primitive types (librw PrimitiveType). */
enum {
	RWGPU_PRIMTYPENONE = 0, RWGPU_PRIMTYPELINELIST = 1, RWGPU_PRIMTYPEPOLYLINE = 2,
	RWGPU_PRIMTYPETRILIST = 3, RWGPU_PRIMTYPETRISTRIP = 4, RWGPU_PRIMTYPETRIFAN = 5,
	RWGPU_PRIMTYPEPOINTLIST = 6
};

/* Camera clear flags (librw Camera::CLEAR*). */
enum { RWGPU_CLEARIMAGE = 1, RWGPU_CLEARZ = 2, RWGPU_CLEARSTENCIL = 4 };

/* Our own enumerations. */
enum { RWGPU_WINDOW_APPKIT = 1 };
enum { RWGPU_FORMAT_RGBA8 = 1, RWGPU_FORMAT_BC1 = 2, RWGPU_FORMAT_BC2 = 3, RWGPU_FORMAT_BC3 = 4 };
enum { RWGPU_SRC_NATIVE = 0, RWGPU_SRC_RGB8 = 1 };
enum { RWGPU_TEXTURE_RENDER_TARGET = 1, RWGPU_TEXTURE_AUTO_MIPMAP = 2 };
enum { RWGPU_RASTER_HAS_ALPHA = 1, RWGPU_RASTER_FORCE_OPAQUE = 2 };
enum { RWGPU_SHADER_DEFAULT = 0, RWGPU_SHADER_SKIN = 1, RWGPU_SHADER_MATFX_ENV = 2 };
enum { RWGPU_LAYOUT_MESH = 0, RWGPU_LAYOUT_SKIN = 1 };
enum { RWGPU_MAX_LIGHTS = 8, RWGPU_MAX_BONES = 64 };

typedef struct RwgpuWindowDesc {
	uint32_t kind;          /* RWGPU_WINDOW_* */
	uint32_t width, height; /* framebuffer pixels */
	uint32_t vsync;
	void *handle[4];        /* AppKit: handle[0] = NSView* */
} RwgpuWindowDesc;

typedef struct RwgpuStats {
	uint64_t frames;
	uint64_t validation_errors;
	uint32_t pipelines;
	uint32_t textures;
	uint32_t meshes;
	uint32_t reserved;
} RwgpuStats;

typedef struct RwgpuCaps {
	uint32_t bc_supported;
	float max_anisotropy;
	uint32_t max_texture_size;
	uint32_t reserved;
} RwgpuCaps;

typedef struct RwgpuTarget {
	uint32_t color;          /* texture handle; 0 = the main frame */
	uint32_t depth;          /* depth handle; 0 = none */
	int32_t x, y, w, h;      /* viewport in target pixels, top-left origin */
} RwgpuTarget;

typedef struct RwgpuLight {
	float type;              /* 1 directional, 2 point, 3 spot */
	float radius;
	float minus_cos_angle;
	float hard_spot;
	float position[4];
	float direction[4];
	float color[4];
} RwgpuLight;

typedef struct RwgpuIm2DVertex {
	float x, y, z, w;
	uint8_t r, g, b, a;
	float u, v;
} RwgpuIm2DVertex;

typedef struct RwgpuIm2DVertexUV2 {
	RwgpuIm2DVertex base;
	float u2, v2;
} RwgpuIm2DVertexUV2;

typedef struct RwgpuIm3DVertex {
	float pos[3];
	float normal[3];
	uint8_t r, g, b, a;
	float u, v;
} RwgpuIm3DVertex;

/* Mesh vertices: layout MESH is 44 bytes (pos[3] @0, normal[3] @12, rgba8 @24, uv0 @28,
 * uv1 @36); layout SKIN is 64 bytes (MESH + weights[4] @44, uint8 indices[4] @60). */
#define RWGPU_MESH_STRIDE 44
#define RWGPU_SKIN_STRIDE 64

/* Matrices are 16 floats in librw RawMatrix order (right, up, at, pos columns). */

/* Lifecycle */
uint32_t rwgpu_abi_version(void);
uint32_t rwgpu_init(const RwgpuWindowDesc *desc);
void rwgpu_shutdown(void);
const char *rwgpu_last_error(void);
void rwgpu_get_caps(RwgpuCaps *out);

/* Frame */
void rwgpu_resize(uint32_t width, uint32_t height);
void rwgpu_present(uint32_t vsync);
void rwgpu_get_stats(RwgpuStats *out);

/* Cameras and targets */
void rwgpu_begin_camera(const RwgpuTarget *target, const float view[16], const float proj[16],
                        float fog_start, float fog_end, const float gl_depth_row[2]);
void rwgpu_end_camera(void);
void rwgpu_clear(const RwgpuTarget *target, const float rgba[4], uint32_t mode);
void rwgpu_copy_main_to_texture(uint32_t tex, int32_t dst_x, int32_t dst_y, uint32_t width, uint32_t height);
uint32_t rwgpu_read_main(void *rgb, uint32_t size);

/* Textures */
uint32_t rwgpu_texture_create(uint32_t format, uint32_t width, uint32_t height, uint32_t levels, uint32_t flags);
uint32_t rwgpu_texture_upload(uint32_t tex, uint32_t level, uint32_t src_format, const void *data, uint32_t size);
uint32_t rwgpu_texture_read(uint32_t tex, uint32_t level, void *out, uint32_t size);
void rwgpu_texture_destroy(uint32_t tex);
uint32_t rwgpu_depth_create(uint32_t width, uint32_t height);
void rwgpu_depth_destroy(uint32_t depth);

/* Render state */
void rwgpu_set_render_state(uint32_t state, uint32_t value);
uint32_t rwgpu_get_render_state(uint32_t state);
void rwgpu_set_raster(uint32_t stage, uint32_t tex, uint32_t flags);
void rwgpu_set_texture(uint32_t stage, uint32_t tex, uint32_t flags, uint32_t filter,
                       uint32_t address_u, uint32_t address_v, uint32_t max_anisotropy);

/* Per object / mesh */
void rwgpu_set_world_matrix(const float m[16]);
void rwgpu_set_lights(const float ambient[4], const RwgpuLight *lights, uint32_t count);
void rwgpu_set_material(const float color[4], const float surface_props[4]);
void rwgpu_set_bones(const float *matrices, uint32_t count);
void rwgpu_set_matfx_env(const float tex_matrix[16], const float fx_params[4],
                         const float color_clamp[4], const float env_color[4]);

/* Meshes */
uint32_t rwgpu_mesh_create(uint32_t layout, const void *vertices, uint32_t vertex_bytes,
                           const uint16_t *indices, uint32_t index_count);
void rwgpu_mesh_update_vertices(uint32_t mesh, const void *vertices, uint32_t vertex_bytes);
void rwgpu_mesh_destroy(uint32_t mesh);
void rwgpu_draw_mesh(uint32_t mesh, uint32_t shader, uint32_t prim, uint32_t first_index, uint32_t index_count);

/* Immediate mode */
void rwgpu_im2d_draw(uint32_t prim, const RwgpuIm2DVertex *vertices, uint32_t num_vertices,
                     const uint16_t *indices, uint32_t num_indices);
void rwgpu_im2d_uv2_draw(uint32_t prim, const RwgpuIm2DVertexUV2 *vertices, uint32_t num_vertices,
                         const uint16_t *indices, uint32_t num_indices);
uint32_t rwgpu_im2d_shader_create(const char *wgsl);
void rwgpu_im2d_set_override(uint32_t shader, const float params[16]);
void rwgpu_im3d_transform(const RwgpuIm3DVertex *vertices, uint32_t num_vertices, const float world[16], uint32_t lit);
void rwgpu_im3d_draw(uint32_t prim, const uint16_t *indices, uint32_t num_indices);
void rwgpu_im3d_end(void);

#ifdef __cplusplus
}
#endif

#endif /* RWGPU_H */
