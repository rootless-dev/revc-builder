//! Frame dumps and frame statistics (design §9).

use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DumpConfig {
    pub dir: Option<PathBuf>,
    pub frames: BTreeSet<u64>,
    /// Print statistics every this many frames; 0 is off.
    pub stats_every: u64,
}

impl DumpConfig {
    pub fn from_env() -> Self {
        Self::parse(
            std::env::var("REVC_FRAME_DUMP_DIR").ok().as_deref(),
            std::env::var("REVC_FRAME_DUMP_FRAMES").ok().as_deref(),
            std::env::var("REVC_FRAME_STATS").ok().as_deref(),
        )
    }

    pub fn parse(dir: Option<&str>, frames: Option<&str>, stats: Option<&str>) -> Self {
        let dir = dir.filter(|d| !d.is_empty()).map(PathBuf::from);
        let frames = frames
            .unwrap_or("")
            .split(',')
            .filter_map(|f| f.trim().parse::<u64>().ok())
            .filter(|&f| f > 0)
            .collect();
        let stats_every = stats.and_then(|s| s.trim().parse::<u64>().ok()).unwrap_or(0);
        DumpConfig {
            dir,
            frames,
            stats_every,
        }
    }

    /// Where frame `frame` (1 = first presented) is written, if it is to be dumped.
    pub fn path_for(&self, frame: u64) -> Option<PathBuf> {
        let dir = self.dir.as_ref()?;
        self.frames
            .contains(&frame)
            .then(|| dir.join(format!("frame-{frame:06}.png")))
    }
}

/// Counts presented frames and reports the mean interval between presents every
/// `every` frames.
#[derive(Debug)]
pub struct FrameStats {
    every: u64,
    frames: u64,
    /// Time and frame count of the present that opened the current window.
    window_start: Option<(Instant, u64)>,
}

impl FrameStats {
    pub fn new(every: u64) -> Self {
        FrameStats {
            every,
            frames: 0,
            window_start: None,
        }
    }

    pub fn frames(&self) -> u64 {
        self.frames
    }

    /// Records a presented frame; returns the line to print when a window is complete.
    pub fn record(&mut self, now: Instant) -> Option<String> {
        self.frames += 1;
        if self.every == 0 {
            return None;
        }
        let (start, start_frame) = *self.window_start.get_or_insert((now, self.frames));
        if self.frames.is_multiple_of(self.every) && self.frames > start_frame {
            let line = Self::line(self.frames, now - start, self.frames - start_frame);
            self.window_start = Some((now, self.frames));
            return Some(line);
        }
        None
    }

    /// `intervals` presents took `elapsed` in total.
    pub fn line(total: u64, elapsed: Duration, intervals: u64) -> String {
        let avg_ms = elapsed.as_secs_f64() * 1000.0 / intervals.max(1) as f64;
        let fps = if avg_ms > 0.0 { 1000.0 / avg_ms } else { 0.0 };
        format!("frame-stats: frames={total} avg_ms={avg_ms:.3} fps={fps:.1}")
    }
}

/// Writes top-down RGB8 pixels as a PNG.
pub fn write_png(path: &Path, width: u32, height: u32, rgb: &[u8]) -> Result<(), String> {
    let file = std::fs::File::create(path).map_err(|e| format!("{}: {e}", path.display()))?;
    let mut encoder = png::Encoder::new(std::io::BufWriter::new(file), width, height);
    encoder.set_color(png::ColorType::Rgb);
    encoder.set_depth(png::BitDepth::Eight);
    let mut writer = encoder.write_header().map_err(|e| e.to_string())?;
    writer.write_image_data(rgb).map_err(|e| e.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_dump_configuration() {
        let c = DumpConfig::parse(Some("/tmp/x"), Some("3, 10,bad,0,10"), Some("120"));
        assert_eq!(c.frames.iter().copied().collect::<Vec<_>>(), vec![3, 10]);
        assert_eq!(c.stats_every, 120);
        assert_eq!(c.path_for(10), Some(PathBuf::from("/tmp/x/frame-000010.png")));
        assert_eq!(c.path_for(4), None);
    }

    #[test]
    fn dumping_is_off_without_a_directory() {
        let c = DumpConfig::parse(None, Some("1"), None);
        assert_eq!(c.path_for(1), None);
        assert_eq!(c.stats_every, 0);
        assert_eq!(DumpConfig::parse(Some(""), Some("1"), Some("x")).path_for(1), None);
    }

    #[test]
    fn stats_report_every_n_frames() {
        let mut s = FrameStats::new(2);
        let t0 = Instant::now();
        assert_eq!(s.record(t0), None);
        let line = s.record(t0 + Duration::from_millis(20)).unwrap();
        assert_eq!(line, "frame-stats: frames=2 avg_ms=20.000 fps=50.0");
        assert_eq!(s.record(t0 + Duration::from_millis(30)), None);
        let line = s.record(t0 + Duration::from_millis(40)).unwrap();
        assert_eq!(line, "frame-stats: frames=4 avg_ms=10.000 fps=100.0");
        assert_eq!(FrameStats::new(0).record(t0), None);
    }

    #[test]
    fn png_round_trips() {
        let dir = std::env::temp_dir().join(format!("rwgpu-png-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("t.png");
        let rgb = [255, 0, 0, 0, 255, 0, 0, 0, 255, 9, 9, 9];
        write_png(&path, 2, 2, &rgb).unwrap();
        let decoder = png::Decoder::new(std::io::BufReader::new(std::fs::File::open(&path).unwrap()));
        let mut reader = decoder.read_info().unwrap();
        let mut buf = vec![0; reader.output_buffer_size().unwrap()];
        let info = reader.next_frame(&mut buf).unwrap();
        assert_eq!((info.width, info.height), (2, 2));
        assert_eq!(&buf[..12], &rgb);
        std::fs::remove_dir_all(&dir).unwrap();
    }
}
