# syntax=docker/dockerfile:1
ARG PYTHON_BASE_IMAGE=python:3.12-slim
FROM ${PYTHON_BASE_IMAGE}
WORKDIR /app
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1 DETECTION_ENGINE=pth DETECTION_SOURCE_DIR=/opt/model-source
COPY requirements.txt /app/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=bind,source=cpu-wheels,target=/wheels,ro \
    pip install --find-links /wheels --index-url "$PIP_INDEX_URL" -r requirements.txt && pip check \
    && groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app
COPY kafka_detection_worker.py kafka_event_models.py kafka_settings.py detection_worker_receipts.py oss_result_uploader.py pth_detection_engine.py detection_image.py worker_health.py LICENSE /app/
COPY model-source/ /opt/model-source/
COPY DINOv3-LICENSE.md BUILD_PROVENANCE.json /opt/model-source/
COPY PyMySQL-LICENSE.txt /app/licenses/PyMySQL-LICENSE.txt
USER app
HEALTHCHECK --interval=15s --timeout=3s --start-period=90s --retries=3 CMD python /app/worker_health.py
CMD ["python", "/app/kafka_detection_worker.py"]
