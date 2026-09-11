#!/bin/bash
# ============================================================
# DoorHandleCatch 启动脚本
# 自动加载 .env 环境变量
# 用法: bash start.sh [java|python|memory|all]
# ============================================================
set -a  # 自动导出所有变量

# 加载 .env 文件
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/.env" ]; then
    source "$SCRIPT_DIR/.env"
    echo "[INFO] 已加载 .env 环境变量"
else
    echo "[WARN] 未找到 .env 文件，使用默认配置"
fi

set +a

MODE="${1:-all}"

start_python() {
    echo "[INFO] 启动 Python Kafka Worker..."
    conda run -n leetcode python kafka_detection_worker.py
}

start_java() {
    echo "[INFO] 启动 Java Spring Boot 服务..."
    ./mvnw spring-boot:run
}

start_memory() {
    echo "[INFO] 启动 mem0 记忆服务 (端口 8081)..."
    cd "$SCRIPT_DIR/memory_service" && conda run -n leetcode uvicorn main:app --host 0.0.0.0 --port 8081
}

case "$MODE" in
    python)
        start_python
        ;;
    java)
        start_java
        ;;
    memory)
        start_memory
        ;;
    all)
        echo "[INFO] 启动所有服务..."
        start_java &
        sleep 5
        start_python &
        start_memory &
        wait
        ;;
    *)
        echo "用法: bash start.sh [java|python|memory|all]"
        ;;
esac
