/*
 * reVC's custom pipelines on librw's WGPU platform. Part of reVC Builder (MIT licence).
 *
 * The Neo pipelines (vehicle reflections, world lightmaps, road gloss, rim light) are not
 * ported (Phase 2 design, section 8.3): every pipeline renders as reVC's GL3 pipelines do
 * when those options are off. reVC's NEW_RENDERER is not ported either; its WorldRender
 * entry points exist so that reVC links, and are never called because gbNewRenderer
 * stays false with RW_WGPU.
 */
#include "common.h"

#ifdef RW_WGPU
#include "main.h"
#include "custompipes.h"

#ifdef EXTENDED_PIPELINES

#ifndef LIBRW
#error "Need librw for EXTENDED_PIPELINES"
#endif

namespace CustomPipes {

static void
vehicleRenderCB(rw::Atomic *atomic, rw::wgpu::InstanceDataHeader *header)
{
	rw::wgpu::matfxRenderCB(atomic, header);
}

static void
worldRenderCB(rw::Atomic *atomic, rw::wgpu::InstanceDataHeader *header)
{
	rw::wgpu::defaultRenderCB(atomic, header);
}

static void
rimSkinRenderCB(rw::Atomic *atomic, rw::wgpu::InstanceDataHeader *header)
{
	rw::wgpu::skinRenderCB(atomic, header);
}

static rw::ObjPipeline*
makePipe(void (*instanceCB)(rw::Geometry*, rw::wgpu::InstanceDataHeader*, rw::bool32),
	void (*renderCB)(rw::Atomic*, rw::wgpu::InstanceDataHeader*))
{
	rw::wgpu::ObjPipeline *pipe = rw::wgpu::ObjPipeline::create();
	pipe->instanceCB = instanceCB;
	pipe->uninstanceCB = nil;
	pipe->renderCB = renderCB;
	return pipe;
}

static void
destroyPipe(rw::ObjPipeline **pipe)
{
	((rw::wgpu::ObjPipeline*)*pipe)->destroy();
	*pipe = nil;
}

void CreateVehiclePipe(void) { vehiclePipe = makePipe(rw::wgpu::defaultInstanceCB, vehicleRenderCB); }
void DestroyVehiclePipe(void) { destroyPipe(&vehiclePipe); }

void CreateWorldPipe(void) { worldPipe = makePipe(rw::wgpu::defaultInstanceCB, worldRenderCB); }
void DestroyWorldPipe(void) { destroyPipe(&worldPipe); }

void CreateGlossPipe(void) { glossPipe = makePipe(rw::wgpu::defaultInstanceCB, worldRenderCB); }
void DestroyGlossPipe(void) { destroyPipe(&glossPipe); }

void
CreateRimLightPipes(void)
{
	rimPipe = makePipe(rw::wgpu::defaultInstanceCB, worldRenderCB);
	rimSkinPipe = makePipe(rw::wgpu::skinInstanceCB, rimSkinRenderCB);
}

void
DestroyRimLightPipes(void)
{
	destroyPipe(&rimPipe);
	destroyPipe(&rimSkinPipe);
}

void
CustomPipeRegisterWGPU(void)
{
}

}

#endif

#ifdef NEW_RENDERER
namespace WorldRender
{
int numBlendInsts[3];

void AtomicFirstPass(RpAtomic *atomic, int pass) {}
void AtomicFullyTransparent(RpAtomic *atomic, int pass, int fadeAlpha) {}
void RenderBlendPass(int pass) {}
}
#endif

#endif
