# Voicebox macOS Custom Build — Execution Plan

Target: **Apple Silicon (M1 Pro) only**, additive changes, no rewrites.
Spec doc: `~/Downloads/voicebox-macos-custom-build-spec.md`
Companion doc: `CODEBASE_MAP.md` (full code understanding).

---

## Ground Rules (from spec §0)

- Follow `docs/content/docs/developer/tts-engines.mdx` phased pattern when touching engines (Phase 0 dependency audit is mandatory before engine code).
- Do not refactor outside each workstream's diff surface. If a change needs an unlisted file, stop and surface it first.
- Every workstream ends with `just dev` smoke test **and** `just build` frozen-binary test.
- One commit per workstream for bisectability.
- Grep every touched file for outbound network primitives before closing it.

### Environment caveats found during recon

1. **Git**: repo now initialized (`main`, baseline `9d8778a`). Committing per workstream from here.
2. **Spec path assumptions are wrong in two places** — the real codebase differs from the spec's assumed layout. Everything below uses real paths:
   - `backend/engines/` → actually `backend/backends/`
   - `src-tauri/` → actually `tauri/src-tauri/`
3. **`librosa` is ALREADY a dependency** (`backend/requirements.txt:57`, bundled via `--collect-all librosa` already in `backend/build_binary.py:180-183` and `backend/voicebox-server.spec:30`). Workstream 2's "new Python dependency: librosa" is a no-op — no dependency change needed, one less PyInstaller risk.
4. **Multi-sample cloning already exists** in the codebase: `create_voice_prompt_for_profile()` combines 2+ samples into a single audio file and extracts one prompt from it (`backend/services/profiles.py:593-624`). Spec §2b's `clone_from_multiple` would be a *new per-embedding averaging path*, layered on top — only where an engine exposes an embedding.
5. **This build is M-series-only (macOS arm64). CUDA/ROCM are moot on M-series:**
   - Both startup "call-home" tasks (`backend/app.py:338-339` → `check_and_update_cuda_binary()` / `check_and_update_rocm_binary()`) **early-return before any network I/O on macOS** — no CUDA dir exists (`cuda.py:412-414`) / no ROCm dir (`rocm.py:427-429`). Zero leaks.
   - Both manual endpoints (`POST /backend/download-cuda`, `POST /backend/download-rocm`) gate on Windows and raise `RuntimeError` elsewhere.
   - **Decision: CUDA/ROCm code gets NO work in this build.** Remove the startup tasks (dead code) and hide the Windows-only UI, but never build/download any CUDA/ROCm artefacts. M-series runs the PyTorch CPU+acclerate + MLX path only.

---

## Locked Decisions (confirmed with user, 2026-09-18)

| Decision | State |
|---|---|
| **TADA engine** | **DROPPED** from the M1 build. Remove `tada` + `tada-3b-ml` from `TTS_ENGINES`, `_get_non_qwen_tts_configs`, `CLONING_ENGINES`, `EngineModelSelector`, preset routing. `hume-tada` wheel stays installed but unregistered — folded into W1. Prevents a 5-8GB model download. |
| **Git** | **Init here** (done, `main` @ baseline commit). Per-workstream commits. |
| **Voicebox Cloud** (`voicebox.sh`) | **KEEP** — user-initiated; outside W5 diff surface. |
| **HF metadata lookup** (ModelManagement.tsx) | **KEEP** — display-only; outside W5 diff surface. |
| **Env** | Python 3.12.8 arm64 venv at `backend/venv` verified: torch 2.14.0 (MPS ✅), mlx 0.32.2/mlx-lm 0.31.1/mlx-audio 0.4.1 ✅, transformers 4.57.3, librosa 0.11, kokoro/misaki 0.9.4, qwen-tts 0.1.1, chatterbox-tts 0.1.7, hume-tada 0.1.9. `dac_shim` handles the missing `dac` pkg at runtime. |

> **W1 phase-0 blocker (resolved 2026-09-19):** MOSS-TTS-Nano = `OpenMOSS/MOSS-TTS-Nano` + HF `OpenMOSS-Team/MOSS-TTS-Nano`/`OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano`; AuK = `Tencent-Hunyuan/AuK` + HF `tencent/AuK(-Flash)` + `Qwen/Qwen2.5-Omni-3B` encoder. Audit written to `docs/plans/W1_ENGINE_AUDIT.md`. W1 shipped: registry + `/engines`, MOSS wired, AuK experimental, TADA dropped. Fresh-cache download+generate deferred to overnight weights pull.

---

## Phase Order (lock these in)

| # | Workstream | Risk | Depends on |
|---|-----------|------|-----------|
| 1 | **W5 — De-networking** | Low, isolated | — |
| 2 | **W4 — Kokoro/preset preview button** | Low, quick win | — |
| 3 | **W1 — Pluggable Engine Registry + MOSS-TTS-Nano + AUK** | High (structural) | — (but W1 enables W3) |
| 4 | **W2 — Clone-quality controls** | Medium (librosa already bundled → lower) | W1 (validate new + old engines together) |
| 5 | **W3 — Streaming beyond Qwen+MLX** | Medium-High (WebSocket + PyInstaller) | W1 (EngineAdapter protocol) |

---

## Phase 1 — Workstream 5: Remove Auto-Updater (Call-Home)

M-series-only note: the only network call-home on macOS is the **Tauri auto-updater** (CUDA/ROCm startup tasks are already no-ops on M-series — leave their code, but delete the two startup-scheduled tasks as dead weight).

### Diff surface (real paths)

| Item | File | Change |
|------|------|--------|
| Tauri updater config | `tauri/src-tauri/tauri.conf.json` | `plugins.updater.active: false` (keep signing key/config in place so builds don't break) |
| Tauri updater registration | `tauri/src-tauri/src/main.rs` (~L1400) | Remove `.plugin(tauri_plugin_updater::Builder::new().build())` |
| Tauri updater dep | `tauri/src-tauri/Cargo.toml` L52-54 | Remove `tauri-plugin-updater` (verify `tauri-plugin-process` is unused once updater's relaunch goes; it also powers server restart UI — check before removing) |
| Capability | `tauri/src-tauri/capabilities/default.json` | Remove `updater:default` permission |
| Frontend updater wiring | `tauri/src/platform/updater.ts` | Neutralize: `checkForUpdates` → no-op `{status:'up-to-date'}` |
| Frontend updater hooks | `app/src/hooks/useAutoUpdater.ts` + `useAutoUpdater.tsx` | Both exist; `.ts` wins bundler resolution. Remove `checkOnMount` path at `app/src/App.tsx:99` |
| Update UI (current) | `app/src/components/ServerTab/GeneralPage.tsx` `UpdatesSection` L267-369 | Remove/replace with "Updates disabled (custom build)" note |
| Update UI (legacy card) | `app/src/components/ServerSettings/UpdateStatus.tsx` | Remove or stub |
| Sidebar badge | `app/src/components/Sidebar.tsx` L38-39,100-107 | Remove updater subscription |
| Startup dead code | `backend/app.py` L335-339 | Delete the two `create_background_task(check_and_update_*_binary())` calls (CUDA/ROCm paths are M-series no-ops; this removes the imports from startup path) |
| CUDA/ROCm UI | `app/src/components/ServerSettings/GpuAcceleration.tsx`, `app/src/components/ServerTab/GpuPage.tsx` | Hide CUDA/ROCm cards on macOS; optionally keep MPS card |
| Cloud (optional) | `backend/services/cloud.py`, cloud UI | Voicebox Cloud login is a network path but user-initiated, not call-home — RECOMMEND leaving intact; confirm with user |

### Known "remaining" network (kept intentionally)
- HuggingFace model downloads — intentional feature.
- `ModelManagement.tsx:50` HF `https://huggingface.co/api/models/{repoId}` metadata lookup — metadata, not call-home (can be left; or note as optional).

### Gates
- Grep audit (spec 5c) before/after; nothing new beyond HF + license URLs.
- Block network launch frozen `.app` → boots, generates (cached models), no error toasts.
- Commit message: `build: disable auto-updater and cuda/rocm call-home for macos custom build`.

---

## Phase 2 — Workstream 4: Preset-Voice Preview Buttons

### Root cause (verified)
- Backend `GET /profiles/presets/{engine}` returns only `{voice_id, name, gender, language}` — **no `sampleAudioUrl`** (`backend/routes/profiles.py:74-107`).
- Frontend renders preset voices as a plain button grid in `ProfileForm.tsx` L905-938 — **no player slotted in**. Preset profile cards (`ProfileCard.tsx`) also lack preview.
- `PresetVoice` TS type has no sample field (`app/src/lib/api/types.ts:44-49`).

### Diff surface
| Item | File | Change |
|------|------|--------|
| Preset schema | `backend/routes/profiles.py` L74-107 + `backend/models.py` | Add `sampleAudioUrl` (path to a bundled static sample per voice) |
| TS type | `app/src/lib/api/types.ts:44-49` | Add `sampleAudioUrl?: string` |
| Static samples | new script (e.g. `scripts/generate_preset_samples.py`), run once at build/dev time | Generate ≥1 short clip per Kokoro + Qwen CustomVoice voice into `backend/static/preset_samples/` |
| Static serving | `backend/app.py` or `routes/audio.py` (existing static asset route) | Serve the samples dir (check Tauri bundle glob so PyInstaller/sidecar includes it) |
| Voice rows | `app/src/components/VoiceProfiles/ProfileForm.tsx` L905-938 | Add `AudioPreviewButton`/player per grid cell |
| Profile card | `app/src/components/VoiceProfiles/ProfileCard.tsx` | Optional: preview on preset cards too |
| Playback component | reuse existing `AudioPlayer.tsx` / `MiniSamplePlayer` / `useAudioPlayer` | Slot into preset grid |

### Gates
- `just dev`: every preset row shows a play button; playback does not disturb in-progress generation.
- `just build`: static samples actually bundled in the frozen app (classic PyInstaller glob miss — verify the asset glob).

---

## Phase 3 — Workstream 1: Pluggable Engine Registry + MOSS-TTS-Nano + AUK

### Phase 0 dependency audit (MANDATORY, per tts-engines.mdx)
Before any code:
1. Clone MOSS-TTS-Nano (0.1B, Apache-2.0, 48kHz stereo) and AUK (1.5B, MIT, Sept 2026) repos to `/tmp/engine-research`.
2. Run the Phase 0.2 grep battery (inspect.getsource, typeguard, importlib.metadata, torch.load map_location, torch.from_numpy float64, token=True, @torch.jit.script, torchaudio.load, gated HF repos).
3. Test CPU load + generate in a throwaway venv; note sample rate, download method, MPS behavior.
4. Write the written audit before touching `backend/backends/`.

### Real structure to wrap (do NOT rewrite internals)
- `backend/backends/__init__.py`: `ModelConfig` dataclass, `TTS_ENGINES` dict, `get_tts_backend_for_engine()` if/elif factory (L670-730), `get_tts_model_configs()`. **This is the existing "registry"** — the spec's `EngineDescriptor`/`EngineAdapter` layer should sit *over* it, not replace it.
- Each existing backend already implements the async `TTSBackend` protocol (`load_model`, `create_voice_prompt`, `combine_voice_prompts`, `generate`, `unload_model`, `is_loaded`, `_get_model_path`).
- New adapter = thin sync/async wrapper mapping `EngineAdapter` (spec shape) → existing `TTSBackend` methods, plus metadata (`supports_mps`, `sample_rate`, `supports_streaming`, license, min_ram_gb).

### Diff surface (real paths)
| Item | File |
|------|------|
| Registry | new `backend/backends/registry.py` (`EngineAdapter` Protocol + `EngineDescriptor` + `EngineRegistry`) |
| MOSS adapter | new `backend/backends/moss_tts_nano_backend.py` (TTSBackend impl OR registry adapter) |
| AUK adapter | new `backend/backends/auk_backend.py` |
| Per-engine adapters | one thin adapter class in each of the 6 existing kept backend files (TADA backend is dropped, gets no adapter) |
| `/engines` route | new `backend/routes/engines.py`, registered in `backend/routes/__init__.py` (`register_routers`) |
| Config metadata | `ModelConfig` entries + `TTS_ENGINES` + factory branches in `backend/backends/__init__.py` |
| Request regex | `backend/models.py` engine regex (add `moss-tts-nano`, `auk`) |
| Frontend hook | new `app/src/lib/hooks/useEngines.ts` fetching `/engines` |
| Frontend picker | `app/src/components/Generation/EngineModelSelector.tsx` — make `ENGINE_OPTIONS` data-driven, keep `ENGINE_DESCRIPTIONS` for local labels/fallback |
| Deps | `backend/requirements.txt` + `justfile` setup + `requirements-mlx.txt` if needed |
| PyInstaller | `backend/build_binary.py` + `backend/voicebox-server.spec` hidden-imports/collect-all/copy-metadata per audit; `backend/server.py` env overrides if native data paths |

### Notes
- MLX-relevant: MOSS-TTS-Nano claims CPU-realtime — verify it even runs on the M1 Pro target before committing to the adapter; on Apple Silicon we may prefer CPU (thermal safety net is the point).
- AUK = cloning + editing + noise cleanup; check whether editing/indexing needs extra input fields (spec's `EngineAdapter.clone`/`generate` may need extension — surface if so).
- Sample rate: MOSS is 48kHz stereo — confirm `save_audio`/audio pipeline handles stereo + non-24k without the `needs_trim` assumptions.

### Gates
- `GET /engines` lists all 8 engines (6 kept existing + 2 new) with correct metadata.
- Fresh HF cache: download + clone + generate for MOSS and AUK.
- Regression: Qwen3-TTS, CustomVoice, LuxTTS, Chatterbox, Chatterbox-Turbo, Kokoro still clone/generate identically. TADA entries confirmed fully absent (registry, UI, presets).
- `just build` + same pass frozen.

---

## Phase 4 — Workstream 2: Clone-Quality Controls

### Reality checks (adjusts the spec)
- **librosa already bundled** → 2a's scoring helper (`backend/audio/quality.py`) is a pure additive utility using existing deps; PyInstaller risk already de-risked.
- **Multi-sample already works** via combine → one prompt. The real additive is:
  - 2a: pre-flight scoring endpoint `POST /profiles/{profile_id}/quality-check` (or accept a temp upload like spec) — pure-warning, never blocking.
  - 2b: `clone_from_multiple` embedding averaging **only** for engines exposing embeddings (Qwen3-TTS, AUK). Existing combine path stays for everyone else.

### Diff surface (real paths)
| Item | File |
|------|------|
| Scoring util | new `backend/audio/quality.py` (`score_reference_audio`) — reuse `backend/utils/audio.py` `load_audio` instead of raw librosa for consistency (float64→float32 handling already exists there) |
| Quality route | `backend/routes/profiles.py` — additive `POST /profiles/quality-check` (multipart audio) |
| Embedding averaging | `backend/backends/base.py` → add `clone_from_multiple()` as optional protocol method; implement on `pytorch_backend.py`, `mlx_backend.py`, `auk_backend.py` |
| Confidence badge | new `app/src/components/VoiceProfiles/ConfidenceBadge.tsx` |
| Creation flow | `app/src/components/VoiceProfiles/ProfileForm.tsx` — call quality-check on chosen sample(s), render badge + warning text after upload, allow multi-file drop |
| Multi-sample wiring | `app/src/lib/api/client.ts` + `useProfiles.ts` (batch sample add) |

### Gates
- Clean 15s sample → score >75, no warnings; noisy/short sample → correct warnings fire.
- 3-sample clone vs 1-sample baseline by ear (old engines + AUK).
- `just build` frozen — librosa path confirmed working (already exists, but verify no new breakage).

---

## Phase 5 — Workstream 3: Streaming Beyond Qwen+MLX

### Reality checks
- **Streaming today = SSE for progress only**; generation is generate-then-play for every engine except the Qwen+MLX path (`mlx_backend.py:234-259` streams results from `mlx_audio`).
- No WebSocket anywhere in the codebase yet. This is a net-new transport: new `backend/routes/generate_stream.py` WebSocket route + register in `routes/__init__.py`.
- Requires `EngineAdapter.stream_generate` from W1. Where upstream has no streaming primitive (verify in W1's Phase 0 audit), `supports_streaming=False` and the frontend falls back to REST automatically.

### Diff surface (real paths)
| Item | File |
|------|------|
| Protocol | `backend/backends/registry.py` — optional `stream_generate` |
| Streaming impls | `backend/backends/auk_backend.py`, `backend/backends/moss_tts_nano_backend.py` (only if upstream supports chunked output) |
| Route | new `backend/routes/generate_stream.py`; register in `backend/routes/__init__.py` |
| Disconnect cleanup | `ws.close()` / `WebSocketDisconnect` handler → cancel generation task; add zombie-process test |
| Frontend client | new `app/src/lib/hooks/useStreamingGenerate.ts` — auto-fallback to `useGeneration`/REST when `supports_streaming=false` |
| Generation panel | `app/src/components/Generation/FloatingGenerateBox.tsx` — branch on `supports_streaming` from `/engines` |
| PyInstaller | WebSocket + async workers quirks in frozen build — watch logs closely (uvicorn websockets in onedir) |

### Gates
- Non-streaming engines 100% unaffected (additive only).
- Measure time-to-first-audio streaming vs non-streaming per engine on the M1 Pro.
- Mid-stream disconnect leaves no zombie process.
- `just build` → test WebSocket against frozen binary.

---

## Final Global Pass (spec Global Test Checklist)
1. Fresh clone + fresh HF cache → first-run-to-first-generation for every engine.
2. Frozen `.app` repeat.
3. Network fully blocked at OS level → boots, no crash/hang/toast (except intentional HF fetch failures when downloading new models).
4. All 6+ existing engines still clone + generate — the non-negotiable regression bar.

---

## Open Items (most decisions now locked — see "Locked Decisions" above)

1. **AUK/MOSS upstream access**: resolved 2026-09-19 (see W1 blocker note above).
2. **49 Kokoro preset voices**: resolved — W4 pre-warmed all 54 `.pt` files + generated 54 preview samples.
3. **AuK full capability surface** (user reminder, 2026-09-19): the W1 adapter covers the TTS/zero-shot-cloning slice only. AuK's docs expose more — speech editing (insert/replace/delete), denoising/enhancement, source separation, cross-voice conversion — all via the same instruction-driven `generate(messages, audio=...)` API. Follow-up: expose edit/denoise/SE as Voicebox endpoints + UI on `auk_backend.py` reusing `AukInfer` (single model load, different instructions/modes). Defer until weights land and TTS slice is verified on torch 2.14.
4. **Stop-any-server option** (user request, 2026-09-19, shipped): the production app's old sidecar squatted on port 17493 and silently served stale code to a dev app instance ("Backend already running" reuse trap). Shipped: `stop_any_server` + `force_restart_server` Tauri commands (kill every voicebox-named listener on the port, not just our own), a tauri-only Settings → General row ("Stop any server & start fresh"), and a justfile guard (`dev`/`dev-web` probe `/engines` and error with the kill command if a foreign server squats). Makes the shipped app work anywhere.
5. **Breeze TTS 2** (user request, 2026-09-19 — scheduled later, after W3 + real-world testing): #1 open-weight TTS on Artificial Analysis (Elo 1215). Runs on M1 via mlx-audio (needs upgrading venv's mlx-audio 0.4.1 → newer; re-verify the Qwen MLX path after) or the standalone `mlx-breeze-tts2` port. Sizes: 4-bit 3.0GB / 8-bit 4.6GB (sweet spot) / bf16 7.6GB. Capabilities: cloning (existing flow), voice direction via `instruct`+`cfg_scale` (existing instruct field), streaming (W3 WS path), 24kHz mono, en+zh (open model). One net-new UI: the designed-voice flow (`voice_type="designed"` + `design_prompt` scaffold already exists). **License: weights are research/non-commercial only** — fine for personal use, not for commercial shipping.