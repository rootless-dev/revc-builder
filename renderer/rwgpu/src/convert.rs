//! CPU-side conversions that need no GPU: pixel formats, mipmaps, block sizes and
//! primitive types.

use crate::abi::*;

/// Expands tightly packed RGB8 rows to RGBA8 with alpha 255.
pub fn rgb8_to_rgba8(rgb: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(rgb.len() / 3 * 4);
    for px in rgb.chunks_exact(3) {
        out.extend_from_slice(&[px[0], px[1], px[2], 255]);
    }
    out
}

/// Drops the alpha channel of RGBA8 pixels.
pub fn rgba8_to_rgb8(rgba: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(rgba.len() / 4 * 3);
    for px in rgba.chunks_exact(4) {
        out.extend_from_slice(&px[..3]);
    }
    out
}

/// Size of mip level `level` of a `width`×`height` texture (each side at least 1).
pub fn level_extent(width: u32, height: u32, level: u32) -> (u32, u32) {
    ((width >> level).max(1), (height >> level).max(1))
}

/// Number of levels in a full mip chain: `floor(log2(max(w, h))) + 1`.
pub fn full_chain_levels(width: u32, height: u32) -> u32 {
    32 - width.max(height).max(1).leading_zeros()
}

/// The next level of an RGBA8 image with a 2×2 box filter (edges repeat when a side is 1).
pub fn downsample_rgba8(src: &[u8], width: u32, height: u32) -> (Vec<u8>, u32, u32) {
    let (w, h) = ((width / 2).max(1), (height / 2).max(1));
    let mut out = vec![0u8; (w * h * 4) as usize];
    for y in 0..h {
        for x in 0..w {
            let x0 = (x * 2).min(width - 1);
            let x1 = (x * 2 + 1).min(width - 1);
            let y0 = (y * 2).min(height - 1);
            let y1 = (y * 2 + 1).min(height - 1);
            for c in 0..4 {
                let at = |xx: u32, yy: u32| src[((yy * width + xx) * 4 + c) as usize] as u32;
                let sum = at(x0, y0) + at(x1, y0) + at(x0, y1) + at(x1, y1);
                out[((y * w + x) * 4 + c) as usize] = ((sum + 2) / 4) as u8;
            }
        }
    }
    (out, w, h)
}

/// Bytes per 4×4 block of a BC format, or `None` for uncompressed formats.
pub fn block_bytes(format: u32) -> Option<u32> {
    match format {
        FORMAT_BC1 => Some(8),
        FORMAT_BC2 | FORMAT_BC3 => Some(16),
        _ => None,
    }
}

/// `(bytes per row, rows)` of a tightly packed level as uploaded: rows of pixels, or rows of
/// 4×4 blocks for BC formats (a level smaller than a block still takes a whole block).
pub fn level_layout(format: u32, width: u32, height: u32) -> (u32, u32) {
    match block_bytes(format) {
        Some(bytes) => (width.div_ceil(4) * bytes, height.div_ceil(4)),
        None => (width * 4, height),
    }
}

/// Index list for a primitive that wgpu cannot draw directly: triangle fans become lists.
/// `indices` is `None` for non-indexed draws of `count` vertices.
pub fn fan_to_list(indices: Option<&[u16]>, count: usize) -> Vec<u16> {
    let get = |i: usize| -> u16 { indices.map_or(i as u16, |ix| ix[i]) };
    let mut out = Vec::with_capacity(count.saturating_sub(2) * 3);
    for i in 1..count.saturating_sub(1) {
        out.extend_from_slice(&[get(0), get(i), get(i + 1)]);
    }
    out
}

/// Pads `data` with zero bytes to a multiple of 4 (`Queue::write_buffer` needs it).
pub fn pad4(data: &[u8]) -> std::borrow::Cow<'_, [u8]> {
    if data.len().is_multiple_of(4) {
        std::borrow::Cow::Borrowed(data)
    } else {
        let mut v = data.to_vec();
        v.resize(data.len().next_multiple_of(4), 0);
        std::borrow::Cow::Owned(v)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rgb8_expands_with_opaque_alpha() {
        assert_eq!(rgb8_to_rgba8(&[1, 2, 3, 4, 5, 6]), vec![1, 2, 3, 255, 4, 5, 6, 255]);
        assert_eq!(rgba8_to_rgb8(&[1, 2, 3, 9, 4, 5, 6, 9]), vec![1, 2, 3, 4, 5, 6]);
    }

    #[test]
    fn full_chain_matches_floor_log2_plus_one() {
        assert_eq!(full_chain_levels(1, 1), 1);
        assert_eq!(full_chain_levels(2, 1), 2);
        assert_eq!(full_chain_levels(256, 64), 9);
        assert_eq!(full_chain_levels(255, 3), 8);
        assert_eq!(level_extent(256, 64, 7), (2, 1));
        assert_eq!(level_extent(256, 64, 8), (1, 1));
    }

    #[test]
    fn box_filter_averages_with_rounding() {
        let src = [0, 0, 0, 0, 255, 255, 255, 255, 255, 255, 255, 255, 1, 1, 1, 1];
        let (out, w, h) = downsample_rgba8(&src, 2, 2);
        assert_eq!((w, h), (1, 1));
        assert_eq!(out, vec![128, 128, 128, 128]);
        // A 2x1 image: the single row is used twice.
        let (out, w, h) = downsample_rgba8(&[10, 10, 10, 10, 20, 20, 20, 20], 2, 1);
        assert_eq!((w, h, out), (1, 1, vec![15, 15, 15, 15]));
    }

    #[test]
    fn bc_levels_round_up_to_whole_blocks() {
        assert_eq!(level_layout(FORMAT_BC1, 64, 32), (128, 8));
        assert_eq!(level_layout(FORMAT_BC3, 2, 2), (16, 1));
        assert_eq!(level_layout(FORMAT_BC2, 1, 1), (16, 1));
        assert_eq!(level_layout(FORMAT_RGBA8, 3, 2), (12, 2));
    }

    #[test]
    fn fans_become_lists() {
        assert_eq!(fan_to_list(None, 5), vec![0, 1, 2, 0, 2, 3, 0, 3, 4]);
        assert_eq!(fan_to_list(Some(&[7, 8, 9, 10]), 4), vec![7, 8, 9, 7, 9, 10]);
        assert!(fan_to_list(None, 2).is_empty());
        assert!(fan_to_list(None, 0).is_empty());
    }

    #[test]
    fn padding_reaches_a_multiple_of_four() {
        assert_eq!(pad4(&[1, 2]).as_ref(), &[1, 2, 0, 0]);
        assert_eq!(pad4(&[1, 2, 3, 4]).len(), 4);
        assert_eq!(pad4(&[]).len(), 0);
    }
}
