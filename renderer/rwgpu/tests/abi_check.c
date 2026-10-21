/* Compiled by tests/abi.rs: the header's layouts and constants match the design (§4.2). */
#include <stddef.h>
#include "rwgpu.h"

#define CHECK(cond) _Static_assert(cond, #cond)

CHECK(sizeof(RwgpuWindowDesc) == 48);
CHECK(offsetof(RwgpuWindowDesc, handle) == 16);
CHECK(sizeof(RwgpuStats) == 32);
CHECK(offsetof(RwgpuStats, pipelines) == 16);
CHECK(sizeof(RwgpuCaps) == 16);
CHECK(sizeof(RwgpuTarget) == 24);
CHECK(offsetof(RwgpuTarget, x) == 8);
CHECK(sizeof(RwgpuLight) == 64);
CHECK(offsetof(RwgpuLight, position) == 16);
CHECK(offsetof(RwgpuLight, direction) == 32);
CHECK(offsetof(RwgpuLight, color) == 48);
CHECK(sizeof(RwgpuIm2DVertex) == 28);
CHECK(offsetof(RwgpuIm2DVertex, r) == 16);
CHECK(offsetof(RwgpuIm2DVertex, u) == 20);
CHECK(sizeof(RwgpuIm2DVertexUV2) == 36);
CHECK(offsetof(RwgpuIm2DVertexUV2, u2) == 28);
CHECK(sizeof(RwgpuIm3DVertex) == 36);
CHECK(offsetof(RwgpuIm3DVertex, normal) == 12);
CHECK(offsetof(RwgpuIm3DVertex, r) == 24);
CHECK(offsetof(RwgpuIm3DVertex, u) == 28);
CHECK(RWGPU_MESH_STRIDE == 44);
CHECK(RWGPU_SKIN_STRIDE == 64);
CHECK(RWGPU_ABI_VERSION == EXPECTED_ABI_VERSION);

/* librw's numbering (rwrender.h, rwbase.h, rwobjects.h at librw 0ad67ee). */
CHECK(RWGPU_TEXTURERASTER == 0 && RWGPU_CULLMODE == 12 && RWGPU_STENCILENABLE == 13 && RWGPU_GSALPHATESTREF == 24);
CHECK(RWGPU_ALPHAALWAYS == 0 && RWGPU_ALPHAGREATEREQUAL == 1 && RWGPU_ALPHALESS == 2);
CHECK(RWGPU_STENCILKEEP == 1 && RWGPU_STENCILDEC == 8 && RWGPU_STENCILNEVER == 1 && RWGPU_STENCILALWAYS == 8);
CHECK(RWGPU_CULLNONE == 1 && RWGPU_CULLBACK == 2 && RWGPU_CULLFRONT == 3);
CHECK(RWGPU_BLENDZERO == 1 && RWGPU_BLENDSRCALPHA == 5 && RWGPU_BLENDSRCALPHASAT == 11);
CHECK(RWGPU_FILTERNEAREST == 1 && RWGPU_FILTERLINEARMIPLINEAR == 6 && RWGPU_ADDRESSWRAP == 1 && RWGPU_ADDRESSBORDER == 4);
CHECK(RWGPU_PRIMTYPENONE == 0 && RWGPU_PRIMTYPETRIFAN == 5 && RWGPU_PRIMTYPEPOINTLIST == 6);
CHECK(RWGPU_CLEARIMAGE == 1 && RWGPU_CLEARZ == 2 && RWGPU_CLEARSTENCIL == 4);
