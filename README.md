# Banking AI Agent

A friendly bank assistant ("Asha") built with FastAPI, SQLAlchemy and Claude. It can:

- answer everyday banking questions
- explain how to open a new account (savings, zero-balance, salary, current)
- help fill in account and loan application forms step by step, then save them to the database
- cover gold, house (home) and personal loans: rates, documents, eligibility and EMI
- check the status of an application

## Run

```bash
cd ~/banking-agent
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...        # or run `ant auth login`
./venv/bin/uvicorn app.main:app --reload
```

- Chat UI: http://localhost:8000/
- API docs (Swagger): http://localhost:8000/docs

## Configuration (env vars)

| Var | Default | |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./bank.db` | any SQLAlchemy URL (Postgres/MySQL) |
| `CLAUDE_MODEL` | `claude-opus-5` | |
| `CLAUDE_EFFORT` | `medium` | `low` is cheaper/faster for simple FAQ traffic |
| `BANK_NAME` | `Sunrise Bank` | used in the system prompt |

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/chat` | `{"message": "...", "session_id": null}` → `{session_id, reply, actions}` |
| GET | `/chat/{session_id}` | conversation transcript |
| GET | `/accounts/types` | account catalogue |
| GET | `/loans?category=gold\|house\|personal` | loan catalogue |
| GET | `/forms/{account\|loan}?product_code=` | fields required for a form |
| GET | `/loans/emi?principal=&annual_rate_pct=&tenure_months=` | EMI calculator |
| POST | `/applications/account` | submit an account application |
| POST | `/applications/loan` | submit a loan application (runs an eligibility pre-check) |
| GET | `/applications/{ref}?phone_last4=` | application status |

```bash
curl -s localhost:8000/chat -H 'content-type: application/json' \
  -d '{"message":"I want a gold loan for 2 lakhs, what documents do I need?"}'
```

## Layout

```
app/
  main.py      FastAPI routes
  agent.py     Claude tool-use loop + system prompt; history stored in chat_sessions
  tools.py     tool schemas exposed to Claude -> services
  services.py  business logic (catalogue, EMI, eligibility, applications)
  models.py    SQLAlchemy tables
  seed.py      sample products - replace with your bank's real rates
  static/index.html  chat UI
```

## Before production

- The rates, limits and gold price in `seed.py` / `services.py` are **sample values**.
- Add authentication (e.g. OTP login) before letting the agent read customer data.
- PAN and other PII are stored in plain text. Encrypt them at rest and follow RBI data-localisation rules.
- Eligibility is an indicative check only. Wire in your real credit bureau and LOS/CBS systems.
