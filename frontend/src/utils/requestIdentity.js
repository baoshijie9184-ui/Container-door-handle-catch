// Request correlation only; server-side command idempotency is a separate contract.
export function createUiRequestId(){
  if(globalThis.crypto?.randomUUID)return globalThis.crypto.randomUUID()
  if(!globalThis.crypto?.getRandomValues)throw new Error('浏览器无法生成请求编号，请更换浏览器或使用安全连接')
  const bytes=new Uint8Array(16)
  globalThis.crypto.getRandomValues(bytes)
  return 'ui-'+Array.from(bytes,value=>value.toString(16).padStart(2,'0')).join('')
}
