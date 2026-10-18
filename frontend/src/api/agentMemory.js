const BASE='/api/agent/memories'
async function invoke(path='',options={}) {
  const response=await fetch(BASE+path,{credentials:'include',cache:'no-store',...options,headers:{'Content-Type':'application/json',...options.headers}})
  const body=await response.json().catch(()=>({}))
  if(!response.ok||body.code&&body.code!==200){const error=new Error(body.message||'个人记忆暂不可用 请稍后重试');error.status=response.status;throw error}
  return body
}
export const memoryPreferences=()=>invoke('/preferences')
export const memoryList=(limit=50,offset=0)=>invoke('?'+new URLSearchParams({limit,...(offset?{offset}:{})}))
export const personalMemory=id=>invoke('/'+encodeURIComponent(id))
export const memoryAudit=()=>invoke('/audit')
export const verifyMemoryExtraction=id=>invoke('/operations/'+encodeURIComponent(id)+'/verify',{method:'POST',headers:{'X-Agent-Action':'memory-verify'}})
export const changeMemoryPreferences=body=>invoke('/preferences',{method:'PUT',body:JSON.stringify(body)})
export const deletePersonalMemory=(id,body)=>invoke('/'+encodeURIComponent(id)+'/delete',{method:'POST',body:JSON.stringify(body)})
export const updatePersonalMemory=(id,body)=>invoke('/'+encodeURIComponent(id)+'/update',{method:'POST',body:JSON.stringify(body)})
