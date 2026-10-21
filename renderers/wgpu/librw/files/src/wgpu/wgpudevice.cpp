/*
 * librw WGPU platform: the render device (window, cameras, render states, frames).
 *
 * Part of reVC Builder (MIT licence). Adapted from librw's GL3 backend
 * (src/gl/gl3device.cpp), Copyright (c) 2014 aap, MIT licence.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>

#include "../rwbase.h"
#include "../rwerror.h"
#include "../rwplg.h"
#include "../rwrender.h"
#include "../rwengine.h"
#include "../rwpipeline.h"
#include "../rwobjects.h"

#ifdef RW_WGPU

#include "rwwgpu.h"
#include "rwwgpuimpl.h"

#ifdef __APPLE__
#define GLFW_EXPOSE_NATIVE_COCOA
#include <GLFW/glfw3native.h>
#endif

#define PLUGIN_ID 0

namespace rw {
namespace wgpu {

// The C ABI reuses librw's numbering (design §4.4).
static_assert(RWGPU_TEXTURERASTER == TEXTURERASTER && RWGPU_GSALPHATESTREF == GSALPHATESTREF, "render states");
static_assert(RWGPU_VERTEXALPHA == VERTEXALPHA && RWGPU_CULLMODE == CULLMODE && RWGPU_ALPHATESTREF == ALPHATESTREF, "render states");
static_assert(RWGPU_STENCILFUNCTIONWRITEMASK == STENCILFUNCTIONWRITEMASK, "render states");
static_assert(RWGPU_ALPHAALWAYS == ALPHAALWAYS && RWGPU_ALPHALESS == ALPHALESS, "alpha test functions");
static_assert(RWGPU_CULLNONE == CULLNONE && RWGPU_CULLFRONT == CULLFRONT, "cull modes");
static_assert(RWGPU_BLENDZERO == BLENDZERO && RWGPU_BLENDSRCALPHASAT == BLENDSRCALPHASAT, "blend functions");
static_assert(RWGPU_STENCILKEEP == STENCILKEEP && RWGPU_STENCILDEC == STENCILDEC, "stencil operations");
static_assert(RWGPU_STENCILNEVER == STENCILNEVER && RWGPU_STENCILALWAYS == STENCILALWAYS, "stencil functions");
static_assert(RWGPU_FILTERNEAREST == Texture::NEAREST && RWGPU_FILTERLINEARMIPLINEAR == Texture::LINEARMIPLINEAR, "filters");
static_assert(RWGPU_ADDRESSWRAP == Texture::WRAP && RWGPU_ADDRESSBORDER == Texture::BORDER, "addressing");
static_assert(RWGPU_PRIMTYPELINELIST == PRIMTYPELINELIST && RWGPU_PRIMTYPEPOINTLIST == PRIMTYPEPOINTLIST, "primitives");
static_assert(RWGPU_CLEARIMAGE == Camera::CLEARIMAGE && RWGPU_CLEARSTENCIL == Camera::CLEARSTENCIL, "clear flags");
static_assert(RWGPU_TEXTUREADDRESS == TEXTUREADDRESS && RWGPU_TEXTUREADDRESSU == TEXTUREADDRESSU &&
	RWGPU_TEXTUREADDRESSV == TEXTUREADDRESSV && RWGPU_TEXTUREFILTER == TEXTUREFILTER &&
	RWGPU_SRCBLEND == SRCBLEND && RWGPU_DESTBLEND == DESTBLEND && RWGPU_ZTESTENABLE == ZTESTENABLE &&
	RWGPU_ZWRITEENABLE == ZWRITEENABLE && RWGPU_FOGENABLE == FOGENABLE && RWGPU_FOGCOLOR == FOGCOLOR &&
	RWGPU_STENCILENABLE == STENCILENABLE && RWGPU_STENCILFAIL == STENCILFAIL &&
	RWGPU_STENCILZFAIL == STENCILZFAIL && RWGPU_STENCILPASS == STENCILPASS &&
	RWGPU_STENCILFUNCTION == STENCILFUNCTION && RWGPU_STENCILFUNCTIONREF == STENCILFUNCTIONREF &&
	RWGPU_STENCILFUNCTIONMASK == STENCILFUNCTIONMASK && RWGPU_ALPHATESTFUNC == ALPHATESTFUNC &&
	RWGPU_GSALPHATEST == GSALPHATEST, "render states");
static_assert(RWGPU_ALPHAGREATEREQUAL == ALPHAGREATEREQUAL && RWGPU_CULLBACK == CULLBACK, "alpha test, cull");
static_assert(RWGPU_BLENDONE == BLENDONE && RWGPU_BLENDSRCCOLOR == BLENDSRCCOLOR &&
	RWGPU_BLENDINVSRCCOLOR == BLENDINVSRCCOLOR && RWGPU_BLENDSRCALPHA == BLENDSRCALPHA &&
	RWGPU_BLENDINVSRCALPHA == BLENDINVSRCALPHA && RWGPU_BLENDDESTALPHA == BLENDDESTALPHA &&
	RWGPU_BLENDINVDESTALPHA == BLENDINVDESTALPHA && RWGPU_BLENDDESTCOLOR == BLENDDESTCOLOR &&
	RWGPU_BLENDINVDESTCOLOR == BLENDINVDESTCOLOR, "blend functions");
static_assert(RWGPU_STENCILZERO == STENCILZERO && RWGPU_STENCILREPLACE == STENCILREPLACE &&
	RWGPU_STENCILINCSAT == STENCILINCSAT && RWGPU_STENCILDECSAT == STENCILDECSAT &&
	RWGPU_STENCILINVERT == STENCILINVERT && RWGPU_STENCILINC == STENCILINC, "stencil operations");
static_assert(RWGPU_STENCILLESS == STENCILLESS && RWGPU_STENCILEQUAL == STENCILEQUAL &&
	RWGPU_STENCILLESSEQUAL == STENCILLESSEQUAL && RWGPU_STENCILGREATER == STENCILGREATER &&
	RWGPU_STENCILNOTEQUAL == STENCILNOTEQUAL && RWGPU_STENCILGREATEREQUAL == STENCILGREATEREQUAL, "stencil functions");
static_assert(RWGPU_FILTERLINEAR == Texture::LINEAR && RWGPU_FILTERMIPNEAREST == Texture::MIPNEAREST &&
	RWGPU_FILTERMIPLINEAR == Texture::MIPLINEAR && RWGPU_FILTERLINEARMIPNEAREST == Texture::LINEARMIPNEAREST &&
	RWGPU_ADDRESSMIRROR == Texture::MIRROR && RWGPU_ADDRESSCLAMP == Texture::CLAMP, "filters and addressing");
static_assert(RWGPU_PRIMTYPENONE == PRIMTYPENONE && RWGPU_PRIMTYPEPOLYLINE == PRIMTYPEPOLYLINE &&
	RWGPU_PRIMTYPETRILIST == PRIMTYPETRILIST && RWGPU_PRIMTYPETRISTRIP == PRIMTYPETRISTRIP &&
	RWGPU_PRIMTYPETRIFAN == PRIMTYPETRIFAN && RWGPU_CLEARZ == Camera::CLEARZ, "primitives, clear flags");
static_assert(sizeof(Im2DVertex) == sizeof(RwgpuIm2DVertex) && sizeof(Im3DVertex) == sizeof(RwgpuIm3DVertex), "vertices");
static_assert(sizeof(Im2DVertexUV2) == sizeof(RwgpuIm2DVertexUV2), "vertices");

WgpuGlobals wgpuGlobals;
WgpuCaps caps;
bool32 needToReadBackTextures;
Raster *boundRasters[8];

uint32
rasterFlags(Raster *raster)
{
	if(raster == nil)
		return 0;
	WgpuRaster *natras = GETWGPURASTEREXT(raster);
	// Without alpha GL3 stores RGB (or RGB DXT1), so sampled alpha is 1.
	return natras->hasAlpha ? RWGPU_RASTER_HAS_ALPHA : RWGPU_RASTER_FORCE_OPAQUE;
}

uint32
rasterTexture(Raster *raster)
{
	if(raster == nil)
		return 0;
	return GETWGPURASTEREXT(raster)->texture;
}

void
evictRaster(Raster *raster)
{
	for(int i = 0; i < 8; i++)
		if(boundRasters[i] == raster)
			boundRasters[i] = nil;
}

void
setTexture(int32 stage, Texture *tex)
{
	if(stage < 0 || stage >= 8)
		return;
	if(tex == nil || tex->raster == nil){
		boundRasters[stage] = nil;
		rwgpu_set_texture(stage, 0, 0, 0, 0, 0, 1);
		return;
	}
	boundRasters[stage] = tex->raster;
	rwgpu_set_texture(stage, rasterTexture(tex->raster), rasterFlags(tex->raster),
		tex->getFilter(), tex->getAddressU(), tex->getAddressV(), tex->getMaxAnisotropy());
}

static void
setRenderState(int32 state, void *pvalue)
{
	if(state == TEXTURERASTER){
		Raster *raster = (Raster*)pvalue;
		boundRasters[0] = raster;
		rwgpu_set_raster(0, rasterTexture(raster), rasterFlags(raster));
		return;
	}
	rwgpu_set_render_state(state, (uint32)(uintptr)pvalue);
}

static void*
getRenderState(int32 state)
{
	if(state == TEXTURERASTER)
		return boundRasters[0];
	return (void*)(uintptr)rwgpu_get_render_state(state);
}

void
setWorldMatrix(Matrix *mat)
{
	RawMatrix world;
	convMatrix(&world, mat);
	rwgpu_set_world_matrix((float*)&world);
}

int32
setLights(WorldLights *lightData)
{
	RwgpuLight lights[RWGPU_MAX_LIGHTS];
	int32 i, n, bits;
	Light *l;

	memset(lights, 0, sizeof(lights));
	bits = 0;
	if(lightData->numAmbients)
		bits |= 8;	// VSLIGHT_AMBIENT

	n = 0;
	for(i = 0; i < lightData->numDirectionals && n < RWGPU_MAX_LIGHTS; i++){
		l = lightData->directionals[i];
		lights[n].type = 1.0f;
		memcpy(lights[n].color, &l->color, sizeof(RGBAf));
		memcpy(lights[n].direction, &l->getFrame()->getLTM()->at, sizeof(V3d));
		bits |= 1;
		n++;
	}
	for(i = 0; i < lightData->numLocals && n < RWGPU_MAX_LIGHTS; i++){
		l = lightData->locals[i];
		switch(l->getType()){
		case Light::POINT:
			lights[n].type = 2.0f;
			lights[n].radius = l->radius;
			memcpy(lights[n].color, &l->color, sizeof(RGBAf));
			memcpy(lights[n].position, &l->getFrame()->getLTM()->pos, sizeof(V3d));
			bits |= 2;
			n++;
			break;
		case Light::SPOT:
		case Light::SOFTSPOT:
			lights[n].type = 3.0f;
			lights[n].minus_cos_angle = l->minusCosAngle;
			lights[n].radius = l->radius;
			memcpy(lights[n].color, &l->color, sizeof(RGBAf));
			memcpy(lights[n].position, &l->getFrame()->getLTM()->pos, sizeof(V3d));
			memcpy(lights[n].direction, &l->getFrame()->getLTM()->at, sizeof(V3d));
			// lower bound of falloff
			lights[n].hard_spot = l->getType() == Light::SOFTSPOT ? 0.0f : 1.0f;
			bits |= 4;
			n++;
			break;
		}
	}
	rwgpu_set_lights((float*)&lightData->ambient, lights, n);
	return bits;
}

void
setMaterial(const RGBA &color, const SurfaceProperties &surfaceprops, float extraSurfProp)
{
	RGBAf col;
	convColor(&col, &color);
	float surfProps[4];
	surfProps[0] = surfaceprops.ambient;
	surfProps[1] = surfaceprops.specular;
	surfProps[2] = surfaceprops.diffuse;
	surfProps[3] = extraSurfProp;
	rwgpu_set_material((float*)&col, surfProps);
}

/* The size of the window's framebuffer, telling the renderer when it changed. */
static void
updateFramebufferSize(void)
{
	int w, h;
	glfwGetFramebufferSize(wgpuGlobals.window, &w, &h);
	if(w > 0 && h > 0 && (w != wgpuGlobals.fbWidth || h != wgpuGlobals.fbHeight)){
		wgpuGlobals.fbWidth = w;
		wgpuGlobals.fbHeight = h;
		rwgpu_resize(w, h);
	}
}

/* Colour and depth target and viewport of a camera (GL3's setFrameBuffer and
 * getFramebufferRect, with a top-left origin). */
static void
getTarget(Camera *cam, RwgpuTarget *t)
{
	Raster *fb = cam->frameBuffer;
	Raster *parent = fb->parent;
	int32 w, h;

	if(parent->type == Raster::CAMERA){
		updateFramebufferSize();
		t->color = 0;
		w = wgpuGlobals.fbWidth;
		h = wgpuGlobals.fbHeight;
	}else{
		t->color = GETWGPURASTEREXT(parent)->texture;
		w = parent->width;
		h = parent->height;
	}
	t->depth = cam->zBuffer ? GETWGPURASTEREXT(cam->zBuffer->parent)->depth : 0;
	if(fb != parent){
		t->x = fb->offsetX;
		t->y = fb->offsetY;
		t->w = fb->width;
		t->h = fb->height;
	}else{
		t->x = 0;
		t->y = 0;
		t->w = w;
		t->h = h;
	}
}

static void
beginUpdate(Camera *cam)
{
	float view[16], proj[16], glDepth[2];
	// View Matrix
	Matrix inv;
	Matrix::invert(&inv, cam->getFrame()->getLTM());
	// Since we're looking into positive Z,
	// flip X to ge a left handed view space.
	view[0]  = -inv.right.x;
	view[1]  =  inv.right.y;
	view[2]  =  inv.right.z;
	view[3]  =  0.0f;
	view[4]  = -inv.up.x;
	view[5]  =  inv.up.y;
	view[6]  =  inv.up.z;
	view[7]  =  0.0f;
	view[8]  =  -inv.at.x;
	view[9]  =   inv.at.y;
	view[10] =  inv.at.z;
	view[11] =  0.0f;
	view[12] = -inv.pos.x;
	view[13] =  inv.pos.y;
	view[14] =  inv.pos.z;
	view[15] =  1.0f;
	memcpy(&cam->devView, &view, sizeof(RawMatrix));

	// Projection Matrix: depth in [0, 1], as librw's D3D backend.
	float32 invwx = 1.0f/cam->viewWindow.x;
	float32 invwy = 1.0f/cam->viewWindow.y;
	float32 invz = 1.0f/(cam->farPlane-cam->nearPlane);

	proj[0] = invwx;
	proj[1] = 0.0f;
	proj[2] = 0.0f;
	proj[3] = 0.0f;

	proj[4] = 0.0f;
	proj[5] = invwy;
	proj[6] = 0.0f;
	proj[7] = 0.0f;

	proj[8] = cam->viewOffset.x*invwx;
	proj[9] = cam->viewOffset.y*invwy;
	proj[12] = -proj[8];
	proj[13] = -proj[9];
	if(cam->projection == Camera::PERSPECTIVE){
		proj[10] = cam->farPlane*invz;
		proj[11] = 1.0f;
		proj[15] = 0.0f;
		// GL3's depth row, for its skin shader's fog (design §5.5)
		glDepth[0] = (cam->farPlane+cam->nearPlane)*invz;
		glDepth[1] = -2.0f*cam->nearPlane*cam->farPlane*invz;
	}else{
		proj[10] = invz;
		proj[11] = 0.0f;
		proj[15] = 1.0f;
		glDepth[0] = 2.0f*invz;
		glDepth[1] = -(cam->farPlane+cam->nearPlane)*invz;
	}
	proj[14] = -cam->nearPlane*proj[10];
	memcpy(&cam->devProj, &proj, sizeof(RawMatrix));

	RwgpuTarget target;
	getTarget(cam, &target);
	rwgpu_begin_camera(&target, view, proj, cam->fogPlane, cam->farPlane, glDepth);
}

static void
endUpdate(Camera *cam)
{
	rwgpu_end_camera();
}

static void
clearCamera(Camera *cam, RGBA *col, uint32 mode)
{
	RGBAf colf;
	RwgpuTarget target;
	convColor(&colf, col);
	getTarget(cam, &target);
	rwgpu_clear(&target, (float*)&colf, mode);
}

static void
showRaster(Raster *raster, uint32 flags)
{
	updateFramebufferSize();
	rwgpu_present(flags & Raster::FLIPWAITVSYNCH ? 1 : 0);
}

static bool32
rasterRenderFast(Raster *raster, int32 x, int32 y)
{
	Raster *src = raster;
	Raster *dst = Raster::getCurrentContext();

	switch(dst->type){
	case Raster::NORMAL:
	case Raster::TEXTURE:
	case Raster::CAMERATEXTURE:
		switch(src->type){
		case Raster::CAMERA:
			rwgpu_copy_main_to_texture(rasterTexture(dst), x, y, src->width, src->height);
			return 1;
		}
		break;
	}
	return 0;
}

static void
addVideoMode(const GLFWvidmode *mode)
{
	int i;

	for(i = 1; i < wgpuGlobals.numModes; i++){
		if(wgpuGlobals.modes[i].mode.width == mode->width &&
		   wgpuGlobals.modes[i].mode.height == mode->height &&
		   wgpuGlobals.modes[i].mode.redBits == mode->redBits &&
		   wgpuGlobals.modes[i].mode.greenBits == mode->greenBits &&
		   wgpuGlobals.modes[i].mode.blueBits == mode->blueBits){
			// had this mode already, remember highest refresh rate
			if(mode->refreshRate > wgpuGlobals.modes[i].mode.refreshRate)
				wgpuGlobals.modes[i].mode.refreshRate = mode->refreshRate;
			return;
		}
	}

	// none found, add
	wgpuGlobals.modes[wgpuGlobals.numModes].mode = *mode;
	wgpuGlobals.modes[wgpuGlobals.numModes].flags = VIDEOMODEEXCLUSIVE;
	wgpuGlobals.numModes++;
}

static void
makeVideoModeList(GLFWmonitor *monitor)
{
	int i, num;
	const GLFWvidmode *modes;

	modes = glfwGetVideoModes(monitor, &num);
	rwFree(wgpuGlobals.modes);
	wgpuGlobals.modes = rwNewT(DisplayMode, num+1, ID_DRIVER | MEMDUR_EVENT);

	wgpuGlobals.modes[0].mode = *glfwGetVideoMode(monitor);
	wgpuGlobals.modes[0].flags = 0;
	wgpuGlobals.numModes = 1;

	for(i = 0; i < num; i++)
		addVideoMode(&modes[i]);

	for(i = 0; i < wgpuGlobals.numModes; i++){
		num = wgpuGlobals.modes[i].mode.redBits +
			wgpuGlobals.modes[i].mode.greenBits +
			wgpuGlobals.modes[i].mode.blueBits;
		// set depth to power of two
		for(wgpuGlobals.modes[i].depth = 1; wgpuGlobals.modes[i].depth < num; wgpuGlobals.modes[i].depth <<= 1);
	}
}

static void
glfwerr(int error, const char *desc)
{
	fprintf(stderr, "GLFW Error: %s\n", desc);
}

static int
openGLFW(EngineOpenParams *openparams)
{
	wgpuGlobals.winWidth = openparams->width;
	wgpuGlobals.winHeight = openparams->height;
	wgpuGlobals.winTitle = openparams->windowtitle;
	wgpuGlobals.pWindow = openparams->window;

	memset(&caps, 0, sizeof(caps));

	glfwSetErrorCallback(glfwerr);
	if(!glfwInit()){
		RWERROR((ERR_GENERAL, "glfwInit() failed"));
		return 0;
	}

	wgpuGlobals.monitor = glfwGetMonitors(&wgpuGlobals.numMonitors)[0];

	makeVideoModeList(wgpuGlobals.monitor);

	return 1;
}

static int
closeGLFW(void)
{
	glfwTerminate();
	return 1;
}

static int
startGLFW(void)
{
	GLFWwindow *win;
	DisplayMode *mode;

	if(rwgpu_abi_version() != RWGPU_ABI_VERSION){
		fprintf(stderr, "rwgpu: the renderer library has ABI %u, this build needs %u\n",
			rwgpu_abi_version(), (unsigned)RWGPU_ABI_VERSION);
		RWERROR((ERR_GENERAL, "rwgpu ABI mismatch"));
		return 0;
	}

	mode = &wgpuGlobals.modes[wgpuGlobals.currentMode];

	glfwWindowHint(GLFW_CLIENT_API, GLFW_NO_API);
	glfwWindowHint(GLFW_REFRESH_RATE, mode->mode.refreshRate);

	if(mode->flags & VIDEOMODEEXCLUSIVE)
		win = glfwCreateWindow(mode->mode.width, mode->mode.height, wgpuGlobals.winTitle, wgpuGlobals.monitor, nil);
	else
		win = glfwCreateWindow(wgpuGlobals.winWidth, wgpuGlobals.winHeight, wgpuGlobals.winTitle, nil, nil);
	if(win == nil){
		RWERROR((ERR_GENERAL, "glfwCreateWindow() failed"));
		return 0;
	}

	int fbw, fbh;
	glfwGetFramebufferSize(win, &fbw, &fbh);

	RwgpuWindowDesc desc;
	memset(&desc, 0, sizeof(desc));
#ifdef __APPLE__
	desc.kind = RWGPU_WINDOW_APPKIT;
	desc.handle[0] = (void*)glfwGetCocoaView(win);
#else
#error "the WGPU platform only knows how to hand a macOS window to the renderer so far"
#endif
	desc.width = fbw;
	desc.height = fbh;
	desc.vsync = 1;
	if(!rwgpu_init(&desc)){
		fprintf(stderr, "rwgpu: %s\n", rwgpu_last_error());
		RWERROR((ERR_GENERAL, "rwgpu_init failed"));
		glfwDestroyWindow(win);
		return 0;
	}

	RwgpuCaps rcaps;
	rwgpu_get_caps(&rcaps);
	caps.dxtSupported = !!rcaps.bc_supported;
	caps.maxAnisotropy = rcaps.max_anisotropy;

	wgpuGlobals.window = win;
	*wgpuGlobals.pWindow = win;
	wgpuGlobals.fbWidth = fbw;
	wgpuGlobals.fbHeight = fbh;
	memset(boundRasters, 0, sizeof(boundRasters));
	return 1;
}

static int
stopGLFW(void)
{
	rwgpu_shutdown();
	glfwDestroyWindow(wgpuGlobals.window);
	return 1;
}

static int
deviceSystemGLFW(DeviceReq req, void *arg, int32 n)
{
	GLFWmonitor **monitors;
	VideoMode *rwmode;

	switch(req){
	case DEVICEOPEN:
		return openGLFW((EngineOpenParams*)arg);
	case DEVICECLOSE:
		return closeGLFW();

	case DEVICEINIT:
		return startGLFW();
	case DEVICETERM:
		return stopGLFW();

	case DEVICEFINALIZE:
		return 1;

	case DEVICEGETNUMSUBSYSTEMS:
		return wgpuGlobals.numMonitors;

	case DEVICEGETCURRENTSUBSYSTEM:
		return wgpuGlobals.currentMonitor;

	case DEVICESETSUBSYSTEM:
		monitors = glfwGetMonitors(&wgpuGlobals.numMonitors);
		if(n >= wgpuGlobals.numMonitors)
			return 0;
		wgpuGlobals.currentMonitor = n;
		wgpuGlobals.monitor = monitors[wgpuGlobals.currentMonitor];
		return 1;

	case DEVICEGETSUBSSYSTEMINFO:
		monitors = glfwGetMonitors(&wgpuGlobals.numMonitors);
		if(n >= wgpuGlobals.numMonitors)
			return 0;
		strncpy(((SubSystemInfo*)arg)->name, glfwGetMonitorName(monitors[n]), sizeof(SubSystemInfo::name));
		return 1;

	case DEVICEGETNUMVIDEOMODES:
		return wgpuGlobals.numModes;

	case DEVICEGETCURRENTVIDEOMODE:
		return wgpuGlobals.currentMode;

	case DEVICESETVIDEOMODE:
		if(n >= wgpuGlobals.numModes)
			return 0;
		wgpuGlobals.currentMode = n;
		return 1;

	case DEVICEGETVIDEOMODEINFO:
		rwmode = (VideoMode*)arg;
		rwmode->width = wgpuGlobals.modes[n].mode.width;
		rwmode->height = wgpuGlobals.modes[n].mode.height;
		rwmode->depth = wgpuGlobals.modes[n].depth;
		rwmode->flags = wgpuGlobals.modes[n].flags;
		return 1;

	// No multisampling (design §1.1).
	case DEVICEGETMAXMULTISAMPLINGLEVELS:
	case DEVICEGETMULTISAMPLINGLEVELS:
		return 1;
	case DEVICESETMULTISAMPLINGLEVELS:
		return 1;
	default:
		assert(0 && "not implemented");
		return 0;
	}
	return 1;
}

Device renderdevice = {
	0.0f, 1.0f,
	wgpu::beginUpdate,
	wgpu::endUpdate,
	wgpu::clearCamera,
	wgpu::showRaster,
	wgpu::rasterRenderFast,
	wgpu::setRenderState,
	wgpu::getRenderState,
	wgpu::im2DRenderLine,
	wgpu::im2DRenderTriangle,
	wgpu::im2DRenderPrimitive,
	wgpu::im2DRenderIndexedPrimitive,
	wgpu::im3DTransform,
	wgpu::im3DRenderPrimitive,
	wgpu::im3DRenderIndexedPrimitive,
	wgpu::im3DEnd,
	wgpu::deviceSystemGLFW
};

}
}

#endif
