# Fedora / RPM spec. Build from a source checkout with packaging/build-rpm.sh,
# or use it on COPR (Source0 points at the tagged release).
%global srcname monctl

Name:           monctl
Version:        0.6.0
Release:        1%{?dist}
Summary:        Monitor control: profiles, per-game profiles, tray app
License:        MIT
URL:            https://github.com/doodersrage/monctl
Source0:        %{url}/archive/refs/tags/v%{version}/%{srcname}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  python3-devel
Requires:       python3
Requires:       ddcutil
Recommends:     python3-pyqt6
Recommends:     python3-dbus
Recommends:     python3-gobject

%description
Profiles across all monitors, applied automatically while a game runs, on a
schedule or from global keyboard shortcuts. Brightness, contrast and input over
DDC/CI for any monitor, and MSI on-screen settings (game mode, Night Vision,
crosshair...) over USB through msigd. Includes a settings window, a tray icon
and a command line tool.

%prep
%autosetup -n %{srcname}-%{version}

%build

%install
mkdir -p %{buildroot}%{python3_sitelib} %{buildroot}%{_bindir}
cp -r monctl %{buildroot}%{python3_sitelib}/
find %{buildroot} -name __pycache__ -prune -exec rm -rf {} +
cat > %{buildroot}%{_bindir}/monctl <<'PY'
#!/usr/bin/python3
from monctl.cli import main
raise SystemExit(main())
PY
chmod 755 %{buildroot}%{_bindir}/monctl
./install-files.sh %{buildroot}
# rpm puts the license and docs itself
rm -rf %{buildroot}%{_datadir}/licenses %{buildroot}%{_docdir}

%files
%license LICENSE
%doc README.md CHANGELOG.md
%{_bindir}/monctl
%{python3_sitelib}/monctl/
%{_datadir}/applications/monctl.desktop
%{_metainfodir}/io.github.doodersrage.monctl.metainfo.xml
%{_mandir}/man1/monctl.1*
%{_datadir}/bash-completion/completions/monctl
%{_datadir}/zsh/site-functions/_monctl
%{_datadir}/fish/vendor_completions.d/monctl.fish

%changelog
* Thu Nov 19 2026 Robert McDowell <1476679+doodersrage@users.noreply.github.com> - 0.6.0-1
- Shell completions, man page, AppStream metadata, COPR packaging
* Thu Nov 19 2026 Robert McDowell <1476679+doodersrage@users.noreply.github.com> - 0.5.0-1
- Steam game picker; Debian, Fedora and Arch packages
