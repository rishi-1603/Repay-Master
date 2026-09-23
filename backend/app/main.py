"""RepayMaster FastAPI application entrypoint.

Day 1 scope: this API exposes the same deterministic finance math and ML
risk model that already existed inside the Streamlit app (`utils/finance.py`,
`utils/risk.py`), as real, independently callable, testable HTTP endpoints.
The Streamlit app is unchanged today and keeps working standalone; converting
it into a thin client of this API, plus auth/history/Kafka endpoints, is
tracked as Day 2-4 work (see repo README "Roadmap" section) rather than
pretended to be finished here.
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import loans, risk
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


@app.get("/", include_in_schema=False)
def root() -> dict:
    return {"app": settings.APP_NAME, "docs": "/docs"}


@app.get("/health", tags=["health"])
def health_check() -> dict:
    return {"status": "ok", "app": settings.APP_NAME}
