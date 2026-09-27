from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")  # before importing modules that read env vars

import anthropic
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import agent, services
from .database import Base, SessionLocal, engine, get_db
from .models import ChatSession
from .seed import seed

STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
    yield


app = FastAPI(title="Banking AI Agent", version="1.0", lifespan=lifespan)


# ---------- schemas ----------

class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None


class ChatOut(BaseModel):
    session_id: str
    reply: str
    actions: list[dict]


class CustomerIn(BaseModel):
    full_name: str
    phone: str
    email: str
    date_of_birth: str = Field(description="YYYY-MM-DD")
    pan: str
    address: str


class AccountApplicationIn(BaseModel):
    account_type: str
    customer: CustomerIn


class LoanDetailsIn(BaseModel):
    amount: float
    tenure_months: int
    monthly_income: float | None = None
    employment_type: str | None = None
    gold_weight_grams: float | None = None
    property_value: float | None = None
    purpose: str | None = None


class LoanApplicationIn(BaseModel):
    product_code: str
    customer: CustomerIn
    loan: LoanDetailsIn


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except services.ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ---------- AI agent ----------

@app.post("/chat", response_model=ChatOut, tags=["agent"])
def chat(body: ChatIn, db: Session = Depends(get_db)):
    """Talk to the assistant. Pass back `session_id` to continue the same conversation."""
    try:
        return agent.chat(db, body.message, body.session_id)
    except agent.NotConfiguredError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except anthropic.AuthenticationError:
        raise HTTPException(status_code=503, detail="Assistant is misconfigured: the Claude API key was rejected.")
    except anthropic.RateLimitError:
        raise HTTPException(status_code=429, detail="Assistant is busy, please retry in a moment.")
    except anthropic.APIConnectionError:
        raise HTTPException(status_code=503, detail="Assistant is unreachable, please retry.")
    except anthropic.APIStatusError as e:
        raise HTTPException(status_code=502, detail=f"Assistant error ({e.status_code}).")


@app.get("/chat/{session_id}", tags=["agent"])
def chat_history(session_id: str, db: Session = Depends(get_db)):
    session = db.get(ChatSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "messages": agent.transcript(session)}


# ---------- catalogue & calculators ----------

@app.get("/accounts/types", tags=["catalogue"])
def account_types(db: Session = Depends(get_db)):
    return services.list_account_types(db)


@app.get("/loans", tags=["catalogue"])
def loans(category: str | None = None, db: Session = Depends(get_db)):
    """category: gold | house | personal"""
    return _call(services.list_loan_products, db, category)


@app.get("/forms/{kind}", tags=["catalogue"])
def form(kind: str, product_code: str | None = None):
    return _call(services.form_fields, kind, product_code)


@app.get("/loans/emi", tags=["calculators"])
def emi(principal: float, annual_rate_pct: float, tenure_months: int):
    return _call(services.calculate_emi, principal, annual_rate_pct, tenure_months)


# ---------- applications ----------

@app.post("/applications/account", status_code=201, tags=["applications"])
def apply_account(body: AccountApplicationIn, db: Session = Depends(get_db)):
    return _call(services.create_account_application, db, body.account_type, body.customer.model_dump())


@app.post("/applications/loan", status_code=201, tags=["applications"])
def apply_loan(body: LoanApplicationIn, db: Session = Depends(get_db)):
    return _call(services.create_loan_application, db, body.product_code, body.customer.model_dump(), body.loan.model_dump(exclude_none=True))


@app.get("/applications/{reference_no}", tags=["applications"])
def application_status(reference_no: str, phone_last4: str, db: Session = Depends(get_db)):
    try:
        return services.get_application_status(db, reference_no, phone_last4)
    except services.ValidationError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/", include_in_schema=False)
def ui():
    return FileResponse(STATIC / "index.html")
