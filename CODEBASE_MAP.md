# Codebase Map — Voicebox (what I know as of this session)

Comprehensive read of the working copy at `voicebox-main/`. This is the standing knowledge base for the custom macOS build; the phased execution plan lives in `BUILD_PLAN.md`.

---

## 0. Top-level layout

```
voicebox-main/
├── backend/        Python FastAPI server (uvicorn :17493) + PyInstaller sidecar + MCP
├── tauri/          Rust/Tauri 2 desktop shell — THE desktop app (src-tauri + thin React wrapper)
├── app/            Shared React UI core (@voicebox/app) — imported by tauri/ and web/
├── web/            Browser build — imports the SAME App.tsx, uses webPlatform
├── landing/        Next.js 16 marketing site for voicebox.sh (not part of the app)
├── docs/           Astro docs incl. docs/content/docs/developer/tts-engines.mdx
├── scripts/        build-server.sh, generate-api.sh, prepare-release.sh, packaging, setup-dev-sidecar.js
├── .github/        ci.yml, release.yml, build-windows.yml
├── data/           app data dir
├── justfile        dev/build/test/check orchestration (just dev, just build, just check, ...)
├── requirements.txt  (root, thin — real deps in backend/requirements*.txt)
└── CHANGELOG.md, README.md, CONTRIBUTING.md, .bumpversion.cfg
```

**Notable:** this working copy is **not a git repo** (no `.git`) despite spec's per-workstream commit gate.

---

## 1. Backend (`backend/`)

### 1.1 Layering (from `tts-engines.mdx`)
| Layer | Purpose |
|-------|---------|
| `routes/` | Thin HTTP handlers (FastAPI routers) |
| `services/` | Business logic |
| `backends/` | TTS/STT/LLM engine implementations |
| `utils/` | Shared utilities |
| `database/` | SQLAlchemy + SQLite (voicebox.db) |

### 1.2 App factory & lifecycle — `backend/app.py`
- `create_app()` builds FastAPI, wires MCP lifespan (`compose_lifespan`), CORS (`_configure_cors` local-first), mounts `/mcp`, SPA frontend if `frontend/` dir exists.
- Startup (`_run_startup`, L274-356): init DB, mark stale generations failed, log GPU, **starts `check_and_update_cuda_binary()` + `check_and_update_rocm_binary()` background tasks (L335-339)** — the launch-time network call-home (Workstream 5 target).
- Shutdown: unloads TTS/Whisper/LLM.
- `main.py` entry for uvicorn; `server.py` is the PyInstaller frozen entrypoint (freeze_support, espeak/env overrides, stdout safety).

### 1.3 Engine registry — `backend/backends/__init__.py` (this IS the "registry," spec calls it `engines/`)
- `ModelConfig` dataclass: `model_name, display_name, engine, hf_repo_id, model_size, size_mb, needs_trim, retries_runaway, supports_instruct, languages`.
- `TTS_ENGINES` dict: `qwen, qwen_custom_voice, luxtts, chatterbox, chatterbox_turbo, tada, kokoro` (L211-219). `LLM_ENGINES`: `qwen_llm`. Whisper under STT.
- Config builders: `_get_qwen_model_configs()` (MLX→`mlx-community/*-bf16`, else `Qwen/*`), `_get_qwen_custom_voice_configs()`, `_get_non_qwen_tts_configs()` (luxtts `YatharthS/LuxTTS` 300MB; chatterbox `ResembleAI/chatterbox` 3.2GB 23 langs; chatterbox-turbo 1.5GB en; tada-1b English 4GB / tada-3b-ml multilingual 8GB; kokoro `hexgrad/Kokoro-82M` 350MB 8 langs).
- Helpers: `get_tts_model_configs()`, `get_model_config()`, `engine_needs_trim()`, `engine_retries_runaway()` (MLX), `engine_has_model_sizes()`, `load_engine_model()`, `ensure_model_cached_or_raise()`, `unload_model_by_config()`, `check_model_loaded()`.
- **Factory `get_tts_backend_for_engine()` (L670-730)** — the if/elif chain: qwen→(MLX→`MLXTTSBackend` / PyTorch→`PyTorchTTSBackend`), luxtts, chatterbox, chatterbox_turbo, tada→`HumeTadaBackend`, kokoro, qwen_custom_voice. Extends to mins: **this is the branch list the spec's registry replaces.**
- Protocols in `backends/base.py`: `TTSBackend` (async `load_model`, `create_voice_prompt`, `combine_voice_prompts`, `generate`→`(np.ndarray, sample_rate)`, `unload_model`, `is_loaded`, `_get_model_path`), `STTBackend`, `LLMBackend`. `get_torch_device()` + `model_load_progress()` live here too.

### 1.4 Engine backends (`backend/backends/`)
| File | Class | Notes |
|------|-------|-------|
| `pytorch_backend.py` | `PyTorchTTSBackend` / STT | Qwen3-TTS via `qwen_tts`, `generate_voice_clone`, 16k ref load |
| `mlx_backend.py` | `MLXTTSBackend` / STT | Qwen+MLX — **the one streaming-capable path** (L234-259 pulls per-chunk `result` from mlx_audio); retries runaway chunks |
| `qwen_custom_voice_backend.py` | `QwenCustomVoiceBackend` | `QWEN_CUSTOM_VOICES = [(id, name, gender, lang, desc)]`; instruct support |
| `luxtts_backend.py` | `LuxTTSBackend` | 48kHz CPU-friendly, en-only, voices via LinaCodec/Zipvoice git deps |
| `chatterbox_backend.py` / `chatterbox_turbo_backend.py` | | `sr`/`sample_rate` fallback 24000, `needs_trim=True` |
| `hume_backend.py` | `HumeTadaBackend` | TADA 1B/3B via `hume_tada`, encoder extracts prompt |
| `kokoro_backend.py` | `KokoroTTSBackend` | `KOKORO_SAMPLE_RATE`, `KOKORO_VOICES = [(id, name, gender, lang)]` (L42), preset-only |
| `qwen_llm_backend.py` | MLX/PyTorch Qwen3 LLM | chat/refinement |

Voice-prompt storage patterns: Qwen stores precomputed tensor dicts; Chatterbox/Hume store deferred file paths; kokoro returns `{voice_type:"preset", preset_engine, preset_voice_id}`.

### 1.5 Routes (`backend/routes/`, registered in `routes/__init__.py` L6-48)
Profiles, channels, generations, history, transcription, llm, captures, stories, effects, audio, models, settings, tasks, cuda, rocm, speak, mcp_bindings, events, cloud, health.

Key endpoints:
- `POST /profiles` create; `POST /profiles/import` zip; `GET /profiles/presets/{engine}` **(L74-107: returns `{voice_id,name,gender,language}` — NO sampleAudioUrl)**; `POST /profiles/{id}/samples`; `GET/POST/DELETE .../avatar`; export/channels/compose.
- `POST /generate` (generations.py L56) → `GenerationResponse`; `POST /generate/{id}/retry`; SSE `GET /generate/{id}/status` (progress). `engine` resolved from request or profile `default_engine`/`preset_engine` (L53).
- `GET /models/...`, `POST /models/download` (L390-425, triggers `from_pretrained` in background), SSE `/models/progress/{name}`.
- `POST /backend/download-cuda` (cuda.py L24-48), `GET /backend/cuda-status`, SSE `/backend/cuda-progress`; mirror in `rocm.py`. Windows-only underneath.
- `POST /transcribe`, `POST /speak`, `GET /events/speak` (SSE streamed to Rust `speak_monitor`), `POST /shutdown`, `/health`, `/backend/*-progress`.
- Cloud: `POST /login/start`, `GET /callback`, `GET /status`, `POST /disconnect` (voicebox.sh).

### 1.6 Services
- `profiles.py`: profile CRUD, `add_profile_sample` (validates via `validate_and_load_reference_audio`, saves WAV), `create_voice_prompt_for_profile` (**L516-624: preset/designed/cloned branches; multi-sample path combines audio → single prompt → caches `combined_{id}_{hash}.wav`**), `CLONING_ENGINES = {qwen, luxtts, chatterbox, chatterbox_turbo, tada}`.
- `generation.py`: chunked generation (`chunked_tts`), trims, effects chains, versions.
- `cuda.py` / `rocm.py`: **httpx downloads of `voicebox-server-cuda.tar.gz` / `cuda-libs-*.tar.gz` from GitHub Releases** (`CUDA_LIBS_VERSION=cu128-v1`, `ROCM_LIBS_VERSION=rocm7.2-v1`), `check_and_update_*_binary()` startup auto-update.
- `cloud.py`: httpx to `https://voicebox.sh/api/connect/exchange`.
- `tts.py`/`transcribe.py`/`llm.py`: singleton model holders.

### 1.7 Models & DB
- `backend/models.py`: Pydantic schemas + `GenerationRequest.engine`/`language` regexes (engine pattern L88 — add new engine ids here).
- `backend/database/models.py`: `VoiceProfile` (voice_type `"cloned"/"preset"/"designed"`, `preset_engine`, `preset_voice_id`, `design_prompt`, `default_engine`, `personality`), `ProfileSample` (audio_path + reference_text), `Generation`, `Channel`, `Capture`, `Story*`, `Effect*`.
- `seed.py` / `routes/models.py` `seed_preset_profiles()` creates preset-voice DB profiles after model download.

### 1.8 Build / packaging
- `backend/build_binary.py`: PyInstaller driver — CPU/CUDA/ROCm variants, **common hidden-import/collect-all/copy-metadata registry (L95-331, L337-466)**; MLX conditionals; `--shim` builds `voicebox-mcp`. New engines MUST be added here.
- `backend/voicebox-server.spec`: `collect_all('librosa')` already; big hiddenimports incl. every `backend.backends.*` mod; copy_metadata for transformers/huggingface-hub/etc.
- `server.py`: frozen runtime — `freeze_support()`, `ESPEAK_DATA_PATH` redirect, devnull stdout.
- `requirements.txt`: torch stack, transformers ≤4.57 cap, **librosa>=0.10.0 (L57)**; `requirements-mlx.txt` for Apple Silicon (mlx-lm/mlx-audio --no-deps). justfile `setup-python` installs chatterbox-tts + hume-tada `--no-deps`, Qwen3-TTS from git.
- `justfile`: `just dev` (backend + `cd tauri && bun run tauri dev`), `just build` (`build-server` → `scripts/build-server.sh` → copies bins to `tauri/src-tauri/binaries/`, then `build-tauri`), `just test-models` (e2e per-model), `just check/lint/format/test/db-*`.

### 1.9 MCP
- `backend/mcp_server/`: FastMCP server (build_mcp_server), mounted at `/mcp`; tools for generate/speak/profiles/etc. `backend/mcp_shim/` → separate `voicebox-mcp` binary.

---

## 2. Tauri desktop shell (`tauri/`)

- **`tauri/` is the real desktop app.** `tauri/src/main.tsx` mounts `App` from `app/src/App` inside `PlatformProvider` with `tauriPlatform`.
- `tauri/src-tauri/src/main.rs` (~1600 lines): launches sidecar via `app.shell().sidecar("voicebox-server")` (L504), picks rocm/cuda variant exe (L428-430 / L467-469), health-check `reqwest::blocking` on port (L175), port probe/reuse, `VOICEBOX_MODELS_DIR` env, **updater plugin init ~L1400** (`tauri_plugin_updater::Builder`). `speak_monitor.rs` SSE-consumes `/events/speak`.
- `tauri/src-tauri/Cargo.toml`: `reqwest` 0.12, tokio, `tauri-plugin-updater` 2.0 (**L52-54 — Workstream 5 removes this**), `tauri-plugin-process`, dialog/fs/shell, macOS `screencapturekit`/`coreaudio-sys`.
- `tauri/src-tauri/tauri.conf.json`: productName Voicebox v0.5.0, id `sh.voicebox.app`, `externalBin ["binaries/voicebox-server","binaries/voicebox-mcp"]` (L16), `createUpdaterArtifacts:"v1Compatible"`, updater `pubkey` + `endpoint` → `https://github.com/jamiepine/voicebox/releases/latest/download/latest.json`, `macOSPrivateApi:true`.
- `capabilities/default.json`: grants `updater:default`, `process:default`, shell, dialog, fs.
- Platform impls: `tauri/src/platform/` (`updater.ts` TauriUpdater via `@tauri-apps/plugin-updater` check/download/install + `process.relaunch`; `lifecycle.ts` start/stop/restart server; `audio.ts`, `filesystem.ts`).

## 3. Shared React UI (`app/src/`)

- API client: `app/src/lib/api/client.ts` — single `apiClient`, base URL from `serverStore` (`http://127.0.0.1:17493` default; Tauri uses dynamically-bound port; web uses origin). Plus legacy generated SDK in `lib/api/services/`.
- **Engine picker is hardcoded**: `app/src/components/Generation/EngineModelSelector.tsx` L19-30 `ENGINE_OPTIONS` (qwen:1.7B/0.6B, qwen_custom_voice:1.7B/0.6B, luxtts, chatterbox, chatterbox_turbo, tada:1B/3B, kokoro), `ENGINE_DESCRIPTIONS`, `CLONING_ENGINES`, `ENGLISH_ONLY_ENGINES`, filters by profile `voice_type` preset/cloned, auto-switch on preset select. Comment L15-17 explicitly says "adding a new engine means adding one entry here."
- `useGenerationForm.ts` zod `generationSchema` (`engine` enum etc.), posts `/generate`. `useGeneration.ts`, `useGenerationProgress.ts` (SSE `/generate/{id}/status`), `useModelDownloadToast.tsx` (SSE `/models/progress/{name}`).
- **Voice profile creation** = `app/src/components/VoiceProfiles/ProfileForm.tsx` (1317 lines): modes `clone` + `builtin`, mic recording (29s max) / upload (`AudioSampleUpload.tsx`) / system audio, transcription, then `createProfile` + `addSample`, rollback on failure. Sample mgmt: `SampleList.tsx` / `MiniSamplePlayer` / `SampleUpload.tsx`. **Preset voice grid L905-938 — plain buttons, no preview player.** `ProfileCard.tsx` engine badges; `ProfileList.tsx` `PRESET_ENGINES={kokoro, qwen_custom_voice}`.
- `useProfiles.ts`: create/update/delete/samples/export/import/avatar hooks.
- Settings: `app/src/components/ServerTab/*` (GeneralPage incl. `UpdatesSection` L267-369, GpuPage, etc.) + legacy `ServerSettings/*` (UpdateStatus, GpuAcceleration, ModelManagement, ConnectionForm, ModelProgress).
- **Updater UI**: `app/src/App.tsx:99` `useAutoUpdater({checkOnMount:true, showToast:true})`; `app/src/hooks/useAutoUpdater.ts` **and** `useAutoUpdater.tsx` both exist (`.ts` wins bundler resolution — toasts likely dead); Sidebar badge L100-107.
- **CUDA UI**: `GpuAcceleration.tsx` + `GpuPage.tsx` (cuda/rocm status, SSE progress, download/delete/restart).
- Stores (zustand): `serverStore` (serverUrl), `uiStore` (selectedEngine default 'qwen'), `generationStore`, `playerStore`, `effectsStore`, `audioChannelStore`, `logStore`, `storyStore`.
- Router: `app/src/router.tsx` (/, /stories, /captures, /voices, /effects, /models, /settings*). i18n via i18next.

## 4. Network audit (outbound calls — Workstream 5 input)

| Destination | Where | Intent |
|---|---|---|
| `github.com/jamiepine/voicebox/releases/...latest.json` | Tauri updater (tauri.conf.json, main.rs, updater.ts) | Auto-update — **disable** |
| GitHub Releases `voicebox-server-cuda.tar.gz` + `cuda-libs-*.tar.gz` | `services/cuda.py` (httpx, L174/286/319), started at **every launch** via `app.py:338` | CUDA backend downloader — **disable** |
| GitHub Releases `voicebox-server-rocm.tar.gz` + rocm libs | `services/rocm.py` (httpx L151/258/315), started at **every launch** via `app.py:339` | ROCM downloader — **disable (same pattern)** |
| `huggingface.co` model weights | `huggingface_hub` in all backends | **Keep — core feature** |
| `https://huggingface.co/api/models/{id}` | `ModelManagement.tsx:50` | Model-card metadata (display) |
| `voicebox.sh` / `api.voicebox.sh` | `services/cloud.py` (login), CORS/config | User-initiated cloud login |
| `api.github.com/...` + Solana price APIs | `landing/` (marketing site) | Landing page only |
| Everything else | 127.0.0.1/loopback IPC (health, shutdown, SSE, MCP) | Local |

**No telemetry/analytics anywhere (no posthog/sentry/mixpanel). No `requests.get`/`urlopen`/`http.client` usage.** HTTPX only in cuda/rocm/cloud services. All `fetch(` in app = local API.

## 5. Doc of record for engine work

`docs/content/docs/developer/tts-engines.mdx` (703 lines) — Phase 0 (dependency research, 0.2 grep battery) → 1 (backend) → 2/3 (routes/frontend, preset pattern) → 4 (deps) → 5 (PyInstaller, real v0.2.1→v.2.2→v0.2.3 war stories) → 6 (upstream workarounds: torch.load patch, float64 cast, token bug, `@torch.jit.script` shims, dac_shim.py). Its candidate table lists **MOSS-TTS-Nano as Tier 1** already; VoxCPM backlogged (CUDA-only) — matches the spec.

## 6. Key spec-vs-reality deltas (feed into planning)

1. `backend/engines/` → `backend/backends/`; the if/elif factory IS the current registry.
2. `src-tauri/` → `tauri/src-tauri/`.
3. librosa already present + already PyInstaller-collected → W2 no new dep.
4. Multi-sample cloning already exists (combine→single prompt) → W2 adds per-embedding averaging as an alternative path.
5. CUDA call-home includes startup background tasks, not just the route.
6. Preset voices have no sampleAudioUrl anywhere (backend response + TS type) → W4 requires the deeper fix (static samples + schema field).
7. Cloud login is user-initiated (not call-home) — candidate to keep.
8. No git repo in this working copy.