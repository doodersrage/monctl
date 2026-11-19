# Builds the package from this source checkout:  makepkg -si
pkgname=monctl
pkgver=0.2.1
pkgrel=1
pkgdesc="Monitor control for Linux: profiles, tray, DDC/CI brightness and MSI OSD settings over USB"
arch=('any')
url="https://github.com/doodersrage/monctl"
license=('MIT')
depends=('python' 'ddcutil')
makedepends=('python-build' 'python-installer' 'python-setuptools' 'python-wheel')
checkdepends=('python-pytest')
optdepends=('python-pyqt6: tray icon and window'
            'msigd: MSI monitor settings over USB (needs a build with your model, e.g. the doodersrage fork)')

build() {
  cd "$startdir"
  rm -rf "$srcdir/dist"
  /usr/bin/python -m build --wheel --no-isolation --outdir "$srcdir/dist"
}

check() {
  cd "$startdir"
  QT_QPA_PLATFORM=offscreen /usr/bin/python -m pytest -q -p no:cacheprovider
}

package() {
  /usr/bin/python -m installer --destdir="$pkgdir" "$srcdir"/dist/*.whl
  install -Dm644 "$startdir/data/monctl.desktop" "$pkgdir/usr/share/applications/monctl.desktop"
  install -Dm644 "$startdir/LICENSE" "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
