# W1 Phase 0 Dependency Audit — MOSS-TTS-Nano + AuK

Status: **written 2026-09-18 from /tmp/engine-research clones.** Generation smoke
tests (load + synthesize timing on torch 2.14 / MPS) are **deferred until the
user downloads weights overnight**; this doc records the static findings now and
will be amended with runtime numbers.

## Sources audited (shallow clones)

| Project | Repo | Commit-less (shallow) | License | Weights |
|---|---|---|---|---|
| MOSS-TTS-Nano | `OpenMOSS/MOSS-TTS-Nano` | `/tmp/engine-research/MOSS-TTS-Nano` | Apache-2.0 | `OpenMOSS-Team/MOSS-TTS-Nano` (235MB) + `OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano` (88MB) |
| AuK | `Tencent-Hunyuan/AuK` | `/tmp/engine-research/AuK` | MIT | `tencent/AuK` (6.76GB) or `tencent/AuK-Flash` (6.76GB) + `Qwen/Qwen2.5-Omni-3B` text encoder (~7GB, separate license) |

## Phase 0.2 grep battery results

| Check | MOSS-TTS-Nano | AuK |
|---|---|---|
| `inspect.getsource` | none | none |
| `typeguard` | none | none |
| `importlib.metadata` probes | none | none |
| `@torch.jit.script` | none | **yes** — `src/auk/model/vae/modules/vits/flows.py:7` (PyInstaller jit-runtime bundling concern) |
| `torch.load` | none in infer path (HF `from_pretrained`) | **`weights_only=False`** at `infer/infer_auk.py:138`, `train.py`, `model/vae/__init__.py:25` (arbitrary-pickle load of EMA ckpt) |
| `torchaudio.load` | finetuning + ONNX runtime only (ref-audio encode) | `infer/infer_auk.py`, `infer/pe.py`, `train.py` |
| `torch.from_numpy` / float64 | float64 only in ONNX softmax on numpy | `.to(torch.float64)` in post-processing (`infer/pe.py`, `infer_gradio.py`) |
| `token=True` / gated HF | none (public repos) | none |
| `TrustRemoteCode` | `trust_remote_code=True` on both loaders (model + codec) | n/a (custom `cfg_edit`/`flux2_edit` in-repo) |
| Remote code | weights repo ships modeling code; `local_files_only` used when cached → **works offline after one cache fill** | Qwen2.5-Omni encoder loaded via transformers (also offline-capable once cached) |

## Integration posture against the existing Voicebox stack

### MOSS-TTS-Nano — GOOD FIT
- 0.1B, CPU real-time, **48 kHz stereo**, 20 languages, zero-shot cloning from ~3 s reference audio.
- Loads via `AutoModelForCausalLM.from_pretrained(...)` + `AutoModel.from_pretrained(...)` with `trust_remote_code=True`, `local_files_only` when cached → same pattern as Voicebox's remote-code engines; clean offline behavior after the repo snapshot is in the HF cache.
- GAp surface maps 1:1 onto `TTSBackend` (`create_voice_prompt` → `prompt_audio_path`, `generate(text, voice, seed)`, `combine_voice_prompts` analogous to kokoro/chatterbox prompt concat).
- 16 built-in voice presets (zh/en/jp); `assets/audio/*` reference clips ship with the repo.
- New deps are light: `sentencepiece` (installed, ok), `onnxruntime` (already in venv), `WeTextProcessing`/`pynini` (**not required** — the manager is try/except optional; text normalization falls back to the bundled `tts_robust_normalizer_single_script.py`). `WeTextProcessing` install currently **fails on this macOS/Python** (pynini must build from source) — do not rely on it, keep `enable_wetext=False`.
- Version drift risk: repo pins `torch==2.7.0` + `transformers==4.57.1`; Voicebox venv has torch 2.14.0 + transformers 4.57.3. The runtime's own imports are minimal (torch, transformers, numpy — no torch.compile gate). **Must be confirmed by the deferred load/generate smoke test**; transformers delta is patch-level, torch delta larger but API surface used is stable.

### AuK — PROBLEMATIC FOR THIS TARGET (needs a decision)
- Hard dependency pins collide with the Voicebox bundle: `torch>=2.7,<2.8`, `torchaudio>=2.7,<2.8`, `torchvision>=0.22,<0.23`; Voicebox ships torch 2.14. Installing AuK into the same venv forces a torch downgrade that would break the MLX/Qwen/Chatterbox stack. **(May still run on 2.14 — the pin is conservative — but this needs the deferred runtime test and must not auto-downgrade.)**
- Footprint: auk checkpoint 6.12GB + VAE 0.64GB + Qwen2.5-Omni-3B encoder ~7GB ≈ **13-14GB disk**; flow-matching DiT (32 NFE base / 4-step Flash) + Qwen encoder resident → borderline/uncomfortable on a 16GB M1 Pro.
- New heavy deps: `qwen-omni-utils`, `omegaconf`, `torchdiffeq`, `x_transformers`, `accelerate>=0.33`.
- `weights_only=False torch.load` for the EMA checkpoint; `@torch.jit.script` VAE flows — both PyInstaller-sensitive.
- Language coverage: **Chinese + English** only (base has no formal list; Flash declares zh/en).
- This is a *generation + editing* foundation model; Voicebox only uses the TTS slice. AuK-Flash (4-step, CFG-off) is the sane sampling variant if integrated at all.

## Decisions & deferred checks

- Weights are **not pre-cached now** (user network constrained). Build the app so MOSS-TTS-Nano and AuK appear as **downloadable models in the Model Management UI**, pulling into the HF cache at the user's leisure; registration code is complete regardless of cache state. Offline-first behavior after the one snapshot fill.
- Deferred (run on the nightly download, then append to this doc): MOSS load+generate on torch 2.14/transformers 4.57.3 (verifies the drift), AuK load on 2.14, real MPS timing for both, RAM ceiling on the 16GB M1 Pro.
- Open question to user: AuK integration posture (register + flag "experimental, zh/en, heavy"; run in same venv at torch 2.14 pending test; vs. isolated sidecar venv).