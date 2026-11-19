#!/bin/sh
# Install the non-Python files into a package root:  ./install-files.sh DESTDIR
# Used by the Debian and RPM packaging (the Arch PKGBUILD installs the same files).
set -e
dest=${1:?usage: install-files.sh DESTDIR}
install -Dm644 data/monctl.desktop "$dest/usr/share/applications/monctl.desktop"
install -Dm644 LICENSE "$dest/usr/share/licenses/monctl/LICENSE"
