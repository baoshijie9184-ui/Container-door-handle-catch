import axios from 'axios'
import { accountSession, accountSignal, contextError } from '../utils/accountContext'
import { createUiRequestId } from '../utils/requestIdentity'
import { decimalVersion } from '../utils/mutationVersion'

axios.defaults.baseURL = import.meta.env.VITE_API_URL || ''
axios.defaults.timeout = 15000
axios.defaults.withCredentials = true
const authEndpoint = url => /^\/api\/auth\/(check|login|logout|refresh)(?:\?|$)/.test(url || '')
axios.interceptors.request.use(config => {
  if (config.url && !config.url.startsWith('/')) config.url = '/' + config.url
  config._accountAuth = authEndpoint(config.url)
  if (!config._accountAuth) {
    if (!accountSession.state.authenticated) throw contextError()
    // Preserve a replay's original identity instead of rebinding it to another account.
    if (config._accountStamp) accountSession.assert(config._accountStamp)
    else config._accountStamp = accountSession.stamp()
    config.signal = accountSignal(config.signal, config._accountStamp.signal)
  }
  if (config.method && !['get', 'head', 'options'].includes(config.method.toLowerCase())) {
    if (!config._accountAuth && !config._accountStamp?.accountContext) throw contextError('当前服务器尚未提供安全账号上下文，请更新登录身份后再修改')
    config.headers = config.headers || {}
    const context = config._accountStamp?.accountContext || accountSession.state.accountContext
    if (context && !config.headers['X-Account-Context']) config.headers['X-Account-Context'] = context
    if (!config.headers['X-Request-ID']) config.headers['X-Request-ID'] = config.data?.requestId || createUiRequestId()
    const version = decimalVersion(config.data?.expectedVersion)
    if (version !== null) {
      config.headers['X-Expected-Version'] ??= version
      config.headers['If-Match'] ??= '"' + version + '"'
    }
  }
  return config
})
axios.interceptors.response.use(response => {
  if (!response.config._accountAuth) accountSession.assert(response.config._accountStamp)
  return response
}, error => {
  const config = error.config
  if (config && !config._accountAuth) {
    if (!accountSession.current(config._accountStamp)) return Promise.reject(contextError())
    if (error.response?.data?.code === 'ACCOUNT_CONTEXT_CHANGED') {
      accountSession.clear('登录账号已变化，旧页面已暂停提交')
      globalThis.dispatchEvent?.(new Event('doorhandle-account-recheck'))
      return Promise.reject(contextError())
    }
  }
  return Promise.reject(error)
})
const dataMethods=new Set(['post','put','patch'])
function bindRequest(stamp) {
  const captured=config=>({...config,_accountStamp:config?._accountStamp || stamp || accountSession.stamp()})
  const send=(url,config)=>typeof url==='string'?axios(url,captured(config)):axios(captured(url))
  for(const method of ['get','head','options','delete','post','put','patch'])send[method]=(url,data,config)=>
    dataMethods.has(method)?axios[method](url,data,captured(config)):axios[method](url,captured(data))
  send.request=config=>axios.request(captured(config))
  send.assert=()=>accountSession.assert(stamp || accountSession.stamp())
  send.interceptors=axios.interceptors;send.defaults=axios.defaults
  return send
}
// The default captures synchronously when called, before Axios schedules its interceptors.
// A component with confirmations or other awaits can bind its complete lifetime explicitly.
export const captureAccountRequest = () => bindRequest(accountSession.stamp())
export default bindRequest()
