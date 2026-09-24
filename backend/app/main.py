"""RepayMaster FastAPI application entrypoint.

Day 1: this API exposed the same deterministic finance math and ML risk
model that already existed inside the Streamlit app (`utils/finance.py`,
`utils/risk.py`), as real, independently callable, testable HTTP endpoints.

Day 2: added /auth (register/login, reusing utils/auth.py's existing
sqlite3 + PBKDF2 user store) and /history (saved-scenario CRUD, scoped to
the authenticated user). The Streamlit app is unchanged and keeps working
standalone; converting it into a thin client of this API, plus a Gemini
explain endpoint and Kafka event publishing, remains tracked as future work
(see repo README "Roadmap" section) rather than pretended to be finished
here.
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import auth, history, loans, risk
from app.core.config import settings

app = FastAPI(
    title=settings.APP_NAME,
    description="Loan repayment calculation + ML affordability-risk prediction API for RepayMaster.",
    version="0.1.0",
)

origins = ["*"] if settings.CORS_ORIGINS == "*" else [o.strip() for o in settings.CORS_ORIGINS.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    """Pydantic v2 field_validator ValueErrors surface as 422s, not raw 500s."""
    return JSONResponse(status_code=422, content={"error": "ValidationError", "detail": str(exc)})


app.include_router(loans.router)
app.include_router(risk.router)
app.include_router(auth.router)
app.include_router(history.router)


@app.get("/", include_in_schema=False)
def root() -> dict:
    return {"app": settings.APP_NAME, "docs": "/docs"}


@app.get("/health", tags=["health"])
def health_check() -> dict:
    return {"status": "ok", "app": settings.APP_NAME}
