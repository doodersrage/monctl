#!/bin/sh
# Build the Debian/Ubuntu package with the debian/ packaging:  packaging/build-deb.sh [outdir]
# Needs: build-essential debhelper dh-python python3-pytest (dpkg-buildpackage runs the tests).
set -e
src=$(cd "$(dirname "$0")/.." && pwd)
out=${1:-$src/dist}
version=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$src/monctl/__init__.py")
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
# build from a clean copy (like a release tarball)
mkdir "$work/monctl-$version"
(cd "$src" && tar --exclude=.git --exclude=__pycache__ --exclude=./pkg --exclude=./src \
    --exclude='*.pkg.tar.zst' --exclude=./dist --exclude=./build --exclude='*.egg-info' \
    --exclude=.pytest_cache --exclude=./packaging/aur -cf - .) | tar -C "$work/monctl-$version" -xf -
# the package version follows monctl/__init__.py
sed -i "1s/^monctl ([^)]*)/monctl ($version)/" "$work/monctl-$version/debian/changelog"
(cd "$work/monctl-$version" && dpkg-buildpackage -us -uc -b)
mkdir -p "$out"
cp "$work"/monctl_*_all.deb "$out/"
