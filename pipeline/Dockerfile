# Training/batch image: same Python and the same locked library versions as the host (uv.lock),
# so models trained here load in the mlserver-mlflow serving image (pickle stores object state,
# not class code: a different sklearn breaks loading).
# Build (repo root):  docker build -f pipeline/Dockerfile --build-arg GIT_COMMIT=$(git rev-parse --short HEAD) -t mlops-pipeline:v1 .
FROM python:3.12-slim

# LightGBM needs the OpenMP runtime
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv==0.9.21
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH

WORKDIR /app
COPY pyproject.toml uv.lock ./
# dependencies layer: rebuilt only when the lock file changes
RUN uv sync --frozen --no-dev --no-install-project

COPY training ./training
COPY features ./features
COPY pipeline/*.py pipeline/monitoring.yaml ./pipeline/
ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=$GIT_COMMIT
# data/ is NOT in the image: it is mounted from the PVC at /app/data (feature runs); Gold and fs_* are Iceberg tables in MinIO
