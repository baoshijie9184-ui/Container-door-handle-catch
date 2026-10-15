"""手动运行的 AgentScope 主站只读冒烟检查，会创建会话并调用真实模型。

仅检查接口、文本持久化和 SDK 事件摘要，不评价回答事实准确性，
不触发业务写工具，不使用旧版意图路由或断点恢复协议。
"""
import argparse
import getpass
import os
import sys

import requests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--username", default=os.getenv("AGENT_SMOKE_USERNAME"))
    parser.add_argument("--question", action="append", help="可以重复传入，默认仅查询一次检测任务")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    if not args.username:
        parser.error("请设置 AGENT_SMOKE_USERNAME 或传入 --username，需要员工或主管测试账号")
    password = os.getenv("AGENT_SMOKE_PASSWORD") or getpass.getpass("测试账号密码: ")
    base = args.base_url.rstrip("/")
    with requests.Session() as client:
        # 本地服务不使用终端的外网代理；远程服务沿用现有环境。
        if base.startswith(("http://127.0.0.1:", "http://localhost:")):
            client.trust_env = False

        def request(method, path, payload=None, wrapped=True):
            response = client.request(method, base + path, json=payload, timeout=args.timeout)
            if response.status_code != 200:
                raise RuntimeError(f"{method} {path}: HTTP {response.status_code}")
            data = response.json()
            if wrapped:
                if data.get("code") != 200:
                    raise RuntimeError(f"{method} {path}: 业务状态 {data.get('code')}")
                return data.get("data")
            return data

        request("POST", "/api/auth/login", {"username": args.username, "password": password})
        health = request("GET", "/api/chat-assistant/agent-health")
        if health.get("framework") != "AgentScope" or health.get("mode") not in {"READ_ONLY", "CONFIRMABLE"}:
            raise RuntimeError("需要已启用的 AgentScope 只读入口")
        catalog = request("GET", "/agui/catalog", wrapped=False)
        if catalog.get("mode") not in {"READ_ONLY", "CONFIRMABLE"}:
            raise RuntimeError("AG-UI 不是预期的只读模式")
        session = request("POST", "/api/chat-assistant/sessions")
        session_id = session["sessionId"]
        api = "/api/chat-assistant"
        for question in args.question or ["查询最近的检测任务"]:
            answer = request("POST", api + "/messages", {"sessionId": session_id, "content": question})
            if answer.get("intent") != "AGENTSCOPE" or not answer.get("content", "").strip():
                raise RuntimeError("未返回 AgentScope 文本回答")
            history = request("GET", f"{api}/sessions/{session_id}/messages")
            if not any(m.get("role") == "user" and m.get("content") == question for m in history):
                raise RuntimeError("问题没有保存在当前会话")
            if not any(m.get("role") == "assistant" and m.get("content") == answer["content"] for m in history):
                raise RuntimeError("回答没有保存在当前会话")
            trace = request("GET", f"{api}/sessions/{session_id}/trace")
            if trace.get("framework") != "AgentScope" or trace.get("status") != "COMPLETED" or not trace.get("runId"):
                raise RuntimeError("最近一轮执行摘要状态错误")
            events = trace.get("events", [])
            types = {event.get("type") for event in events}
            if not {"RUN_STARTED", "RUN_FINISHED"}.issubset(types) or len(events) > 200:
                raise RuntimeError("缺少真实运行事件或摘要超过上限")
            if any(set(event) - {"type", "agent", "tool", "text", "elapsedMs"} or event.get("text") for event in events):
                raise RuntimeError("摘要包含非预期字段或正文")
            tools = sum(event.get("type") == "TOOL_CALL" for event in events)
            print(f"PASS framework=AgentScope status=COMPLETED events={len(events)} toolCalls={tools}")
        print("冒烟检查通过；测试会话已保留。结果不代表回答事实、业务审批或 Eval 已验收。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (requests.RequestException, RuntimeError, KeyError, ValueError) as error:
        # 不输出响应正文、认证 Cookie、密码或原始网络异常。
        print(f"FAIL {type(error).__name__}: 请检查服务、角色、模型配置和服务端日志", file=sys.stderr)
        sys.exit(1)
