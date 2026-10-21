/*
 * librw WGPU platform: declarations shared by the driver's files.
 *
 * Part of reVC Builder (MIT licence). Adapted from librw's GL3 backend
 * (src/gl/rwgl3impl.h), Copyright (c) 2014 aap, MIT licence.
 */
#include <rwgpu.h>

namespace rw {
namespace wgpu {

#if RWGPU_DRIVER_ABI != RWGPU_ABI_VERSION
#error "this WGPU driver and the rwgpu.h it is compiled with are for different ABI versions"
#endif

struct DisplayMode
{
	GLFWvidmode mode;
	int32 depth;
	uint32 flags;
};

struct WgpuGlobals
{
	GLFWwindow **pWindow;
	GLFWwindow *window;

	GLFWmonitor *monitor;
	int numMonitors;
	int currentMonitor;

	DisplayMode *modes;
	int numModes;
	int currentMode;

	// for opening the window
	int winWidth, winHeight;
	const char *winTitle;

	// framebuffer size the renderer was last told about
	int fbWidth, fbHeight;
};
extern WgpuGlobals wgpuGlobals;

/* librw rasters bound to the texture stages, for GetRenderState(TEXTURERASTER). */
extern Raster *boundRasters[8];

/* RWGPU_RASTER_* flags of a raster (HAS_ALPHA; FORCE_OPAQUE for rasters without alpha). */
uint32 rasterFlags(Raster *raster);
/* The rwgpu texture of a texture or camera-texture raster, 0 otherwise. */
uint32 rasterTexture(Raster *raster);
/* Drops a raster that is being destroyed from the stage bookkeeping. */
void evictRaster(Raster *raster);

Raster *rasterCreate(Raster *raster);
uint8 *rasterLock(Raster*, int32 level, int32 lockMode);
void rasterUnlock(Raster*, int32);
int32 rasterNumLevels(Raster*);
bool32 imageFindRasterFormat(Image *img, int32 type,
	int32 *width, int32 *height, int32 *depth, int32 *format);
bool32 rasterFromImage(Raster *raster, Image *image);
Image *rasterToImage(Raster *raster);

void im2DRenderLine(void *vertices, int32 numVertices, int32 vert1, int32 vert2);
void im2DRenderTriangle(void *vertices, int32 numVertices, int32 vert1, int32 vert2, int32 vert3);
void im2DRenderPrimitive(PrimitiveType primType, void *vertices, int32 numVertices);
void im2DRenderIndexedPrimitive(PrimitiveType primType, void *vertices, int32 numVertices,
	void *indices, int32 numIndices);

void im3DTransform(void *vertices, int32 numVertices, Matrix *world, uint32 flags);
void im3DRenderPrimitive(PrimitiveType primType);
void im3DRenderIndexedPrimitive(PrimitiveType primType, void *indices, int32 numIndices);
void im3DEnd(void);

/* Instancing helpers shared by the default and skin pipelines (wgpupipe.cpp). */
void allocateVertices(Geometry *geo, InstanceDataHeader *header, uint32 layout);
void instanceCommon(Geometry *geo, InstanceDataHeader *header, bool32 reinstance);
void uploadVertices(InstanceDataHeader *header);

}
}
