"""Claude-powered banking assistant: a tool-use loop whose history is persisted in the DB."""

import os
import uuid

import anthropic
from sqlalchemy.orm import Session

from .models import ChatSession
from .tools import TOOLS, run_tool

MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5")
EFFORT = os.getenv("CLAUDE_EFFORT", "medium")  # low | medium | high - chat rarely needs more
MAX_TOOL_ROUNDS = 8
BANK_NAME = os.getenv("BANK_NAME", "Sunrise Bank")

SYSTEM_PROMPT = f"""You are "Asha", the friendly virtual assistant of {BANK_NAME}, an Indian retail bank.
You help customers with day-to-day banking questions, opening new accounts, filling application forms,
and loans - gold loans, home (house) loans and personal loans.

How to talk:
- Warm, simple and encouraging. Short paragraphs, bullet points for steps and document lists.
- Use INR amounts formatted like ₹5,00,000. Reply in the language the customer writes in.
- Always end with a helpful next step or question so the customer knows what to do next.

How to work:
- Product facts (rates, limits, fees, documents, eligibility) come ONLY from your tools. Never invent numbers.
- Filling a form: call get_form_fields first, then collect the fields a few at a time (not all at once).
  Before submitting, show a neat summary of every field and ask "Shall I submit this?".
  Call a submit_* tool only after the customer clearly says yes.
- If a tool returns an error, explain it kindly and ask for the corrected value.
- Eligibility and EMI results are indicative; say so.
- Never ask for passwords, OTPs, CVV, PIN or full card numbers. If a customer shares one, tell them not to share it with anyone.
- For complaints, fraud, blocked cards or anything you cannot do, give the 24x7 helpline 1800-123-4567 and suggest visiting a branch.
- Stay on banking topics; politely steer other requests back."""

client = anthropic.Anthropic()


class NotConfiguredError(RuntimeError):
    pass


def _serialize(content) -> list[dict]:
    # `fallback` blocks are audit markers only; drop them from the replayed history.
    return [b.model_dump(mode="json", exclude_none=True) for b in content if b.type != "fallback"]


def _text(content) -> str:
    return "\n".join(b.text for b in content if b.type == "text").strip()


def chat(db: Session, message: str, session_id: str | None = None) -> dict:
    if not (client.api_key or client.auth_token):
        raise NotConfiguredError("Assistant is not configured: set ANTHROPIC_API_KEY in the environment or in .env.")
    session = db.get(ChatSession, session_id) if session_id else None
    if session is None:
        session = ChatSession(id=session_id or str(uuid.uuid4()), messages=[])
        db.add(session)

    messages = list(session.messages) + [{"role": "user", "content": message}]
    actions: list[dict] = []
    reply = ""

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            tools=TOOLS,
            messages=messages,
            thinking={"type": "adaptive"},
            output_config={"effort": EFFORT},
            # If a safety classifier declines, retry server-side on Anthropic's recommended fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )

        if response.stop_reason == "refusal":
            reply = "Sorry, I can't help with that request. For further help, please call our 24x7 helpline 1800-123-4567."
            messages = list(session.messages)  # drop the refused turn from the history
            break

        messages.append({"role": "assistant", "content": _serialize(response.content)})

        if response.stop_reason != "tool_use":
            reply = _text(response.content)
            break

        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            output, is_error = run_tool(db, block.name, block.input)
            actions.append({"tool": block.name, "input": block.input, "is_error": is_error})
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": output, "is_error": is_error})
        messages.append({"role": "user", "content": results})
    else:
        reply = "Sorry, that took longer than expected. Could you please rephrase your question?"

    session.messages = messages
    db.commit()
    return {"session_id": session.id, "reply": reply, "actions": actions}


def transcript(session: ChatSession) -> list[dict]:
    """User-visible history: only plain user text and assistant text, no tool plumbing."""
    out = []
    for m in session.messages:
        if isinstance(m["content"], str):
            out.append({"role": m["role"], "text": m["content"]})
        elif m["role"] == "assistant":
            text = "\n".join(b["text"] for b in m["content"] if b.get("type") == "text").strip()
            if text:
                out.append({"role": "assistant", "text": text})
    return out
