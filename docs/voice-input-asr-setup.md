# 智能助手语音输入接入说明

当前项目已内置本地 `faster-whisper` 智能助手语音输入链路：

```text
浏览器 MediaRecorder 录音
  -> POST /api/chat-assistant/voice/transcribe
  -> 本地 ASR 服务（127.0.0.1:9001）
  -> 返回识别文本
  -> 填入智能助手输入框，由用户确认后发送
```

## ASR 服务与健康检查

语音服务源码在 [asr_service.py](../python/asr/asr_service.py)，依赖声明在 [requirements-asr.txt](../python/asr/requirements-asr.txt)。旧 Windows 启动器已退役；在获准的运行环境准备 ASR 和模型后，再把单体后端指向该服务可达的地址。若采用原来的 `base` 模型，首次准备会下载权重。以下健康检查只用于 ASR 已监听当前主机环回地址的情形：

```powershell
Invoke-RestMethod http://127.0.0.1:9001/health
```

默认使用 CPU INT8，避免与图像检测争抢显存。可通过 `ASR_MODEL`、`ASR_DEVICE` 和 `ASR_COMPUTE_TYPE` 覆盖；本地服务只监听环回地址，不向局域网开放。

## Spring Boot 配置

通过私有运行配置设置 ASR 地址和允许主机。下例适用于后端与 ASR 共用环回网络的情形；容器隔离部署时应改用后端容器可达的服务地址：

```powershell
$env:CHAT_ASSISTANT_VOICE_TRANSCRIBE_URL="http://127.0.0.1:9001/transcribe"
$env:CHAT_ASSISTANT_VOICE_TRANSCRIBE_ALLOWED_HOSTS="localhost,127.0.0.1,::1"
$env:CHAT_ASSISTANT_VOICE_READ_TIMEOUT_MS="30000"
```

也可以在 `application.yml` 中查看这些配置项：

```yaml
chat-assistant:
  voice-transcribe-url: ${CHAT_ASSISTANT_VOICE_TRANSCRIBE_URL:}
  voice-transcribe-allowed-hosts: ${CHAT_ASSISTANT_VOICE_TRANSCRIBE_ALLOWED_HOSTS:localhost,127.0.0.1,::1}
  voice-connect-timeout-ms: ${CHAT_ASSISTANT_VOICE_CONNECT_TIMEOUT_MS:1500}
  voice-read-timeout-ms: ${CHAT_ASSISTANT_VOICE_READ_TIMEOUT_MS:15000}
  voice-max-bytes: ${CHAT_ASSISTANT_VOICE_MAX_BYTES:10485760}
```

如果接入第三方 ASR，需要同时配置服务地址和允许主机：

```powershell
$env:CHAT_ASSISTANT_VOICE_TRANSCRIBE_URL="https://asr.example.com/transcribe"
$env:CHAT_ASSISTANT_VOICE_TRANSCRIBE_ALLOWED_HOSTS="asr.example.com"
```

## ASR 服务返回格式

后端兼容以下常见 JSON 字段：

```json
{ "text": "查看今天待复核质检队列" }
```

```json
{ "transcript": "查看今天待复核质检队列" }
```

```json
{ "data": { "text": "查看今天待复核质检队列" } }
```

## 交互安全

语音识别结果只会填入助手输入框，不会自动发送。用户需要再次确认文本后手动发送，避免语音误识别直接触发“返工、放行、报废”等业务动作。

后端只允许访问 `http/https` ASR 地址，并要求主机命中 `voice-transcribe-allowed-hosts`。默认只放行本机 ASR，避免误配到 SSH key、本机文件、云元数据地址或公司内网地址。

## 浏览器录音格式

前端会按浏览器支持情况自动选择录音格式，优先级如下：

```text
audio/webm;codecs=opus -> audio/webm -> audio/mp4 -> audio/ogg;codecs=opus
```

ASR 服务建议至少支持 `webm`；如果需要兼容 Safari，可同时支持 `mp4`。

前端单次录音最长 60 秒，到达上限会自动停止并发起识别，避免忘记停止录音导致上传超大音频。
