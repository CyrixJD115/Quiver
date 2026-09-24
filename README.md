# quiver — the AppImage quiver

`quiver` installs, registers, updates, launches and cleans up AppImages on Linux.
It is a real package-manager-style utility — a registry of *managed* apps,
pluggable upstream update providers, safe atomic updates with rollback, and
XDG-correct desktop integration.

## Safety model (read this first)

- **Only registered apps are managed.** Finding an AppImage on your disk does
  nothing. `scan` and `doctor` are read-only; nothing outside the registry is
  ever modified, moved or deleted by `update`, `clean`, `fix`, etc.
- **Desktop entries are ownership-marked** (`X-Quiver=managed`). Files without
  the marker belong to something else (waydroid, wine, your DE) and are never
  touched. The one exception is *adoption*: when you import an AppImage, an
  existing unmanaged entry whose `Exec` points exactly at that file gets
  rewritten to point at the managed copy — and even if a desktop tool later
  strips the markers, registry-based ownership detection still recognizes it.
- **Updates never destroy the working file.** Downloads go to a `.part` file,
  are verified (AppImage magic bytes, architecture, size, sha256 when the
  provider publishes one), the current file is backed up, and only then does
  an atomic `rename` swap it in. Failures leave the old file untouched.
- **Destructive commands confirm first** and all support `--dry-run` / `--yes`.
- Nothing is ever installed automatically. Checking and installing are always
  separate steps you run yourself (a systemd *check* timer is opt-in).

## Install

Requires [uv](https://docs.astral.sh/uv/) and Python 3.11+:

```bash
git clone https://github.com/CyrixJD115/Quiver.git
cd Quiver
uv tool install .
```

Data lives in `~/.config/quiver/`, `~/.local/share/quiver/`,
`~/.local/state/quiver/` and `~/.cache/quiver/` (see `quiver config path`).

## Quick start

```bash
quiver import                # adopt the AppImages in your collection dirs
quiver source detect --all   # figure out where updates come from
quiver check                 # any updates available? (one app or all)
quiver update                # install safely (one app or all)
quiver launch zcode          # run from managed storage, output to a log
quiver doctor                # health report
```

## CLI reference

Every command accepts `--json`.

| Command | What it does |
| --- | --- |
| `quiver add <path> [--alias a] [--source github:o/r]` | register an AppImage (copies into storage) |
| `quiver rm <alias> [--purge]` | unregister (+ optional file delete) |
| `quiver ls [--source-only]` | managed apps, versions, sources |
| `quiver info <alias>` | everything known about one app (history, backups) |
| `quiver launch <alias> [-- app args]` | launch detached; output goes to a per-app log |
| `quiver path <alias>` | print the managed file path |
| `quiver check [alias] [--notify]` | look for updates — one app or all |
| `quiver update [alias] [--force] [--dry-run]` | verify + install safely — one or all |
| `quiver history <alias>` / `quiver rollback <alias> [--to VER]` | history and restore |
| `quiver refresh [alias]` | re-read files that self-updated in place; sync registry |
| `quiver source <alias> set/show/clear/detect` | manage update sources |
| `quiver scan` | read-only inventory incl. broken/duplicate entries, legacy icons |
| `quiver doctor` | read-only diagnostics (config, tools, every managed app) |
| `quiver fix [alias]` | repair exec bits, entries, icons, markers |
| `quiver clean [--dry-run]` | remove leftovers quiver owns |
| `quiver import [--adopt-all] [--in-place]` | adopt AppImages found in collection dirs |
| `quiver modify <alias>` | change registered metadata |
| `quiver config show/get/set/path` | configuration |
| `quiver timer install/uninstall/status` | systemd user update-check timer |

Old names (`list`, `remove`, `check-all`, `update-all`, `detect-source`,
`import-existing`, `repair`, `set`) still work as hidden aliases.

## Architecture

```
        ┌─────────────┐
        │  quiver CLI │  Typer + Rich
        └──────┬──────┘
               ▼
        ┌─────────────┐
        │ services.py │  headless orchestration  single source of truth
        │  registry   │  SQLite registry + history + backups
        │  updater    │  providers: GitHub, GitLab, Codeberg, URL, command
        │  desktop    │  XDG integration with ownership markers
        │ maintenance │  scan / doctor / clean / fix / import / refresh
        └─────────────┘
```

## Development

```bash
uv sync                       # python deps
uv run pytest                 # backend/CLI tests
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy src
```

## License

MIT
