# Publishing monctl

Every release puts `.pkg.tar.zst`, `.deb` and `.rpm` packages on the GitHub release page
automatically: bump `__version__` in `monctl/__init__.py`, add a `## X.Y.Z` section to
`CHANGELOG.md` (it becomes the release notes) and a `<release>` to
`data/io.github.doodersrage.monctl.metainfo.xml`, then push a tag `vX.Y.Z`. Running the
*release* workflow by hand builds the packages without publishing anything.

The channels below give users automatic updates through their package manager; each needs an
account once.

## Fedora: COPR

1. Sign in at <https://copr.fedorainfracloud.org> with a Fedora account (free).
2. *New project* `monctl`, chroots: the current Fedora releases (e.g. `fedora-*-x86_64`; the package is `noarch`).
3. *Packages → New package → SCM*:
   - Clone URL: `https://github.com/doodersrage/monctl`
   - Committish: the release tag, e.g. `v0.6.0` (or leave empty for the latest code)
   - Build SRPM with: **make srpm** (uses `.copr/Makefile`)
4. *Rebuild*. Optionally add a GitHub webhook (COPR → Settings → Integrations) to build every tag.

Users then install with:

```sh
sudo dnf copr enable doodersrage/monctl
sudo dnf install monctl
```

## Ubuntu: Launchpad PPA

One-time setup:
1. Create a Launchpad account, upload your GPG key and sign the Ubuntu Code of Conduct.
2. Create a PPA named `monctl` (<https://launchpad.net/~YOUR-ID/+activate-ppa>).
3. `sudo apt install devscripts debhelper dh-python dput`

For each release and Ubuntu series (Launchpad needs one upload per series, e.g. `jammy`, `noble`):

```sh
git checkout v0.6.0
dch -v "0.6.0~noble1" -D noble "New upstream release."   # edits debian/changelog (don't commit this)
debuild -S -sa                                          # signed source package in ../
dput ppa:YOUR-ID/monctl ../monctl_0.6.0~noble1_source.changes
git checkout debian/changelog
```

Users then install with:

```sh
sudo add-apt-repository ppa:YOUR-ID/monctl
sudo apt install monctl
```

Ubuntu 22.04 (jammy) has Python 3.10, the oldest monctl supports.

## Arch: AUR

New AUR account registration was closed at the time of writing. The package name `monctl` is
taken on the AUR by an unrelated project, so this one is `monctl-msi` (`packaging/aur/`).

1. Create an AUR account and add your SSH public key.
2. After tagging a release: in `packaging/aur/`, set `pkgver`, run `updpkgsums` and
   `makepkg --printsrcinfo > .SRCINFO`.
3. `git clone ssh://aur@aur.archlinux.org/monctl-msi.git`, copy `PKGBUILD` and `.SRCINFO` into it,
   commit and push.
