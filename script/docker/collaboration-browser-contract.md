# ECS 真实浏览器协同验收组件

状态：仅源码、Python/JSON 语法检查。本轮没有构建工具镜像、下载浏览器、启动容器或执行任何测试。首轮实际 ECS 结果可能暴露页面选择器、代理、资源预算或业务约束问题；这些必须按固定提交修复后重跑，不能改成跳过。

该组件供现有 `compact-runtime-acceptance.py` 完整 `verify-runtime` 的浏览器 hook 调用。它不代替九个真实业务场景，不改变升级/恢复、MySQL、全套测试或发布门。由 runtime 在原九场景通过之后、清理本轮 owned stack 之前调用；该文档没有授权手工发布、启停云实例或绕开 Jenkins。

## 固定 CLI 与输入

容器内命令：

```text
python /opt/doorhandle/collaboration-browser-runner.py --descriptor /run/doorhandle/browser-descriptor.json --accounts /run/doorhandle/users.json --output /evidence
```

调用即执行真实验收，没有默认通过或自动安装依赖的路径。退出码 `0` 为全部必需浏览器检查通过，`1` 为业务断言失败/覆盖不足/超时，`2` 为配置、工具或容器资源准入不满足。固定产物 `browser-evidence.json` 与 `screenshots/*.png`。配置失败可留下受控 FAIL JSON；原始 stdout/stderr、私有输入不应归档。

`browser-descriptor.json` 是私有只读输入：

```json
{
  "schemaVersion": 1,
  "commit": "<40 lowercase hex>",
  "sourceSha256": "<64 lowercase hex>",
  "ownership": {
    "project": "<existing owned compose project>",
    "network": "<existing owned network>",
    "token": "<existing private ownership token, not a login token>"
  },
  "upstream": "http://ui:80",
  "runtime": {
    "browserImageId": "sha256:<64 lowercase hex>",
    "browserContainerId": "<64 lowercase hex>",
    "cpuLimit": 2,
    "memoryLimitBytes": 2147483648,
    "pidsLimit": 512
  },
  "fixtures": { "reportTaskId": "<actual worker-completed existing report_task_id>" },
  "budgets": {
    "accounts": 20,
    "tabsPerAccount": 2,
    "p95MaxMs": 2000,
    "minimumLatencySamples": 20,
    "timeoutSeconds": 600
  }
}
```

可选 `fixtures.deviceId` 仅能指向本轮已拥有设备，并必须同时提供 `deviceOwned: true`；否则 runner 通过真实主管新增设备页面创建隔离设备，不借用宿主或生产资源。已创建资源 ID 即时写入证据，最终随 runtime owned schema 统一清理。浏览器不自行删库/停服务。

`users.json` 接受 runtime 的现有结构 `{ "accounts": { ... } }`，必须恰有 `inspector`、`peer`、`supervisor`、`reviewer`、`load_01` 至 `load_16`，共 20 个不同真实用户；每项含 `username,password,userId,role,employeeId,departmentId`。后两个字段由 runtime 保留，不从它们伪造登录身份。前两主管角色为 `SUPERVISOR`，两检测角色为 `INSPECTOR`；登录后逐个从真实 `/api/auth/check` 验证 ID、角色、会话上下文和四个能力开关。输入中的 ID 可以是整数或 decimal string，输出统一字符串。无正确开关/资格/会话时 FAIL。

容器 ID 在 Docker create 后由 runtime inspect 取得。先绑定只读私有输入目录，再在启动前写入描述符；不要绑定不存在的单个文件后让 Docker 创建同名目录。使用 Docker 默认 hostname，runner 核对 hostname 等于容器 ID 前 12 位。

## 工具构建与资源准入

`Dockerfile.collaboration-browser` 要求明确的 `BASE_IMAGE=ubuntu:24.04@sha256:<admitted digest>`，没有浮动默认；只支持当前 ECS 的 linux/amd64、CPython 3.12。锁定 Playwright 1.65.0、greenlet 3.5.6 的二进制 wheel SHA，浏览器使用官方安装器的 `--only-shell chromium`，固定 headless shell 158.0.8127.18/r1254，不安装 Firefox、WebKit 或完整 Chromium。

版本、许可证和兼容性来源记录于 `collaboration-browser-sources.json`。来源为 [Playwright 官方发布](https://github.com/microsoft/playwright-python/releases/tag/v1.65.0)、[固定浏览器清单](https://raw.githubusercontent.com/microsoft/playwright/v1.65.0/packages/playwright-core/browsers.json)、[官方 headless shell 安装说明](https://playwright.dev/python/docs/browsers)、[Ubuntu/Python 支持说明](https://playwright.dev/python/docs/intro) 和 [官方容器说明](https://playwright.dev/python/docs/docker)。Playwright 为 Apache-2.0；Chromium 为 BSD-style 并包含其他第三方许可证；greenlet 为 MIT AND PSF-2.0。镜像保留安装包的 LICENSE/NOTICE/credits 文件，不为压缩大小而删除。

没有在本轮下载/验证浏览器 archive，故清单的 archive SHA 明确为空。后续受准入约束的工具构建必须记录实际基础镜像 digest、工具镜像 ID、browser executable SHA、包清单与实际磁盘大小。APT 依赖来自 Ubuntu noble 仓库，其具体版本由构建产生的包清单与最终不可变工具镜像固定；这不是对任意未来浮动 APT 仓库的逐字节复现承诺。

以下是 runtime 的准入要求，不是已执行命令或资源已够用的结论：

- 为 browser 单独创建 owned 容器、cgroup、PID/IPC namespace；加入已经拥有的 network，仅通过 `ui:80` alias 访问实际 Nginx。禁止 host network、host PID/IPC、privileged、额外 capabilities、Docker socket、宿主业务目录或浏览器缓存挂载。
- 建议 Docker `--init --read-only --cap-drop ALL --security-opt no-new-privileges --cpus 2 --memory 2g --memory-swap 2g --pids-limit 512 --shm-size 256m`；只读私有输入、可写 `/evidence`，另给受限 `/tmp` tmpfs。运行 UID/GID 10001，runtime 预设 evidence 目录权限。`/dev/shm`、`/tmp`、页面和代理线程均计入本轮浏览器内存资源。
- Chromium 仅访问本轮 owned UI，以 `chromium_sandbox=False` 运行，明确记录此事实；容器资源、权限和网络边界由外层约束。没有 `SYS_ADMIN`、`--ipc=host` 或把非安全源伪装安全的启动标志。
- runner 复核 Docker marker、默认 hostname、无 Docker socket、可读 cgroup v2 有限 memory/CPU/pids 与描述符一致；namespace 内的 cgroup path 可以合法为 `/`。runtime 仍须外部 inspect 实际容器 ID/镜像/labels/network/mounts/资源限制/非 privileged 及非 host namespace，并单列后台 JVM 等资源样本。runner 内部自述不代替这个外部证据。
- 40 个实际 Vue 标签的峰值内存尚未实测。2 GiB 是 runner 的最低准入线，实际不足必须失败并按总 ECS 预算重新评估，不能通过移除 cgroup 限制来“通过”。
- 额外磁盘暂估：镜像稳态 0.5–1.0 GiB，构建峰值 1.0–1.5 GiB，证据 0.1–0.3 GiB，全部为规划区间。先读回可用空间、原服务/制品保留量、镜像实际 shared layers 和峰值，再做准入；不将估算当测量，不影响运行中的 #198。

## 真实拓扑、页面与测量口径

浏览器访问容器自己的 `http://127.0.0.1:<随机端口>`。透明代理固定转发 owned network 的 `http://ui:80`，透传原 Host/Origin/Referer 和 Set-Cookie，以 `read1` 逐块读取并立即 flush；不改变业务响应、不缓存 SSE。此拓扑等效已有用户通过 SSH 回环访问真实 Nginx，localhost 按浏览器标准为可信上下文，因此可以使用真实 Web Locks。没有给 `http://ui` 使用忽略安全限制的参数，也不宣称公网 HTTP/2。证据分别记录 CDP 观察的浏览器协议和上游 Nginx HTTP 版本。

实际页面沿用 Vue 组织/设备/报告/修改记录和 React `/agent-ui/` 持久工作台；选择器来自现有 diagnostics 和这些页面源码。React 必须真实读取会话 workbench 返回 200、通过原 UI 格式校验、文件控件进入已加载可用状态且没有工作台错误，不能只凭 region 出现就通过。没有测试专用业务页面、`page.set_content`、伪造业务 API、模型调用或提供者计费。Playwright route 仅拒绝外部 origin；迟到 logout、私有 GET 和 refresh 在透明代理收到真实上游响应后、向浏览器发送任何 headers 之前暂停，保留原服务器结果及真实迟到 Set-Cookie 顺序。没有使用可能提前更新同一 cookie jar 的 `route.fetch` 冒充此竞态。

20 个独立 context 各有两张真实设备列表标签。主管从原设备表单打开并固定版本后修改型号；每轮 19 个其他账号的可见标签用 DOM MutationObserver 观测实际行文本，两个主管轮换写，所有 20 个账号至少取得一个真实样本。采样量不足、账号缺失、隐藏观察页、没有匹配命名事件、缺时间戳或超过 P95 阈值均失败。

主指标是匹配 `requestId + resourceId + version` 的服务端 `occurredAt` 到实际可见 DOM 更新，浏览器和后端共享 ECS kernel wall clock。该时间是审计创建时刻、位于提交前，因此是保守的提交到页面延迟口径；同时单列成功响应到 DOM 的时间，不把响应时间、事件到达或仅在测试中拼出的 DOM 当成提交到更新。负延迟、缺 offset 或无法匹配真实事件时 FAIL。P95 使用 nearest-rank，不能把少样本结果声称为生产容量结论。

每个账号两标签共享一条原生 EventSource 的连接预算；记录实际 CDP 协议、连接数和 heartbeat/resource-changed/resync-required、断开后的 Last-Event-ID 及首帧 resync。后台标签按产品的 visibility 规则不纳入前台 P95，另以真实 focus 验证收敛；不覆盖 `document.visibilityState`。每秒记录浏览器 cgroup memory/cpu/pids、OOM 计数与 runner 线程样本，后台服务资源及慢客户端队列仍需 runtime 单独采证。

## 证据边界与不足

固定 JSON 中账号仅保留 alias、decimal userId 与 role。ownership project/network 只记 SHA，token 不输出。截图遮盖密码、用户名字段以及本轮账号名/ownership token 所在文本；不启用 HAR、trace、video、storage-state 或原始 HTTP/SSE正文归档。仅存字段白名单的事件定位、版本、请求号、时间和受控错误类型；异常原文可能含凭据，故不打印。精确秘密扫描只是附加防线，不替代上述最小化设计。

JSON 对 A01–A28 逐项列 `BROWSER_PORTION_PASS`、`FAIL` 或 `NOT_COVERED` 及具体限制。required 检查一项未执行会导致总 FAIL，绝不默认 skip 当通过。A02、A05、A08、A16、A18、A19 没有本组件可独立完成的夹具/控制面，明确未覆盖；A27 通过真实浏览器 fetch 验证双标签并发 refresh、logout/B 登录后迟到 refresh headers 不改变 B、旧 A context 再刷新被拒绝，并不替代过期/重启/事务夹具。其他项也只证明浏览器部分。`fullA01A28AcceptanceClaimed` 永远为 false，必须与保留的 HTTP、MySQL、会话、真实模型/工具、迁移/恢复及外部资源证据共同评估。
