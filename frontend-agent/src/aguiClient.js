// 仅把正文事件呈现为回答，工具参数和状态事件不能混进正文。
export async function readAnswer(response, onChange, onCards) {
  if (!response.ok) throw new Error(response.status === 401 || response.status === 403 ? '请先登录检测系统' : `请求失败 (${response.status})`);
  if (!response.body) throw new Error('服务未返回流式响应');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let answer = '';
  let finished = false;
  function consume(frame) {
    const data = frame.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
    if (!data) return;
    const event = JSON.parse(data);
    if (event.type === 'RUN_ERROR') throw new Error(event.message || '智能助手执行失败');
    if (event.type === 'RUN_FINISHED') finished = true;
    if (event.type === 'CUSTOM' && event.name === 'doorhandle.business-cards.v1') onCards?.(event.value);
    if (event.type === 'TEXT_MESSAGE_CONTENT' && typeof event.delta === 'string') {
      answer += event.delta;
      onChange(answer);
    }
  }
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      buffer = buffer.replace(/\r\n/g, '\n');
      let boundary;
      while ((boundary = buffer.indexOf('\n\n')) >= 0) {
        consume(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
      }
      if (done) break;
    }
    if (buffer.trim()) consume(buffer);
    if (!finished) throw new Error('连接中断，请重新发送');
    if (!answer) throw new Error('助手未返回正文，请重试');
    return answer;
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}
