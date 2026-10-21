//! rwgpu: the wgpu renderer behind librw's WGPU platform (see the Phase 2 design in
//! `docs/superpowers/specs/2026-10-21-phase2-wgpu-renderer-design.md`).

pub mod abi;
pub mod convert;
pub mod dump;
pub mod ffi;
pub mod pipeline;
pub mod renderer;
pub mod shaders;
pub mod state;
