# syntax=docker/dockerfile:1
ARG PYTHON_BASE_IMAGE=eclipse-temurin:17-jre-noble
FROM ${PYTHON_BASE_IMAGE}
ARG UBUNTU_MIRROR=http://mirrors.cloud.aliyuncs.com/ubuntu
RUN sed -i "s|http://archive.ubuntu.com/ubuntu|$UBUNTU_MIRROR|g; s|http://security.ubuntu.com/ubuntu|$UBUNTU_MIRROR|g" /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get update && apt-get install -y --no-install-recommends python3 python3-venv python3-pip ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
LABEL doorhandle.mcp.fetch="true" doorhandle.mcp.version="2026.10.10" doorhandle.mcp.package-sha256="d722c48bdc1de3e2a81727853bc490cf55c6c935e2038cdcad3c111b1d85db77"
LABEL io.doorhandle.mcp-image-lifecycle="2"
COPY script/shell/install-local-fetch-mcp.py /app/install-fetch.py
# Preserve the existing reviewed Fetch wheel hash, dependency lock and legal files.
RUN mkdir /opt/fetch \
    && python3 /app/install-fetch.py --directory /opt/fetch --gateway-runtime --package-index https://mirrors.aliyun.com/pypi/simple \
    && /opt/fetch/.venv/bin/python -I -m pip check \
    && groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app \
    && mkdir -p /var/lib/doorhandle-mcp && chown 10001:10001 /var/lib/doorhandle-mcp && chmod 700 /var/lib/doorhandle-mcp
COPY deploy/mcp/runner.py /app/runner.py
COPY deploy/mcp/execution_store.py /app/execution_store.py
COPY deploy/mcp/image_lifecycle.py /app/image_lifecycle.py
COPY deploy/mcp/configure.py /app/configure.py
COPY LICENSE /app/LICENSE
ENV PATH=/opt/fetch/.venv/bin:/usr/local/bin:/usr/bin:/bin PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
CMD ["/opt/fetch/.venv/bin/python", "/app/runner.py"]
