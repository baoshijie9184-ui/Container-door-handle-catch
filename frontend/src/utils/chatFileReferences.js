// Only explicit user-message references become interactive; tool/model text remains ordinary text.
const reference=/@file:([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})(?![a-z0-9_-])/gi;
export function splitFileReferences(content,role='user'){
 const value=typeof content==='string'?content:'';if(role!=='user')return {text:value,ids:[]};
 const ids=[];const text=value.replace(reference,(match,id)=>{id=id.toLowerCase();if(!ids.includes(id)){if(ids.length>=8)return match;ids.push(id)}return ''});
 return {text:ids.length?text.trim():value,ids};
}
export async function referencedFiles(session,ids,{base='',fetcher=globalThis.fetch,signal}={}){
 if(!session||!ids.length)return [];
 const response=await fetcher(base+'/api/agent/conversations/'+encodeURIComponent(session)+'/workbench',{credentials:'include',cache:'no-store',signal});
 if(!response.ok)throw Error('资料不可用，请核对当前账号权限或刷新重试');
 const data=await response.json();if(!Array.isArray(data.files))throw Error('资料信息暂不可读取');
 return ids.map(id=>{const file=data.files.find(value=>value?.id===id);return file&&typeof file.name==='string'&&typeof file.contentType==='string'&&Number.isSafeInteger(file.bytes)&&file.bytes>=0?{id,name:file.name,contentType:file.contentType,bytes:file.bytes}: {id,unavailable:true}});
}
export async function readReferencedFile(session,file,{base='',fetcher=globalThis.fetch,signal}={}){
 if(!session||file.unavailable||!splitFileReferences('@file:'+file.id).ids.includes(file.id))throw Error('资料引用无效');
 const response=await fetcher(base+'/api/agent/conversations/'+encodeURIComponent(session)+'/files/'+encodeURIComponent(file.id)+'/content',{credentials:'include',cache:'no-store',signal});
 if(!response.ok){const error=Error('资料已移除或当前账号无权读取');error.status=response.status;throw error}return response.blob();
}
export function filePreviewKind(file){return ['image/png','image/jpeg','image/webp'].includes(file.contentType)?'image':file.contentType==='application/pdf'?'pdf':'text'}
