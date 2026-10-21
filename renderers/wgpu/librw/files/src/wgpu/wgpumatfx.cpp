/*
 * librw WGPU platform: the matfx (environment map) pipeline.
 *
 * Part of reVC Builder (MIT licence). Adapted from librw's GL3 backend
 * (src/gl/gl3matfx.cpp), Copyright (c) 2014 aap, MIT licence.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <assert.h>

#include "../rwbase.h"
#include "../rwerror.h"
#include "../rwplg.h"
#include "../rwrender.h"
#include "../rwpipeline.h"
#include "../rwobjects.h"
#include "../rwanim.h"
#include "../rwengine.h"
#include "../rwplugins.h"

#include "rwwgpu.h"

#ifdef RW_WGPU
#include "rwwgpuimpl.h"

namespace rw {
namespace wgpu {

static void
matfxDefaultRender(InstanceDataHeader *header, InstanceData *inst, uint32 flags)
{
	Material *m;
	m = inst->material;

	setMaterial(flags, m->color, m->surfaceProps);

	setTexture(0, m->texture);

	rw::SetRenderState(VERTEXALPHA, inst->vertexAlpha || m->color.alpha != 0xFF);

	drawInst(header, inst, SHADER_DEFAULT);
}

static RawMatrix normal2texcoord = {
	{ 0.5f,  0.0f, 0.0f }, 0.0f,
	{ 0.0f, -0.5f, 0.0f }, 0.0f,
	{ 0.0f,  0.0f, 1.0f }, 0.0f,
	{ 0.5f,  0.5f, 0.0f }, 1.0f
};

static void
envMatrix(Frame *frame, RawMatrix *envMtx)
{
	Matrix invMat;
	if(frame == nil)
		frame = engine->currentCamera->getFrame();

	RawMatrix invMtx;
	Matrix::invert(&invMat, frame->getLTM());
	convMatrix(&invMtx, &invMat);
	invMtx.pos.set(0.0f, 0.0f, 0.0f);
	float uscale = fabs(normal2texcoord.right.x);
	normal2texcoord.right.x = MatFX::envMapFlipU ? -uscale : uscale;
	RawMatrix::mult(envMtx, &invMtx, &normal2texcoord);
}

static void
matfxEnvRender(InstanceDataHeader *header, InstanceData *inst, uint32 flags, MatFX::Env *env)
{
	Material *m;
	m = inst->material;

	if(env->tex == nil || env->coefficient == 0.0f){
		matfxDefaultRender(header, inst, flags);
		return;
	}

	setTexture(0, m->texture);
	setTexture(1, env->tex);
	RawMatrix envMtx;
	envMatrix(env->frame, &envMtx);

	setMaterial(flags, m->color, m->surfaceProps);

	float fxparams[4];
	fxparams[0] = env->coefficient;
	fxparams[1] = env->fbAlpha ? 0.0f : 1.0f;
	fxparams[2] = fxparams[3] = 0.0f;

	static float zero[4];
	static float one[4] = { 1.0f, 1.0f, 1.0f, 1.0f };
	// This clamps the vertex color below. With it we can achieve both PC and PS2 style matfx
	float *colorClamp = MatFX::envMapApplyLight ? zero : one;
	RGBAf envcol;
	if(MatFX::envMapUseMatColor)
		convColor(&envcol, &m->color);
	else
		convColor(&envcol, &MatFX::envMapColor);
	rwgpu_set_matfx_env((float*)&envMtx, fxparams, colorClamp, (float*)&envcol);

	rw::SetRenderState(VERTEXALPHA, 1);
	rw::SetRenderState(SRCBLEND, BLENDONE);

	drawInst(header, inst, SHADER_MATFX_ENV);

	rw::SetRenderState(SRCBLEND, BLENDSRCALPHA);
}

void
matfxRenderCB(Atomic *atomic, InstanceDataHeader *header)
{
	uint32 flags = atomic->geometry->flags;
	setWorldMatrix(atomic->getFrame()->getLTM());
	lightingCB(atomic);

	InstanceData *inst = header->inst;
	int32 n = header->numMeshes;

	while(n--){
		MatFX *matfx = MatFX::get(inst->material);

		if(matfx == nil)
			matfxDefaultRender(header, inst, flags);
		else switch(matfx->type){
		case MatFX::ENVMAP:
			matfxEnvRender(header, inst, flags, &matfx->fx[0].env);
			break;
		default:
			matfxDefaultRender(header, inst, flags);
			break;
		}
		inst++;
	}
}

ObjPipeline*
makeMatFXPipeline(void)
{
	ObjPipeline *pipe = ObjPipeline::create();
	pipe->instanceCB = defaultInstanceCB;
	pipe->uninstanceCB = defaultUninstanceCB;
	pipe->renderCB = matfxRenderCB;
	pipe->pluginID = ID_MATFX;
	pipe->pluginData = 0;
	return pipe;
}

static void*
matfxOpen(void *o, int32, int32)
{
	matFXGlobals.pipelines[PLATFORM_WGPU] = makeMatFXPipeline();
	return o;
}

static void*
matfxClose(void *o, int32, int32)
{
	((ObjPipeline*)matFXGlobals.pipelines[PLATFORM_WGPU])->destroy();
	matFXGlobals.pipelines[PLATFORM_WGPU] = nil;
	return o;
}

void
initMatFX(void)
{
	Driver::registerPlugin(PLATFORM_WGPU, 0, ID_MATFX,
	                       matfxOpen, matfxClose);
}

}
}

#endif
