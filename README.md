# MuftyKare Voice Agent

Telugu-first AI voice agent for [MuftyKare](https://muftykare.com) — a premium laundry and dry-cleaning service in Visakhapatnam, India.

## Tech Stack

| Layer | Technology |
|---|---|
| Voice orchestration | LiveKit Agents SDK (Python) v1.6.x |
| STT | Sarvam `saaras:v3` — Telugu + English + code-mixed |
| LLM | OpenAI `gpt-4o` |
| TTS | Sarvam `bulbul:v3` — Telugu voice |
| Database | PostgreSQL via `asyncpg` |
| API server | FastAPI + Uvicorn |
| SIP/Telephony | Plivo (dev) → Vobiz (production) |

---

## Project Structure

```
muftykare-agent/
├── agent.py                  ← LiveKit worker entrypoint (AgentServer pattern)
├── muftykare_agent.py        ← MuftyKareAgent class (extends Agent)
├── prompts.py                ← Telugu system prompt
├── tools/
│   ├── __init__.py
│   ├── customer.py           ← lookup_customer, save_new_customer
│   ├── booking.py            ← create_booking, check_slot_availability, get_order_status
│   └── sms.py                ← send_sms_confirmation
├── db/
│   ├── __init__.py
│   ├── connection.py         ← asyncpg pool setup
│   └── queries.py            ← SQL query functions
├── server.py                 ← FastAPI app (health + outbound call API)
├── requirements.txt
└── .env.example
```

---

## Component Build Status

| Component | Description | Status |
|---|---|---|
| **1** | Project setup, folder structure, LiveKit connection | ✅ Done |
| **2** | Wire Sarvam STT + OpenAI LLM + Sarvam TTS | 🔜 Next |
| **3** | Telugu system prompt (full, production-grade) | 🔜 |
| **4** | Telugu greeting + conversation flow | 🔜 |
| **5** | asyncpg tool implementations + DB schema | 🔜 |
| **6** | Outbound call API + Plivo webhook | 🔜 |

---

## Getting Started

### 1. Create and activate a virtual environment

```bash
python -m venv venv

# macOS/Linux:
source venv/bin/activate

# Windows:
venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env with your actual keys
```

Required keys:
- `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` — from your [LiveKit Cloud](https://cloud.livekit.io) project
- `OPENAI_API_KEY` — from [OpenAI Platform](https://platform.openai.com)
- `SARVAM_API_KEY` — from [Sarvam AI](https://sarvam.ai)
- `DATABASE_URL` — PostgreSQL connection string
- `PLIVO_AUTH_ID`, `PLIVO_AUTH_TOKEN`, `PLIVO_PHONE_NUMBER` — from [Plivo](https://plivo.com)

### 4. Run the voice agent (dev mode with hot reload)

```bash
python agent.py dev
```

### 5. Run the FastAPI server (separate terminal)

```bash
python server.py
```

### 6. Test the agent

1. Open [https://agents-playground.livekit.io](https://agents-playground.livekit.io)
2. Enter your `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET`
3. Connect — you should see `muftykare-agent` appear as a participant in the room
4. Terminal should log: room name + participant identity when you join

### 7. Verify tool imports

```bash
python -c "from tools.customer import lookup_customer; print('OK')"
python -c "from tools.booking import create_booking; print('OK')"
python -c "from tools.sms import send_sms_confirmation; print('OK')"
python -c "from db.connection import get_pool; print('OK')"
```

---

## Key Implementation Notes

- **Agent pattern**: Uses `AgentServer` + `@server.rtc_session()` from LiveKit Agents v1.6.x. The old `WorkerOptions(entrypoint_fnc=...)` pattern is **not used**.
- **Sarvam STT config** (Component 2): `flush_signal=True` — required for VAD/turn-taking. No separate VAD plugin needed.
- **AgentSession config** (Component 2): `turn_detection="stt"`, `min_endpointing_delay=0.07` (70ms for Sarvam latency).
- **DB pool**: Created once in `agent.py` entrypoint, injected into `MuftyKareAgent(db_pool=pool)`. Never open a new connection inside a tool function.
- **Tool docstrings**: Always in English — GPT-4o reads these to decide when to call each tool.

---

## API Endpoints (Component 1)

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |

Additional endpoints (`/call/outbound`, `/webhook/plivo`, `/orders/{phone}`) are added in Component 6.
