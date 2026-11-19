#!/bin/sh
# Build an RPM from this source tree:  packaging/build-rpm.sh [--srpm] [outdir]   (needs rpm-build)
# --srpm builds only the source RPM (what Fedora COPR does).
set -e
srpm=
if [ "$1" = --srpm ]; then srpm=1; shift; fi
src=$(cd "$(dirname "$0")/.." && pwd)
out=${1:-$src/dist}
version=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$src/monctl/__init__.py")
top=$(mktemp -d)
trap 'rm -rf "$top"' EXIT
mkdir -p "$top/SOURCES" "$top/staging/monctl-$version"
(cd "$src" && tar --exclude=.git --exclude=__pycache__ --exclude=./pkg --exclude=./src \
    --exclude='*.pkg.tar.zst' --exclude=./dist --exclude=./build --exclude='*.egg-info' \
    --exclude=.pytest_cache --exclude=./packaging/aur -cf - .) | tar -C "$top/staging/monctl-$version" -xf -
tar -C "$top/staging" -czf "$top/SOURCES/monctl-$version.tar.gz" "monctl-$version"
sed "s/^Version:.*/Version:        $version/" "$src/packaging/monctl.spec" > "$top/monctl.spec"
mkdir -p "$out"
if [ -n "$srpm" ]; then
    rpmbuild -bs --define "_topdir $top" "$top/monctl.spec"
    cp "$top"/SRPMS/*.src.rpm "$out/"
else
    rpmbuild -bb --define "_topdir $top" "$top/monctl.spec"
    cp "$top"/RPMS/noarch/*.rpm "$out/"
fi
