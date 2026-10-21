/*
 * librw WGPU platform: Im2D and Im3D.
 *
 * Part of reVC Builder (MIT licence). Adapted from librw's GL3 backend
 * (src/gl/gl3immed.cpp), Copyright (c) 2014 aap, MIT licence.
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

static Im2DVertex tmpprimbuf[3];

void
im2DRenderLine(void *vertices, int32 numVertices, int32 vert1, int32 vert2)
{
	Im2DVertex *verts = (Im2DVertex*)vertices;
	tmpprimbuf[0] = verts[vert1];
	tmpprimbuf[1] = verts[vert2];
	im2DRenderPrimitive(PRIMTYPELINELIST, tmpprimbuf, 2);
}

void
im2DRenderTriangle(void *vertices, int32 numVertices, int32 vert1, int32 vert2, int32 vert3)
{
	Im2DVertex *verts = (Im2DVertex*)vertices;
	tmpprimbuf[0] = verts[vert1];
	tmpprimbuf[1] = verts[vert2];
	tmpprimbuf[2] = verts[vert3];
	im2DRenderPrimitive(PRIMTYPETRILIST, tmpprimbuf, 3);
}

void
im2DRenderPrimitive(PrimitiveType primType, void *vertices, int32 numVertices)
{
	rwgpu_im2d_draw(primType, (RwgpuIm2DVertex*)vertices, numVertices, nil, 0);
}

void
im2DRenderIndexedPrimitive(PrimitiveType primType,
	void *vertices, int32 numVertices,
	void *indices, int32 numIndices)
{
	rwgpu_im2d_draw(primType, (RwgpuIm2DVertex*)vertices, numVertices, (uint16*)indices, numIndices);
}

void
im2DRenderIndexedPrimitiveUV2(PrimitiveType primType, Im2DVertexUV2 *vertices, int32 numVertices,
	void *indices, int32 numIndices)
{
	rwgpu_im2d_uv2_draw(primType, (RwgpuIm2DVertexUV2*)vertices, numVertices, (uint16*)indices, numIndices);
}

uint32
im2DCreateShader(const char *wgsl)
{
	return rwgpu_im2d_shader_create(wgsl);
}

void
im2DSetOverride(uint32 shader, const float32 *params)
{
	rwgpu_im2d_set_override(shader, params);
}

// settable by user - TOOD: make this less shit
RGBA im3dMaterialColor = { 255, 255, 255, 255 };
SurfaceProperties im3dSurfaceProps = { 1.0f, 1.0f, 1.0f };

void
im3DTransform(void *vertices, int32 numVertices, Matrix *world, uint32 flags)
{
	RawMatrix rawWorld;
	if(world == nil){
		static Matrix ident;
		ident.setIdentity();
		world = &ident;
	}
	convMatrix(&rawWorld, world);
	uint32 lit = 0;
	if(flags & im3d::LIGHTING){
		setMaterial(im3dMaterialColor, im3dSurfaceProps);
		lightingCB();
		lit = 1;
	}

	if((flags & im3d::VERTEXUV) == 0)
		SetRenderStatePtr(TEXTURERASTER, nil);

	rwgpu_im3d_transform((RwgpuIm3DVertex*)vertices, numVertices, (float*)&rawWorld, lit);
}

void
im3DRenderPrimitive(PrimitiveType primType)
{
	rwgpu_im3d_draw(primType, nil, 0);
}

void
im3DRenderIndexedPrimitive(PrimitiveType primType, void *indices, int32 numIndices)
{
	rwgpu_im3d_draw(primType, (uint16*)indices, numIndices);
}

void
im3DEnd(void)
{
	rwgpu_im3d_end();
}

}
}

#endif
