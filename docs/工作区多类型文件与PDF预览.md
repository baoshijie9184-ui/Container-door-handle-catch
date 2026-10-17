# 工作区多类型文件与 PDF 预览

适用分支：`java-cloud`，Java 模块化单体。时间使用 UTC+8。此文分别记录代码能力、本地检查和云端验收，不把上传成功当作模型理解成功。

## 文件能力

| 类型 | 上传校验 | 页面展示 | Agent 工具读取 |
| --- | --- | --- | --- |
| PNG、JPEG、WebP | 匹配真实解码器并解码首帧，读取警告视为不可接受；最长边 8192，最多 1600 万像素 | 图片，加载失败给出下载核对提示 | 明确返回尚无视觉识别/OCR，不能凭附件推断图像内容 |
| PDF | PDFBox 解析文档结构、页树、页尺寸；拒绝加密、禁止提取、空文档和超过 100 页或 10000 个交叉引用对象 | 服务端每次按授权编号渲染一页为 PNG；两入口的消息附件和文件树均可翻页，不向浏览器嵌入原 PDF | `read_workspace_file` 提取文字层，带页数与能力说明；扫描件/无文字层提示没有 OCR |
| TXT、Markdown、CSV | 严格 UTF-8，拒绝二进制控制字符 | 惰性文本；按字节上限截断并提示，不切坏中文或补充平面字符 | 有界文本片段，不执行公式、命令或文件中指令 |
| JSON | UTF-8、单个合法 JSON 值，无尾随内容；深度至多 100，单字符串至多 1000000 字符，数字长度至多 1000 | 惰性源码 | 有界文本，不将截断 JSON 当完整结构 |
| HTML、SVG | UTF-8 文本校验 | 仅源码，保持 `text/plain`，不执行脚本或事件属性 | 有界源码，不能扩大工具权限 |

沿用单文件默认 25 MiB、每账号默认 500 MiB 和默认 64000 字节文字预览配置。文件上传与产物生成共用校验；产物仅允许 Markdown/CSV/JSON。CSV 以文本读取，不进行 Excel 公式求值。图片读取不保证所有动画帧或全部附加元数据都符合标准；PDF 结构接受不保证所有字体、内容流或页面都能成功渲染，页面失败会提示下载核对。

## 权限和接口

App 模块拥有文件存储与解析，AI 模块只调用 `WorkbenchSessionApi.readText`。所有解析入口先重新核对当前账号、角色、会话文件引用、磁盘长度和 SHA-256，再解析正文；其他账号和没有文件引用的会话不能通过编号读取。文件原始字节不修改，原有幂等编号、配额锁、审计回滚和持久卷位置保留。

- 原文件下载仍使用 `GET /api/agent/conversations/{session}/files/{id}/content`，每次鉴权。
- PDF 页面预览使用 `GET /api/agent/conversations/{session}/files/{id}/preview?page=1`，成功返回 `image/png`，响应头 `X-PDF-Page` / `X-PDF-Pages` 表示当前页和总页数；页码须在真实文档范围内。
- CORS 默认公开这两个页码响应头，仍使用原有来源白名单；如自定义 `APP_CORS_EXPOSED_HEADERS`，须包含 `X-PDF-Page,X-PDF-Pages`，否则跨来源前端无法读取页码。相同来源及反向代理入口不受该浏览器限制。
- 响应为 `no-store`，同时设置 `nosniff` 和限制性 CSP。浏览器只创建 PNG Blob URL；原 PDF 的 JavaScript、超链接和嵌入文件不进入预览页面。
- 页面切换再次鉴权；403/404 关闭预览，消息卡片还会移除文件名和读取动作。切换会话时丢弃旧请求结果，关闭弹窗后不接受迟到的翻页结果。
- HTML/SVG 和文件名始终作为文本，不通过 `innerHTML`、脚本、Shell 或 Skill 运行。

## 解析资源边界

同一 JVM 最多两个图片/PDF 解析同时执行，忙时 429，明确本次操作尚未开始。PDF 页面按最长 1400×1800 的视窗缩放（旋转后宽高可交换），放大倍数不超过 2；内嵌图片允许下采样。文字层输出有字节上限，累计文字位置超过 200000 时拒绝，流操作之间检查 10 秒期限与线程中断。

这些是同进程的资源与合作式限制，**不是独立进程的硬内存/超时沙箱**。PDF 加载、字体和复杂绘图操作内部未必及时让出执行；压缩内容的资源消耗也不由输入字节数完全决定。服务器资源压力和恶意压缩样本仍需真实环境验证，不能据此宣称已通过任意不可信文件压力验收。

## 开源依据

采用 [Apache PDFBox 3.0.8](https://pdfbox.apache.org/3.0/getting-started.html)（Apache-2.0）和 [TwelveMonkeys ImageIO WebP 3.13.1](https://github.com/haraldk/TwelveMonkeys/releases/tag/twelvemonkeys-3.13.1)（BSD-3-Clause），锁定于父 POM。维护情况依据官方发布记录，Java 兼容性依据 [PDFBox 3.0 迁移说明](https://pdfbox.apache.org/3.0/migration.html) 及本项目 Java 17 编译/测试。未复制第三方解析实现；运行 JAR 保留依赖内许可证，评审副本位于 [licenses/workspace-file-parsers](licenses/workspace-file-parsers)。

## 验证记录

以当前检查日志为准：`work/file-content-tests.log`、`work/file-formats-maven.log`、`work/file-formats-node.log`、`work/file-formats-react-node.log`、`work/file-formats-*-build.log`。真实解析器测试覆盖格式损坏、图片尺寸、PDF 加密/页数/文字层、UTF-8 截断、JSON 限制、不同账号/会话及摘要变化。PDF 渲染样本有不同颜色的两页及文档打开脚本，检查生成图片像素与页码，不在测试中执行脚本。

浏览器验收脚本为 `script/diagnostics/workspace-file-formats-acceptance.py`，先运行 `WorkspaceFileContentTest` 生成 `target` 内的 PDF/PNG，再连接 Vite 3011/5175。浏览器 API 使用隔离样本，PNG 来自实际 PDFBox 测试；不等于已完成真实 MySQL、生产接口或云端验收。七项整体目标、真实模型评测和最终 Jenkins 统一发布仍需继续完成。

2026-10-18（UTC+8）验证：隔离 Maven 工作目录 775 项中 748 通过、27 跳过，最终源码/POM 一致；Node 119/5 项、Python 104 项及 6 subtest 通过。文件浏览器 38 项验证八类文件的预览/原样下载、桌面/手机 PDF 页码、翻页权限撤销、Esc 关闭慢请求及迟到响应不重开弹窗，无 JavaScript 错误。测试字体缓存固定到模块 `target`，不额外写入 C 盘用户目录。真实 Linux PDF 字体渲染、生产 MySQL/文件卷与真实模型读取仍需最终统一部署验收。现有 Temurin JRE noble 基础镜像的 [官方构建文件](https://github.com/adoptium/containers/blob/main/17/jre/ubuntu/noble/Dockerfile) 包含 fontconfig，但不能以此替代镜像实测。
