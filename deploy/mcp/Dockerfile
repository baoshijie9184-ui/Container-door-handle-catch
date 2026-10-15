# syntax=docker/dockerfile:1
ARG PYTHON_BASE_IMAGE=eclipse-temurin:17-jre-noble
FROM ${PYTHON_BASE_IMAGE}
ARG UBUNTU_MIRROR=http://mirrors.cloud.aliyuncs.com/ubuntu
RUN sed -i "s|http://archive.ubuntu.com/ubuntu|$UBUNTU_MIRROR|g; s|http://security.ubuntu.com/ubuntu|$UBUNTU_MIRROR|g" /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get update && apt-get install -y --no-install-recommends python3 python3-venv python3-pip ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY script/shell/install-local-fetch-mcp.py /app/install-fetch.py
# Preserve the existing reviewed Fetch wheel hash, dependency lock and legal files.
RUN mkdir /opt/fetch \
    && python3 /app/install-fetch.py --directory /opt/fetch --gateway-runtime --package-index https://mirrors.aliyun.com/pypi/simple \
    && /opt/fetch/.venv/bin/python -I -m pip check \
    && groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app
COPY deploy/mcp/runner.py /app/runner.py
COPY deploy/mcp/configure.py /app/configure.py
COPY LICENSE /app/LICENSE
ENV PATH=/opt/fetch/.venv/bin:/usr/local/bin:/usr/bin:/bin PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
CMD ["/opt/fetch/.venv/bin/python", "/app/runner.py"]
