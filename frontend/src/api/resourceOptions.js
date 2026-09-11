import request from './request'

export const fetchEmployeesForSelect = () => request.get('/api/employees', { params: { size: 200 } })

export const fetchDevicesForSelect = () => request.get('/api/devices', { params: { size: 200 } })
