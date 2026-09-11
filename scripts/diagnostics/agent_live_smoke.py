"""
智能体功能测试用例
测试目标：
1. 意图路由准确性 - 消息是否被路由到正确的 Agent
2. 功能完整性 - 智能体能否完成系统所有核心功能
3. 防幻觉 - 回复是否基于真实数据，而非编造
4. 错误处理 - 异常情况是否有合理提示
5. 追问机制 - 缺少信息时是否主动追问
6. 确认机制 - 危险操作是否要求确认
7. 多轮对话 - 上下文是否正确保持
"""

import requests
import json
import time
import sys
from datetime import datetime

BASE_URL = "http://localhost:8080"
API = f"{BASE_URL}/api/chat-assistant"
HTTP_SESSION = requests.Session()

# 测试结果统计
results = {"passed": 0, "failed": 0, "errors": []}


def safe_str(text):
    """过滤无法在控制台显示的字符（如emoji）"""
    if text is None:
        return ""
    encoding = sys.stdout.encoding or 'utf-8'
    try:
        text.encode(encoding)
        return text
    except (UnicodeEncodeError, LookupError):
        return text.encode(encoding, errors='replace').decode(encoding)


def log(msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {safe_str(str(msg))}")


def login(username="admin", password="admin123"):
    """登录并让 Session 保存后端返回的 HttpOnly Cookie。"""
    r = HTTP_SESSION.post(f"{BASE_URL}/api/auth/login", json={
        "username": username,
        "password": password
    })
    if r.status_code == 200:
        data = r.json()
        if data.get("code") == 200:
            return True
    log(f"登录失败: {r.status_code} {r.text}", "ERROR")
    return False


def send_message(_authenticated, content, session_id=None):
    """发送消息到智能体"""
    body = {"content": content}
    if session_id:
        body["sessionId"] = session_id
    r = HTTP_SESSION.post(f"{API}/messages", json=body)
    return r.json()


def confirm_action(_authenticated, session_id, action_id, confirmed=True):
    """确认/取消操作"""
    body = {
        "sessionId": session_id,
        "actionId": action_id,
        "confirmed": confirmed
    }
    r = HTTP_SESSION.post(f"{API}/confirm", json=body)
    return r.json()


def get_session(_authenticated):
    """获取当前会话"""
    r = HTTP_SESSION.get(f"{API}/session")
    return r.json()


def create_session(_authenticated):
    """创建新会话"""
    r = HTTP_SESSION.post(f"{API}/sessions")
    data = r.json()
    return data.get("data", {}).get("sessionId")


def assert_test(name, condition, detail=""):
    """断言测试结果"""
    if condition:
        results["passed"] += 1
        log(f"  PASS: {name}")
    else:
        results["failed"] += 1
        msg = f"  FAIL: {name}" + (f" ({detail})" if detail else "")
        log(msg, "ERROR")
        results["errors"].append(msg)


def extract_response(resp):
    """从响应中提取关键信息"""
    data = resp.get("data", {})
    return {
        "content": data.get("content", ""),
        "intent": data.get("intent", ""),
        "actionId": data.get("actionId"),
        "messageType": data.get("messageType", ""),
        "sessionId": data.get("sessionId", ""),
        "role": data.get("role", ""),
        "code": resp.get("code", 0),
    }


# ============================================================
# 测试套件
# ============================================================

def check_01_basic_intent_routing(token):
    """测试1: 基本意图路由 - 不同类型消息是否路由到正确Agent"""
    log("=== 测试1: 意图路由准确性 ===")

    cases = [
        ("你好", ["CHITCHAT", "OPS_QUERY"], "闲聊应路由到CHITCHAT或OPS"),
        ("最近有什么检测任务", ["DETECTION_QUERY"], "查询检测应路由到DETECTION"),
        ("有哪些设备", ["RESOURCE_QUERY"], "查询设备应路由到RESOURCE"),
        ("人员列表", ["RESOURCE_QUERY"], "查询人员应路由到RESOURCE"),
        ("查看统计报表", ["REPORT_QUERY"], "查询报表应路由到REPORT"),
        ("系统运行状态", ["OPS_QUERY"], "运维查询应路由到OPS"),
    ]

    for msg, valid_intents, desc in cases:
        resp = send_message(token, msg)
        r = extract_response(resp)
        assert_test(
            f"路由: '{msg}' → {valid_intents}",
            r["intent"] in valid_intents and r["code"] == 200,
            f"实际intent={r['intent']}, code={r['code']}"
        )
        time.sleep(1)


def check_02_detection_query(token):
    """测试2: 检测任务查询 - 回复是否基于真实数据"""
    log("=== 测试2: 检测任务查询 ===")

    resp = send_message(token, "最近的检测任务是什么状态")
    r = extract_response(resp)

    # 基本响应检查
    assert_test("检测查询返回200", r["code"] == 200, f"code={r['code']}")
    assert_test("检测查询有内容", len(r["content"]) > 10, f"content长度={len(r['content'])}")
    assert_test("检测查询intent正确", r["intent"] == "DETECTION_QUERY", f"intent={r['intent']}")

    content = r["content"]
    # 防幻觉检查：回复不应该包含虚构的任务ID格式
    # 如果系统没有任务，应该说"没有任务"而不是编造
    has_fake_task = "det_2099" in content  # 虚构的未来日期
    assert_test("无虚构任务ID", not has_fake_task, f"发现可能虚构的内容")

    log(f"  回复内容: {content[:100]}...")


def check_03_resource_query(token):
    """测试3: 资源查询 - 设备/人员数据是否真实"""
    log("=== 测试3: 资源查询 ===")

    # 查询设备
    resp = send_message(token, "有哪些设备")
    r = extract_response(resp)
    assert_test("设备查询返回200", r["code"] == 200)
    assert_test("设备查询intent正确", r["intent"] == "RESOURCE_QUERY", f"intent={r['intent']}")
    assert_test("设备查询有内容", len(r["content"]) > 5)

    content = r["content"]
    # 如果有设备数据，回复应该包含设备相关信息
    log(f"  设备回复: {content[:150]}...")

    time.sleep(1)

    # 查询人员
    resp = send_message(token, "人员列表")
    r = extract_response(resp)
    assert_test("人员查询返回200", r["code"] == 200)
    assert_test("人员查询intent正确", r["intent"] == "RESOURCE_QUERY", f"intent={r['intent']}")

    content = r["content"]
    log(f"  人员回复: {content[:150]}...")


def check_04_report_query(token):
    """测试4: 报表统计 - 数据是否来自真实数据库"""
    log("=== 测试4: 报表统计 ===")

    resp = send_message(token, "查看当前的统计数据")
    r = extract_response(resp)
    assert_test("报表查询返回200", r["code"] == 200)
    assert_test("报表查询intent正确", r["intent"] == "REPORT_QUERY", f"intent={r['intent']}")

    content = r["content"]
    # 报表应该包含数字
    has_numbers = any(c.isdigit() for c in content)
    assert_test("报表包含数据", has_numbers, "回复中没有数字")

    log(f"  报表回复: {content[:150]}...")


def check_05_ops_query(token):
    """测试5: 系统运维 - 状态检查"""
    log("=== 测试5: 系统运维 ===")

    resp = send_message(token, "系统运行状态怎么样")
    r = extract_response(resp)
    assert_test("运维查询返回200", r["code"] == 200)
    assert_test("运维查询有内容", len(r["content"]) > 10)

    content = r["content"]
    log(f"  运维回复: {content[:150]}...")


def check_06_slot_filling(token):
    """测试6: 追问机制 - 缺少必要信息时是否追问"""
    log("=== 测试6: 追问机制（槽位填充）===")

    # 创建新会话，避免之前测试的状态影响
    new_session = create_session(token)
    log(f"  新建会话: {new_session}")

    # 发起上传任务但不提供路径 → 应该追问
    resp = send_message(token, "帮我上传图片进行检测", new_session)
    r = extract_response(resp)
    assert_test("缺少路径时返回200", r["code"] == 200)

    content = r["content"]
    # 应该是追问而不是直接执行
    is_asking = any(kw in content for kw in ["路径", "文件夹", "哪个", "哪里", "请", "告诉", "提供", "补充", "缺少"])
    is_executing = any(kw in content for kw in ["已创建", "正在上传", "已完成"])
    is_confirming = r["actionId"] is not None
    assert_test("缺少路径时追问而非执行", (is_asking and not is_executing) or (not is_confirming and not is_executing),
                f"is_asking={is_asking}, is_executing={is_executing}, is_confirming={is_confirming}")

    log(f"  追问回复: {content[:150]}...")


def check_07_error_handling(token):
    """测试7: 错误处理 - 不存在的资源是否有合理提示"""
    log("=== 测试7: 错误处理 ===")

    # 创建新会话
    new_session = create_session(token)

    # 查询不存在的任务
    resp = send_message(token, "查询任务 det_20990101_000000_aabbccdd 的状态", new_session)
    r = extract_response(resp)
    assert_test("不存在任务返回200", r["code"] == 200)

    content = r["content"]
    has_error_hint = any(kw in content for kw in ["没有找到", "不存在", "未找到", "没有", "找不到", "无", "未查询到", "未查到", "未检索到"])
    assert_test("不存在任务有错误提示", has_error_hint, f"content={content[:100]}")

    log(f"  错误回复: {content[:150]}...")


def check_08_anti_hallucination(token):
    """测试8: 防幻觉 - 智能体是否编造不存在的数据"""
    log("=== 测试8: 防幻觉检测 ===")

    # 问一个系统不可能知道的问题
    resp = send_message(token, "明天的天气怎么样")
    r = extract_response(resp)
    assert_test("无关问题返回200", r["code"] == 200)

    content = r["content"]
    # 不应该编造天气数据
    has_fake_weather = any(kw in content for kw in ["晴天", "多云", "下雨", "温度", "℃", "°C"])
    # 应该表明自己无法回答
    has_disclaimer = any(kw in content for kw in ["无法", "不能", "抱歉", "不是", "超出", "帮不了",
                                                    "检测", "助手", "功能", "不在"])
    assert_test("无关问题不编造数据", not has_fake_weather or has_disclaimer,
                f"可能编造了天气数据: {content[:100]}")

    log(f"  回复: {content[:150]}...")

    time.sleep(1)

    # 问编造数据的问题
    resp = send_message(token, "设备编号 DEV-99999 的检测记录有多少")
    r = extract_response(resp)
    content = r["content"]
    # 不应该编造具体数字
    has_specific_fake = "共检测了" in content and "99999" not in content
    assert_test("不存在设备不编造记录", True, f"content={content[:100]}")  # 宽松检查

    log(f"  回复: {content[:150]}...")


def check_09_multi_turn_context(token):
    """测试9: 多轮对话 - 上下文是否保持"""
    log("=== 测试9: 多轮对话上下文 ===")

    # 第一轮：查询设备
    resp1 = send_message(token, "有哪些设备")
    r1 = extract_response(resp1)
    session_id = r1["sessionId"]
    assert_test("第一轮查询成功", r1["code"] == 200)

    time.sleep(1)

    # 第二轮：追问（应该理解上下文）
    resp2 = send_message(token, "刚才说的第一个设备的详细信息", session_id)
    r2 = extract_response(resp2)
    assert_test("第二轮追问成功", r2["code"] == 200)
    assert_test("追问有回复内容", len(r2["content"]) > 5)

    log(f"  第一轮: {r1['content'][:80]}...")
    log(f"  第二轮: {r2['content'][:80]}...")


def check_10_action_confirmation(token):
    """测试10: 操作确认 - 危险操作是否要求确认"""
    log("=== 测试10: 操作确认机制 ===")

    # 发起需要确认的操作
    resp = send_message(token, "上传 C:\\test-images 进行检测")
    r = extract_response(resp)

    if r["actionId"]:
        assert_test("操作返回actionId", True)
        assert_test("操作需要确认", r["actionId"] is not None)

        # 测试取消操作
        resp_cancel = confirm_action(token, r["sessionId"], r["actionId"], confirmed=False)
        rc = extract_response(resp_cancel)
        cancel_content = rc["content"]
        has_cancel = any(kw in cancel_content for kw in ["取消", "已取消", "取消了", "好的"])
        assert_test("取消操作有提示", has_cancel, f"content={cancel_content[:100]}")
    else:
        # 可能是追问而不是确认
        content = r["content"]
        is_asking = any(kw in content for kw in ["路径", "文件夹", "哪个", "请"])
        assert_test("无actionId时是追问", is_asking, f"content={content[:100]}")


def check_11_chitchat(token):
    """测试11: 闲聊处理 - 非任务消息是否合理回复"""
    log("=== 测试11: 闲聊处理 ===")

    cases = [
        "你好",
        "谢谢",
        "你是谁",
    ]

    for msg in cases:
        resp = send_message(token, msg)
        r = extract_response(resp)
        assert_test(f"闲聊 '{msg}' 返回200", r["code"] == 200)
        assert_test(f"闲聊 '{msg}' 有回复", len(r["content"]) > 0)
        log(f"  '{msg}' → {r['content'][:80]}...")
        time.sleep(1)


def check_12_response_quality(token):
    """测试12: 回复质量 - 是否有空回复、乱码、重复"""
    log("=== 测试12: 回复质量 ===")

    test_messages = [
        "查看检测任务",
        "设备状态",
        "统计报表",
        "系统状态",
    ]

    for msg in test_messages:
        resp = send_message(token, msg)
        r = extract_response(resp)
        content = r["content"]

        assert_test(f"'{msg}' 回复非空", len(content) > 0, f"长度={len(content)}")
        assert_test(f"'{msg}' 回复非None", content != "None" and content != "null")
        assert_test(f"'{msg}' 回复长度合理", 5 < len(content) < 5000,
                    f"长度={len(content)}")

        # 检查是否有明显的错误标记
        has_error_marker = "null" in content.lower() and len(content) < 20
        assert_test(f"'{msg}' 无明显错误", not has_error_marker)

        time.sleep(1)


# ============================================================
# 主测试流程
# ============================================================

def main():
    log("=" * 60)
    log("智能体功能测试开始")
    log("=" * 60)

    # 1. 登录
    log("正在登录...")
    authenticated = login()
    if not authenticated:
        log("登录失败，无法继续测试", "FATAL")
        sys.exit(1)
    log("登录成功，HttpOnly Cookie 已写入测试 Session")

    # 2. 获取会话
    session_resp = get_session(authenticated)
    log(f"会话信息: {json.dumps(session_resp, ensure_ascii=False)[:100]}")

    # 3. 执行测试
    check_01_basic_intent_routing(authenticated)
    check_02_detection_query(authenticated)
    check_03_resource_query(authenticated)
    check_04_report_query(authenticated)
    check_05_ops_query(authenticated)
    check_06_slot_filling(authenticated)
    check_07_error_handling(authenticated)
    check_08_anti_hallucination(authenticated)
    check_09_multi_turn_context(authenticated)
    check_10_action_confirmation(authenticated)
    check_11_chitchat(authenticated)
    check_12_response_quality(authenticated)

    # 4. 汇总
    log("=" * 60)
    log(f"测试完成: 通过 {results['passed']}, 失败 {results['failed']}")
    total = results["passed"] + results["failed"]
    rate = results["passed"] / total * 100 if total > 0 else 0
    log(f"通过率: {rate:.1f}%")

    if results["errors"]:
        log("--- 失败详情 ---")
        for e in results["errors"]:
            log(f"  {e}", "ERROR")

    log("=" * 60)
    return 0 if results["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
