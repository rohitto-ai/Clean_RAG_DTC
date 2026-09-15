# Phase 0 — Environment Setup

## Objective

Stand up a fully local, CPU-only Python environment for the DTC RAG pipeline on a
GitHub Codespace, with no cloud APIs, no GPU and no API keys. Verify the machine
matches the build plan's assumptions before any pipeline work begins.

## Method

Probed the box directly (`nproc`, `/proc/meminfo`, cgroup limits, `df`, `swapon`),
identified the Python interpreters available, installed the system OCR package,
created a virtualenv, and verified every dependency imports.

## Key Decisions

| Decision | Rationale |
|---|---|
| **Python 3.12**, not the 3.14 on `PATH` | `/usr/local/python/3.14.2` is the Codespace default, but `torch`, `chromadb` and `llama-cpp-python` have no reliable 3.14 wheels. `llama-cpp-python` would fall back to a source build on 2 vCPUs. `/usr/bin/python3.12` is present and safe. |
| Install **CPU-only torch** from the PyTorch CPU index *first* | The default PyPI `torch` drags in ~2.5 GB of CUDA wheels that can never be used on this box. Installing `torch==2.5.1+cpu` first pins the resolution. Venv total: 1.6 GB. |
| Build **`llama-cpp-python` from source** | The project's own prebuilt CPU wheel index serves a **musl/Alpine** build that fails to load on this glibc image: `libc.musl-x86_64.so.1: cannot open shared object file`. Built with `-DGGML_NATIVE=OFF -DGGML_CUDA=OFF -DGGML_BLAS=OFF`. |
| **No `.env`, no API keys** | Nothing leaves the box, by design. |

## Results & Metrics

| Check | Result |
|---|---|
| `nproc` | 2 vCPU (AMD EPYC 7763) |
| `MemTotal` | **7.75 GiB** |
| cgroup `memory.max` | `max` (no container cap) |
| Swap | none |
| Python (PATH) | 3.14.2 — **not used** |
| Python (venv) | 3.12.3 |
| Tesseract | 5.3.4 (installed; `apt-get update` was required first) |
| Disk | 19 GB free on `/workspaces` |
| Source PDF | `3.3L DTC Manual.pdf`, 9.3 MB, 545 pages |

All imports verified: `pdfplumber, fitz, pytesseract, PIL, imagehash,
sentence_transformers, chromadb, rank_bm25, llama_cpp, fastapi, uvicorn, pydantic`.

## Evidence & Artifacts

- [requirements.txt](../../requirements.txt) — pinned, CPU-only
- [README.md](../../README.md) — reproducible setup including both wheel workarounds

## Issues Found & Fixed

1. **Tesseract absent** — `apt-get install` failed until `apt-get update` was run.
2. **`ensurepip` missing** for the system 3.12 — needed `python3.12-venv`.
3. **musl wheel for `llama-cpp-python`** — see Key Decisions.

## Limitations

**The box is 7.75 GiB, not the 16 GB the build plan budgets against.** It is the
2-core/8 GB Codespace machine type; there is no cgroup cap masking a larger VM.
Base OS + VS Code server already consume ~2.7 GB, leaving ~5 GB usable.

This does not block the project — steady-state query is projected at ~4 GB — but
it removes the headroom for the plan's **optional local VLM pass (+2–3 GB)**, which
would land at ~5.5–6 GB against a 7.75 GB ceiling **with no swap**. That is an OOM
kill, not a slowdown. The VLM is therefore treated as unavailable. Actual pipeline
peaks so far are far below any limit: parse 72 MB, enrichment 241 MB.
