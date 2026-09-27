"""Business logic shared by the REST API and the AI agent's tools."""

import re
import secrets
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AccountType, Application, Customer, LoanProduct

LOAN_CATEGORIES = ("gold", "house", "personal")

PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
PHONE_RE = re.compile(r"^[6-9]\d{9}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

CUSTOMER_FIELDS = {
    "full_name": "Full name as per PAN",
    "phone": "10-digit mobile number",
    "email": "Email address",
    "date_of_birth": "Date of birth (YYYY-MM-DD)",
    "pan": "PAN number (e.g. ABCDE1234F)",
    "address": "Full residential address with PIN code",
}
LOAN_EXTRA_FIELDS = {
    "amount": "Loan amount required (INR)",
    "tenure_months": "Repayment tenure in months",
    "monthly_income": "Net monthly income (INR)",
    "employment_type": "salaried / self_employed / other",
}


class ValidationError(ValueError):
    pass


# ---------- catalogue ----------

def account_type_to_dict(a: AccountType) -> dict:
    return {
        "code": a.code, "name": a.name, "description": a.description,
        "min_balance": a.min_balance, "interest_rate_pct": a.interest_rate,
        "features": a.features, "documents_required": a.documents,
    }


def loan_product_to_dict(p: LoanProduct) -> dict:
    return {
        "code": p.code, "category": p.category, "name": p.name, "description": p.description,
        "interest_rate_pct": f"{p.interest_rate_min}-{p.interest_rate_max}",
        "amount_range_inr": [p.min_amount, p.max_amount],
        "max_tenure_months": p.max_tenure_months,
        "processing_fee_pct": p.processing_fee_pct,
        "eligibility": p.eligibility, "documents_required": p.documents,
    }


def list_account_types(db: Session) -> list[dict]:
    return [account_type_to_dict(a) for a in db.scalars(select(AccountType))]


def list_loan_products(db: Session, category: str | None = None) -> list[dict]:
    q = select(LoanProduct)
    if category:
        if category not in LOAN_CATEGORIES:
            raise ValidationError(f"category must be one of {LOAN_CATEGORIES}")
        q = q.where(LoanProduct.category == category)
    return [loan_product_to_dict(p) for p in db.scalars(q)]


def form_fields(kind: str, product_code: str | None = None) -> dict:
    """Fields the customer must fill for an application form."""
    if kind not in ("account", "loan"):
        raise ValidationError("kind must be 'account' or 'loan'")
    fields = dict(CUSTOMER_FIELDS)
    if kind == "loan":
        fields.update(LOAN_EXTRA_FIELDS)
        if product_code == "GOLD_STD":
            fields["gold_weight_grams"] = "Approximate weight of gold jewellery (grams)"
        if product_code == "HOME_STD":
            fields["property_value"] = "Market value of the property (INR)"
    return {"kind": kind, "product_code": product_code, "fields": fields}


# ---------- calculators ----------

def calculate_emi(principal: float, annual_rate_pct: float, tenure_months: int) -> dict:
    if principal <= 0 or tenure_months <= 0 or annual_rate_pct < 0:
        raise ValidationError("principal and tenure must be positive, rate non-negative")
    r = annual_rate_pct / 12 / 100
    emi = principal / tenure_months if r == 0 else principal * r * (1 + r) ** tenure_months / ((1 + r) ** tenure_months - 1)
    total = emi * tenure_months
    return {
        "monthly_emi": round(emi, 2),
        "total_payment": round(total, 2),
        "total_interest": round(total - principal, 2),
        "principal": principal, "annual_rate_pct": annual_rate_pct, "tenure_months": tenure_months,
    }


def _age(dob: str) -> int:
    try:
        d = date.fromisoformat(dob)
    except ValueError:
        raise ValidationError("date_of_birth must be YYYY-MM-DD")
    today = date.today()
    return today.year - d.year - ((today.month, today.day) < (d.month, d.day))


def check_loan_eligibility(
    db: Session, product_code: str, age: int, amount: float, tenure_months: int,
    monthly_income: float = 0, existing_emi: float = 0, credit_score: int | None = None,
    gold_weight_grams: float | None = None, property_value: float | None = None,
) -> dict:
    """Indicative eligibility check - not a credit decision."""
    p = db.get(LoanProduct, product_code)
    if not p:
        raise ValidationError(f"Unknown loan product {product_code}")
    e, reasons = p.eligibility, []

    if not e.get("min_age", 0) <= age <= e.get("max_age", 200):
        reasons.append(f"Age must be between {e['min_age']} and {e['max_age']}.")
    if not p.min_amount <= amount <= p.max_amount:
        reasons.append(f"Amount must be between INR {p.min_amount:,.0f} and INR {p.max_amount:,.0f}.")
    if tenure_months > p.max_tenure_months:
        reasons.append(f"Maximum tenure is {p.max_tenure_months} months.")
    if "min_monthly_income" in e and monthly_income < e["min_monthly_income"]:
        reasons.append(f"Minimum net monthly income is INR {e['min_monthly_income']:,}.")
    if "min_credit_score" in e and credit_score is not None and credit_score < e["min_credit_score"]:
        reasons.append(f"Credit score of at least {e['min_credit_score']} is required.")

    max_eligible = p.max_amount
    if p.category == "gold" and gold_weight_grams:
        gold_rate_per_gram = 7000  # illustrative 22K rate; fetch live rate in production
        max_eligible = min(max_eligible, gold_weight_grams * gold_rate_per_gram * e["ltv_pct"] / 100)
    if p.category == "house" and property_value:
        max_eligible = min(max_eligible, property_value * e["max_ltv_pct"] / 100)
    if "max_foir_pct" in e and monthly_income:
        affordable_emi = monthly_income * e["max_foir_pct"] / 100 - existing_emi
        per_lakh = calculate_emi(100000, p.interest_rate_min, min(tenure_months, p.max_tenure_months))["monthly_emi"]
        max_eligible = min(max_eligible, max(affordable_emi, 0) / per_lakh * 100000)
    if amount > max_eligible:
        reasons.append(f"Based on the details given, the maximum eligible amount is about INR {max_eligible:,.0f}.")

    emi = calculate_emi(amount, p.interest_rate_min, min(tenure_months, p.max_tenure_months))
    return {
        "product": p.name, "eligible": not reasons, "reasons": reasons,
        "max_eligible_amount": int(max_eligible // 1000 * 1000),
        "indicative_emi_at_best_rate": emi["monthly_emi"],
        "note": "Indicative only. Final approval depends on document verification and credit assessment.",
    }


# ---------- applications ----------

def _validate_customer(c: dict) -> dict:
    missing = [k for k in CUSTOMER_FIELDS if not str(c.get(k, "")).strip()]
    if missing:
        raise ValidationError(f"Missing fields: {', '.join(missing)}")
    c = {k: str(c[k]).strip() for k in CUSTOMER_FIELDS}
    c["pan"] = c["pan"].upper()
    c["phone"] = re.sub(r"\D", "", c["phone"])[-10:]
    if not PAN_RE.match(c["pan"]):
        raise ValidationError("PAN must look like ABCDE1234F")
    if not PHONE_RE.match(c["phone"]):
        raise ValidationError("Phone must be a valid 10-digit Indian mobile number")
    if not EMAIL_RE.match(c["email"]):
        raise ValidationError("Invalid email address")
    if _age(c["date_of_birth"]) < 18:
        raise ValidationError("Applicant must be at least 18 years old")
    return c


def _upsert_customer(db: Session, data: dict) -> Customer:
    cust = db.scalar(select(Customer).where(Customer.phone == data["phone"]))
    if cust:
        for k, v in data.items():
            setattr(cust, k, v)
    else:
        cust = Customer(**data)
        db.add(cust)
    db.flush()
    return cust


def _reference(prefix: str) -> str:
    return f"{prefix}{date.today():%y%m%d}{secrets.token_hex(3).upper()}"


def application_to_dict(a: Application) -> dict:
    return {
        "reference_no": a.reference_no, "kind": a.kind, "product_code": a.product_code,
        "status": a.status, "applicant": a.customer.full_name,
        "phone_masked": "******" + a.customer.phone[-4:],
        "details": a.details, "submitted_at": a.created_at.isoformat(timespec="seconds"),
    }


def create_account_application(db: Session, account_type: str, customer: dict) -> dict:
    if not db.get(AccountType, account_type):
        raise ValidationError(f"Unknown account type {account_type}")
    cust = _upsert_customer(db, _validate_customer(customer))
    app = Application(reference_no=_reference("AC"), kind="account", product_code=account_type, customer=cust, details={})
    db.add(app)
    db.commit()
    return application_to_dict(app) | {"next_steps": "Complete video KYC via the link sent to your mobile, or visit any branch with original KYC documents."}


def create_loan_application(db: Session, product_code: str, customer: dict, loan: dict) -> dict:
    p = db.get(LoanProduct, product_code)
    if not p:
        raise ValidationError(f"Unknown loan product {product_code}")
    c = _validate_customer(customer)
    try:
        amount, tenure = float(loan["amount"]), int(loan["tenure_months"])
        income = float(loan.get("monthly_income") or 0)
    except (KeyError, TypeError, ValueError):
        raise ValidationError("amount, tenure_months and monthly_income must be numbers")
    elig = check_loan_eligibility(
        db, product_code, _age(c["date_of_birth"]), amount, tenure, income,
        gold_weight_grams=loan.get("gold_weight_grams"), property_value=loan.get("property_value"),
    )
    cust = _upsert_customer(db, c)
    app = Application(
        reference_no=_reference("LN"), kind="loan", product_code=product_code, customer=cust,
        details={**loan, "precheck": elig},
        status="SUBMITTED" if elig["eligible"] else "NEEDS_REVIEW",
    )
    db.add(app)
    db.commit()
    return application_to_dict(app) | {"next_steps": "A loan officer will call you within 1 working day to collect documents."}


def get_application_status(db: Session, reference_no: str, phone_last4: str) -> dict:
    app = db.scalar(select(Application).where(Application.reference_no == reference_no.strip().upper()))
    # Require the last 4 digits of the phone so reference numbers alone don't leak data.
    if not app or app.customer.phone[-4:] != phone_last4.strip():
        raise ValidationError("No application found for that reference number and phone number")
    return application_to_dict(app)
