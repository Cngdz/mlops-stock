# Deployer image = the pipeline image (same locked MLflow client, training.registry) + the deployer code + kubectl
# for the convergence check (kubectl uses the pod's service account in-cluster, no kubeconfig).
# Build after the pipeline image (repo root):
#   docker build -f deployer/Dockerfile -t harbor.local/mlops/mlops-deployer:v1 .
#   docker push harbor.local/mlops/mlops-deployer:v1
ARG BASE=harbor.local/mlops/mlops-pipeline:v1
FROM ${BASE}

ARG KUBECTL_VERSION=v1.31.4
ADD https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl /usr/local/bin/kubectl
RUN chmod 0755 /usr/local/bin/kubectl

COPY deployer ./deployer
# Non-root: the deployer only talks to MLflow, MinIO, GitHub and the Kubernetes API.
RUN useradd -u 1000 -m deployer
USER 1000
CMD ["python", "-m", "deployer", "--loop", "--interval", "60", "--verify-every", "600"]
