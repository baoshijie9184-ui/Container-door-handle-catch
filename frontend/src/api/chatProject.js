import request from './request'

export const fetchProjectList = () => request.get('/api/chat-projects')

export const createProject = (data) => request.post('/api/chat-projects', data)

export const updateProject = (projectId, data) => request.put(`/api/chat-projects/${projectId}`, data)

export const deleteProject = (projectId) => request.delete(`/api/chat-projects/${projectId}`)

export const moveSessionToProject = (sessionId, projectId) => request.put(`/api/chat-projects/sessions/${sessionId}/move/${projectId}`)

export const removeSessionFromProject = (sessionId) => request.put(`/api/chat-projects/sessions/${sessionId}/remove`)
