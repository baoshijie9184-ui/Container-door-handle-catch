# syntax=docker/dockerfile:1
FROM python:3.12-slim
WORKDIR /app
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1 MEM0_DATA_DIR=/data \
    MEM0_TELEMETRY=false ANONYMIZED_TELEMETRY=false
COPY deploy/mem0/requirements.txt ./requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --index-url "$PIP_INDEX_URL" -r requirements.txt \
    && groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app \
    && mkdir /data && chown app:app /data
COPY --chmod=0644 memory_service/main.py /app/main.py
COPY --chmod=0644 LICENSE /app/LICENSE
USER app
EXPOSE 8081
HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=10 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/health',timeout=4)"
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8081", "--workers", "1"]
