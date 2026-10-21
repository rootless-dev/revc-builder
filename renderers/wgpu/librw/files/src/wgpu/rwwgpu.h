/*
 * librw WGPU platform: public declarations.
 *
 * Part of reVC Builder (MIT licence). Adapted from librw's GL3 backend (src/gl/rwgl3.h),
 * Copyright (c) 2014 aap, MIT licence. Rendering is done by the rwgpu Rust library
 * (rwgpu.h); this header does not depend on it.
 */
#ifdef RW_WGPU
#ifndef GLFW_INCLUDE_NONE
#define GLFW_INCLUDE_NONE
#endif
#include <GLFW/glfw3.h>
#endif

namespace rw {

#ifdef RW_WGPU
struct EngineOpenParams
{
	GLFWwindow **window;
	int width, height;
	const char *windowtitle;
};
#endif

namespace wgpu {

/* The rwgpu ABI version this driver was written for (design §4.1). */
#define RWGPU_DRIVER_ABI 1

void registerPlatformPlugins(void);

extern Device renderdevice;

struct InstanceData
{
	uint32    numIndex;
	uint32    minVert;
	int32     numVertices;
	Material *material;
	bool32    vertexAlpha;
	uint32    offset;	// first index in the mesh's index buffer
};

struct InstanceDataHeader : rw::InstanceDataHeader
{
	uint32      serialNumber;
	uint32      numMeshes;
	uint16     *indexBuffer;
	uint32      primType;	// librw PrimitiveType
	uint8      *vertexBuffer;
	uint32      layout;	// RWGPU_LAYOUT_*
	uint32      stride;
	uint32      totalNumIndex;
	uint32      totalNumVertex;
	uint32      mesh;	// rwgpu mesh handle

	InstanceData *inst;
};

/* Mesh vertex layouts (design §4.2). */
enum { LAYOUT_MESH = 0, LAYOUT_SKIN = 1 };
enum { SHADER_DEFAULT = 0, SHADER_SKIN = 1, SHADER_MATFX_ENV = 2 };

#ifdef RW_WGPU

struct Im3DVertex
{
	V3d     position;
	V3d     normal;		// librw extension
	uint8   r, g, b, a;
	float32 u, v;

	void setX(float32 x) { this->position.x = x; }
	void setY(float32 y) { this->position.y = y; }
	void setZ(float32 z) { this->position.z = z; }
	void setNormalX(float32 x) { this->normal.x = x; }
	void setNormalY(float32 y) { this->normal.y = y; }
	void setNormalZ(float32 z) { this->normal.z = z; }
	void setColor(uint8 r, uint8 g, uint8 b, uint8 a) {
		this->r = r; this->g = g; this->b = b; this->a = a; }
	void setU(float32 u) { this->u = u; }
	void setV(float32 v) { this->v = v; }

	float getX(void) { return this->position.x; }
	float getY(void) { return this->position.y; }
	float getZ(void) { return this->position.z; }
	float getNormalX(void) { return this->normal.x; }
	float getNormalY(void) { return this->normal.y; }
	float getNormalZ(void) { return this->normal.z; }
	RGBA getColor(void) { return makeRGBA(this->r, this->g, this->b, this->a); }
	float getU(void) { return this->u; }
	float getV(void) { return this->v; }
};
extern RGBA im3dMaterialColor;
extern SurfaceProperties im3dSurfaceProps;

struct Im2DVertex
{
	float32 x, y, z, w;
	uint8   r, g, b, a;
	float32 u, v;

	void setScreenX(float32 x) { this->x = x; }
	void setScreenY(float32 y) { this->y = y; }
	void setScreenZ(float32 z) { this->z = z; }
	void setCameraZ(float32 z) { this->w = z; }
	void setRecipCameraZ(float32 recipz) { this->w = 1.0f/recipz; }
	void setColor(uint8 r, uint8 g, uint8 b, uint8 a) {
		this->r = r; this->g = g; this->b = b; this->a = a; }
	void setU(float32 u, float /*recipz*/) { this->u = u; }
	void setV(float32 v, float /*recipz*/) { this->v = v; }

	float getScreenX(void) { return this->x; }
	float getScreenY(void) { return this->y; }
	float getScreenZ(void) { return this->z; }
	float getCameraZ(void) { return this->w; }
	float getRecipCameraZ(void) { return 1.0f/this->w; }
	RGBA getColor(void) { return makeRGBA(this->r, this->g, this->b, this->a); }
	float getU(void) { return this->u; }
	float getV(void) { return this->v; }
};

/* An Im2D vertex with a second set of texture coordinates (reVC's screen droplets). */
struct Im2DVertexUV2 : Im2DVertex
{
	float32 u2, v2;
};

// per Object
void setWorldMatrix(Matrix*);
int32 setLights(WorldLights *lightData);

// per Mesh
void setTexture(int32 stage, Texture *tex);
void setMaterial(const RGBA &color, const SurfaceProperties &surfaceprops, float extraSurfProp = 0.0f);
inline void setMaterial(uint32 flags, const RGBA &color, const SurfaceProperties &surfaceprops, float extraSurfProp = 0.0f)
{
	static RGBA white = { 255, 255, 255, 255 };
	if(flags & Geometry::MODULATE)
		setMaterial(color, surfaceprops, extraSurfProp);
	else
		setMaterial(white, surfaceprops, extraSurfProp);
}

/* Im2D override shaders (design §4.3): WGSL defining fs_main(in: Im2DOut). */
uint32 im2DCreateShader(const char *wgsl);
/* shader 0 restores the built-in fragment stage; params are 16 floats or nil. */
void im2DSetOverride(uint32 shader, const float32 *params);
void im2DRenderIndexedPrimitiveUV2(PrimitiveType primType, Im2DVertexUV2 *vertices, int32 numVertices,
	void *indices, int32 numIndices);

#endif

class ObjPipeline : public rw::ObjPipeline
{
public:
	void init(void);
	static ObjPipeline *create(void);

	void (*instanceCB)(Geometry *geo, InstanceDataHeader *header, bool32 reinstance);
	void (*uninstanceCB)(Geometry *geo, InstanceDataHeader *header);
	void (*renderCB)(Atomic *atomic, InstanceDataHeader *header);
};

void defaultInstanceCB(Geometry *geo, InstanceDataHeader *header, bool32 reinstance);
void defaultUninstanceCB(Geometry *geo, InstanceDataHeader *header);
void defaultRenderCB(Atomic *atomic, InstanceDataHeader *header);
int32 lightingCB(Atomic *atomic);
int32 lightingCB(void);

/* Draws one mesh of an instanced geometry, with the PS2 alpha-test emulation when
 * GSALPHATEST is on (in rwgpu). */
void drawInst(InstanceDataHeader *header, InstanceData *inst, uint32 shader = SHADER_DEFAULT);

void *destroyNativeData(void *object, int32, int32);

ObjPipeline *makeDefaultPipeline(void);

void initMatFX(void);
ObjPipeline *makeMatFXPipeline(void);
void matfxRenderCB(Atomic *atomic, InstanceDataHeader *header);

void initSkin(void);
ObjPipeline *makeSkinPipeline(void);
void skinInstanceCB(Geometry *geo, InstanceDataHeader *header, bool32 reinstance);
void skinRenderCB(Atomic *atomic, InstanceDataHeader *header);
void uploadSkinMatrices(Atomic *atomic);

// Native Texture and Raster

struct WgpuRaster
{
	uint32 texture;		// rwgpu texture handle (textures and camera textures)
	uint32 depth;		// rwgpu depth handle (z-buffers)
	int32 bpp;		// bytes per pixel of the CPU layout (top-down)
	bool isCompressed;
	bool hasAlpha;
	bool autogenMipmap;
	int8 numLevels;		// levels librw may lock
	int32 compression;	// 0, or 1/3/5 for DXT1/3/5
	RasterLevels *backingStore;	// CPU copy while needToReadBackTextures is set
};

struct WgpuCaps
{
	bool dxtSupported;
	float maxAnisotropy;
};
extern WgpuCaps caps;
// Set by reVC while it writes txd.img, so compressed levels can be read back cheaply.
extern bool32 needToReadBackTextures;

void allocateDXT(Raster *raster, int32 dxt, int32 numLevels, bool32 hasAlpha);

Texture *readNativeTexture(Stream *stream);
void writeNativeTexture(Texture *tex, Stream *stream);
uint32 getSizeNativeTexture(Texture *tex);

extern int32 nativeRasterOffset;
void registerNativeRaster(void);
#define GETWGPURASTEREXT(raster) PLUGINOFFSET(rw::wgpu::WgpuRaster, raster, rw::wgpu::nativeRasterOffset)

}
}
