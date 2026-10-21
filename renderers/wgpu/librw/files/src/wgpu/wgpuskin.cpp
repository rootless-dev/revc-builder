/*
 * librw WGPU platform: the skin pipeline.
 *
 * Part of reVC Builder (MIT licence). Adapted from librw's GL3 backend
 * (src/gl/gl3skin.cpp), Copyright (c) 2014 aap, MIT licence.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
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

void
skinInstanceCB(Geometry *geo, InstanceDataHeader *header, bool32 reinstance)
{
	if(!reinstance)
		allocateVertices(geo, header, LAYOUT_SKIN);
	instanceCommon(geo, header, reinstance);

	if(!reinstance){
		Skin *skin = Skin::get(geo);
		uint8 *verts = header->vertexBuffer;
		instV4d(VERT_FLOAT4, verts + 44, (V4d*)skin->weights,
			header->totalNumVertex, header->stride);
		// not really colors of course but what the heck
		instColor(VERT_RGBA, verts + 60, (RGBA*)skin->indices,
			header->totalNumVertex, header->stride);
	}
	uploadVertices(header);
}

void
skinUninstanceCB(Geometry *geo, InstanceDataHeader *header)
{
	assert(0 && "can't uninstance");
}

static float skinMatrices[64*16];

void
uploadSkinMatrices(Atomic *a)
{
	int i;
	Skin *skin = Skin::get(a->geometry);
	Matrix *m = (Matrix*)skinMatrices;
	HAnimHierarchy *hier = Skin::getHierarchy(a);
	int32 count;

	if(hier){
		Matrix *invMats = (Matrix*)skin->inverseMatrices;
		Matrix tmp;

		assert(skin->numBones == hier->numNodes);
		count = hier->numNodes;
		if(hier->flags & HAnimHierarchy::LOCALSPACEMATRICES){
			for(i = 0; i < hier->numNodes; i++){
				invMats[i].flags = 0;
				Matrix::mult(m, &invMats[i], &hier->matrices[i]);
				m++;
			}
		}else{
			Matrix invAtmMat;
			Matrix::invert(&invAtmMat, a->getFrame()->getLTM());
			for(i = 0; i < hier->numNodes; i++){
				invMats[i].flags = 0;
				Matrix::mult(&tmp, &hier->matrices[i], &invAtmMat);
				Matrix::mult(m, &invMats[i], &tmp);
				m++;
			}
		}
	}else{
		count = skin->numBones;
		for(i = 0; i < skin->numBones; i++){
			m->setIdentity();
			m++;
		}
	}
	if(count > 64)
		count = 64;
	// As in GL3, the matrices go up as Matrix structs; their fourth row (flags and
	// padding) only reaches the discarded w of the skinned vertex.
	rwgpu_set_bones(skinMatrices, count);
}

void
skinRenderCB(Atomic *atomic, InstanceDataHeader *header)
{
	Material *m;

	uint32 flags = atomic->geometry->flags;
	setWorldMatrix(atomic->getFrame()->getLTM());
	lightingCB(atomic);

	InstanceData *inst = header->inst;
	int32 n = header->numMeshes;

	uploadSkinMatrices(atomic);

	while(n--){
		m = inst->material;

		setMaterial(flags, m->color, m->surfaceProps);

		setTexture(0, m->texture);

		rw::SetRenderState(VERTEXALPHA, inst->vertexAlpha || m->color.alpha != 0xFF);

		drawInst(header, inst, SHADER_SKIN);
		inst++;
	}
}

static void*
skinOpen(void *o, int32, int32)
{
	skinGlobals.pipelines[PLATFORM_WGPU] = makeSkinPipeline();
	return o;
}

static void*
skinClose(void *o, int32, int32)
{
	((ObjPipeline*)skinGlobals.pipelines[PLATFORM_WGPU])->destroy();
	skinGlobals.pipelines[PLATFORM_WGPU] = nil;
	return o;
}

void
initSkin(void)
{
	Driver::registerPlugin(PLATFORM_WGPU, 0, ID_SKIN,
	                       skinOpen, skinClose);
}

ObjPipeline*
makeSkinPipeline(void)
{
	ObjPipeline *pipe = ObjPipeline::create();
	pipe->instanceCB = skinInstanceCB;
	pipe->uninstanceCB = skinUninstanceCB;
	pipe->renderCB = skinRenderCB;
	pipe->pluginID = ID_SKIN;
	pipe->pluginData = 1;
	return pipe;
}

}
}

#endif
