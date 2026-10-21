/*
 * librw WGPU platform: rasters, textures and the native texture stream.
 *
 * Part of reVC Builder (MIT licence). Adapted from librw's GL3 backend
 * (src/gl/gl3raster.cpp), Copyright (c) 2014 aap, MIT licence.
 *
 * Rasters are top-down (row 0 is the top, sampled at v = 0), unlike GL3's bottom-up
 * rasters, so images are copied without flipping (design §6).
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

#define PLUGIN_ID ID_DRIVER

namespace rw {
namespace wgpu {

int32 nativeRasterOffset;

static int32
bcFormat(int32 compression)
{
	switch(compression){
	case 1: return RWGPU_FORMAT_BC1;
	case 3: return RWGPU_FORMAT_BC2;
	case 5: return RWGPU_FORMAT_BC3;
	}
	return 0;
}

/* Bytes of mip level `level` in the CPU layout (GL3's getLevelSize). */
static uint32
getLevelSize(Raster *raster, int32 level)
{
	int i;
	WgpuRaster *natras = GETWGPURASTEREXT(raster);

	int w = raster->originalWidth;
	int h = raster->originalHeight;
	int s = raster->originalStride;
	int minDim = natras->isCompressed ? 4 : 1;

	for(i = 0; i < level; i++){
		if(w > minDim){
			w /= 2;
			s /= 2;
		}
		if(h > minDim)
			h /= 2;
	}

	return s*h;
}

static int32
fullChainLevels(int32 w, int32 h)
{
	int32 n = 1;
	while(w != 1 || h != 1){
		n++;
		if(w > 1) w /= 2;
		if(h > 1) h /= 2;
	}
	return n;
}

static Raster*
rasterCreateTexture(Raster *raster)
{
	if(raster->format & (Raster::PAL4 | Raster::PAL8)){
		RWERROR((ERR_NOTEXTURE));
		return nil;
	}

	WgpuRaster *natras = GETWGPURASTEREXT(raster);
	switch(raster->format & 0xF00){
	case Raster::C8888:
		natras->hasAlpha = 1;
		natras->bpp = 4;
		raster->depth = 32;
		break;
	case Raster::C888:
		natras->hasAlpha = 0;
		natras->bpp = 3;
		raster->depth = 24;
		break;
	case Raster::C1555:
		// Kept as RGBA8, as GL3 does on GLES.
		natras->hasAlpha = 1;
		natras->bpp = 4;
		raster->depth = 16;
		break;
	default:
		RWERROR((ERR_INVRASTER));
		return nil;
	}

	raster->stride = raster->width*natras->bpp;

	if(raster->format & Raster::MIPMAP)
		natras->numLevels = fullChainLevels(raster->width, raster->height);
	natras->autogenMipmap = (raster->format & (Raster::MIPMAP|Raster::AUTOMIPMAP)) == (Raster::MIPMAP|Raster::AUTOMIPMAP);
	// As in GL3, which sets GL_TEXTURE_MAX_LEVEL to 0 for these: an automatically
	// mipmapped raster has one level and is sampled at level 0 only.
	if(natras->autogenMipmap)
		natras->numLevels = 1;

	natras->texture = rwgpu_texture_create(RWGPU_FORMAT_RGBA8, raster->width, raster->height, natras->numLevels, 0);
	if(natras->texture == 0){
		RWERROR((ERR_GENERAL, "rwgpu could not create a texture"));
		return nil;
	}
	return raster;
}

static Raster*
rasterCreateCameraTexture(Raster *raster)
{
	if(raster->format & (Raster::PAL4 | Raster::PAL8)){
		RWERROR((ERR_NOTEXTURE));
		return nil;
	}

	WgpuRaster *natras = GETWGPURASTEREXT(raster);
	switch(raster->format & 0xF00){
	case Raster::C8888:
	case Raster::C1555:
		natras->hasAlpha = 1;
		natras->bpp = 4;
		break;
	case Raster::C888:
	default:
		natras->hasAlpha = 0;
		natras->bpp = 3;
		break;
	}
	raster->stride = raster->width*natras->bpp;
	natras->autogenMipmap = 0;
	natras->texture = rwgpu_texture_create(RWGPU_FORMAT_RGBA8, raster->width, raster->height, 1, RWGPU_TEXTURE_RENDER_TARGET);
	if(natras->texture == 0){
		RWERROR((ERR_GENERAL, "rwgpu could not create a camera texture"));
		return nil;
	}
	return raster;
}

static Raster*
rasterCreateCamera(Raster *raster)
{
	WgpuRaster *natras = GETWGPURASTEREXT(raster);
	// used for locking right now
	raster->format = Raster::C888;
	natras->hasAlpha = 0;
	natras->bpp = 3;
	natras->autogenMipmap = 0;
	natras->texture = 0;
	return raster;
}

static Raster*
rasterCreateZbuffer(Raster *raster)
{
	WgpuRaster *natras = GETWGPURASTEREXT(raster);
	natras->autogenMipmap = 0;
	natras->depth = rwgpu_depth_create(raster->width, raster->height);
	return raster;
}

void
allocateDXT(Raster *raster, int32 dxt, int32 numLevels, bool32 hasAlpha)
{
	assert(raster->type == Raster::TEXTURE);

	WgpuRaster *natras = GETWGPURASTEREXT(raster);
	switch(dxt){
	case 1:
		// bogus, but stride*height should be the size of the image: 4x4 in 8 bytes
		raster->stride = raster->width/2;
		break;
	case 3:
	case 5:
		// 4x4 in 16 bytes
		raster->stride = raster->width;
		break;
	default:
		assert(0 && "invalid DXT format");
	}
	natras->compression = dxt;
	natras->hasAlpha = hasAlpha;
	natras->bpp = 2;
	raster->depth = 16;

	natras->isCompressed = 1;
	if(raster->format & Raster::MIPMAP)
		natras->numLevels = numLevels;
	// As in GL3: an automatically mipmapped raster keeps (and samples) one level.
	if((raster->format & (Raster::MIPMAP|Raster::AUTOMIPMAP)) == (Raster::MIPMAP|Raster::AUTOMIPMAP))
		natras->numLevels = 1;
	natras->autogenMipmap = 0;

	natras->texture = rwgpu_texture_create(bcFormat(dxt), raster->width, raster->height, natras->numLevels, 0);
	assert(natras->texture && "allocateDXT needs BC support and sizes that are multiples of 4");

	raster->originalStride = raster->stride;

	if(needToReadBackTextures){
		// Keep a copy in CPU memory so writing txd.img needs no readback.
		int32 i;
		int32 size = 0;
		for(i = 0; i < natras->numLevels; i++)
			size += getLevelSize(raster, i);
		uint8 *data = (uint8*)rwNew(sizeof(RasterLevels)+sizeof(RasterLevels::Level)*(natras->numLevels-1)+size,
			MEMDUR_EVENT | ID_DRIVER);
		RasterLevels *levels = (RasterLevels*)data;
		data += sizeof(RasterLevels)+sizeof(RasterLevels::Level)*(natras->numLevels-1);
		levels->numlevels = natras->numLevels;
		levels->format = 0;
		for(i = 0; i < natras->numLevels; i++){
			levels->levels[i].data = data;
			levels->levels[i].size = getLevelSize(raster, i);
			levels->levels[i].width = 0;
			levels->levels[i].height = 0;
			data += levels->levels[i].size;
		}
		natras->backingStore = levels;
	}

	raster->flags &= ~Raster::DONTALLOCATE;
}

Raster*
rasterCreate(Raster *raster)
{
	WgpuRaster *natras = GETWGPURASTEREXT(raster);

	natras->isCompressed = 0;
	natras->hasAlpha = 0;
	natras->numLevels = 1;
	natras->compression = 0;

	Raster *ret = raster;

	if(raster->width == 0 || raster->height == 0){
		raster->flags |= Raster::DONTALLOCATE;
		raster->stride = 0;
		goto ret;
	}
	if(raster->flags & Raster::DONTALLOCATE)
		goto ret;

	switch(raster->type){
	case Raster::NORMAL:
	case Raster::TEXTURE:
		ret = rasterCreateTexture(raster);
		break;
	case Raster::CAMERATEXTURE:
		ret = rasterCreateCameraTexture(raster);
		break;
	case Raster::ZBUFFER:
		ret = rasterCreateZbuffer(raster);
		break;
	case Raster::CAMERA:
		ret = rasterCreateCamera(raster);
		break;

	default:
		RWERROR((ERR_INVRASTER));
		return nil;
	}

ret:
	raster->originalWidth = raster->width;
	raster->originalHeight = raster->height;
	raster->originalStride = raster->stride;
	raster->originalPixels = raster->pixels;
	return ret;
}

/* Reads a level back from the GPU into the CPU layout. */
static void
readLevel(Raster *raster, int32 level, uint8 *px, uint32 size)
{
	WgpuRaster *natras = GETWGPURASTEREXT(raster);
	if(natras->isCompressed || natras->bpp == 4){
		rwgpu_texture_read(natras->texture, level, px, size);
		return;
	}
	// RGB8 rasters are RGBA8 on the GPU.
	uint32 n = size/3;
	uint8 *rgba = (uint8*)rwMalloc(n*4, MEMDUR_FUNCTION | ID_DRIVER);
	if(rwgpu_texture_read(natras->texture, level, rgba, n*4) == n*4)
		for(uint32 i = 0; i < n; i++)
			memcpy(px + i*3, rgba + i*4, 3);
	rwFree(rgba);
}

uint8*
rasterLock(Raster *raster, int32 level, int32 lockMode)
{
	WgpuRaster *natras = GETWGPURASTEREXT(raster);
	uint8 *px;
	uint32 allocSz;
	int i;

	assert(raster->privateFlags == 0);

	switch(raster->type){
	case Raster::NORMAL:
	case Raster::TEXTURE:
	case Raster::CAMERATEXTURE:
		for(i = 0; i < level; i++){
			if(raster->width > 1){
				raster->width /= 2;
				raster->stride /= 2;
			}
			if(raster->height > 1)
				raster->height /= 2;
		}

		allocSz = getLevelSize(raster, level);
		px = (uint8*)rwMalloc(allocSz, MEMDUR_EVENT | ID_DRIVER);
		assert(raster->pixels == nil);
		raster->pixels = px;

		if(lockMode & Raster::LOCKREAD || !(lockMode & Raster::LOCKNOFETCH)){
			if(natras->backingStore){
				assert(level < natras->backingStore->numlevels);
				assert(allocSz >= (uint32)natras->backingStore->levels[level].size);
				memcpy(px, natras->backingStore->levels[level].data, allocSz);
			}else
				readLevel(raster, level, px, allocSz);
		}

		raster->privateFlags = lockMode;
		break;

	case Raster::CAMERA:
		if(lockMode & Raster::PRIVATELOCK_WRITE)
			assert(0 && "can't lock framebuffer for writing");
		raster->width = wgpuGlobals.fbWidth;
		raster->height = wgpuGlobals.fbHeight;
		raster->stride = raster->width*natras->bpp;
		assert(natras->bpp == 3);
		allocSz = raster->height*raster->stride;
		px = (uint8*)rwMalloc(allocSz, MEMDUR_EVENT | ID_DRIVER);
		assert(raster->pixels == nil);
		raster->pixels = px;
		rwgpu_read_main(px, allocSz);

		raster->privateFlags = lockMode;
		break;

	default:
		assert(0 && "cannot lock this type of raster yet");
		return nil;
	}

	return px;
}

void
rasterUnlock(Raster *raster, int32 level)
{
	WgpuRaster *natras = GETWGPURASTEREXT(raster);

	assert(raster->pixels);

	switch(raster->type){
	case Raster::NORMAL:
	case Raster::TEXTURE:
	case Raster::CAMERATEXTURE:
		if(raster->privateFlags & Raster::LOCKWRITE){
			uint32 size = getLevelSize(raster, level);
			uint32 src = natras->bpp == 3 && !natras->isCompressed ? RWGPU_SRC_RGB8 : RWGPU_SRC_NATIVE;
			rwgpu_texture_upload(natras->texture, level, src, raster->pixels, size);
			if(natras->backingStore){
				assert(level < natras->backingStore->numlevels);
				memcpy(natras->backingStore->levels[level].data, raster->pixels,
					natras->backingStore->levels[level].size);
			}
		}
		break;

	case Raster::CAMERA:
		break;
	}

	rwFree(raster->pixels);
	raster->pixels = nil;
	raster->width = raster->originalWidth;
	raster->height = raster->originalHeight;
	raster->stride = raster->originalStride;
	raster->pixels = raster->originalPixels;
	raster->privateFlags = 0;
}

int32
rasterNumLevels(Raster *raster)
{
	return GETWGPURASTEREXT(raster)->numLevels;
}

// Same as GL3's
bool32
imageFindRasterFormat(Image *img, int32 type,
	int32 *pWidth, int32 *pHeight, int32 *pDepth, int32 *pFormat)
{
	int32 width, height, depth, format;

	assert((type&0xF) == Raster::TEXTURE);

	width = img->width;
	height = img->height;
	depth = img->depth;

	if(depth <= 8)
		depth = 32;

	switch(depth){
	case 32:
		if(img->hasAlpha())
			format = Raster::C8888;
		else{
			format = Raster::C888;
			depth = 24;
		}
		break;
	case 24:
		format = Raster::C888;
		break;
	case 16:
		format = Raster::C1555;
		break;

	case 8:
	case 4:
	default:
		RWERROR((ERR_INVRASTER));
		return 0;
	}

	format |= type;

	*pWidth = width;
	*pHeight = height;
	*pDepth = depth;
	*pFormat = format;

	return 1;
}

bool32
rasterFromImage(Raster *raster, Image *image)
{
	if((raster->type&0xF) != Raster::TEXTURE)
		return 0;

	void (*conv)(uint8 *out, uint8 *in) = nil;

	// Unpalettize image if necessary but don't change original
	Image *truecolimg = nil;
	if(image->depth <= 8){
		truecolimg = Image::create(image->width, image->height, image->depth);
		truecolimg->pixels = image->pixels;
		truecolimg->stride = image->stride;
		truecolimg->palette = image->palette;
		truecolimg->unpalettize();
		image = truecolimg;
	}

	WgpuRaster *natras = GETWGPURASTEREXT(raster);
	assert(!natras->isCompressed);
	switch(image->depth){
	case 32:
		conv = natras->bpp == 4 ? conv_RGBA8888_from_RGBA8888 : conv_RGB888_from_RGB888;
		break;
	case 24:
		conv = natras->bpp == 4 ? conv_RGBA8888_from_RGB888 : conv_RGB888_from_RGB888;
		break;
	case 16:
		if(natras->bpp != 4)
			goto err;
		conv = conv_RGBA8888_from_ARGB1555;
		break;

	case 8:
	case 4:
	default:
	err:
		if(truecolimg)
			truecolimg->destroy();
		RWERROR((ERR_INVRASTER));
		return 0;
	}

	natras->hasAlpha = image->hasAlpha();

	bool unlock = false;
	if(raster->pixels == nil){
		raster->lock(0, Raster::LOCKWRITE|Raster::LOCKNOFETCH);
		unlock = true;
	}

	uint8 *pixels = raster->pixels;
	assert(pixels);
	uint8 *imgpixels = image->pixels;

	int x, y;
	assert(image->width == raster->width);
	assert(image->height == raster->height);
	for(y = 0; y < image->height; y++){
		uint8 *imgrow = imgpixels;
		uint8 *rasrow = pixels;
		for(x = 0; x < image->width; x++){
			conv(rasrow, imgrow);
			imgrow += image->bpp;
			rasrow += natras->bpp;
		}
		imgpixels += image->stride;
		pixels += raster->stride;
	}
	if(unlock)
		raster->unlock(0);

	if(truecolimg)
		truecolimg->destroy();

	return 1;
}

Image*
rasterToImage(Raster *raster)
{
	int32 depth;
	Image *image;

	WgpuRaster *natras = GETWGPURASTEREXT(raster);
	if(natras->isCompressed){
		// TODO, as in GL3
		RWERROR((ERR_INVRASTER));
		return nil;
	}
	if(raster->format & Raster::PAL4 ||
	   raster->format & Raster::PAL8){
		RWERROR((ERR_INVRASTER));
		return nil;
	}

	void (*conv)(uint8 *out, uint8 *in) = nil;
	if(natras->bpp == 4){
		depth = 32;
		conv = conv_RGBA8888_from_RGBA8888;
	}else if(natras->bpp == 3){
		depth = 24;
		conv = conv_RGB888_from_RGB888;
	}else{
		RWERROR((ERR_INVRASTER));
		return nil;
	}

	bool unlock = false;
	if(raster->pixels == nil){
		raster->lock(0, Raster::LOCKREAD);
		unlock = true;
	}

	image = Image::create(raster->width, raster->height, depth);
	image->allocate();

	uint8 *imgpixels = image->pixels;
	uint8 *pixels = raster->pixels;

	int x, y;
	assert(image->width == raster->width);
	assert(image->height == raster->height);
	for(y = 0; y < image->height; y++){
		uint8 *imgrow = imgpixels;
		uint8 *rasrow = pixels;
		for(x = 0; x < image->width; x++){
			conv(imgrow, rasrow);
			imgrow += image->bpp;
			rasrow += natras->bpp;
		}
		imgpixels += image->stride;
		pixels += raster->stride;
	}

	if(unlock)
		raster->unlock(0);

	return image;
}

static void*
createNativeRaster(void *object, int32 offset, int32)
{
	WgpuRaster *ras = PLUGINOFFSET(WgpuRaster, object, offset);
	ras->texture = 0;
	ras->depth = 0;
	ras->backingStore = nil;
	ras->compression = 0;
	return object;
}

static void*
destroyNativeRaster(void *object, int32 offset, int32)
{
	Raster *raster = (Raster*)object;
	WgpuRaster *natras = PLUGINOFFSET(WgpuRaster, object, offset);
	evictRaster(raster);
	if(natras->texture)
		rwgpu_texture_destroy(natras->texture);
	if(natras->depth)
		rwgpu_depth_destroy(natras->depth);
	natras->texture = 0;
	natras->depth = 0;
	rwFree(natras->backingStore);
	natras->backingStore = nil;
	return object;
}

static void*
copyNativeRaster(void *dst, void *, int32 offset, int32)
{
	WgpuRaster *d = PLUGINOFFSET(WgpuRaster, dst, offset);
	d->texture = 0;
	d->depth = 0;
	d->backingStore = nil;
	return dst;
}

Texture*
readNativeTexture(Stream *stream)
{
	uint32 platform;
	if(!findChunk(stream, ID_STRUCT, nil, nil)){
		RWERROR((ERR_CHUNK, "STRUCT"));
		return nil;
	}
	platform = stream->readU32();
	if(platform != PLATFORM_WGPU){
		RWERROR((ERR_PLATFORM, platform));
		return nil;
	}
	Texture *tex = Texture::create(nil);
	if(tex == nil)
		return nil;

	// Texture
	tex->filterAddressing = stream->readU32();
	stream->read8(tex->name, 32);
	stream->read8(tex->mask, 32);

	// Raster
	uint32 format = stream->readU32();
	int32 width = stream->readI32();
	int32 height = stream->readI32();
	int32 depth = stream->readI32();
	int32 numLevels = stream->readI32();

	// Native raster
	stream->readI32();	// reserved (GL3's subplatform)
	int32 flags = stream->readI32();
	int32 compression = stream->readI32();

	Raster *raster;
	if(flags & 2){
		if(!caps.dxtSupported || width % 4 || height % 4){
			tex->destroy();
			RWERROR((ERR_FORMAT_UNSUPPORTED));
			return nil;
		}
		raster = Raster::create(width, height, depth, format | Raster::TEXTURE | Raster::DONTALLOCATE, PLATFORM_WGPU);
		allocateDXT(raster, compression, numLevels, flags & 1);
	}else{
		raster = Raster::create(width, height, depth, format | Raster::TEXTURE, PLATFORM_WGPU);
	}
	if(raster == nil){
		tex->destroy();
		return nil;
	}
	// As in GL3, an uncompressed raster's alpha follows its format, not the flags.
	tex->raster = raster;

	uint32 size;
	uint8 *data;
	for(int32 i = 0; i < numLevels; i++){
		size = stream->readU32();
		data = raster->lock(i, Raster::LOCKWRITE|Raster::LOCKNOFETCH);
		stream->read8(data, size);
		raster->unlock(i);
	}
	return tex;
}

void
writeNativeTexture(Texture *tex, Stream *stream)
{
	Raster *raster = tex->raster;
	WgpuRaster *natras = GETWGPURASTEREXT(raster);

	int32 chunksize = getSizeNativeTexture(tex);
	writeChunkHeader(stream, ID_STRUCT, chunksize-12);
	stream->writeU32(PLATFORM_WGPU);

	// Texture
	stream->writeU32(tex->filterAddressing);
	stream->write8(tex->name, 32);
	stream->write8(tex->mask, 32);

	// Raster
	int32 numLevels = natras->numLevels;
	stream->writeI32(raster->format);
	stream->writeI32(raster->width);
	stream->writeI32(raster->height);
	stream->writeI32(raster->depth);
	stream->writeI32(numLevels);

	// Native raster
	int32 flags = 0;
	if(natras->hasAlpha)
		flags |= 1;
	if(natras->isCompressed)
		flags |= 2;
	stream->writeI32(0);
	stream->writeI32(flags);
	stream->writeI32(natras->isCompressed ? natras->compression : 0);

	uint32 size;
	uint8 *data;
	for(int32 i = 0; i < numLevels; i++){
		size = getLevelSize(raster, i);
		stream->writeU32(size);
		data = raster->lock(i, Raster::LOCKREAD);
		stream->write8(data, size);
		raster->unlock(i);
	}
}

uint32
getSizeNativeTexture(Texture *tex)
{
	uint32 size = 12 + 72 + 32;
	int32 levels = tex->raster->getNumLevels();
	for(int32 i = 0; i < levels; i++)
		size += 4 + getLevelSize(tex->raster, i);
	return size;
}

void registerNativeRaster(void)
{
	nativeRasterOffset = Raster::registerPlugin(sizeof(WgpuRaster),
	                                            ID_RASTERWGPU,
	                                            createNativeRaster,
	                                            destroyNativeRaster,
	                                            copyNativeRaster);
}

}
}

#endif
