const test=require('node:test'),assert=require('node:assert/strict');
const {readFrontendFile}=require('./helpers/project-source.cjs');
const mod=import('data:text/javascript;base64,'+Buffer.from(readFrontendFile('src','utils','chatFileReferences.js')).toString('base64'));
const id='01234567-0123-4567-89ab-0123456789ab';
test('only bounded valid user file references become cards; model text and malformed references stay text',async()=>{
 const {splitFileReferences,filePreviewKind}=await mod;
 assert.deepEqual(splitFileReferences('读取附件\n@file:'+id+' @file:'+id),{text:'读取附件',ids:[id]});
 assert.deepEqual(splitFileReferences('@file:'+id,'assistant'),{text:'@file:'+id,ids:[]});
 assert.deepEqual(splitFileReferences('@file:'+id+'-escape'),{text:'@file:'+id+'-escape',ids:[]});
 assert.equal(splitFileReferences(Array.from({length:10},(_,n)=>'@file:'+id.slice(0,-2)+String(n).padStart(2,'0')).join(' ')).ids.length,8);
 assert.equal(filePreviewKind({contentType:'image/svg+xml'}),'text');assert.equal(filePreviewKind({contentType:'text/html'}),'text');assert.equal(filePreviewKind({contentType:'application/pdf'}),'pdf');
});
test('metadata and each file read use private session endpoints; access denial never exposes a download',async()=>{
 const {referencedFiles,readReferencedFile}=await mod;const calls=[];const file={id,name:'<script>.md',contentType:'text/plain',bytes:4};
 const fetcher=async(path,options)=>{calls.push({path,options});return {ok:true,json:async()=>({files:[file]}),blob:async()=>new Blob(['test'])}};
 assert.deepEqual(await referencedFiles('session/a',[id],{fetcher}),[file]);assert.equal(await (await readReferencedFile('session/a',file,{fetcher})).text(),'test');
 assert.ok(calls.every(c=>c.options.credentials==='include'&&c.options.cache==='no-store'&&c.path.includes('session%2Fa')));
 assert.equal((await referencedFiles('s',[id],{fetcher:async()=>({ok:true,json:async()=>({files:[]})})}))[0].unavailable,true);
 await assert.rejects(readReferencedFile('s',file,{fetcher:async()=>({ok:false})}),/无权/);
 await assert.rejects(readReferencedFile('s',{...file,id:'../../secret'},{fetcher}),/无效/);assert.equal(calls.length,2);
});
test('UTF-8 preview limits are explicit and never split multi-byte characters',async()=>{
 const {boundedTextPreview}=await mod;const blob=new Blob(['A中𠀀B']);
 assert.equal(await boundedTextPreview(blob,3),'A\n[内容已按预览上限截断，请下载查看完整文件]');
 assert.equal(await boundedTextPreview(blob,7),'A中\n[内容已按预览上限截断，请下载查看完整文件]');
 assert.equal(await boundedTextPreview(blob,9),'A中𠀀B');
 await assert.rejects(boundedTextPreview(new Blob([new Uint8Array([0xff])])),/编码无效/);
});
test('PDF previews request authorized raster pages and reject malformed metadata or access revocation',async()=>{
 const {readFilePreview}=await mod;const file={id,name:'report.pdf',contentType:'application/pdf'};let request;
 const fetcher=async(url,options)=>{request={url,options};return new Response(new Uint8Array([137,80,78,71]),{headers:{'Content-Type':'image/png','X-PDF-Page':'2','X-PDF-Pages':'3'}})};
 const preview=await readFilePreview('s/a',file,{fetcher,page:2});assert.equal(preview.page,2);assert.equal(preview.pages,3);assert.equal(preview.blob.type,'image/png');assert.match(request.url,/s%2Fa\/files\/.*\/preview\?page=2$/);assert.equal(request.options.credentials,'include');assert.equal(request.options.cache,'no-store');
 await assert.rejects(readFilePreview('s',file,{fetcher:async()=>new Response('',{headers:{'Content-Type':'text/html'}})}),/响应无效/);
 await assert.rejects(readFilePreview('s',file,{fetcher:async()=>new Response('',{status:403})}),error=>error.status===403);
 await assert.rejects(readFilePreview('s',file,{fetcher,page:101}),/页码无效/);
});
