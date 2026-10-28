# md2speech

Convert Markdown study materials into natural‑sounding audio using the
[`nazdridoy/kokoro-tts`](https://github.com/nazdridoy/kokoro-tts) command-line
text‑to‑speech engine.

The goal is that listening to your notes sounds like **someone naturally
explaining the material**, not a robot reading Markdown punctuation out loud.

## Why it sounds natural

`md2speech` does **not** feed raw Markdown to the TTS engine. It parses the
document structurally with `markdown-it-py` and rewrites it into narration‑ready
text:

- Headings become spoken titles, with **longer pauses between sections**.
- Bold, italic, strikethrough and blockquote **syntax is removed** (the words stay).
- Ordered lists — including nonstandard `1.-` markers — are read **without speaking punctuation**.
- Unordered and nested list items keep their meaning, with natural pauses.
- Links are read as their **visible label**; raw URLs are dropped by default.
- Tables become understandable sentences (`Header is value, Header is value`), or can be skipped.
- Fenced code blocks are **skipped by default** (includable with a flag).
- **ASCII-art diagrams** inside code fences are announced as "Diagram omitted" rather than read as garbage.
- Image paths/URLs are skipped.
- **Technical normalization:** file extensions (`.js` → "dot jay ess"), plural initialisms (`APIs` → "A P Iz"), and operators (`===` → "triple equals", `=>` → "arrow", `??` → "nullish coalescing") are spoken sensibly.
- Pauses are inserted using **real audio silence** (via ffmpeg), not just punctuation.
- Long content is split at **sentence/paragraph boundaries — never mid‑sentence**.
- Chapter/section order is preserved. No paraphrasing or summarizing.

## Architecture

The pipeline is deliberately layered so pieces can be swapped independently:

| Layer | Module | Responsibility |
|-------|--------|----------------|
| Parse | `parser.py` | Markdown → ordered narration blocks (markdown-it-py) |
| Normalize | `chunking.py` | Pronunciation replacements + sentence‑safe chunking |
| Synthesize | `tts.py` | `kokoro-tts` subprocess wrapper + chunk caching |
| Assemble | `audio.py` | Silence/pauses, WAV concat, MP3/WAV output (ffmpeg) |
| Play | `playback.py` | Configurable backend (default `paplay` / WSLg) |
| Orchestrate | `pipeline.py`, `cli.py` | Tie it together; CLI |

A new playback backend can be added by implementing the `PlaybackBackend`
protocol in `playback.py` without touching the parser or TTS integration.

## Requirements

- **Python 3.10+** (developed and tested on the 3.10/3.12 line).
- **`kokoro-tts`** CLI and its model files (see below).
- **`ffmpeg`** — audio assembly and MP3 output.
- **`paplay`** (from `pulseaudio-utils`) — for `--play`.

System packages (Debian/Ubuntu/WSL2):

```bash
sudo apt install ffmpeg pulseaudio-utils libportaudio2
```

> On WSL2, `paplay` routes audio to Windows through **WSLg's PulseAudio**.
> md2speech never installs, configures, or starts a PulseAudio server — it uses
> the existing WSLg connection.

## Installation

### With `uv` (recommended)

```bash
cd ~/repos/md2speech
uv pip install -e .
```

### With `pip`

```bash
cd ~/repos/md2speech
pip install --user -e .
```

Both expose the `md2speech` command. Ensure `~/.local/bin` is on your `PATH`.

### Install the `kokoro-tts` backend + models

```bash
pip install --user kokoro-tts

# Download the model + voices once (works offline afterwards):
mkdir -p ~/.local/share/md2speech/models
cd ~/.local/share/md2speech/models
wget https://github.com/nazdridoy/kokoro-tts/releases/download/v1.0.0/kokoro-v1.0.onnx
wget https://github.com/nazdridoy/kokoro-tts/releases/download/v1.0.0/voices-v1.0.bin
```

md2speech looks for the model files at
`~/.local/share/md2speech/models/` by default (override with `--model`/`--voices`
is available through the config if needed).

> **Note on `kokoro-tts` dependencies:** the engine imports `sounddevice`
> (needs `libportaudio2`) and `pymupdf4llm`. If `pip` pulls in a broken empty
> `pymupdf4llm`, install a working version: `pip install --user "pymupdf4llm==0.0.17"`.
> If you hit a NumPy/SciPy ABI error (`_ARRAY_API not found`), install a SciPy
> built for NumPy 2.x: `pip install --user "scipy>=1.13"`.

## Usage

```bash
# Convert to an MP3 next to the notes
md2speech notes.md --output notes.mp3

# Pick a voice and slow it down slightly
md2speech notes.md --voice af_heart --speed 0.95

# Just inspect the narration text (no audio generated)
md2speech notes.md --preview

# Generate and play immediately (streams long documents)
md2speech notes.md --play

# Process a whole folder recursively into a target directory
md2speech ./study-material/ --recursive --output ./audio/

# List available voices
md2speech --list-voices
```

### Options

| Option | Description |
|--------|-------------|
| `-o, --output PATH` | Output file (or directory for folder input). |
| `--voice TEXT` | Voice, e.g. `af_heart`. Blends: `af_sarah:60,am_adam:40`. |
| `--speed FLOAT` | Speech speed multiplier (default `1.0`). |
| `--lang TEXT` | Language code (default `en-us`). |
| `-f, --format [wav\|mp3]` | Output format (default `wav`). |
| `--preview` | Print narration text, don't synthesize. |
| `--play` | Play through `paplay` (WSLg). Streams chunk by chunk. |
| `-r, --recursive` | Recurse into subdirectories for folder input. |
| `--include-code / --skip-code` | Include fenced code blocks (default: skip). |
| `--skip-tables` | Skip tables instead of reading rows as sentences. |
| `--list-transitions` | Speak ordinal lead-ins ("First,", "Second,"). |
| `--pronunciation PATH` | YAML of term → spoken‑form replacements (overrides built-ins). |
| `--no-default-pronunciation` | Disable the built-in tech acronym dictionary. |
| `--max-chunk-chars INT` | Soft cap per synthesis chunk (default `500`). |
| `--list-voices` | List available voices and exit. |

### Pronunciation

md2speech ships a **built-in, tech-friendly pronunciation dictionary that is
applied by default**, so common software acronyms are spoken the way an
English-speaking engineer says them — e.g. `UX` → "you ex", `QA` → "Q A",
`API` → "A P I", `CI/CD` → "C I C D", `OIDC` → "O I D C", `PKCE` → "pixy",
`JWT` → "J W T". Without this, Kokoro tries to pronounce all-caps tokens as
words and produces the wrong (often Spanish-sounding) vowels.

You only need a YAML file to **add** terms the built-ins don't cover (project
or client names) or to **override** how a built-in term is spoken:

```yaml
# md2speech.pronunciation.yaml
replacements:
  ACME: "ackme"            # add a custom term
  Kubernetes: "koober netties"
  UX: "user experience"    # override a built-in (say the words instead)
```

Use it with `--pronunciation md2speech.pronunciation.yaml`. If omitted,
md2speech also checks `./md2speech.pronunciation.yaml` and
`~/.local/share/md2speech/pronunciation.yaml` automatically. **Precedence:**
built-in defaults first, then your YAML on top (your entries win). Replacements
are whole‑word and case‑insensitive; longer terms win over shorter ones.

Disable the built-ins entirely with `--no-default-pronunciation`.

## Playback controls

During `--play`, when stdin is an interactive terminal, single‑key controls are
active (no Enter needed):

| Key | Action |
|-----|--------|
| `p` | Pause (suspends the player with `SIGSTOP`) |
| `c` | Continue (resumes with `SIGCONT`) |
| `q` or Ctrl+C | Stop playback and exit cleanly |

Pausing suspends the actual audio process, so it resumes exactly where it left
off. On quit/Ctrl+C the player subprocess is terminated promptly and temporary
files are cleaned up — no orphaned audio processes.

## Resume (bookmarks)

When you play a file and stop partway (`q` / Ctrl+C), md2speech saves a small
resume pointer so you can pick up where you left off:

```bash
md2speech notes.md --play          # stop with q partway through…
md2speech notes.md --play          # …later: auto-resumes from that spot
```

- The pointer is stored **next to the source** in `<dir>/.md2speech/<name>.sav`
  (JSON). The original Markdown is never modified.
- It records the next chunk index, the **section heading** where you stopped
  (e.g. "1.4 Ordering puzzle #2 …"), voice/speed, and a content hash.
- Resume is automatic when a save exists. Control it explicitly:
  - `--resume` — force resume from the save.
  - `--restart` — ignore the save and start from the beginning.
  - `--clear-progress` — delete the saved pointer and exit.
- If the Markdown file changed since you saved (hash mismatch), md2speech warns
  and starts over rather than resuming at a stale position.
- Finishing a file clears its pointer automatically.

## Caching

Synthesized chunks are cached under `~/.cache/md2speech/`, keyed by a hash of
the text, voice, speed, language and model. Re‑running on unchanged content is
near‑instant. Delete the directory to clear the cache.

## Reliability notes

- `kokoro-tts` presence and the model/voices files are validated up front with
  actionable error messages.
- The requested voice is validated against the engine's advertised voices
  (blends supported).
- All subprocess calls use argument lists (no shell string interpolation).
- Temporary files are created safely and cleaned up; a crashed synthesis never
  leaves a half‑written cache entry.
- Exit codes: `0` success, `1` processing error, `2` bad input/arguments,
  `130` interrupted (Ctrl+C).

## WSLg playback smoke test (manual)

Confirm WSLg audio works before using `--play`:

```bash
# 1. Baseline: a known WAV should play through Windows speakers.
paplay /usr/share/sounds/alsa/Front_Center.wav

# 2. End-to-end: generate and play a short note.
printf '# Hello\n\nThis is a WSLg playback smoke test.\n' > /tmp/smoke.md
md2speech /tmp/smoke.md --play --voice af_heart
```

If step 1 is silent, WSLg audio isn't wired up (this is outside md2speech's
scope — md2speech uses the existing WSLg PulseAudio connection and does not
manage audio devices).

## Development & tests

```bash
cd ~/repos/md2speech
python3 -m pytest          # 73 tests; TTS and playback are mocked (no audio device needed)
```

The tests cover headings, nested lists, nonstandard list markers, tables, code
blocks, links/images, pronunciation, sentence‑safe chunking, the Kokoro wrapper
(mocked subprocess + caching), audio pause mapping, and playback including
Ctrl+C cleanup.

## License

MIT
