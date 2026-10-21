#!/bin/sh
# Builds the rwgpu release archive (design §7.2 and §11):
#   <out>/rwgpu-<version>/{lib/librwgpu.a, lib/link-libs.txt, include/rwgpu.h, LICENSE,
#                          THIRD_PARTY_LICENSES.txt}
#   <out>/rwgpu-<version>-macos-universal.tar.gz
# The directory is also what `python -m vcbuilder --rwgpu-dir` expects.
#
# Usage: renderer/build-universal.sh [out-dir]       (default: renderer/target/dist)
# RWGPU_ARCHS="arm64" builds a single-architecture library for quick local tests.
set -eu
cd "$(dirname "$0")"
out=${1:-target/dist}
archs=${RWGPU_ARCHS:-"arm64 x86_64"}
version=$(sed -n 's/^version = "\(.*\)"$/\1/p' rwgpu/Cargo.toml | head -n 1)

libs=""
for arch in $archs; do
    case $arch in
        arm64) target=aarch64-apple-darwin; floor=11.0 ;;
        x86_64) target=x86_64-apple-darwin; floor=10.15 ;;
        *) echo "unknown architecture $arch" >&2; exit 1 ;;
    esac
    MACOSX_DEPLOYMENT_TARGET=$floor cargo build --release --locked -p rwgpu --target "$target"
    libs="$libs target/$target/release/librwgpu.a"
done

stage="$out/rwgpu-$version"
rm -rf "$stage"
mkdir -p "$stage/lib" "$stage/include"
# shellcheck disable=SC2086
lipo -create $libs -output "$stage/lib/librwgpu.a"
cp include/rwgpu.h "$stage/include/"
cp link-libs.txt "$stage/lib/"
cp ../LICENSE "$stage/LICENSE"
python3 collect-licenses.py > "$stage/THIRD_PARTY_LICENSES.txt"
tar -czf "$out/rwgpu-$version-macos-universal.tar.gz" -C "$out" "rwgpu-$version"
lipo -archs "$stage/lib/librwgpu.a"
echo "$stage"
