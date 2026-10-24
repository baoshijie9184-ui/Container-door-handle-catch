# syntax=docker/dockerfile:1
# 仅构建 Java 后端镜像；MySQL/Redis/Kafka/Mem0/Chroma 在 compose.cloud.yml 定义。
# 应用入口见 compose.monolith.yml；CPU PTH worker 见 compose.detection.yml。
# 容器关系与编排顺序见 docs/docker-monolith-deployment.md。
FROM maven:3.9.9-eclipse-temurin-17@sha256:f58d59b6273e785ac0a4477f6e9b5ba1d7731c75b906c0f7b34076f1851318cc AS build
ARG MAVEN_MIRROR_URL=https://repo.maven.apache.org/maven2
WORKDIR /workspace
COPY deploy/backend/maven-settings.xml /tmp/maven-settings.xml
COPY pom.xml ./
COPY doorhandle-dependencies/pom.xml doorhandle-dependencies/pom.xml
COPY doorhandle-common/pom.xml doorhandle-common/pom.xml
COPY doorhandle-framework/pom.xml doorhandle-framework/pom.xml
COPY doorhandle-contracts/pom.xml doorhandle-contracts/pom.xml
COPY doorhandle-module-system/pom.xml doorhandle-module-system/pom.xml
COPY doorhandle-module-infra/pom.xml doorhandle-module-infra/pom.xml
COPY doorhandle-module-device/pom.xml doorhandle-module-device/pom.xml
COPY doorhandle-module-detection/pom.xml doorhandle-module-detection/pom.xml
COPY doorhandle-module-model/pom.xml doorhandle-module-model/pom.xml
COPY doorhandle-module-ai/pom.xml doorhandle-module-ai/pom.xml
COPY doorhandle-module-app/pom.xml doorhandle-module-app/pom.xml
COPY doorhandle-server/pom.xml doorhandle-server/pom.xml
COPY doorhandle-common/src/main doorhandle-common/src/main
COPY doorhandle-framework/src/main doorhandle-framework/src/main
COPY doorhandle-contracts/src/main doorhandle-contracts/src/main
COPY doorhandle-module-system/src/main doorhandle-module-system/src/main
COPY doorhandle-module-infra/src/main doorhandle-module-infra/src/main
COPY doorhandle-module-device/src/main doorhandle-module-device/src/main
COPY doorhandle-module-detection/src/main doorhandle-module-detection/src/main
COPY doorhandle-module-model/src/main doorhandle-module-model/src/main
COPY doorhandle-module-ai/src/main doorhandle-module-ai/src/main
COPY doorhandle-module-app/src/main doorhandle-module-app/src/main
COPY doorhandle-server/src/main doorhandle-server/src/main
# Reactor 内部依赖在同一次构建解析，避免 go-offline 预先寻找尚未发布的本项目模块。
RUN --mount=type=cache,target=/root/.m2,sharing=locked \
    mvn -s /tmp/maven-settings.xml -B -ntp -DskipTests package -pl doorhandle-server -am \
    && mkdir /out \
    && set -- doorhandle-server/target/doorhandle-server-*.jar \
    && test "$#" -eq 1 && cp "$1" /out/app.jar

FROM eclipse-temurin:17-jre-noble@sha256:07fa0356cf354c5252947575f42ed42aa6fd921f36438b7bc77ad81c31c537dd AS runtime
LABEL io.doorhandle.model-config-format="1"
LABEL io.doorhandle.assignment-json="2" io.doorhandle.assignment-identity="1"
LABEL io.doorhandle.identity-review="1"
LABEL io.doorhandle.identity-evidence="2"
LABEL io.doorhandle.context-provenance="2"
LABEL io.doorhandle.mcp-native-protocol="4"
ARG UBUNTU_MIRROR=""
# ONNX/OpenCV 使用 glibc；Python 仅供已受控的 Skill 下载和本地 Stdio MCP 安装器。
RUN if [ -n "$UBUNTU_MIRROR" ]; then \
      sed -i "s|http://archive.ubuntu.com/ubuntu|$UBUNTU_MIRROR|g; s|http://security.ubuntu.com/ubuntu|$UBUNTU_MIRROR|g" /etc/apt/sources.list.d/ubuntu.sources; \
    fi \
    && apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl libgomp1 libgl1 libglib2.0-0t64 \
    python3 python3-venv python3-pip python3-requests python3-yaml \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app
WORKDIR /app
ENV JAVA_OPTS="-XX:InitialRAMPercentage=15 -XX:MaxRAMPercentage=60 -Djava.awt.headless=true" \
    AGENTSCOPE_AI_WORKSPACE=/app/.agentscope/workspace \
    AGENT_WORKSPACE_ROOT=/app/.agentscope/workspace \
    AGENT_LOCAL_MCP_PYTHON=/usr/bin/python3 \
    AGENT_SKILL_LINK_PYTHON=/usr/bin/python3 \
    PYTHONNOUSERSITE=1 PYTHONUNBUFFERED=1
RUN mkdir -p /app/uploads /app/logs /app/.agentscope/workspace /app/script/shell /app/docs \
    && chown -R app:app /app
COPY --from=build --chown=app:app /out/app.jar /app/app.jar
COPY script/shell/install-local-fetch-mcp.py script/shell/download-linked-skill.py /app/script/shell/
COPY script/shell/native-fetch-process.py /app/script/shell/native-fetch-process.py
COPY script/shell/native-fetch-install.py /app/script/shell/native-fetch-install.py
COPY README.md /app/README.md
COPY LICENSE /app/LICENSE
COPY docs/system-user-guide.md docs/chroma-rag-setup.md /app/docs/
COPY --chmod=0755 deploy/backend/entrypoint.sh /usr/local/bin/doorhandle-entrypoint
USER app
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=45s --retries=5 \
  CMD curl -fsS http://127.0.0.1:8080/actuator/health || exit 1
ENTRYPOINT ["doorhandle-entrypoint"]
