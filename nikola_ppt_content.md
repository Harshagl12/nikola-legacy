# NIKOLA — Local AI Agent
## VTU Final Year Project | PPT Content

---

## 1. INTRODUCTION

### 1.1 Project Title
**NIKOLA — A Production-Ready Local AI Agent for Windows with Zero Cloud Dependency**

### 1.2 Problem Statement
Current AI assistants (ChatGPT, Siri, Alexa, Google Assistant) require:
- Constant internet connectivity
- Sending personal data to cloud servers — **privacy risk**
- Paid API subscriptions for advanced features
- No control over how user data is stored or processed

> **There is a need for a fully offline, privacy-preserving AI agent that runs entirely on the user's local machine while providing intelligent automation, voice interaction, document Q&A, and system control.**

### 1.3 Proposed Solution
**NIKOLA** is a complete local AI agent that provides:
- 100% offline AI inference using **Ollama** (LLaMA 3.1 8B)
- Multi-interface access: **Telegram Bot**, **Electron Desktop Sidebar**, **Chrome Extension**
- Document Q&A via a **RAG (Retrieval-Augmented Generation) pipeline**
- Voice interaction with **wake-word detection** and **speech-to-text**
- Encrypted autofill profiles for browser form filling
- Natural language system control (files, apps, processes)
- Self-healing command execution with automatic error recovery

### 1.4 Objectives
1. Build a fully local AI agent with **zero cloud dependency**
2. Implement a **RAG pipeline** for contextual document Q&A using ChromaDB
3. Develop **multi-platform interfaces** (Telegram, Desktop, Browser)
4. Create an **always-on voice engine** with wake-word detection
5. Ensure **data privacy** through Fernet encryption for stored profiles
6. Implement **self-healing** and **intent disambiguation** for robust command execution
7. Automate repetitive user workflows via **pattern detection**

### 1.5 Scope
| In Scope | Out of Scope |
|----------|-------------|
| Windows 10/11 platform | Linux/macOS support |
| Local LLM inference (Ollama) | Cloud API integration |
| PDF, TXT, MD, PY file indexing | DOCX, RTF, spreadsheets |
| Telegram + Electron + Chrome | Mobile native apps |
| English language support | Multi-language NLP |
| Single-user operation | Multi-user/server mode |

### 1.6 Hardware & Software Requirements

| Component | Requirement |
|-----------|------------|
| OS | Windows 10/11 (x64) |
| RAM | 8 GB minimum, 16 GB recommended |
| Storage | ~5 GB (models + dependencies) |
| Python | 3.11+ |
| Node.js | For Electron sidebar |
| Ollama | Local LLM runtime (~3 GB models) |

---

## 2. ALGORITHMS USED

### 2.1 Retrieval-Augmented Generation (RAG)
**Purpose:** Enable the AI to answer questions using the user's own documents.

**How it works:**
1. **Document Ingestion** → User uploads PDF/TXT/MD/PY files
2. **Text Extraction** → PyMuPDF for PDFs, UTF-8/latin-1 for text files
3. **Chunking** → Split text into **500-token chunks** with **50-token overlap** using `tiktoken` (cl100k_base tokenizer)
4. **Embedding** → Each chunk is converted to a vector using **Ollama nomic-embed-text** model
5. **Storage** → Vectors stored in **ChromaDB** (persistent vector database) with cosine similarity indexing
6. **Query** → User question is embedded → **cosine similarity search** → top-5 relevant chunks retrieved → injected as context into LLM prompt
7. **Generation** → LLaMA 3.1 generates answer grounded in retrieved context

```
User Query → Embed Query → Cosine Similarity Search (ChromaDB)
    → Top-5 Chunks → System Prompt + Context + Query → LLM → Answer
```

**Key Parameters:**
- Chunk size: 500 tokens | Overlap: 50 tokens
- Embedding model: `nomic-embed-text`
- Vector space: Cosine similarity (HNSW index)
- Context window: Last 10 conversation turns + RAG results

---

### 2.2 Intent Classification (Hybrid Keyword + LLM)
**Purpose:** Determine what the user wants to do from natural language input.

**Algorithm:**
1. **Keyword Scoring Phase** — Score each intent category by counting keyword matches:
   - `file_op`: open, read, delete, copy, move, list, find
   - `rag_query`: what, explain, summarize, tell me, how does
   - `system_op`: disk, cpu, ram, process, info, status
   - `app_launch`: launch, start, open app, run
   - `voice_op`: say, speak, read aloud, tell
   - `screenshot`: screenshot, screen, capture, show desktop
   - `autofill`: fill, autofill, remember, profile, form
   - `workflow`: workflow, automate, repeat, always

2. **Confidence Score** = `matched_keywords / total_keywords_in_category`

3. **Decision Logic:**
   - If top score ≥ 0.6 → **Direct execution** (high confidence)
   - If top score < 0.6 → **LLM fallback** — send to Ollama for JSON classification (up to 3 intents with confidence scores)
   - If LLM fails → **Fallback** to `rag_query` with 0.4 confidence

4. **Disambiguation** — If confidence < 0.75 with multiple intents, return all options to user for selection

---

### 2.3 Self-Healing Agent Loop
**Purpose:** Automatically recover from failed commands using alternative strategies.

**Algorithm:**
```
Initial Command Fails → Identify Intent → Load Strategy Registry
    → Try Strategy 1 → Failed? → Try Strategy 2 → Failed? → Try Strategy 3
    → If any succeeds → Return result + healing explanation
    → If all fail → Return failure summary
```

**Strategy Registry:**

| Intent | Strategy 1 | Strategy 2 | Strategy 3 | Strategy 4 |
|--------|-----------|-----------|-----------|-----------|
| file_op | direct_path | fuzzy_vault_search | expand_home | downloads_fallback |
| app_launch | startfile | where_command | program_files | start_menu_search |
| rag_query | rag_retrieval | direct_llm | broader_query | — |

- **Max retries:** 3 per command
- After success, LLM generates a one-sentence explanation of what was done

---

### 2.4 Workflow Memory (Pattern Detection)
**Purpose:** Detect repetitive user action sequences and suggest automation.

**Algorithm:**
1. Every user action is logged to **SQLite** with timestamp and session ID
2. After every 3rd action, compute **SHA-256 hash** of the last 3 actions
3. Check if this hash exists in the `workflows` table:
   - **First occurrence** → Store pattern with frequency = 1
   - **Second occurrence** → Suggest automation to user (via LLM-generated suggestion)
   - **User confirms** → Pattern added to **NetworkX directed graph** for future one-click replay
4. Confirmed workflows can be **executed in sequence** automatically

---

### 2.5 Voice Activity Detection (VAD) + Wake Word
**Purpose:** Always-on hands-free voice interaction.

**Algorithm:**
1. **Audio Capture** → 16 kHz, 30ms frames (480 samples/frame) via PyAudio or sounddevice
2. **Speech Detection:**
   - Primary: **WebRTC VAD** (aggressiveness level 2)
   - Fallback: **RMS energy threshold** (threshold = 280.0)
3. **Wake Word Detection:**
   - Accumulate 18+ consecutive speech frames → transcribe with **Faster-Whisper** (int8 quantized)
   - Check if wake word ("nikola") appears in transcription
4. **Command Capture:**
   - After wake word detected → enter LISTENING state
   - Accumulate speech → after 25 silent frames → transcribe → send to `/ask` endpoint
5. **TTS Response** → pyttsx3 speaks the AI's answer back

---

### 2.6 Fernet Symmetric Encryption (Autofill)
**Purpose:** Securely store user profile data for browser form auto-filling.

- **Algorithm:** AES-128-CBC via Python `cryptography.fernet`
- Profile data → JSON serialization → Fernet encrypt → write to disk
- Field values are **never logged** — only field names are exposed via API
- Browser extension maps form fields to profile keys using **LLM-based fuzzy matching**

### 2.7 On-Device Profile Learner
**Purpose:** Learn from user corrections to improve autofill accuracy over time.

- Logs every correction (accepted/rejected mapping) to SQLite
- Builds **learned_patterns** table with normalized field signatures
- Confidence increases with repeated confirmations (starts at 0.7, caps at 1.0)
- Learned patterns bypass LLM calls → faster autofill over time

---

## 3. METHODOLOGY

### 3.1 Development Methodology
**Agile + Modular Architecture** — Each module developed and tested independently.

### 3.2 System Architecture (Layered)

```
┌─────────────────────────────────────────────────────┐
│                   USER INTERFACES                    │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ Telegram │  │   Electron   │  │    Chrome      │  │
│  │   Bot    │  │   Sidebar    │  │   Extension    │  │
│  └────┬─────┘  └──────┬───────┘  └───────┬───────┘  │
├───────┴──────────────┬┴──────────────────┴───────────┤
│               FASTAPI BACKEND (Port 8000)            │
│  ┌─────────┐ ┌──────────┐ ┌───────────┐ ┌────────┐  │
│  │   RAG   │ │    NL    │ │  Voice    │ │Autofill│  │
│  │Pipeline │ │Processor │ │  Engine   │ │ Engine │  │
│  └────┬────┘ └────┬─────┘ └─────┬─────┘ └───┬────┘  │
├───────┴───────────┴─────────────┴────────────┴───────┤
│                 INTELLIGENCE LAYER                    │
│  ┌──────────┐ ┌───────────┐ ┌──────────┐ ┌────────┐ │
│  │ Intent   │ │  Self-    │ │ Workflow │ │Profile │ │
│  │Classifier│ │  Healing  │ │  Memory  │ │Learner │ │
│  └──────────┘ └───────────┘ └──────────┘ └────────┘ │
├──────────────────────────────────────────────────────┤
│                LOCAL AI ENGINE (Ollama)               │
│  ┌────────────┐  ┌────────────┐  ┌───────────────┐   │
│  │ LLaMA 3.1  │  │ moondream2 │  │nomic-embed-txt│   │
│  │  (8B text) │  │  (vision)  │  │ (embeddings)  │   │
│  └────────────┘  └────────────┘  └───────────────┘   │
├──────────────────────────────────────────────────────┤
│             STORAGE & OS LAYER                        │
│  ChromaDB │ SQLite │ Encrypted Files │ Windows APIs   │
└──────────────────────────────────────────────────────┘
```

### 3.3 Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Backend Framework | FastAPI + Uvicorn | Async REST API server |
| LLM Runtime | Ollama | Local model inference |
| Text Model | LLaMA 3.1 (8B) | Conversation, reasoning |
| Vision Model | Moondream2 | Screenshot analysis |
| Embedding Model | nomic-embed-text | Document vectorization |
| Vector Database | ChromaDB | Persistent similarity search |
| Tokenizer | tiktoken (cl100k_base) | Text chunking |
| Speech-to-Text | Faster-Whisper (int8) | Voice transcription |
| Text-to-Speech | pyttsx3 | Voice output |
| VAD | WebRTC VAD / RMS fallback | Speech detection |
| PDF Extraction | PyMuPDF (fitz) | PDF text extraction |
| Encryption | cryptography (Fernet) | Profile data security |
| Pattern Storage | SQLite + NetworkX | Workflow memory |
| Desktop UI | Electron.js | Sidebar panel |
| Bot Framework | python-telegram-bot | Mobile interface |
| Browser Extension | Chrome MV3 | Form auto-filling |
| Launcher | PyInstaller + tkinter | Windows EXE packaging |
| Process Monitoring | psutil | System info & watchdog |

### 3.4 Data Flow Diagram

```
User Input (Text/Voice/File)
        │
        ▼
┌──────────────────┐
│ Interface Layer   │ (Telegram / Electron / Chrome)
└────────┬─────────┘
         │ HTTP POST
         ▼
┌──────────────────┐
│  Intent Classifier│ → Confidence < 0.75? → Disambiguate
└────────┬─────────┘
         │
         ▼
┌──────────────────┐    ┌──────────────┐
│  NL Processor    │───▶│ Self-Healing │ (on failure)
└────────┬─────────┘    └──────────────┘
         │
    ┌────┴────┬──────────┬──────────┐
    ▼         ▼          ▼          ▼
 File Ops  RAG Query  Screenshot  Voice TTS
    │         │          │          │
    │    ┌────┴────┐     │          │
    │    │ChromaDB │     │          │
    │    │ Search  │     │          │
    │    └────┬────┘     │          │
    │         ▼          ▼          │
    │      Ollama     Ollama        │
    │      (Text)    (Vision)       │
    │         │          │          │
    └────┬────┴──────────┴──────────┘
         ▼
   Response to User
         │
         ▼
   Workflow Memory (log action → detect patterns)
```

### 3.5 Module Descriptions

| Module | File | Lines of Code | Responsibility |
|--------|------|--------------|----------------|
| Backend API | `main.py` | 650 | FastAPI endpoints, routing |
| RAG Pipeline | `rag.py` | 448 | Indexing, chunking, embedding, search |
| NL Processor | `nl_processor.py` | 630 | Natural language → system commands |
| Voice Engine | `voice_engine.py` | 417 | Wake word, VAD, STT, TTS |
| Autofill Engine | `autofill.py` | 209 | Encrypted profile management |
| Intent Classifier | `intent_confidence.py` | 72 | Hybrid keyword+LLM classification |
| Self-Healing Agent | `self_healing.py` | 145 | Auto-recovery from failures |
| Workflow Memory | `workflow_memory.py` | 133 | Pattern detection & automation |
| Profile Learner | `profile_learner.py` | 126 | Adaptive autofill learning |
| Telegram Bot | `bot.py` | ~400 | 14 commands + voice + file upload |
| Electron App | `main.js + renderer/` | ~300 | Desktop sidebar UI |
| Chrome Extension | `content.js + popup` | ~200 | Form detection & auto-fill |
| Launcher | `launcher.py` | 315 | 14-step startup orchestrator |

---

## 4. WORKING MODEL

### 4.1 Startup Sequence (14 Steps)

```
1.  Acquire single-instance lock (port 47821)
2.  Show tkinter splash screen with progress bar
3.  Check Ollama installation
4.  Start Ollama server
5.  Download/verify AI models (llama3.1:8b, moondream2, nomic-embed-text)
6.  Create vault directory
7.  Install backend Python venv + pip dependencies
8.  Install Telegram bot Python venv + pip dependencies
9.  Install Electron npm dependencies
10. Run first-setup wizard (if new installation)
11. Start FastAPI backend (port 8000)
12. Wait for backend health check (~15s timeout)
13. Start Telegram bot + Electron sidebar
14. Start service watchdog (30s health polling) + system tray
```

### 4.2 User Interaction Flows

#### Flow 1: Document Q&A via Telegram
```
User sends PDF to Telegram → Bot saves to vault → RAG indexes file
  → 500-token chunks → nomic-embed-text embeddings → ChromaDB storage
User asks "/ask What is in the document?"
  → Query embedded → Cosine search → Top-5 chunks → LLaMA 3.1 answers
```

#### Flow 2: Voice Command
```
User says "Nikola" → Wake word detected → "Yes?" (TTS)
User says "What files are in my vault?"
  → Whisper transcribes → POST /ask → LLaMA answers → pyttsx3 speaks
```

#### Flow 3: Screen Problem Solving
```
User sends /solve → Screenshot captured → Resized to 640px
  → Moondream2 describes screen → LLaMA 3.1 diagnoses issue
  → Solution sent to user
```

#### Flow 4: Browser Auto-Fill
```
User visits web form → Chrome extension detects form fields
  → Profile Learner checks learned patterns (SQLite)
  → If high confidence → Direct fill from encrypted profile
  → If low confidence → LLM maps fields → Fill + log correction
```

#### Flow 5: Self-Healing Execution
```
User: "Open my resume" → NL Processor tries direct path → FAILS
  → Self-Healing activates → fuzzy_vault_search → finds resume.pdf
  → Returns result + "I found your resume by searching the vault"
```

### 4.3 Telegram Bot Commands (14 Total)

| Command | Description |
|---------|-------------|
| `/start` | System info (CPU, RAM, disk) |
| `/ask` | Chat with AI + RAG context |
| `/screenshot` | Capture & analyze screen |
| `/solve` | Diagnose screen problems |
| `/get` | Search & download files |
| `/list` | Show indexed files |
| `/files` | List vault files |
| `/remember` | Save encrypted profile data |
| `/profile` | View saved field names |
| `/remove` | Delete indexed file |
| `/clearall` | Delete all indexed files |
| `/run` | Execute system commands |
| Voice msg | Auto-transcribe + process |
| File upload | Auto-index PDF/TXT/MD/PY |

### 4.4 Security Model
- **Local-only inference** — No data leaves the machine
- **Fernet AES-128-CBC encryption** — Profile data encrypted at rest
- **ALLOWED_USER_ID** — Only authorized Telegram user can issue commands
- **safe_path()** — Prevents directory traversal attacks
- **Values never logged** — Only field names appear in logs

### 4.5 Key Results & Metrics

| Metric | Value |
|--------|-------|
| Total modules | 13+ Python/JS modules |
| API endpoints | 20+ REST endpoints |
| AI models used | 3 (text, vision, embedding) |
| Telegram commands | 14 |
| Supported file types | PDF, TXT, MD, PY |
| Startup time | ~30–45 seconds |
| Query latency | 2–5 seconds (local GPU/CPU) |
| Encryption | AES-128 (Fernet) |
| Zero cloud calls | ✅ 100% offline |

### 4.6 Future Enhancements
- DOCX and RTF file support
- Linux and macOS launcher
- Firefox/Safari browser extensions
- Multi-language voice support
- Web-based UI dashboard
- Mobile companion app

---

> **Project demonstrates:** Local AI inference, RAG pipelines, vector databases, NLP, speech processing, encryption, desktop/mobile/browser integration, and production-grade software engineering — all running without any cloud dependency.
