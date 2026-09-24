# Build context is the REPO ROOT, not backend/ -- unlike DevTrack/CertiFake,
# this FastAPI app is not self-contained inside backend/. Its route handlers
# import utils/finance.py, utils/risk.py, utils/auth.py from the repo root
# (the same modules the Streamlit app uses), and utils/risk.py loads model
# artifacts from models/*.joblib at the repo root too. See
# backend/app/api/*.py's `REPO_ROOT = Path(__file__).resolve().parents[3]`
# sys.path insertion -- this Dockerfile's directory layout must match what
# that code expects on disk: /app/utils, /app/models, /app/backend.
#
# VERIFICATION STATUS (updated Day 3): this image BUILDS -- confirmed by
# the `docker-build` CI job on GitHub Actions (run 35996304233, commit
# ae413bb), which was the first time anything had ever actually built it
# (no Docker daemon exists in the sandbox it was written in). What is
# still NOT verified is that a container started from it RUNS correctly
# end-to-end: that CI job only builds, it does not run the app or drive
# any requests through it. See docker-compose.yml for the compose stack,
# which has never been brought up by anything.
#
# Base image pinned to a specific Debian release: an unpinned
# `python:3.12-slim` silently changes its Debian base over time. That
# broke the sibling CertiFake project's image build when slim moved to
# trixie and three of its apt package names stopped existing. This
# Dockerfile installs no apt packages, so it is not exposed to that
# specific failure today -- but pinning keeps the build reproducible if
# system deps are ever added.
FROM python:3.12-slim-trixie

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
