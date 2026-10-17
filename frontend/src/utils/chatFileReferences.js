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
 const previewBytes=data.limits?.previewBytes;
 return ids.map(id=>{const file=data.files.find(value=>value?.id===id);return file&&typeof file.name==='string'&&typeof file.contentType==='string'&&Number.isSafeInteger(file.bytes)&&file.bytes>=0?{id,name:file.name,contentType:file.contentType,bytes:file.bytes,...(Number.isInteger(previewBytes)&&previewBytes>0&&previewBytes<=1048576?{previewBytes}:{})}: {id,unavailable:true}});
}
export async function readReferencedFile(session,file,{base='',fetcher=globalThis.fetch,signal}={}){
 if(!session||file.unavailable||!splitFileReferences('@file:'+file.id).ids.includes(file.id))throw Error('资料引用无效');
 const response=await fetcher(base+'/api/agent/conversations/'+encodeURIComponent(session)+'/files/'+encodeURIComponent(file.id)+'/content',{credentials:'include',cache:'no-store',signal});
 if(!response.ok){const error=Error('资料已移除或当前账号无权读取');error.status=response.status;throw error}return response.blob();
}
export function filePreviewKind(file){return ['image/png','image/jpeg','image/webp'].includes(file.contentType)?'image':file.contentType==='application/pdf'?'pdf':'text'}

export async function boundedTextPreview(blob,limit=64000){
 const cap=Number.isSafeInteger(limit)&&limit>0?Math.min(limit,1048576):64000;
 const data=new Uint8Array(await blob.slice(0,cap+4).arrayBuffer());let end=Math.min(cap,data.length);
 if(end<data.length)while(end>0&&(data[end]&0xc0)===0x80)end--;
 let text;try{text=new TextDecoder('utf-8',{fatal:true}).decode(data.subarray(0,end))}catch{throw Error('文本编码无效，请下载原文件核对')}
 return text+(blob.size>end?'\n[内容已按预览上限截断，请下载查看完整文件]':'');
}

// PDF 只显示服务端栅格化页面，不在浏览器加载原 PDF 的脚本、链接或嵌入文件。
export async function readFilePreview(session,file,{base='',fetcher=globalThis.fetch,signal,limit=file.previewBytes??64000,page=1}={}){
 const kind=filePreviewKind(file);
 if(kind!=='pdf'){const blob=await readReferencedFile(session,file,{base,fetcher,signal});return {kind,blob,text:kind==='text'?await boundedTextPreview(blob,limit):''}}
 if(!session||file.unavailable||!splitFileReferences('@file:'+file.id).ids.includes(file.id)||!Number.isInteger(page)||page<1||page>100)throw Error('PDF 引用或页码无效');
 const response=await fetcher(base+'/api/agent/conversations/'+encodeURIComponent(session)+'/files/'+file.id+'/preview?page='+page,{credentials:'include',cache:'no-store',signal});
 if(!response.ok){const error=Error(response.status===429?'文件解析繁忙，请稍后重试':response.status===413?'PDF 超出预览限制，请下载核对':response.status===415?'PDF 页面无法预览，请下载核对':'资料已移除或当前账号无权读取');error.status=response.status;throw error}
 const pages=Number(response.headers.get('X-PDF-Pages')),current=Number(response.headers.get('X-PDF-Page'));
 if(response.headers.get('Content-Type')?.split(';')[0]!=='image/png'||!Number.isInteger(pages)||pages<1||pages>100||current!==page||current>pages)throw Error('PDF 预览响应无效');
 return {kind,blob:new Blob([await response.blob()],{type:'image/png'}),page:current,pages};
}
