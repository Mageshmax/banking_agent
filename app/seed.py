"""Sample product catalogue. Replace rates/limits with your bank's real values."""

from sqlalchemy.orm import Session

from .models import AccountType, LoanProduct

KYC_DOCS = ["PAN card", "Aadhaar card (or passport / voter ID / driving licence)", "Recent passport-size photograph"]

ACCOUNT_TYPES = [
    AccountType(
        code="SAVINGS",
        name="Regular Savings Account",
        description="Everyday savings account with debit card, UPI and net banking.",
        min_balance=5000,
        interest_rate=3.0,
        features=["Free debit card", "UPI & net banking", "5 free ATM withdrawals/month"],
        documents=KYC_DOCS,
    ),
    AccountType(
        code="ZERO_BALANCE",
        name="Basic Savings (Zero Balance) Account",
        description="No minimum balance required. Ideal for students and first-time savers.",
        min_balance=0,
        interest_rate=2.7,
        features=["No minimum balance", "RuPay debit card", "UPI"],
        documents=KYC_DOCS,
    ),
    AccountType(
        code="SALARY",
        name="Salary Account",
        description="Zero-balance account for salaried employees of partner companies.",
        min_balance=0,
        interest_rate=3.0,
        features=["Zero balance while salary is credited", "Free cheque book", "Pre-approved personal loan offers"],
        documents=KYC_DOCS + ["Employer ID card or offer letter"],
    ),
    AccountType(
        code="CURRENT",
        name="Current Account",
        description="For businesses and professionals with high transaction volumes.",
        min_balance=10000,
        interest_rate=0,
        features=["Unlimited transactions", "Overdraft facility", "Multi-city cheques"],
        documents=KYC_DOCS + ["Business registration proof (GST / Shop Act / Udyam)"],
    ),
]

LOAN_PRODUCTS = [
    LoanProduct(
        code="GOLD_STD",
        category="gold",
        name="Gold Loan",
        description="Instant loan against gold jewellery (18-22 carat). Disbursed in 30 minutes at the branch.",
        interest_rate_min=8.5,
        interest_rate_max=12.0,
        min_amount=10000,
        max_amount=5000000,
        max_tenure_months=36,
        processing_fee_pct=0.5,
        eligibility={"min_age": 18, "max_age": 75, "ltv_pct": 75, "gold_purity": "18-22 carat"},
        documents=KYC_DOCS + ["Gold jewellery for valuation at branch"],
    ),
    LoanProduct(
        code="HOME_STD",
        category="house",
        name="Home Loan",
        description="Buy, build or renovate a house. Up to 30 years tenure.",
        interest_rate_min=8.35,
        interest_rate_max=9.75,
        min_amount=500000,
        max_amount=50000000,
        max_tenure_months=360,
        processing_fee_pct=0.5,
        eligibility={"min_age": 21, "max_age": 65, "min_monthly_income": 25000, "max_ltv_pct": 80, "max_foir_pct": 50},
        documents=KYC_DOCS + ["Last 6 months salary slips / 2 years ITR", "Last 6 months bank statement", "Property documents (sale agreement, title deed, approved plan)"],
    ),
    LoanProduct(
        code="PERSONAL_STD",
        category="personal",
        name="Personal Loan",
        description="Unsecured loan for any personal need - wedding, travel, medical, education.",
        interest_rate_min=10.5,
        interest_rate_max=18.0,
        min_amount=50000,
        max_amount=4000000,
        max_tenure_months=72,
        processing_fee_pct=1.5,
        eligibility={"min_age": 21, "max_age": 60, "min_monthly_income": 20000, "min_credit_score": 700, "max_foir_pct": 50},
        documents=KYC_DOCS + ["Last 3 months salary slips", "Last 6 months bank statement"],
    ),
]


def seed(db: Session) -> None:
    for obj in ACCOUNT_TYPES + LOAN_PRODUCTS:
        db.merge(obj)
    db.commit()
