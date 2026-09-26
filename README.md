# Nikola V1 - Archived Legacy Implementation

Nikola V1 is a frozen historical/reference implementation. It is not maintained as a production-ready application, and its behavior and security have not been revalidated for deployment. Nikola V2 is being rebuilt separately.

## What V1 Contains

- A Python/FastAPI backend for local model inference, document indexing, hybrid RAG, voice services, memory, file operations, and authentication.
- A Windows-oriented launcher and process manager for the backend and related services.
- An Electron desktop interface, a browser extension, and a Telegram bot.
- Dependency manifests and historical design, audit, and project-status notes.

The repository preserves the V1 source and selected documentation. It does not include runtime environments, downloaded models, databases, logs, user documents, or packaged application builds. See [MODEL_PROVENANCE.md](MODEL_PROVENANCE.md) for model references and unknown provenance details.

## Running the Historical Source

The previous workflow targeted Windows and used `run.bat` or `python nikola_launcher/launcher.py`. A source setup also requires installing the packages in `backend/requirements.txt`; the Electron client has its own `electron_app/package.json` and lockfile. These workflows are retained as historical references and have not been verified against a clean installation.

Local configuration belongs in the root `.env`, which is ignored by Git. Start from `.env.example` and supply only credentials you have generated for your own environment. Configure a unique `NIKOLA_API_KEY` before using authenticated backend routes; the source intentionally has no shared default key. Models and runtime data must be obtained or created locally and remain outside version control.

## Architecture and Local State

The backend combines local model inference with ChromaDB/vector retrieval, BM25 search, reranking, and grounding. The launcher coordinates processes; Electron and the browser extension communicate with the backend; the Telegram bot provides a separate interface. Vault files, profile data, databases, downloaded models, logs, and build output are machine-local state and are ignored.

## Known Limitations

- Model names and provenance are inconsistent in the legacy registry; verify model files, sources, licenses, and runtime compatibility independently.
- Startup and installation behavior depends on Windows, local tools, credentials, and files not included here.
- Historical status and architecture documents contain claims that were not independently re-tested and should not be treated as current verification.
- Authentication, filesystem access, command execution, data migration, and network behavior require a fresh review before any reuse.
- Existing tests depend on local services, models, or environment setup in some cases; no production-readiness claim is made.

## Historical Documents

`ARCHITECTURE_REVIEW_AND_SUGGESTIONS.md`, `PROJECT_MASTER_MANUAL.md`, `nikola_ppt_content.md`, and `status.md` are retained as V1-era context. In particular, older RAG descriptions and audit conclusions may not match the current source. Do not reuse their instructions blindly.

## Archive Scope

This repository exists to preserve useful V1 source for reference, not to continue feature development. Nikola V2 is being developed separately; do not treat this codebase as its foundation without an explicit security, dependency, architecture, and data-format review.
