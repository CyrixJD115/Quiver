# quiver — the AppImage quiver

`quiver` installs, registers, updates, launches and cleans up AppImages on Linux.
It is a real package-manager-style utility — a registry of *managed* apps,
pluggable upstream update providers, safe atomic updates with rollback, and
XDG-correct desktop integration — with two frontends over the same backend:
a scriptable **CLI** and an interactive **OpenTUI console** (`quiver run`).

```
$ quiver
 ⚡ QUIVER v0.3.0                                            5 apps
┌──────────────────┐┌────────────────────────────────────────────────────────────┐
│ 1 Dashboard      ││ APPS                                                       │
│ 2 Apps           ││   ALIAS       VERSION ARCH  SIZE  SRC      STATUS  CHECKED │
│ 3 Updates        ││ ❯ iloader     ?       x86_64 85.3M github  unknown 09-01   │
│ 4 Health         ││   plume-impactor 2.6.0 x86_64 17.5M github  ok      08-31   │
│ 5 Activity       ││   toolcoin    1.5.0   x86_64 22.4M -        no src  08-31   │
│ 6 Settings       ││   zcode       3.10.2… x86_64 190M  -        no src  08-31   │
└──────────────────┘└────────────────────────────────────────────────────────────┘
 : palette   ? help                                                       ready
```

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

The wheel bundles the prebuilt TUI binary. To rebuild it you need
[Bun](https://bun.sh) ≥ 1.3:

```bash
scripts/build-tui.sh && uv tool install . --reinstall --force
```

Data lives in `~/.config/quiver/`, `~/.local/share/quiver/`,
`~/.local/state/quiver/` and `~/.cache/quiver/` (see `quiver config path`).

## Quick start

```bash
quiver                       # interactive TUI (or `quiver run`)
quiver import                # adopt the AppImages in your collection dirs
quiver source detect --all   # figure out where updates come from
quiver check                 # any updates available? (one app or all)
quiver update                # install safely (one app or all)
quiver launch zcode          # run from managed storage, output to a log
quiver doctor                # health report
```

## CLI reference

Bare `quiver` opens the TUI when stdin/stdout are an interactive Linux
terminal; otherwise it prints a hint. Every command accepts `--json`.

| Command | What it does |
| --- | --- |
| `quiver run` | launch the interactive TUI (Linux) |
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

## The interactive console (Linux)

`quiver run` is a real console application, not a menu wrapper: six views, a
command palette, live operation log, toasts and confirm dialogs — keyboard
first (`j/k` select, `enter` act, `:` palette, `?` help, `q` quit).

- **Dashboard** — counts, storage use, health, recent activity
- **Apps** — table + detail pane; `l` launch, `u` update, `c` check,
  `b` rollback, `d` detect source, `x` remove, `a` add, `/` filter
- **Updates** — statuses sorted with available first; `C` check all,
  `U` update all, live log tail
- **Health** — doctor output; `f` fix, `n` clean, `s` scan, `i` import
- **Activity** — sticky scrollback of every backend event this session
- **Settings** — edit config values in place, paths, systemd timer

The TUI is intentionally **Linux-only**. The CLI and backend remain portable.

## Architecture

```
        ┌─────────────┐
        │  quiver CLI │  Typer + Rich           presentation #1
        └──────┬──────┘
               ▼
        ┌─────────────┐
        │ services.py │  headless orchestration  single source of truth
        │  registry   │  SQLite registry + history + backups
        │  updater    │  providers: GitHub, GitLab, Codeberg, URL, command
        │  desktop    │  XDG integration with ownership markers
        │ maintenance │  scan / doctor / clean / fix / import / refresh
        └──────┬──────┘
               │ `quiver api` — JSON-RPC 2.0 over ndjson stdio
               ▼
        ┌─────────────┐
        │  OpenTUI    │  Solid signals + OpenTUI renderables
        │  quiver-tui │  compiled with Bun into one Linux binary
        └─────────────┘  presentation #2 — zero business logic
```

Both frontends call the same Python services; the TUI spawns `quiver api` as a
child process and speaks newline-delimited JSON-RPC (mutations serialize,
long operations stream `log` notifications, state changes trigger refreshes).
Business logic is never duplicated.

## Development

```bash
uv sync                       # python deps
uv run pytest                 # 170 backend/CLI/API tests
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy src

cd tui && bun install
bunx tsc --noEmit             # TUI types
bun test                      # in-memory render tests
bun run dev                   # run the TUI from source
```

## License

MIT
