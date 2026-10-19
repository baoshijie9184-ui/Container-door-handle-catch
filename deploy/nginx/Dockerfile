# syntax=docker/dockerfile:1
FROM node:24-alpine@sha256:44fce696f38ba8c987c4db89954051000bbd05ffd8d8659ba15ed4a8602e937f AS frontend-build
ARG NPM_REGISTRY=https://registry.npmjs.org
WORKDIR /workspace/frontend
COPY frontend/package*.json ./
RUN --mount=type=cache,target=/root/.npm,sharing=locked npm ci --registry="$NPM_REGISTRY"
COPY frontend/ ./
RUN npm run build

FROM node:24-alpine@sha256:44fce696f38ba8c987c4db89954051000bbd05ffd8d8659ba15ed4a8602e937f AS agent-build
ARG NPM_REGISTRY=https://registry.npmjs.org
WORKDIR /workspace/frontend-agent
COPY frontend-agent/package*.json ./
RUN --mount=type=cache,target=/root/.npm,sharing=locked npm ci --registry="$NPM_REGISTRY"
COPY frontend-agent/ ./
# React UI 复用主站契约及执行控制、持久工作台样式。
COPY frontend/src/utils/ /workspace/frontend/src/utils/
COPY frontend/src/assets/ /workspace/frontend/src/assets/
ENV VITE_AGENT_API_URL=/agui/run VITE_BUSINESS_LOGIN_URL=/#/login
RUN npm run build -- --base=/agent-ui/

FROM nginx:1.30-alpine@sha256:970364228b1e4f932abc22d321932816782cca8a20b85a77552a7cfe9acfb3b5
ARG NGINX_CONFIG=deploy/nginx/nginx.conf
ENV OSS_UPLOAD_HOST=oss-cn-beijing.aliyuncs.com NGINX_ENVSUBST_FILTER=^OSS_UPLOAD_HOST$
COPY ${NGINX_CONFIG} /etc/nginx/templates/default.conf.template
COPY --from=frontend-build /workspace/frontend/dist /usr/share/nginx/html
COPY --from=agent-build /workspace/frontend-agent/dist /usr/share/nginx/html/agent-ui
EXPOSE 80
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD wget -q -O - http://127.0.0.1/nginx-health || exit 1
