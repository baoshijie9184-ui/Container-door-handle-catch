# 测试结构优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将自动化测试、在线诊断脚本和源码契约测试明确分层，减少重复样板并拆解超大 Java 测试，同时保持关键业务覆盖。

**Architecture:** 默认测试目录只包含离线、确定性测试；需要运行中服务或浏览器的脚本进入 `scripts/diagnostics`；前端契约测试共享统一文件读取助手并按领域合并；检测任务测试通过共享 Fixture 按职责拆分。

**Tech Stack:** JUnit 5、Mockito、pytest、Node.js Test Runner、Vue 3、Maven 3.9.6

---

## 文件结构

- `scripts/diagnostics/`：人工执行的在线 Agent 与浏览器诊断脚本。
- `tests_python/`：只保留可离线执行的 pytest 测试。
- `frontend/tests/helpers/project-source.cjs`：前端源码契约公共读取工具。
- `frontend/tests/assistant-contracts.test.cjs`：助手领域契约。
- `frontend/tests/quality-contracts.test.cjs`：质检领域契约。
- `frontend/tests/detection-contracts.test.cjs`：检测领域契约。
- `frontend/tests/deployment-contracts.test.cjs`：部署与环境契约。
- `frontend/tests/security-shell-contracts.test.cjs`：认证、租户和应用壳契约。
- `src/test/java/com/ruanzhu/doorhandlecatch/service/impl/DetectionTaskServiceFixture.java`：检测任务测试公共 Fixture。

### Task 1：记录重构前测试基线

**Files:**
- Verify only

- [ ] **Step 1：运行并记录 Java 基线**

```powershell
& 'D:\ruanjian\apache-maven-3.9.6\bin\mvn.cmd' -q test
```

Expected: PASS。

- [ ] **Step 2：运行并记录 Python 基线**

```powershell
.\scripts\run-python.ps1 -m pytest tests_python -q
```

Expected: 20 passed；在线 `test_agent.py` 不应被收集。

- [ ] **Step 3：运行并记录前端基线**

```powershell
Set-Location frontend
node --test tests/*.test.cjs
Set-Location ..
```

Expected: 所有 Node 测试通过。

### Task 2：将在线脚本移出 pytest

**Files:**
- Move: `tests_python/test_agent.py` → `scripts/diagnostics/agent_live_smoke.py`
- Move: `tests_python/test_login_debug.py` → `scripts/diagnostics/login_browser_debug.py`
- Move: `tests_python/test_login_debug2.py` → `scripts/diagnostics/login_browser_debug_alt.py`
- Move: `tests_python/test_usage_status_filter.py` → `scripts/diagnostics/usage_status_browser_debug.py`
- Modify: `tests_python/conftest.py`
- Delete: `tests_python/test_python_collection_config.py`
- Create: `scripts/diagnostics/README.md`

- [ ] **Step 1：验证当前收集规则依赖排除列表**

```powershell
.\scripts\run-python.ps1 -m pytest tests_python/test_python_collection_config.py -q
```

Expected: PASS，证明当前目录结构需要四项 `collect_ignore`。

- [ ] **Step 2：移动并重命名四个诊断脚本**

使用 `git mv` 执行上述四组移动。脚本内部在线请求、Playwright 操作和输出逻辑保持不变；将 `test_01_*` 等函数改名为 `check_01_*`，并在脚本主入口显式依次调用，避免任何工具把它们误识别为自动化测试。

主入口采用：

```python
def main():
    if not login():
        raise SystemExit(1)
    checks = [
        check_01_basic_intent_routing,
        check_02_detection_query,
        check_03_resource_query,
        check_04_report_query,
        check_05_ops_query,
        check_06_slot_filling,
        check_07_error_handling,
        check_08_anti_hallucination,
        check_09_multi_turn_context,
        check_10_action_confirmation,
        check_11_chitchat,
        check_12_response_quality,
    ]
    for check in checks:
        check(True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3：简化 pytest 配置**

`tests_python/conftest.py` 完整内容：

```python
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
```

删除 `test_python_collection_config.py`。

- [ ] **Step 4：添加诊断说明**

`scripts/diagnostics/README.md` 必须列出每个脚本的用途、前置服务和执行命令，例如：

```markdown
# 人工诊断脚本

本目录脚本依赖已启动的后端、前端或浏览器，不参与默认 pytest。

```powershell
.\scripts\run-python.ps1 scripts/diagnostics/agent_live_smoke.py
.\scripts\run-python.ps1 scripts/diagnostics/login_browser_debug.py
```
```

- [ ] **Step 5：验证 pytest 收集结果**

```powershell
.\scripts\run-python.ps1 -m pytest tests_python --collect-only -q
.\scripts\run-python.ps1 -m pytest tests_python -q
```

Expected: 收集列表中没有在线 Agent 或浏览器脚本；全部离线测试通过。

- [ ] **Step 6：提交诊断脚本分层**

```powershell
git add tests_python scripts/diagnostics
git commit -m "refactor: separate live diagnostics from pytest"
```

### Task 3：建立前端契约测试公共助手

**Files:**
- Create: `frontend/tests/helpers/project-source.cjs`
- Modify: `frontend/tests/*.test.cjs`

- [ ] **Step 1：创建公共助手的失败测试**

创建 `frontend/tests/project-source-helper.test.cjs`：

```javascript
const assert = require('node:assert/strict')
const test = require('node:test')
const { readFrontendFile, readProjectFile } = require('./helpers/project-source.cjs')

test('project source helper reads UTF-8 project and frontend files', () => {
  assert.match(readProjectFile('pom.xml'), /<artifactId>DoorHandleCatch<\/artifactId>/)
  assert.match(readFrontendFile('package.json'), /"name": "door-handle-frontend"/)
})
```

- [ ] **Step 2：运行并确认模块尚不存在**

```powershell
Set-Location frontend
node --test tests/project-source-helper.test.cjs
Set-Location ..
```

Expected: FAIL with `MODULE_NOT_FOUND`。

- [ ] **Step 3：实现公共读取助手**

`frontend/tests/helpers/project-source.cjs` 完整内容：

```javascript
const fs = require('node:fs')
const path = require('node:path')

const frontendRoot = path.resolve(__dirname, '..', '..')
const projectRoot = path.resolve(frontendRoot, '..')

const readUtf8 = (root, segments) => {
  const filePath = path.join(root, ...segments)
  return fs.existsSync(filePath) ? fs.readFileSync(filePath, 'utf8') : ''
}

const readFrontendFile = (...segments) => readUtf8(frontendRoot, segments)
const readProjectFile = (...segments) => readUtf8(projectRoot, segments)

module.exports = { frontendRoot, projectRoot, readFrontendFile, readProjectFile }
```

- [ ] **Step 4：迁移现有契约测试的重复读取代码**

所有契约测试删除重复的 `fs`、`path`、`frontendRoot`、`projectRoot` 和 `read` 定义，按作用域使用：

```javascript
const { readFrontendFile, readProjectFile } = require('./helpers/project-source.cjs')
```

原来读取 `frontend/src/...` 的测试使用 `readFrontendFile('src', ...)`；读取根目录部署、脚本或 README 的测试使用 `readProjectFile(...)`。断言内容不改变。

- [ ] **Step 5：运行全部前端测试**

```powershell
Set-Location frontend
node --test tests/*.test.cjs
Set-Location ..
```

Expected: PASS。

- [ ] **Step 6：提交公共助手**

```powershell
git add frontend/tests
git commit -m "test: share frontend source contract helpers"
```

### Task 4：将前端契约测试按领域合并

**Files:**
- Create: `frontend/tests/assistant-contracts.test.cjs`
- Create: `frontend/tests/quality-contracts.test.cjs`
- Create: `frontend/tests/detection-contracts.test.cjs`
- Create: `frontend/tests/deployment-contracts.test.cjs`
- Create: `frontend/tests/security-shell-contracts.test.cjs`
- Delete: 被合并的单主题 `*-contract.test.cjs`

- [ ] **Step 1：按以下映射机械迁移测试，不改变断言**

```text
assistant-contracts.test.cjs
  chat-business-card
  chat-confirm-action-guard
  chat-question-navigator
  chat-responsive-viewport
  chat-text-source
  chat-voice-input
  business-trace-presets

quality-contracts.test.cjs
  quality-records
  quality-workflow
  use-quality-queue
  use-quality-report-downloads
  use-quality-task-actions
  use-trace-reports

detection-contracts.test.cjs
  detection-category
  single-image-preview
  use-defect-gallery
  use-detection-history

deployment-contracts.test.cjs
  nginx-compose-deployment
  python-environment
  layout-sidebar-fixed

security-shell-contracts.test.cjs
  auth-response-guard
  cookie-only-auth
  hash-route-anchor
  single-enterprise-shared-access
```

每个目标文件统一以以下头部开始：

```javascript
const assert = require('node:assert/strict')
const test = require('node:test')
const { readFrontendFile, readProjectFile } = require('./helpers/project-source.cjs')
```

保留原测试名称和每一条断言，删除原单主题文件。`project-source-helper.test.cjs` 保留为助手自身测试。

- [ ] **Step 2：验证测试数量与行为**

```powershell
Set-Location frontend
node --test tests/*.test.cjs
Get-ChildItem tests -File -Filter *.test.cjs | Select-Object -ExpandProperty Name
Set-Location ..
```

Expected: 测试断言全部通过；契约文件收敛为五个领域文件加公共助手测试，不丢失原测试名称。

- [ ] **Step 3：运行前端生产构建**

```powershell
Set-Location frontend
npm run build
Set-Location ..
```

Expected: build success。

- [ ] **Step 4：提交领域合并**

```powershell
git add frontend/tests
git commit -m "test: group frontend contracts by domain"
```

### Task 5：提取检测任务测试 Fixture

**Files:**
- Create: `src/test/java/com/ruanzhu/doorhandlecatch/service/impl/DetectionTaskServiceFixture.java`
- Modify: `src/test/java/com/ruanzhu/doorhandlecatch/service/impl/DetectionTaskServiceImplTest.java`

- [ ] **Step 1：建立 Fixture，集中 Mock 与 Service 构造**

`DetectionTaskServiceFixture` 与测试类位于同一个 `impl` 包，使用包内可见字段集中 Mapper、服务和发布器 Mock。完整内容为：

```java
package com.ruanzhu.doorhandlecatch.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandlecatch.config.properties.OssProperties;
import com.ruanzhu.doorhandlecatch.dto.detection.event.DetectionTaskFinishedEvent;
import com.ruanzhu.doorhandlecatch.entity.DetectionTask;
import com.ruanzhu.doorhandlecatch.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandlecatch.mapper.ModelInfoMapper;
import com.ruanzhu.doorhandlecatch.security.DetectionTaskAccessPolicy;
import com.ruanzhu.doorhandlecatch.service.ChatSessionService;
import com.ruanzhu.doorhandlecatch.service.DetectionTaskDispatchService;
import com.ruanzhu.doorhandlecatch.service.ModelService;
import com.ruanzhu.doorhandlecatch.service.OssStorageService;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;

import static org.mockito.Mockito.mock;

final class DetectionTaskServiceFixture {
    final DetectionTaskMapper detectionTaskMapper = mock(DetectionTaskMapper.class);
    final ModelInfoMapper modelInfoMapper = mock(ModelInfoMapper.class);
    final ModelService modelService = mock(ModelService.class);
    final OssStorageService ossStorageService = mock(OssStorageService.class);
    final DetectionTaskDispatchService detectionTaskDispatchService = mock(DetectionTaskDispatchService.class);
    final ChatSessionService chatSessionService = mock(ChatSessionService.class);
    DetectionTaskServiceImpl service;

    void setUp() {
        SecurityContextHolder.clearContext();
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(
                        "admin", "N/A", List.of(new SimpleGrantedAuthority("ROLE_ADMIN"))));

        OssProperties ossProperties = new OssProperties();
        ossProperties.setUploadUrlExpireMinutes(15);
        ossProperties.setPreviewUrlExpireMinutes(30);
        ossProperties.setBasePrefix("detection");

        service = new DetectionTaskServiceImpl(
                detectionTaskMapper,
                modelInfoMapper,
                modelService,
                ossStorageService,
                ossProperties,
                detectionTaskDispatchService,
                chatSessionService,
                new ObjectMapper(),
                new DetectionTaskAccessPolicy());
        ReflectionTestUtils.setField(service, "maxImagesPerBatch", 200);
        ReflectionTestUtils.setField(service, "maxImageBytes", 10L * 1024L * 1024L);
    }

    DetectionTask task(String taskId, String status) {
        DetectionTask task = new DetectionTask();
        task.setTaskId(taskId);
        task.setStatus(status);
        return task;
    }

    DetectionTaskFinishedEvent finishedEvent(String taskId, String dispatchId, String eventId) {
        DetectionTaskFinishedEvent event = new DetectionTaskFinishedEvent();
        event.setTaskId(taskId);
        event.setDispatchId(dispatchId);
        event.setEventId(eventId);
        return event;
    }
}
```

原测试中的 `detectionTaskService` 替换为 `fixture.service`，六个 Mock 字段分别替换为 `fixture` 上的同名字段；删除 `@ExtendWith(MockitoExtension.class)`、`@Mock` 字段和旧 `setUp()`。

- [ ] **Step 2：迁移原测试并验证行为不变**

```powershell
& 'D:\ruanjian\apache-maven-3.9.6\bin\mvn.cmd' -q -Dtest=DetectionTaskServiceImplTest test
```

Expected: 原测试全部通过。

- [ ] **Step 3：提交 Fixture 提取**

```powershell
git add src/test/java/com/ruanzhu/doorhandlecatch/service/impl
git commit -m "test: extract detection task service fixture"
```

### Task 6：按职责拆分检测任务测试

**Files:**
- Create: `src/test/java/com/ruanzhu/doorhandlecatch/service/impl/DetectionTaskUploadTest.java`
- Create: `src/test/java/com/ruanzhu/doorhandlecatch/service/impl/DetectionTaskEventTest.java`
- Create: `src/test/java/com/ruanzhu/doorhandlecatch/service/impl/DetectionTaskQualityTest.java`
- Create: `src/test/java/com/ruanzhu/doorhandlecatch/service/impl/DetectionTaskTraceTest.java`
- Delete: `src/test/java/com/ruanzhu/doorhandlecatch/service/impl/DetectionTaskServiceImplTest.java`

- [ ] **Step 1：按方法职责迁移**

```text
DetectionTaskUploadTest
  getTaskProgressAllowsTaskOwnedByAnotherUser
  createTask*
  confirmUploaded*
  markUploaded*
  retryTask*

DetectionTaskEventTest
  applyFinishedEvent*
  ignoresFinishedEventFromStaleDispatch
  ignoresDuplicateFinishedEvent
  backgroundFailureCanUpdateTaskWithoutUserSecurityContext
  completionNotificationRestoresTenantFromPersistedSession

DetectionTaskQualityTest
  advanceTaskFlow*
  reviewTask*
  assignQualityTask*
  disposeTask*
  submitReworkResult*
  listQualityQueue*

DetectionTaskTraceTest
  getBatchTraceReport*
  getWorkOrderTraceReport*
  listDefectGallery*
  getQualityReport*
  getTaskTrace*
```

四个类统一使用：

```java
private DetectionTaskServiceFixture fixture;

@BeforeEach
void setUp() {
    fixture = new DetectionTaskServiceFixture();
    fixture.setUp();
}
```

测试方法体和断言原样迁移；共享实体构造改用 Fixture 方法。完成迁移后删除原 1100 行测试类。

- [ ] **Step 2：逐类运行测试**

```powershell
& 'D:\ruanjian\apache-maven-3.9.6\bin\mvn.cmd' -q '-Dtest=DetectionTaskUploadTest,DetectionTaskEventTest,DetectionTaskQualityTest,DetectionTaskTraceTest' test
```

Expected: PASS；测试总数不得少于拆分前该类的测试数。

- [ ] **Step 3：运行完整 Maven 测试**

```powershell
& 'D:\ruanjian\apache-maven-3.9.6\bin\mvn.cmd' -q test
```

Expected: PASS。

- [ ] **Step 4：提交职责拆分**

```powershell
git add src/test/java/com/ruanzhu/doorhandlecatch/service/impl
git commit -m "test: split detection task tests by responsibility"
```

### Task 7：测试结构最终验收

**Files:**
- Verify only

- [ ] **Step 1：运行三套自动化测试**

```powershell
& 'D:\ruanjian\apache-maven-3.9.6\bin\mvn.cmd' -q test
.\scripts\run-python.ps1 -m pytest tests_python -q
Set-Location frontend
node --test tests/*.test.cjs
npm run build
Set-Location ..
```

Expected: Java、Python、前端测试及构建全部通过。

- [ ] **Step 2：验证在线脚本没有进入测试目录**

```powershell
rg -n 'localhost:8080|sync_playwright|chromium\.launch' tests_python
```

Expected: no matches。

- [ ] **Step 3：验证没有测试产物或格式问题**

```powershell
git diff --check
git status -sb
```

Expected: 无未提交代码、截图、日志、`target` 或 `dist` 产物。
