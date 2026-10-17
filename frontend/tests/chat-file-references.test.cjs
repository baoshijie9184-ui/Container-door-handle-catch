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
