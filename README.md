# yt

A fast, scriptable YouTube downloader CLI built on [yt-dlp](https://github.com/yt-dlp/yt-dlp).

`yt` is a command-first developer tool — no menus, no forced prompts. Every
command is predictable, pipe-friendly, and works the same on Windows, Linux,
and macOS.

```
yt <command> [subcommand] [options] [arguments]
```

## Features

- **Download** videos, Shorts, playlists, and channels with live progress bars
- **Batch queue** persisted in `~/.yt/` — add now, download later, export as ZIP
- **Search** videos and channels straight from the terminal (`--json` for scripts)
- **Inspect** every available format, resolution, FPS, codec, and estimated size
- **Robust URL resolver**: `youtu.be`, `/watch`, `/shorts`, `/@handle`, `/c/`,
  `/user/`, `/channel/`, redirects, and even YouTube videos embedded in
  third-party pages — with a search-based fallback when all else fails
- **First-run bootstrap**: missing dependencies are detected and installed
  automatically (disable with `YT_NO_BOOTSTRAP=1`)

## Installation

```bash
git clone https://github.com/Aki2457/Youtube-Video-Downloader.git
cd Youtube-Video-Downloader

python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows
# .venv\Scripts\activate

pip install -e .
yt --version
```

Prefer not to install? Run it in place: `python -m yt <command> ...`

> **Recommended:** install [ffmpeg](https://ffmpeg.org) so the highest-quality
> video and audio streams can be merged. Without it, `yt` automatically falls
> back to the best single-file format and tells you once.

## Usage

### Download

```bash
yt download https://youtu.be/dQw4w9WgXcQ
yt download <url> <url2>                     # multiple URLs, failures don't stop the rest
yt download <url> --quality worst            # best | worst | all | custom
yt download <url> --format 137+140           # explicit yt-dlp format selector
yt download <url> --output ~/Videos          # default: ./downloads
yt download <url> --audio-only
yt download <playlist-url>                   # playlists and channels just work
yt download "chopin nocturne op 9 no 2"      # non-URLs resolve via search
```

`--quality custom` opens an interactive format picker (TTY only); in scripts
use `--format <ID>` instead. `--quality all` downloads every available format.

### Batch queue

```bash
yt batch add <url> <url2>                    # queue anything the resolver accepts
yt batch add --paste                         # URLs from clipboard, or stdin when piped
cat urls.txt | yt batch add --paste
yt batch add --channel @veritasium --limit 10  # queue a channel's latest uploads
yt batch list
yt batch run                                 # download everything, sequentially
yt batch run --quality worst --output ~/Videos
yt batch export --zip                        # ZIP of all downloaded files
yt batch export --zip backup.zip
yt batch clear --yes
```

The queue lives at `~/.yt/batch.json` (override the directory with `YT_HOME`).
State is saved after every item, so an interrupted run resumes where it left
off. Failed items stay in the queue marked `failed`.

### Search

```bash
yt search video "lofi hip hop" --limit 5
yt search channel "3blue1brown"
yt search video "query" --json | jq '.[0].url'   # logs go to stderr, data to stdout

yt search add "boards of canada" --top 3         # queue the first 3 results
yt search add "query" --index 1,3,5              # queue specific results
yt search add "query"                            # interactive picker (TTY only)
```

### Info

```bash
yt info https://youtu.be/dQw4w9WgXcQ    # metadata + full format table
yt info <playlist-or-channel-url>       # summary + item listing
yt info <url> --json                    # raw yt-dlp metadata
```

## Scripting

- Data goes to **stdout**, logs to **stderr** — safe to pipe.
- Exit codes: `0` success · `1` failure (including partial) · `2` usage error.
- Log lines use a fixed format: `[ INFO ]`, `[ Warning ]`, `[ ERROR ]`, `[ X ]`.
- Nothing prompts unless the command is explicitly interactive
  (`--quality custom`, bare `search add`, `batch clear` without `--yes`).

## Project layout

```
yt/
├── main.py        # entry point + first-run dependency bootstrap
├── cli.py         # argument parsing + command routing
├── downloader.py  # yt-dlp subprocess wrapper + live progress
├── resolver.py    # URL normalization + fallback resolution
├── search.py      # video/channel search (yt-dlp backend)
├── batch.py       # persistent queue, history, ZIP export
├── ui.py          # shared Rich theme, tables, panels, progress
├── logger.py      # strict-format logging
├── utils.py       # shared helpers
└── config.py      # paths, constants, defaults
```

## Development

```bash
pip install -e ".[dev]"
python -m pytest tests/
```

## License

MIT — see [LICENSE](LICENSE).
