# Same Python and library versions as training (see the model's requirements.txt in MLflow):
# pickle stores object state, not class code, so a different sklearn breaks loading.
FROM python:3.12-slim

# LightGBM needs the OpenMP runtime
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# KServe runs containers as non-root; MLServer writes metrics to the working dir
RUN useradd -u 1000 -m mlserver
USER 1000
WORKDIR /home/mlserver
