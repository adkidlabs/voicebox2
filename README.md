<p align="center">
  <img src=".github/assets/icon-dark.webp" alt="Voicebox 2" width="120" height="120" />
</p>

<h1 align="center">Voicebox 2</h1>

<p align="center">
  <strong>A macOS (Apple Silicon) custom build of Voicebox.</strong><br/>
  Local-first AI voice studio: clone any voice, generate speech, stream live, dictate into any app.<br/>
  This fork is a personal build — the original project is by <a href="https://github.com/jamiepine">Jamie Pine</a>.
</p>

<p align="center">
  <a href="https://github.com/jamiepine/voicebox">Original: jamiepine/voicebox</a> •
  <a href="https://voicebox.sh">voicebox.sh</a> •
  <a href="#what-changed-from-the-fork">What changed</a> •
  <a href="#running-on-mac">Run on Mac</a>
</p>

---

## What is this?

**Voicebox 2** is a customized fork of [Voicebox](https://github.com/jamiepine/voicebox) — the open-source, local-first AI voice studio (a free alternative to ElevenLabs + WisprFlow in one app). This build is tuned for a **single target: Apple Silicon Macs** (MLX / CPU, no CUDA/ROCm/Windows paths), with a reworked engine layer, live streaming, and quality tooling added on top.

Everything runs locally: models, voice data, and captures never leave your machine.

## What changed from the fork

**1. De-networked** — the auto-updater and CUDA/ROCm call-home are removed. The app boots and runs fully offline; the only network traffic is the model downloads you trigger yourself.

**2. Pluggable engine registry** — a declarative `GET /engines` endpoint now describes every TTS engine (cloning/preset support, streaming capability, model variants, preset voices, licenses). The engine picker, voice-profile flows, and model management all render from it — adding an engine means registering it, not hardcoding UI.

**3. MOSS-TTS-Nano wired end-to-end** — OpenMOSS's 0.1B autoregressive TTS engine: CPU-realtime, 48kHz, zero-shot cloning from a ~3s reference clip, and 8 bundled preset voices (zh/en/jp) with playable previews. The runtime is vendored into the repo (no live pip dependency), a torchaudio/torchcodec fallback shim handles modern torchaudio, and one in-app download pulls both HF repos (~325MB).

**4. AuK-Flash (experimental)** — Tencent Hunyuan's 1.5B speech-generation foundation model, registered as a cloning engine (zh/en, ~14GB with its Qwen2.5-Omni text encoder). Ships behind an "experimental" flag; runs in the same venv on torch 2.14.

**5. TADA dropped** — the HumeAI TADA engine (and its 5-8GB download) was removed from the registry, UI, and bundle.

**6. Clone-quality controls** — a pre-flight `POST /profiles/quality-check` scorer (SNR, clipping, duration, silence, DC offset) that flags weak reference samples without ever blocking. The creation flow shows a confidence badge per sample, supports multi-file drop, and uploads extras as clone samples. Qwen clones from multiple samples via the engine's native multi-reference prompting instead of naive audio concatenation.

**7. Live streaming generation** — a WebSocket transport (`/generate/stream-ws`) streams engine-native audio chunks as they're generated: playback starts while the rest is still synthesizing (MOSS first audio in ~0.5s). Engines without a streaming primitive fall back to REST automatically. Streamed generations persist to history exactly like normal ones, and mid-stream disconnects cancel inference cleanly.

**8. Stop-any-server escape hatch** — the app can kill *any* Voicebox server squatting on its fixed port (including an old production build silently serving stale code) and start fresh: **Settings → General → Stop any server & start fresh**. Dev-mode launch scripts guard against the same trap.

**9. Renamed Voicebox 2 (v0.6.0)** — installs alongside the original app without clashing; both share the same HuggingFace model cache.

### Engines in this build

| Engine | Languages | Notes |
| ------ | --------- | ----- |
| **Qwen3-TTS** (0.6B / 1.7B) | 10 | Multilingual cloning, streams live on MLX |
| **Qwen CustomVoice** (0.6B / 1.7B) | 10 | 9 preset voices, instruct/delivery control |
| **LuxTTS** | English | Fast, lightweight, 48kHz |
| **Chatterbox Multilingual** | 23 | Broadest language coverage |
| **Chatterbox Turbo** | English | Fast, `[laugh]`/`[sigh]` tags |
| **Kokoro 82M** | 8 | 54 preset voices, CPU realtime, previews bundled |
| **MOSS-TTS-Nano** | 10 | 48kHz, zero-shot cloning + 8 preset voices, CPU |
| **AuK-Flash** | en/zh | Experimental, 1.5B, ~14GB, cloning only |

Cloning engines (your own voice from a reference sample): Qwen3-TTS, LuxTTS, Chatterbox, Chatterbox Turbo, MOSS-TTS-Nano, AuK-Flash. Preset-only voices: Kokoro, Qwen CustomVoice. MOSS supports both.

Everything else from the original Voicebox is kept: stories editor, post-processing effects (pedalboard), global dictation with auto-paste, Whisper STT, per-profile personalities via a bundled Qwen3 LLM, the REST API, and the built-in MCP server (`voicebox.speak` / `.transcribe` / `.list_captures` / `.list_profiles`).

---

## Running on Mac

### Build the app (one-time)

Prerequisites: [Bun](https://bun.sh), [Rust](https://rustup.rs), [just](https://github.com/casey/just) (`brew install just`), Xcode Command Line Tools, Python 3.12.

```bash
git clone git@github.com:adkidlabs/voicebox2.git
cd voicebox2

just setup          # creates the Python venv (backend/venv) + installs all deps
just build-server   # builds the Python sidecar (backend/dist)
just build-tauri    # builds the desktop app
```

When the build finishes:

- **App**: `tauri/src-tauri/target/release/bundle/macos/Voicebox 2.app`
- **Installer**: `tauri/src-tauri/target/release/bundle/dmg/Voicebox 2_0.6.0_aarch64.dmg`

Drag `Voicebox 2.app` into `/Applications` and run it like any other app. It starts its own backend on `http://127.0.0.1:17493` automatically.

> Toolchain note: make sure `bun` and `cargo` are on your PATH —
> `export PATH="$HOME/.cargo/bin:$HOME/.bun/bin:$PATH"`.

### Models

- **Kokoro** + all voice previews are pre-bundled — works immediately.
- **MOSS-TTS-Nano** (~325MB) and **AuK-Flash** (~14GB) download from the **Models page** inside the app (`Settings → Models`). One click pulls everything that engine needs.
- After a model downloads once, it's cached and works fully offline.

### Development mode

```bash
just dev          # backend (:17493) + Tauri desktop app, live reload
just dev-backend  # backend only
just dev-web      # backend + web frontend (no Tauri)
```

`just dev` refuses to start if an old/foreign Voicebox server is squatting on port 17493 — kill it with `kill $(lsof -ti :17493)` and re-run.

### Useful API surface

```bash
# Engine registry (picker + download metadata)
curl http://127.0.0.1:17493/engines

# Generate speech
curl -X POST http://127.0.0.1:17493/generate \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello world", "profile_id": "abc123", "language": "en"}'

# Agent voice output (any app or script)
curl -X POST http://127.0.0.1:17493/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "Deploy complete.", "profile": "Morgan"}'

# Reference-sample quality score (never blocks)
curl -X POST http://127.0.0.1:17493/profiles/quality-check -F "file=@sample.wav"

# Full API docs
open http://127.0.0.1:17493/docs
```

### MCP server (agents)

```
claude mcp add voicebox \
  --transport http \
  --url http://127.0.0.1:17493/mcp \
  --header "X-Voicebox-Client-Id: claude-code"
```

Four tools ship: `voicebox.speak`, `voicebox.transcribe`, `voicebox.list_captures`, `voicebox.list_profiles`. A stdio-only fallback binary (`voicebox-mcp`) is bundled inside the app.

---

## Tech stack

| Layer       | Technology                                                        |
| ----------- | ----------------------------------------------------------------- |
| Desktop App | Tauri (Rust)                                                      |
| Frontend    | React, TypeScript, Tailwind CSS                                   |
| Backend     | FastAPI (Python), PyInstaller sidecar                             |
| TTS Engines | Qwen3-TTS, Qwen CustomVoice, LuxTTS, Chatterbox, Chatterbox Turbo, Kokoro, MOSS-TTS-Nano, AuK-Flash |
| STT         | Whisper (MLX on Apple Silicon)                                    |
| Local LLM   | Qwen3 (0.6B / 1.7B / 4B), shared runtime                          |
| MCP Server  | FastMCP at `/mcp` + stdio shim                                    |
| Effects     | Pedalboard (Spotify)                                              |
| Inference   | MLX (Apple Silicon) / CPU                                         |
| Database    | SQLite                                                            |

---

## Credits & License

This fork is a personal custom build. **Voicebox was created by [Jamie Pine](https://github.com/jamiepine/voicebox)** — all core architecture (local-first voice studio, dictation loop, MCP integration, stories editor) is his work; this repository customizes it for a macOS-only target and adds the engine registry, MOSS/AuK integrations, quality tooling, and streaming on top.

Upstream MIT License applies to the original code — see [LICENSE](LICENSE). Individual engines carry their own licenses (MOSS-TTS-Nano: Apache-2.0; AuK weights: research/non-commercial).
