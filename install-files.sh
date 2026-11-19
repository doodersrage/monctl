#!/bin/sh
# Install (or remove) everything except the Python package itself.
#   sudo ./install-files.sh /               install into the system
#   sudo ./install-files.sh --uninstall /   remove those files again
# Also used by the PKGBUILDs, debian/rules and the RPM spec to stage files into the package.
set -e
uninstall=
if [ "$1" = "--uninstall" ]; then uninstall=1; shift; fi
root=${1:?usage: install-files.sh [--uninstall] DESTDIR}
src=$(dirname "$0")

# source  destination
files="
data/monctl.desktop                         usr/share/applications/monctl.desktop
data/io.github.doodersrage.monctl.metainfo.xml usr/share/metainfo/io.github.doodersrage.monctl.metainfo.xml
completions/monctl.bash                     usr/share/bash-completion/completions/monctl
completions/_monctl                         usr/share/zsh/site-functions/_monctl
completions/monctl.fish                     usr/share/fish/vendor_completions.d/monctl.fish
docs/monctl.1                               usr/share/man/man1/monctl.1
README.md                                   usr/share/doc/monctl/README.md
CHANGELOG.md                                usr/share/doc/monctl/CHANGELOG.md
LICENSE                                     usr/share/licenses/monctl/LICENSE
"

echo "$files" | while read -r from to; do
    [ -n "$from" ] || continue
    if [ -n "$uninstall" ]; then
        rm -f "$root/$to"
    else
        install -Dm644 "$src/$from" "$root/$to"
    fi
done
if [ -n "$uninstall" ]; then
    rmdir "$root/usr/share/doc/monctl" "$root/usr/share/licenses/monctl" 2>/dev/null || true
fi
