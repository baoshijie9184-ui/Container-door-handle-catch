import axios from 'axios'

axios.defaults.baseURL = import.meta.env.VITE_API_URL || ''
axios.defaults.timeout = 15000
axios.defaults.withCredentials = true

axios.interceptors.request.use(
  config => {
    if (config.url && !config.url.startsWith('/')) {
      config.url = '/' + config.url
    }

    if (config.method && !['get','head','options'].includes(config.method.toLowerCase())) {
      config.headers = config.headers || {}
      if (!config.headers['X-Request-ID']) config.headers['X-Request-ID'] = config.data?.requestId || crypto.randomUUID()
    }
    return config
  },
  error => Promise.reject(error)
)

export default axios
