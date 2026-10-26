# Dependencies only: the service code, the model registry (models/) and the
# MLServer adapter's mask codec are mounted read-only from the checkout
# (compose.yaml), so a registry change reaches discovery without a rebuild.
FROM python:3.12-slim
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt
RUN useradd --system --uid 10010 --home-dir /nonexistent cerebrate-mcp
USER cerebrate-mcp
WORKDIR /app
ENV PYTHONUNBUFFERED=1
CMD ["python3", "-m", "cerebrate_mcp.server"]
