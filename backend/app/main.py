from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from sqlalchemy import text
from app.db.database import engine, Base
from app.modules.users import router as users_router
from app.modules.loans import router as loans_router
from app.modules.ai import router as ai_router
from app.modules.reports import router as reports_router
Base.metadata.create_all(bind=engine)

# Auto-migrate new columns if they are missing
try:
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE loans ADD COLUMN monthly_income FLOAT DEFAULT 50000;"))
        conn.execute(text("ALTER TABLE loans ADD COLUMN monthly_expenses FLOAT DEFAULT 20000;"))
        conn.commit()
except Exception:
    pass

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Enterprise Loan Intelligence Platform",
    version="1.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users_router.router, prefix=f"{settings.API_V1_STR}/auth", tags=["auth"])
app.include_router(loans_router.router, prefix=f"{settings.API_V1_STR}/loans", tags=["loans"])
app.include_router(ai_router.router, prefix=f"{settings.API_V1_STR}/ai", tags=["ai"])
app.include_router(reports_router.router, prefix=f"{settings.API_V1_STR}/reports", tags=["reports"])

@app.get("/health")
def health_check():
    return {"status": "ok"}
