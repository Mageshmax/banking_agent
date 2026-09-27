"""Tool definitions exposed to Claude, and the dispatcher that runs them against the DB."""

import json

from sqlalchemy.orm import Session

from . import services

_CUSTOMER_SCHEMA = {
    "type": "object",
    "description": "Applicant details collected from the customer.",
    "properties": {
        "full_name": {"type": "string"},
        "phone": {"type": "string", "description": "10-digit mobile number"},
        "email": {"type": "string"},
        "date_of_birth": {"type": "string", "description": "YYYY-MM-DD"},
        "pan": {"type": "string"},
        "address": {"type": "string"},
    },
    "required": list(services.CUSTOMER_FIELDS),
}

TOOLS = [
    {
        "name": "list_account_types",
        "description": "List the bank's account types (savings, zero-balance, salary, current) with minimum balance, interest rate, features and KYC documents required. Use when the customer asks about opening an account or which account suits them.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_loan_products",
        "description": "List loan products with interest rates, amount limits, tenure, fees, eligibility rules and documents required. Optionally filter by category.",
        "input_schema": {
            "type": "object",
            "properties": {"category": {"type": "string", "enum": list(services.LOAN_CATEGORIES)}},
        },
    },
    {
        "name": "get_form_fields",
        "description": "Get the list of fields the customer must fill for an account-opening or loan application form. Call this before collecting details so you ask for exactly the right information.",
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["account", "loan"]},
                "product_code": {"type": "string", "description": "Account type code or loan product code, if known"},
            },
            "required": ["kind"],
        },
    },
    {
        "name": "calculate_emi",
        "description": "Calculate monthly EMI, total interest and total payment for a loan.",
        "input_schema": {
            "type": "object",
            "properties": {
                "principal": {"type": "number"},
                "annual_rate_pct": {"type": "number"},
                "tenure_months": {"type": "integer"},
            },
            "required": ["principal", "annual_rate_pct", "tenure_months"],
        },
    },
    {
        "name": "check_loan_eligibility",
        "description": "Run an indicative eligibility check for a loan product and estimate the maximum eligible amount. Not a final credit decision.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_code": {"type": "string"},
                "age": {"type": "integer"},
                "amount": {"type": "number"},
                "tenure_months": {"type": "integer"},
                "monthly_income": {"type": "number"},
                "existing_emi": {"type": "number", "description": "Total EMIs already being paid per month"},
                "credit_score": {"type": "integer"},
                "gold_weight_grams": {"type": "number", "description": "Gold loans only"},
                "property_value": {"type": "number", "description": "Home loans only"},
            },
            "required": ["product_code", "age", "amount", "tenure_months"],
        },
    },
    {
        "name": "submit_account_application",
        "description": "Submit a new account-opening application to the database. ONLY call after you have shown the customer a summary of every detail and they have explicitly confirmed it is correct.",
        "input_schema": {
            "type": "object",
            "properties": {"account_type": {"type": "string"}, "customer": _CUSTOMER_SCHEMA},
            "required": ["account_type", "customer"],
        },
    },
    {
        "name": "submit_loan_application",
        "description": "Submit a loan application (gold, home or personal) to the database. ONLY call after you have shown the customer a summary of every detail and they have explicitly confirmed it is correct.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_code": {"type": "string"},
                "customer": _CUSTOMER_SCHEMA,
                "loan": {
                    "type": "object",
                    "properties": {
                        "amount": {"type": "number"},
                        "tenure_months": {"type": "integer"},
                        "monthly_income": {"type": "number"},
                        "employment_type": {"type": "string", "enum": ["salaried", "self_employed", "other"]},
                        "gold_weight_grams": {"type": "number"},
                        "property_value": {"type": "number"},
                        "purpose": {"type": "string"},
                    },
                    "required": ["amount", "tenure_months"],
                },
            },
            "required": ["product_code", "customer", "loan"],
        },
    },
    {
        "name": "get_application_status",
        "description": "Look up the status of an existing application. Needs the reference number and the last 4 digits of the registered mobile number.",
        "input_schema": {
            "type": "object",
            "properties": {"reference_no": {"type": "string"}, "phone_last4": {"type": "string"}},
            "required": ["reference_no", "phone_last4"],
        },
    },
]

_TOOL_NAMES = {t["name"] for t in TOOLS}


def run_tool(db: Session, name: str, args: dict) -> tuple[str, bool]:
    """Execute a tool call. Returns (json_result, is_error)."""
    try:
        if name not in _TOOL_NAMES:
            raise services.ValidationError(f"Unknown tool {name}")
        match name:
            case "list_account_types":
                result = services.list_account_types(db)
            case "list_loan_products":
                result = services.list_loan_products(db, args.get("category"))
            case "get_form_fields":
                result = services.form_fields(args["kind"], args.get("product_code"))
            case "calculate_emi":
                result = services.calculate_emi(float(args["principal"]), float(args["annual_rate_pct"]), int(args["tenure_months"]))
            case "check_loan_eligibility":
                result = services.check_loan_eligibility(db, **args)
            case "submit_account_application":
                result = services.create_account_application(db, args["account_type"], args["customer"])
            case "submit_loan_application":
                result = services.create_loan_application(db, args["product_code"], args["customer"], args["loan"])
            case "get_application_status":
                result = services.get_application_status(db, args["reference_no"], args["phone_last4"])
        return json.dumps(result, default=str), False
    except (services.ValidationError, KeyError, TypeError, ValueError) as e:
        db.rollback()
        return json.dumps({"error": str(e)}), True
