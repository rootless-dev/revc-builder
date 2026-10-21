/*
 * librw WGPU platform: object pipelines, instancing and the default render callback.
 *
 * Part of reVC Builder (MIT licence). Adapted from librw's GL3 backend
 * (src/gl/gl3pipe.cpp, src/gl/gl3render.cpp), Copyright (c) 2014 aap, MIT licence.
 *
 * Geometry is instanced into the fixed layouts of rwgpu.h. Attributes a geometry lacks
 * get the values GL3's disabled attributes read: normal (0,0,0), colour (0,0,0,255),
 * texture coordinates (0,0) (design §6).
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
#include "../rwengine.h"

#include "rwwgpu.h"

#ifdef RW_WGPU
#include "rwwgpuimpl.h"

namespace rw {
namespace wgpu {

enum {
	OFFSET_POS = 0,
	OFFSET_NORMAL = 12,
	OFFSET_COLOR = 24,
	OFFSET_TEX0 = 28,
	OFFSET_TEX1 = 36,
	OFFSET_WEIGHTS = 44,
	OFFSET_INDICES = 60
};

static void
freeInstanceData(Geometry *geometry)
{
	if(geometry->instData == nil ||
	   geometry->instData->platform != PLATFORM_WGPU)
		return;
	InstanceDataHeader *header = (InstanceDataHeader*)geometry->instData;
	geometry->instData = nil;
	rwgpu_mesh_destroy(header->mesh);
	rwFree(header->indexBuffer);
	rwFree(header->vertexBuffer);
	rwFree(header->inst);
	rwFree(header);
}

void*
destroyNativeData(void *object, int32, int32)
{
	freeInstanceData((Geometry*)object);
	return object;
}

static InstanceDataHeader*
instanceMesh(rw::ObjPipeline *rwpipe, Geometry *geo)
{
	InstanceDataHeader *header = rwNewT(InstanceDataHeader, 1, MEMDUR_EVENT | ID_GEOMETRY);
	MeshHeader *meshh = geo->meshHeader;
	geo->instData = header;
	header->platform = PLATFORM_WGPU;

	header->serialNumber = meshh->serialNum;
	header->numMeshes = meshh->numMeshes;
	header->primType = meshh->flags == 1 ? PRIMTYPETRISTRIP : PRIMTYPETRILIST;
	header->totalNumVertex = geo->numVertices;
	header->totalNumIndex = meshh->totalIndices;
	header->inst = rwNewT(InstanceData, header->numMeshes, MEMDUR_EVENT | ID_GEOMETRY);

	header->indexBuffer = rwNewT(uint16, header->totalNumIndex, MEMDUR_EVENT | ID_GEOMETRY);
	InstanceData *inst = header->inst;
	Mesh *mesh = meshh->getMeshes();
	uint32 offset = 0;
	for(uint32 i = 0; i < header->numMeshes; i++){
		findMinVertAndNumVertices(mesh->indices, mesh->numIndices,
		                          &inst->minVert, &inst->numVertices);
		assert(inst->minVert != 0xFFFFFFFF);
		inst->numIndex = mesh->numIndices;
		inst->material = mesh->material;
		inst->vertexAlpha = 0;
		inst->offset = offset;
		memcpy(header->indexBuffer + offset, mesh->indices, inst->numIndex*2);
		offset += inst->numIndex;
		mesh++;
		inst++;
	}

	header->vertexBuffer = nil;
	header->mesh = 0;
	return header;
}

/* Fills the attributes the MESH and SKIN layouts share. */
void
instanceCommon(Geometry *geo, InstanceDataHeader *header, bool32 reinstance)
{
	bool isPrelit = !!(geo->flags & Geometry::PRELIT);
	bool hasNormals = !!(geo->flags & Geometry::NORMALS);
	uint32 stride = header->stride;
	uint8 *verts = header->vertexBuffer;

	if(!reinstance || geo->lockedSinceInst&Geometry::LOCKVERTICES)
		instV3d(VERT_FLOAT3, verts + OFFSET_POS, geo->morphTargets[0].vertices,
			header->totalNumVertex, stride);

	if(hasNormals && (!reinstance || geo->lockedSinceInst&Geometry::LOCKNORMALS))
		instV3d(VERT_FLOAT3, verts + OFFSET_NORMAL, geo->morphTargets[0].normals,
			header->totalNumVertex, stride);

	if(isPrelit && (!reinstance || geo->lockedSinceInst&Geometry::LOCKPRELIGHT)){
		int n = header->numMeshes;
		InstanceData *inst = header->inst;
		while(n--){
			assert(inst->minVert != 0xFFFFFFFF);
			inst->vertexAlpha = instColor(VERT_RGBA,
				verts + OFFSET_COLOR + stride*inst->minVert,
				geo->colors + inst->minVert,
				inst->numVertices, stride);
			inst++;
		}
	}

	for(int32 n = 0; n < geo->numTexCoordSets && n < 2; n++){
		if(!reinstance || geo->lockedSinceInst&(Geometry::LOCKTEXCOORDS<<n))
			instTexCoords(VERT_FLOAT2, verts + (n == 0 ? OFFSET_TEX0 : OFFSET_TEX1),
				geo->texCoords[n], header->totalNumVertex, stride);
	}
}

/* Allocates the CPU vertex buffer with GL3's defaults for missing attributes. */
void
allocateVertices(Geometry *geo, InstanceDataHeader *header, uint32 layout)
{
	header->layout = layout;
	header->stride = layout == LAYOUT_SKIN ? RWGPU_SKIN_STRIDE : RWGPU_MESH_STRIDE;
	uint32 size = header->totalNumVertex*header->stride;
	header->vertexBuffer = rwNewT(uint8, size, MEMDUR_EVENT | ID_GEOMETRY);
	memset(header->vertexBuffer, 0, size);
	if(!(geo->flags & Geometry::PRELIT))
		for(uint32 i = 0; i < header->totalNumVertex; i++)
			header->vertexBuffer[i*header->stride + OFFSET_COLOR + 3] = 255;
}

/* Hands the vertices to the renderer: a new mesh, or new vertices for an existing one. */
void
uploadVertices(InstanceDataHeader *header)
{
	uint32 bytes = header->totalNumVertex*header->stride;
	if(header->mesh == 0)
		header->mesh = rwgpu_mesh_create(header->layout, header->vertexBuffer, bytes,
			header->indexBuffer, header->totalNumIndex);
	else
		rwgpu_mesh_update_vertices(header->mesh, header->vertexBuffer, bytes);
}

static void
instance(rw::ObjPipeline *rwpipe, Atomic *atomic)
{
	ObjPipeline *pipe = (ObjPipeline*)rwpipe;
	Geometry *geo = atomic->geometry;
	// don't try to (re)instance native data
	if(geo->flags & Geometry::NATIVE)
		return;

	InstanceDataHeader *header = (InstanceDataHeader*)geo->instData;
	if(geo->instData){
		// Already have instanced data, so check if we have to reinstance
		assert(header->platform == PLATFORM_WGPU);
		if(header->serialNumber != geo->meshHeader->serialNum){
			// Mesh changed, so reinstance everything
			freeInstanceData(geo);
		}
	}

	// no instance or complete reinstance
	if(geo->instData == nil){
		geo->instData = instanceMesh(rwpipe, geo);
		pipe->instanceCB(geo, (InstanceDataHeader*)geo->instData, 0);
	}else if(geo->lockedSinceInst)
		pipe->instanceCB(geo, (InstanceDataHeader*)geo->instData, 1);

	geo->lockedSinceInst = 0;
}

static void
uninstance(rw::ObjPipeline *rwpipe, Atomic *atomic)
{
	assert(0 && "can't uninstance");
}

static void
render(rw::ObjPipeline *rwpipe, Atomic *atomic)
{
	ObjPipeline *pipe = (ObjPipeline*)rwpipe;
	Geometry *geo = atomic->geometry;
	pipe->instance(atomic);
	assert(geo->instData != nil);
	assert(geo->instData->platform == PLATFORM_WGPU);
	if(pipe->renderCB)
		pipe->renderCB(atomic, (InstanceDataHeader*)geo->instData);
}

void
ObjPipeline::init(void)
{
	this->rw::ObjPipeline::init(PLATFORM_WGPU);
	this->impl.instance = wgpu::instance;
	this->impl.uninstance = wgpu::uninstance;
	this->impl.render = wgpu::render;
	this->instanceCB = nil;
	this->uninstanceCB = nil;
	this->renderCB = nil;
}

ObjPipeline*
ObjPipeline::create(void)
{
	ObjPipeline *pipe = rwNewT(ObjPipeline, 1, MEMDUR_GLOBAL);
	pipe->init();
	return pipe;
}

void
defaultInstanceCB(Geometry *geo, InstanceDataHeader *header, bool32 reinstance)
{
	if(!reinstance)
		allocateVertices(geo, header, LAYOUT_MESH);
	instanceCommon(geo, header, reinstance);
	uploadVertices(header);
}

void
defaultUninstanceCB(Geometry *geo, InstanceDataHeader *header)
{
	assert(0 && "can't uninstance");
}

void
drawInst(InstanceDataHeader *header, InstanceData *inst, uint32 shader)
{
	rwgpu_draw_mesh(header->mesh, shader, header->primType, inst->offset, inst->numIndex);
}

int32
lightingCB(Atomic *atomic)
{
	WorldLights lightData;
	Light *directionals[8];
	Light *locals[8];
	lightData.directionals = directionals;
	lightData.numDirectionals = 8;
	lightData.locals = locals;
	lightData.numLocals = 8;

	if(atomic->geometry->flags & rw::Geometry::LIGHT)
		((World*)engine->currentWorld)->enumerateLights(atomic, &lightData);
	else
		memset(&lightData, 0, sizeof(lightData));
	return setLights(&lightData);
}

int32
lightingCB(void)
{
	WorldLights lightData;
	Light *directionals[8];
	Light *locals[8];
	lightData.directionals = directionals;
	lightData.numDirectionals = 8;
	lightData.locals = locals;
	lightData.numLocals = 8;

	((World*)engine->currentWorld)->enumerateLights(&lightData);
	return setLights(&lightData);
}

void
defaultRenderCB(Atomic *atomic, InstanceDataHeader *header)
{
	Material *m;

	uint32 flags = atomic->geometry->flags;
	setWorldMatrix(atomic->getFrame()->getLTM());
	lightingCB(atomic);

	InstanceData *inst = header->inst;
	int32 n = header->numMeshes;

	while(n--){
		m = inst->material;

		setMaterial(flags, m->color, m->surfaceProps);

		setTexture(0, m->texture);

		rw::SetRenderState(VERTEXALPHA, inst->vertexAlpha || m->color.alpha != 0xFF);

		drawInst(header, inst, SHADER_DEFAULT);
		inst++;
	}
}

ObjPipeline*
makeDefaultPipeline(void)
{
	ObjPipeline *pipe = ObjPipeline::create();
	pipe->instanceCB = defaultInstanceCB;
	pipe->uninstanceCB = defaultUninstanceCB;
	pipe->renderCB = defaultRenderCB;
	return pipe;
}

}
}

#endif
