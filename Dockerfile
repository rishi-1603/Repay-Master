# Build context is the REPO ROOT, not backend/ -- unlike DevTrack/CertiFake,
# this FastAPI app is not self-contained inside backend/. Its route handlers
# import utils/finance.py, utils/risk.py, utils/auth.py from the repo root
# (the same modules the Streamlit app uses), and utils/risk.py loads model
# artifacts from models/*.joblib at the repo root too. See
# backend/app/api/*.py's `REPO_ROOT = Path(__file__).resolve().parents[3]`
# sys.path insertion -- this Dockerfile's directory layout must match what
# that code expects on disk: /app/utils, /app/models, /app/backend.
#
# NOT VERIFIED: no Docker daemon is available in the sandbox this was
# written in, so this has not actually been built or run. It is reasoned
# from the real, tested local dependency/path layout (confirmed working via
# `uvicorn app.main:app` against a real venv), not fabricated -- but "docker
# build succeeds" and "the container actually starts" are both unverified
# claims until someone with Docker runs it.
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY utils/ utils/
COPY models/ models/
COPY backend/ backend/

# utils/auth.py creates data/app.db here on first use (os.makedirs +
# sqlite3.connect) -- pre-creating it isn't required, but docker-compose.yml
# mounts a volume here so the DB survives container restarts/recreation.
RUN mkdir -p data

WORKDIR /app/backend

EXPOSE 8010

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]
