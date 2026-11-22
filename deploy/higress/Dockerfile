FROM higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/all-in-one:2.2.6@sha256:3e7de95ac088a0c86a78b9dd236e9cd1e970163f25a6c092ab4589c993073b87
COPY ingress.yaml /opt/data/defaultConfig/ingresses/doorhandle.yaml
COPY registry.yaml /opt/data/defaultConfig/mcpbridges/default.yaml
COPY tracing.yaml /opt/doorhandle/tracing.yaml
RUN config=/opt/data/defaultConfig/configmaps/higress-config.yaml \
    && yq -i '.data.higress |= (from_yaml * load("/opt/doorhandle/tracing.yaml") | to_yaml)' "$config" \
    && yq -i '.data.mesh |= (from_yaml | del(.accessLogFormat) | .accessLogFile = "" | to_yaml)' "$config"
