import axios from 'axios'

axios.defaults.baseURL = import.meta.env.VITE_API_URL || ''
axios.defaults.timeout = 15000
axios.defaults.withCredentials = true

axios.interceptors.request.use(
  config => {
    if (config.url && !config.url.startsWith('/')) {
      config.url = '/' + config.url
    }

    return config
  },
  error => Promise.reject(error)
)

export default axios
