/*
 * librw WGPU platform: driver registration.
 *
 * Part of reVC Builder (MIT licence). Adapted from librw's GL3 backend
 * (src/gl/gl3.cpp), Copyright (c) 2014 aap, MIT licence.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>

#include "../rwbase.h"
#include "../rwerror.h"
#include "../rwplg.h"
#include "../rwpipeline.h"
#include "../rwobjects.h"
#include "../rwengine.h"

#include "rwwgpu.h"

#ifdef RW_WGPU
#include "rwwgpuimpl.h"

namespace rw {
namespace wgpu {

static void*
driverOpen(void *o, int32, int32)
{
	engine->driver[PLATFORM_WGPU]->defaultPipeline = makeDefaultPipeline();
	engine->driver[PLATFORM_WGPU]->rasterNativeOffset = nativeRasterOffset;
	engine->driver[PLATFORM_WGPU]->rasterCreate       = rasterCreate;
	engine->driver[PLATFORM_WGPU]->rasterLock         = rasterLock;
	engine->driver[PLATFORM_WGPU]->rasterUnlock       = rasterUnlock;
	engine->driver[PLATFORM_WGPU]->rasterNumLevels    = rasterNumLevels;
	engine->driver[PLATFORM_WGPU]->imageFindRasterFormat = imageFindRasterFormat;
	engine->driver[PLATFORM_WGPU]->rasterFromImage    = rasterFromImage;
	engine->driver[PLATFORM_WGPU]->rasterToImage      = rasterToImage;
	return o;
}

static void*
driverClose(void *o, int32, int32)
{
	return o;
}

void
registerPlatformPlugins(void)
{
	Driver::registerPlugin(PLATFORM_WGPU, 0, PLATFORM_WGPU,
	                       driverOpen, driverClose);
	registerNativeRaster();
}

}
}

#endif
