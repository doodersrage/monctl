# Changelog

## 0.6.0

- Shell completions for bash, zsh and fish, and a man page (`man monctl`).
- AppStream metadata, so monctl shows up in software centres such as KDE Discover.
- Fedora COPR build support (`.copr/Makefile`) and a publishing guide (`packaging/PUBLISHING.md`).
- README: tray menu screenshot.

## 0.5.0

- Steam game picker: rules can match one installed game (`steam:<appid>`), chosen by name in the
  rule dialog; `monctl auto games` lists them.
- Packages for Arch, Debian/Ubuntu and Fedora on every release.
- Game-mode and Night Vision values show as FPS, RTS, RPG and AI.
- Requires Python 3.10 or newer.

## 0.4.0

- Brightness matching: a per-monitor range for the "all monitors" level (`monctl range`).
- Schedule: apply profiles at times of day (`monctl schedule`); after a game, automatic profiles
  return to the scheduled profile.
- Input switching over DDC/CI and on MSI monitors; hidden for monitors that ignore it.
- "Only while focused" rules on KDE Plasma.

## 0.3.0

- Global keyboard shortcuts through the XDG GlobalShortcuts portal.
- Monitors that come back after being off, unplugged or asleep are re-detected and a profile that
  skipped them is finished on them.

## 0.2.2

- The tray logs unexpected errors to `~/.local/state/monctl/tray.log` instead of crashing.

## 0.2.1

- Steam games are also detected through Steam's launcher; Steam's own container helpers are ignored.

## 0.2.0

- Automatic profiles: switch while an app or any Steam game runs, switch back when it exits.

## 0.1.0

- First version: CLI, profiles, tray icon and window; MSI settings over USB through msigd,
  brightness and contrast over DDC/CI for other monitors.
