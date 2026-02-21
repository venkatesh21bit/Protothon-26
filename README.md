# Nidaan.ai — AI Clinical Documentation System

<div align="center">

![Nidaan.ai](https://img.shields.io/badge/Nidaan.ai-Clinical%20Intelligence-0066cc?style=for-the-badge)
![Version](https://img.shields.io/badge/version-1.0.0-28a745?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.11-3776ab?style=for-the-badge&logo=python)
![Next.js](https://img.shields.io/badge/Next.js-14-black?style=for-the-badge&logo=next.js)
![Gemini](https://img.shields.io/badge/Gemini-3--flash-4285f4?style=for-the-badge&logo=google)
![License](https://img.shields.io/badge/license-MIT-blue?style=for-the-badge)

**Transform wasted time in the waiting room into life-saving clinical data**

[Architecture](#-system-architecture) • [AI Pipeline](#-ai-pipeline) • [API Reference](#-api-reference) • [Database Schema](#-database-schema) • [Installation](#-installation) • [Usage](#-usage)

</div>

---

## Overview

**Nidaan** (Hindi: निदान — "Diagnosis") converts spoken vernacular patient descriptions into structured SOAP notes, differential diagnoses, and red-flag alerts — before the patient even walks into the consultation room.

### The Problem
- Patients waste 30–60 minutes in waiting rooms filling paper forms
- Language barriers isolate rural patients from English-trained doctors
- Manual history-taking consumes 40% of consultation time
- Critical symptoms are missed through poor communication

### The Solution
1. **Multilingual Active Intake** — patients speak naturally in Tamil, Hindi, Telugu, Marathi, Bengali, Kannada, Malayalam, Gujarati or English
2. **Gemini-Powered STT** — audio streamed inline to `gemini-3-flash-preview`; no third-party transcription service needed
3. **Clinical RAG Chain** — four sequential Gemini prompts produce a SOAP note, differential diagnosis, and red-flag matrix
4. **Doctor Pre-Brief** — structured summary is waiting in the doctor's dashboard before they call the patient in

---

## System Architecture

### Top-level Component Map

```mermaid
graph TD
    subgraph Client["Client Layer"]
        PWA[Patient PWA\nNext.js 14 · App Router]
        DOC[Doctor Dashboard\nNext.js 14]
        NURSE[Nurse Station\nNext.js 14]
        ADMIN[Admin Panel\nNext.js 14]
    end

    subgraph API["API Layer  —  FastAPI 0.104 · Python 3.11 · uvicorn --reload"]
        AUTH["/auth\nJWT HS256"]
        PAT["/patients\nChat · STT · Intake FSM"]
        DOC_R["/doctors\nVisits · SOAP"]
        TRIAGE["/triage\nScore · Alert"]
        APPT["/appointments\nCRUD"]
        WS["/ws\nWebSocket Hub"]
        AGENTS["/ai-agents\nOrchestrator"]
    end

    subgraph AI["AI Layer  —  Google Gemini gemini-3-flash-preview"]
        CHAT_G["Intake Chat\nConversational FSM\nmax_output_tokens=1200"]
        STT_G["Inline Audio STT\nPart.from_bytes()\nWebM · OGG · WAV · MP3"]
        CHAIN["MedicalRAGChain\n4 sequential prompts"]
        ORCH["AgentOrchestrator\n4 async sub-agents"]
        TRIAGE_E["TriageEngine\nKeyword scoring + NLU"]
    end

    subgraph DATA["Data Layer"]
        PG[(PostgreSQL 15\ntriage_cases JSONB\nsurveys JSONB)]
        REDIS[(Redis 7\nRate limits · WS pub/sub)]
        FS[(Local Filesystem\naudio uploads)]
    end

    subgraph NOTIFY["Notification Layer"]
        SMTP[Gmail SMTP TLS\nNurse HIGH-severity alerts]
        WS_OUT[WebSocket broadcast\nReal-time dashboard push]
    end

    PWA & DOC & NURSE & ADMIN -->|HTTPS REST + WS| API
    PAT -->|generate_content| CHAT_G & STT_G
    DOC_R -->|on demand| CHAIN
    TRIAGE -->|score| TRIAGE_E
    AGENTS -->|coordinates| ORCH
    CHAIN & ORCH & TRIAGE_E --> PG
    TRIAGE_E -->|HIGH alert| SMTP
    WS -->|pub/sub| REDIS & WS_OUT
    API -->|asyncpg pool size=10 overflow=20| PG
    AUTH -->|bcrypt verify| PG
```

---

## Request Lifecycles

### 1 · Patient Intake Chat

```mermaid
sequenceDiagram
    participant Browser
    participant NextJS as Next.js :3000
    participant FastAPI as FastAPI :8000
    participant Gemini as Gemini API
    participant PG as PostgreSQL

    Browser->>NextJS: POST /patients/chat {message, history, language}
    NextJS->>FastAPI: Bearer JWT · proxy
    FastAPI->>FastAPI: get_current_user() — decode HS256 JWT
    FastAPI->>FastAPI: _get_or_create_collected(user_id)
    FastAPI->>FastAPI: _next_missing_field(collected) → next_field
    FastAPI->>FastAPI: _build_system_prompt(collected, turn, next_field)
    FastAPI->>FastAPI: sanitise history — strip <data>…</data> blocks
    FastAPI->>Gemini: generate_content(model, system_instruction, contents[])
    Note over Gemini: max_output_tokens=1200
    Gemini-->>FastAPI: raw_text
    FastAPI->>FastAPI: _extract_data_json() → merge into collected dict
    FastAPI->>FastAPI: re.sub strip <data> from visible_text
    FastAPI->>PG: UPSERT triage_cases SET data = jsonb_set(…)
    FastAPI-->>Browser: {response, collected_symptoms, severity_assessment}
```

### 2 · Voice STT Pipeline

```mermaid
sequenceDiagram
    participant Mic as Browser Mic
    participant WA as Web Audio API
    participant MR as MediaRecorder
    participant NextJS as Next.js
    participant FastAPI as FastAPI
    participant Gemini as Gemini API

    Mic->>WA: getUserMedia({channelCount:1, sampleRate:16000, echoCancellation:true})
    WA->>WA: AudioContext → AnalyserNode fftSize=256
    Note over WA: rAF loop: getByteFrequencyData() → mean/255 → audioLevel 0‥1
    WA->>MR: MediaRecorder(stream, mimeType='audio/webm;codecs=opus')
    MR->>MR: start(timeslice=250ms) → ondataavailable chunks[]
    Note over MR: User taps Stop orb
    MR->>MR: stop() → onstop fires → Blob(chunks)
    MR->>NextJS: Blob size check (< 500 B → abort)
    NextJS->>FastAPI: POST /api/v1/patients/voice-transcribe\nmultipart: audio=<blob> language=ta-IN
    FastAPI->>FastAPI: detect MIME from content_type
    FastAPI->>Gemini: generate_content([prompt, Part.from_bytes(bytes, mime)])
    Note over Gemini: Inline audio — max 20 MB\nFormats: WebM OGG WAV MP3 AAC FLAC
    Gemini-->>FastAPI: transcript (Tamil / Hindi / etc.)
    FastAPI-->>NextJS: {transcript, language}
    NextJS->>NextJS: setChatInput(transcript) or processVoiceInput(transcript)
```

### 3 · SOAP Note Generation

```mermaid
sequenceDiagram
    participant Dashboard as Doctor Dashboard
    participant FastAPI as FastAPI
    participant RAGChain as MedicalRAGChain
    participant Gemini as Gemini API
    participant PG as PostgreSQL

    Dashboard->>FastAPI: GET /api/v1/doctors/visits/{id}
    FastAPI->>PG: SELECT data JSONB FROM triage_cases WHERE id=?
    alt soap_note absent in JSONB
        FastAPI->>RAGChain: generate_soap_note(transcript, symptoms, language)
        RAGChain->>Gemini: Chain 1 — CLINICAL_TRANSLATION_PROMPT
        Gemini-->>RAGChain: medical_english
        RAGChain->>Gemini: Chain 2 — SOAP_NOTE_GENERATION_PROMPT
        Gemini-->>RAGChain: {subjective, objective, assessment, plan}
        RAGChain->>Gemini: Chain 3 — DIFFERENTIAL_DIAGNOSIS_PROMPT
        Gemini-->>RAGChain: [{condition, probability, reasoning, urgency}]
        RAGChain->>Gemini: Chain 4 — RED_FLAG_DETECTION_PROMPT
        Gemini-->>RAGChain: [{flag, severity, recommended_action}]
        FastAPI->>PG: UPDATE triage_cases SET data = jsonb_set(…soap_note…)
    end
    FastAPI-->>Dashboard: VisitDetailResponse
```

---

## AI Pipeline

### Conversational Intake — Finite State Machine

The intake is a **6-field state machine** running over `MAX_TURNS = 12` turns:

```
INTAKE_FIELDS = [
  "symptoms",            # chief complaint
  "duration",            # hours / days / weeks
  "severity",            # 1–10 pain scale
  "location",            # body part / side / region
  "associated_symptoms", # accompanying symptoms
  "medical_history",     # known conditions + current medications
]

INTAKE_THRESHOLD = 4    # minimum fields before triage is triggered
MAX_TURNS        = 12   # forces wrap-up summary at turn 12
```

Per-turn logic:

```
_get_or_create_collected(user_id)
  └─ _next_missing_field(collected)      → next_field (first empty field)
       └─ _build_system_prompt(...)
            ├─ LANGUAGE RULE: reply in same language as patient
            ├─ INFORMATION ALREADY COLLECTED block  (prevents re-asking)
            ├─ NEXT ACTION: field-specific question script
            └─ 8 ABSOLUTE FORBIDDEN rules
                 1. Never diagnose or speculate
                 2. Never ask for already-known info
                 3. Ask one question per turn
                 4. No medical jargon to patient
                 5. Graceful off-topic redirect
                 6. Warm, culturally sensitive tone
                 7. NEVER re-ask info already listed
                 8. ALWAYS write complete sentences
  └─ sanitise_history()
       └─ re.sub(r"\s*<data>[\s\S]*?(?:</data>|$)", "", msg.content)
  └─ Gemini generate_content  (max_output_tokens=1200)
  └─ _extract_data_json(raw)  → parse JSON in <data>{…}</data>
  └─ visible_text = re.sub(r"\s*<data>[\s\S]*$", "", raw)
  └─ merge extracted fields into collected dict
  └─ UPSERT triage_cases JSONB
```

### MedicalRAGChain — 4-Step Gemini Pipeline

| # | Method | Prompt Template | Output Schema |
|---|--------|-----------------|---------------|
| 1 | `translate_to_medical_english` | `CLINICAL_TRANSLATION_PROMPT` | `str` — medical English |
| 2 | `generate_soap_note` | `SOAP_NOTE_GENERATION_PROMPT` | `{subjective, objective, assessment, plan}` |
| 3 | `generate_differential_diagnosis` | `DIFFERENTIAL_DIAGNOSIS_PROMPT` | `[{condition, probability, reasoning, urgency}]` |
| 4 | `detect_red_flags` | `RED_FLAG_DETECTION_PROMPT` | `[{flag, severity, recommended_action}]` |

All steps use `google-genai` SDK (`genai.Client.models.generate_content`). Falls back to deterministic mock responses when `GEMINI_API_KEY` is absent.

### TriageEngine — Rule + NLU Severity Scoring

```
Input: symptom list + free-text description

Step 1 — Keyword scan (60+ terms)
  RED_FLAG_SYMPTOMS dict  →  each maps to HIGH / MEDIUM / LOW
  e.g. "chest pain" → HIGH, "palpitations" → MEDIUM, "nausea" → LOW

Step 2 — Composite severity score
  base_score   = max(keyword_severity_values)
  count_boost  = len(symptoms) × 0.10
  duration_mod = 0.0 (hours) | 0.1 (days) | 0.2 (weeks+)
  age_mod      = 0.15 if age > 60 else 0.0
  final        = clamp(base_score + count_boost + duration_mod + age_mod,
                       LOW, HIGH)

Step 3 — NLU entity enrichment (nlu_processor.py)
  Entity types: body_part, temporal, medication, negation
  Signal amplifiers: "severe", "unbearable", "worst ever" → +1 severity tier

Step 4 — Persist + alert
  triage_cases.severity_score = HIGH | MEDIUM | LOW
  triage_cases.status         = 'pending'
  IF HIGH → email_service.send_nurse_alert()  (Gmail SMTP port 587 TLS)
```

### AgentOrchestrator — 5-Stage Multi-Agent Workflow

```mermaid
flowchart LR
    A([Appointment\nCreated]) --> B
    B["Stage 1\nSymptomAnalyzerAgent\nurgency · severity_score\npossible_conditions[]"] --> C
    C["Stage 2\nAppointmentSchedulerAgent\nauto-schedule slot\nbased on urgency tier"] --> D
    D["Stage 3\nTriageAgent\nER · GP · Specialist\nrouting decision"] --> E
    E["Stage 4\nFollowUpAgent\ncare plan + reminders\nmedication notes"] --> F
    F([Workflow Result\nstages[] + final_status\nworkflow_id + timestamps])
```

---

## Database Schema

```sql
-- One row per patient visit / triage encounter
CREATE TABLE triage_cases (
    id             TEXT PRIMARY KEY,          -- UUID v4
    patient_id     TEXT NOT NULL,             -- references users table
    severity_score TEXT NOT NULL DEFAULT 'LOW',   -- HIGH | MEDIUM | LOW
    status         TEXT NOT NULL DEFAULT 'pending', -- pending | in_progress | completed
    nurse_alerted  BOOLEAN NOT NULL DEFAULT FALSE,
    data           JSONB NOT NULL DEFAULT '{}',  -- entire encounter payload
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_triage_cases_patient         ON triage_cases (patient_id);
CREATE INDEX idx_triage_cases_severity_status ON triage_cases (severity_score, status);

-- Survey form responses
CREATE TABLE surveys (
    id             TEXT PRIMARY KEY,
    patient_id     TEXT NOT NULL,
    appointment_id TEXT,
    status         TEXT NOT NULL DEFAULT 'pending',
    data           JSONB NOT NULL DEFAULT '{}',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_surveys_patient     ON surveys (patient_id);
CREATE INDEX idx_surveys_appointment ON surveys (appointment_id);
```

**`triage_cases.data` JSONB shape:**

```json
{
  "patient_name": "Ravi Kumar",
  "language": "ta-IN",
  "collected": {
    "symptoms": ["chest pain", "shortness of breath"],
    "duration": "2 days",
    "severity": "8",
    "location": "left chest, radiates to left arm",
    "associated_symptoms": ["nausea", "diaphoresis"],
    "medical_history": ["hypertension", "aspirin 75mg daily"]
  },
  "soap_note": {
    "subjective":  "Patient reports 2-day history of chest pain…",
    "objective":   "Vital signs pending. Patient appears distressed.",
    "assessment":  "Likely ACS given risk factors and symptom pattern.",
    "plan":        "Immediate ECG, troponin, cardiology referral."
  },
  "differential_diagnosis": [
    {"condition": "Acute Coronary Syndrome", "probability": "HIGH",
     "reasoning": "Chest pain with radiation, diaphoresis, hypertension"},
    {"condition": "Unstable Angina",         "probability": "MEDIUM",
     "reasoning": "Exertional component not yet confirmed"}
  ],
  "red_flags": [
    {"flag": "chest pain with arm radiation",
     "severity": "CRITICAL",
     "recommended_action": "Immediate ECG + troponin; do not delay"}
  ],
  "conversation_turns": 7
}
```

---

## Authentication & Security

```mermaid
sequenceDiagram
    participant Client
    participant FastAPI
    participant BCrypt
    participant PG as PostgreSQL

    Client->>FastAPI: POST /api/v1/auth/login {email, password}
    FastAPI->>PG: SELECT hashed_password, role FROM users WHERE email=?
    FastAPI->>BCrypt: verify(plain, hashed)  — cost factor 12
    BCrypt-->>FastAPI: True / False
    FastAPI->>FastAPI: jwt.encode({sub, role, exp: +24h}, HS256)
    FastAPI-->>Client: {access_token, token_type:"bearer"}

    Note over Client,FastAPI: All subsequent requests
    Client->>FastAPI: Authorization: Bearer <token>
    FastAPI->>FastAPI: jwt.decode(token) → {sub, role, exp}
    FastAPI->>FastAPI: get_current_user() → injects user dict
```

| Parameter | Value |
|-----------|-------|
| Algorithm | HS256 |
| Token lifetime | 24 h (configurable) |
| Password hashing | BCrypt cost=12 |
| Transport (prod) | TLS 1.3 |
| Rate limiting | 60 req/min per IP via Redis |
| CORS | configurable origin allow-list |

---

## API Reference

### Patient Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/patients/chat` | Stateful intake chat — FSM-driven, multi-turn |
| `POST` | `/api/v1/patients/voice-transcribe` | Gemini inline audio STT (multipart) |
| `POST` | `/api/v1/patients/reset` | Reset conversation state |
| `GET`  | `/api/v1/patients/` | List patients (admin/nurse) |
| `POST` | `/api/v1/patients/` | Register new patient |

**`POST /api/v1/patients/chat`**
```jsonc
// Request
{
  "message": "நேற்று இரவிலிருந்து மார்பில் வலி உள்ளது",
  "conversation_history": [
    {"role": "assistant", "content": "வணக்கம்! நான் Nidaan AI…"}
  ],
  "language": "ta-IN"
}
// Response
{
  "response": "உங்கள் வலி எந்த இடத்தில் அதிகமாக உள்ளது?",
  "collected_symptoms": ["chest pain"],
  "severity_assessment": "MEDIUM"
}
```

**`POST /api/v1/patients/voice-transcribe`**
```
Content-Type: multipart/form-data
audio:    <binary — WebM / OGG / WAV / MP3 / AAC / FLAC>  max 20 MB
language: ta-IN | hi-IN | te-IN | en-IN | …
```
```json
{"transcript": "நேற்று இரவிலிருந்து மார்பில் வலி உள்ளது", "language": "ta-IN"}
```

### Doctor Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/api/v1/doctors/visits` | All pending / in-progress visits |
| `GET`  | `/api/v1/doctors/visits/{id}` | Visit detail — triggers SOAP generation if absent |
| `PUT`  | `/api/v1/doctors/visits/{id}` | Update visit status |
| `GET`  | `/api/v1/doctors/profile` | Doctor profile |

### Triage Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/triage/assess` | Score symptoms, persist case, alert nurse if HIGH |
| `GET`  | `/api/v1/triage/cases` | List all triage cases |
| `GET`  | `/api/v1/triage/cases/{id}` | Single case detail |
| `POST` | `/api/v1/triage/voice` | Process voice triage recording |

### Admin & Agents

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/ai-agents/process-appointment` | Trigger 5-stage agent workflow |
| `GET`  | `/api/v1/admin/stats` | Clinic-wide analytics |
| `GET`  | `/api/v1/health` | Service health check |

---

## Frontend Architecture

### Page Structure (Next.js 14 App Router)

```
apps/web/app/
├── layout.tsx                    # RootLayout + Tailwind globals
├── page.tsx                      # Root → redirect by JWT role
├── login/page.tsx                # Login form → POST /auth/login
├── register/page.tsx             # Patient registration
├── patient/
│   ├── page.tsx                  # ★ Main patient interface
│   │                              #   Chat mode: stateful Gemini FSM
│   │                              #   Voice mode: MediaRecorder → Gemini STT
│   │                              #              + browser TTS (speechSynthesis)
│   ├── survey/                   # Pre-visit form
│   ├── triage/                   # Result display
│   └── triage-enhanced/          # Animated triage result
├── doctor/
│   ├── dashboard/                # Visit queue + risk stratification
│   ├── dashboard-enhanced/       # Real-time WS + charts
│   └── visit/[visitId]/          # SOAP + differential + red flags
├── nurse/dashboard/              # Nurse alert queue
└── admin/
    ├── dashboard/                # Clinic analytics
    ├── appointments/             # Appointment management
    └── agents/                   # Agent workflow monitor
```

### State Management (Zustand — `lib/store.ts`)

```typescript
interface NidaanStore {
  // Auth slice
  user:  User | null
  token: string | null
  setAuth(user: User, token: string): void
  logout(): void

  // Doctor slice
  visits:      Visit[]
  activeVisit: Visit | null
  setVisits(v: Visit[]): void
  setActiveVisit(v: Visit): void

  // Patient slice
  triageCase: TriageCase | null
  setTriageCase(tc: TriageCase): void
}
```

### WebSocket Integration (`lib/useWebSocket.ts`)

```typescript
// ws://localhost:8000/api/v1/ws/{user_id}
// Message types dispatched by server:
//   visit_update   → update visit in store
//   new_alert      → toast notification
//   agent_progress → render workflow stage UI
useWebSocket(userId, {
  onVisitUpdate: (visit) => store.setActiveVisit(visit),
  onAlert:       (alert) => toast(alert.message),
})
```

### Voice Recording Architecture

```
navigator.mediaDevices.getUserMedia
  └─ AudioContext (16 kHz mono)
       ├─ AnalyserNode fftSize=256
       │    └─ rAF: getByteFrequencyData() → mean(buf)/255 → audioLevel
       │         └─ CSS: width = ${128 + audioLevel×60}px  (live ring)
       └─ MediaRecorder (audio/webm;codecs=opus, timeslice=250 ms)
            └─ ondataavailable → chunks.push(e.data)  (250 ms slices)
            └─ onstop
                 ├─ Blob(chunks, {type: 'audio/webm;codecs=opus'})
                 ├─ size < 500 B → abort (silence guard)
                 └─ FormData → POST /api/v1/patients/voice-transcribe
                      └─ transcript → setChatInput() or processVoiceInput()
```

---

## Infrastructure

### Docker Compose

```mermaid
graph LR
    subgraph Stack["docker-compose.yml"]
        WEB["web :3000\nNext.js 14 · Node 18-alpine\nnpm run dev · hot reload"]
        API["api :8000\nFastAPI · Python 3.11-slim\nuvicorn --reload"]
        PG["postgres :5433→5432\npostgres:15-alpine"]
        REDIS["redis :6380→6379\nredis:7-alpine"]
    end

    WEB -->|HTTP proxy| API
    API -->|asyncpg pool_size=10 max_overflow=20| PG
    API -->|aioredis| REDIS
```

| Service | Image | Host Port | Volume |
|---------|-------|-----------|--------|
| `web`     | Node 18-alpine      | 3000 | `./apps/web:/app` (hot reload) |
| `api`     | Python 3.11-slim    | 8000 | `./apps/api:/app` (uvicorn --reload) |
| `postgres`| postgres:15-alpine  | 5433 | `postgres-data` (named volume) |
| `redis`   | redis:7-alpine      | 6380 | `redis-data` (named volume) |

### Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `GEMINI_API_KEY` | **Yes** | — | Google AI Studio key |
| `GEMINI_MODEL` | No | `gemini-3-flash-preview` | Model name |
| `DATABASE_URL` | **Yes** | — | asyncpg connection string |
| `REDIS_URL` | No | `redis://localhost:6379` | Redis connection |
| `JWT_SECRET` | **Yes (prod)** | `your-secret-key…` | HS256 signing secret |
| `JWT_EXPIRATION_MINUTES` | No | `1440` (24 h) | Token lifetime |
| `SMTP_EMAIL` | No | — | Nurse alert sender |
| `SMTP_PASSWORD` | No | — | Gmail app password |
| `NURSE_STATION_EMAIL` | No | — | Alert recipient |
| `STORAGE_PATH` | No | `./uploads` | Audio file directory |
| `DEBUG` | No | `True` | Enable Swagger UI + SQL echo |

---

## Supported Languages

| Language | Code | Gemini Chat | Gemini STT |
|----------|------|-------------|-----------|
| Tamil | `ta-IN` | ✅ | ✅ |
| Hindi | `hi-IN` | ✅ | ✅ |
| Telugu | `te-IN` | ✅ | ✅ |
| Marathi | `mr-IN` | ✅ | ✅ |
| Bengali | `bn-IN` | ✅ | ✅ |
| Kannada | `kn-IN` | ✅ | ✅ |
| Malayalam | `ml-IN` | ✅ | ✅ |
| Gujarati | `gu-IN` | ✅ | ✅ |
| Punjabi | `pa-IN` | ✅ | ✅ |
| English | `en-IN` / `en-US` | ✅ | ✅ |

STT uses `types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)` — the same `gemini-3-flash-preview` model handles both transcription and clinical reasoning with no additional service.

---

## Project Structure

```
nidaan/
├── docker-compose.yml
├── apps/
│   ├── api/                               # FastAPI backend
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── app/
│   │       ├── main.py                    # App factory · lifespan events
│   │       ├── core/
│   │       │   ├── config.py              # Pydantic Settings (env vars)
│   │       │   ├── db.py                  # SQLAlchemy async engine + DDL
│   │       │   ├── security.py            # JWT + BCrypt
│   │       │   └── exceptions.py          # Custom exception hierarchy
│   │       ├── api/v1/
│   │       │   ├── router.py              # Top-level API router
│   │       │   ├── auth.py                # Login / register
│   │       │   ├── patients.py            # ★ Chat FSM + Gemini STT
│   │       │   ├── doctors.py             # Visit queue + SOAP
│   │       │   ├── triage.py              # Triage assess + voice
│   │       │   ├── appointments.py        # Appointment CRUD
│   │       │   ├── ai_agents.py           # Agent workflow API
│   │       │   ├── websocket.py           # WS hub + broadcast
│   │       │   └── admin.py               # Clinic stats
│   │       ├── schemas/
│   │       │   ├── patient.py             # PatientCreate / Response
│   │       │   ├── triage.py              # TriageCase schemas
│   │       │   └── medical.py             # SOAP / Differential models
│   │       └── services/
│   │           ├── llm_engine/
│   │           │   ├── chain.py           # MedicalRAGChain (4 Gemini calls)
│   │           │   └── prompts.py         # Prompt templates
│   │           ├── ai_agents/
│   │           │   ├── orchestrator.py    # AgentOrchestrator
│   │           │   ├── symptom_analyzer.py
│   │           │   ├── appointment_scheduler.py
│   │           │   ├── triage_agent.py
│   │           │   └── followup_agent.py
│   │           ├── ibm/
│   │           │   ├── triage_engine.py   # Rule + NLU severity scoring
│   │           │   ├── nlu_processor.py   # Entity extraction
│   │           │   └── email_service.py   # SMTP nurse alerts
│   │           ├── storage.py             # Filesystem audio storage
│   │           └── seed_data.py           # Demo data seeder
│   └── web/                               # Next.js 14 frontend
│       ├── app/                           # App Router pages
│       ├── components/                    # Shared React components
│       └── lib/
│           ├── api.ts                     # Typed fetch client
│           ├── store.ts                   # Zustand global store
│           ├── useWebSocket.ts            # WS hook
│           └── utils.ts                  # cn() + helpers
```

---

## Installation

### Quick Start (Docker)

```bash
git clone https://github.com/venkatesh21bit/Nidaan .
cd nidaan

# Minimum: set your Gemini key inside docker-compose.yml
# or copy an .env and edit it:
cp apps/api/.env.example apps/api/.env

docker-compose up -d
docker-compose logs -f api   # watch startup
```

| URL | Service |
|-----|---------|
| http://localhost:3000/patient | Patient voice & chat interface |
| http://localhost:3000/doctor/dashboard | Doctor visit queue |
| http://localhost:3000/admin/dashboard | Admin analytics |
| http://localhost:8000/api/docs | Swagger UI (DEBUG=True) |
| http://localhost:8000/api/redoc | ReDoc |

### Local Development

**Backend:**
```bash
cd apps/api
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export GEMINI_API_KEY=your_key
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/nidaan
uvicorn app.main:app --reload --port 8000
```

**Frontend:**
```bash
cd apps/web
npm install
echo "NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1" > .env.local
npm run dev
```

---

## Demo Accounts

| Role | Email | Password |
|------|-------|----------|
| Doctor | `doctor@nidaan.ai` | `password` |
| Admin | `admin@nidaan.ai` | `admin123` |
| Demo  | `demo@nidaan.ai`  | `demo123`  |

---

## Contributing

1. Fork → `git checkout -b feat/your-feature`
2. Commit → `git commit -m 'feat: describe change'`
3. Push → `git push origin feat/your-feature`
4. Open a pull request

---

## License

MIT — see [LICENSE](LICENSE) for details.

---

<div align="center">

**Made in India 🇮🇳 for India**

*Transforming Healthcare Documentation, One Voice at a Time*

</div>
