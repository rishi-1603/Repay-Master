# Build context is the REPO ROOT, not backend/ -- unlike DevTrack/CertiFake,
# this FastAPI app is not self-contained inside backend/. Its route handlers
# import utils/finance.py, utils/risk.py, utils/auth.py from the repo root
# (the same modules the Streamlit app uses), and utils/risk.py loads model
# artifacts from models/*.joblib at the repo root too. See
# backend/app/api/*.py's `REPO_ROOT = Path(__file__).resolve().parents[3]`
# sys.path insertion -- this Dockerfile's directory layout must match what
# that code expects on disk: /app/utils, /app/models, /app/backend.
#
# VERIFICATION STATUS (updated Day 6): this image BUILDS -- confirmed by the
# `docker-build` CI job (run 35996304233, commit ae413bb), which was the first
# time anything had ever actually built it, no Docker daemon existing in the
# sandbox it was written in.
#
# A container started from it also RUNS correctly end to end, which was the
# outstanding caveat here until Day 6. The `compose-smoke-test` CI job boots
# the compose stack and drives real requests through this image's uvicorn
# process; it passed on commit 4cda54b (run 36611637287, 2026-09-29), having
# observed the container reach Docker-healthy, the models/*.joblib artifacts
# load and predict inside it, and the sqlite DB persist to the /app/data
# volume. docker-compose.yml records the full list of what was checked.
#
# Still NOT covered by anything, stated so the green check is not over-read:
# this image serves only the FastAPI backend. The Streamlit front end (app.py at
# the repo root) is not part of docker-compose.yml and has never been
# containerized or smoke-tested -- the checks above cover the API surface the
# UI calls, not the UI. This repo has no Kubernetes manifests at all, so unlike
# its two siblings there is no deployment schema being validated here either.
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
# The base image ships its own pip (25.0.1 here), which no pin in
# backend/requirements.txt can reach and no scan of the CI runner's Python can see.
# Measured by scanning this image from the inside in CI: 7 advisories
# (PYSEC-2026-1795, -1796, -196, -2875, -2876, -3721), several of them about how
# pip extracts wheels and tarballs -- i.e. they apply to the very next command,
# which resolves dependencies from the network at build time. Python 3.12's
# ensurepip does not bundle setuptools, so unlike the 3.11-based CertiFake image
# there is nothing else in here to upgrade.
RUN pip install --no-cache-dir --upgrade "pip>=26.2.0"
RUN pip install --no-cache-dir -r backend/requirements.txt backend/requirements.txt

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
