const test=require('node:test'),assert=require('node:assert/strict')
const {readFrontendFile}=require('./helpers/project-source.cjs')
const {createHash,webcrypto}=require('node:crypto')
const utility=import(`data:text/javascript;base64,${Buffer.from(readFrontendFile('src','utils','researchEvidence.js')).toString('base64')}`)
const id='src-00000000-0000-0000-0000-000000000001'
const source=(extra={})=>({sourceId:id,runId:'run',callId:'fetch-1',requestedUrl:'https://example.com/article',queryOmitted:false,urlRedacted:false,title:'Public title',excerpt:'<img src=x onerror=alert(1)>Untrusted text',contentSha256:'a'.repeat(64),textChars:100,startIndex:0,maxLength:5000,fetchedAt:'2026-10-16T12:00:00',expiresAt:'2026-11-15T12:00:00',...extra})
const evidence=(extra={})=>({runId:'run',enabled:true,sources:[source()],citations:[],answerSha256:null,answerRecorded:false,unresolvedCitationCount:0,expiredSourceCount:0,...extra})
test('export rate errors show only bounded retry seconds and never server text',async()=>{
 const {researchExportError}=await utility
 assert.match(researchExportError({response:{status:429,headers:{'retry-after':'37'}}}),/约 37 秒/)
 for(const value of ['0','3601','-1','1.5','1e2','<img src=x>','PRIVATE_SERVER_TEXT',null]) {
   const message=researchExportError({response:{status:429,headers:{'retry-after':value},data:'PRIVATE_SERVER_TEXT'}})
   assert.match(message,/稍后重新确认/);assert.doesNotMatch(message,/PRIVATE|<img/)
 }
 assert.match(researchExportError({response:{status:503,headers:{'retry-after':'37'}}}),/结果未确认/)
 assert.match(researchExportError(new Error('PRIVATE_SERVER_TEXT')),/不会自动重试/)
})

test('export capability requires an explicitly enabled current source view',async()=>{
 const {normalizeResearchEvidence}=await utility
 assert.equal(normalizeResearchEvidence(evidence(),'run').exportEnabled,false)
 assert.equal(normalizeResearchEvidence(evidence({exportEnabled:'true'}),'run').exportEnabled,false)
 assert.equal(normalizeResearchEvidence(evidence({exportEnabled:true}),'run').exportEnabled,true)
})

const exportResponse=(extra={},headers={})=>{
 const text=JSON.stringify({version:1,exportId:'00000000-0000-0000-0000-000000000001',exportedAt:'2026-10-16T12:00:00Z',evidence:evidence(),...extra})
 return {data:new TextEncoder().encode(text).buffer,headers:{'x-export-id':'00000000-0000-0000-0000-000000000001','x-content-sha256':createHash('sha256').update(text).digest('hex'),...headers}}
}
test('download validates exact UTF8 bytes hash schema and selected run before saving',async()=>{
 const {validateResearchDownload}=await utility
 const response=exportResponse(),file=await validateResearchDownload(response,'run',webcrypto.subtle)
 assert.equal(file.filename,'research-00000000-0000-0000-0000-000000000001.json');assert.equal(file.bytes,response.data)
 await assert.rejects(()=>validateResearchDownload(response,'other',webcrypto.subtle))
 await assert.rejects(()=>validateResearchDownload(exportResponse({}, {'x-content-sha256':'b'.repeat(64)}),'run',webcrypto.subtle),/INVALID_EXPORT_HASH/)
})
test('bad export IDs versions evidence size and missing integrity support cannot produce a download',async()=>{
 const {validateResearchDownload}=await utility
 for(const response of [exportResponse({exportId:'other'}),exportResponse({version:2}),exportResponse({evidence:evidence({enabled:false})}),exportResponse({}, {'x-export-id':'../../secret'}),{data:new ArrayBuffer(524289)}, {data:new TextEncoder().encode('invalid-json').buffer}])
   await assert.rejects(()=>validateResearchDownload(response,'run',webcrypto.subtle))
 await assert.rejects(()=>validateResearchDownload(exportResponse(),'run',null),/INVALID_EXPORT/)
})

test('evidence scope must match every source and the requested run',async()=>{
 const {normalizeResearchEvidence}=await utility
 assert.throws(()=>normalizeResearchEvidence(evidence(),'other'))
 assert.throws(()=>normalizeResearchEvidence(evidence({sources:[source({runId:'other'})]}),'run'))
 assert.throws(()=>normalizeResearchEvidence(evidence({sources:[source(),source()]}),'run'))
})
test('unsafe addresses are never clickable and stripped targets are not presented as exact URLs',async()=>{
 const {researchUrl,normalizeResearchEvidence}=await utility
 for(const value of ['javascript:alert(1)','http://user:pass@example.com','https://example.com/?token=secret','http://127.0.0.1/','http://0x7f000001/','file:///secret','http://169.254.169.254/'])assert.equal(researchUrl(value),null)
 const result=normalizeResearchEvidence(evidence({sources:[source({queryOmitted:true,urlRedacted:true})]}),'run')
 assert.equal(result.sources[0].href,null)
 assert.equal(normalizeResearchEvidence(evidence(),'run').sources[0].href,'https://example.com/article')
})
test('metadata keeps untrusted excerpt as text and removes undeclared fields',async()=>{
 const {normalizeResearchEvidence}=await utility
 const value=normalizeResearchEvidence(evidence({sources:[source({rawHtml:'SECRET',apiKey:'SECRET'})]}),'run')
 assert.equal(value.sources[0].excerpt,'<img src=x onerror=alert(1)>Untrusted text');assert.equal(value.sources[0].apiKey,undefined);assert.equal(value.sources[0].rawHtml,undefined)
})
test('citation matching requires an exact SHA256 and exact UTF16 ranges including supplementary characters',async()=>{
 const {normalizeResearchEvidence,citationContext}=await utility
 const marker=`[source:${id}]`,answer=`文字 🚀 引用 ${marker}`
 const record=normalizeResearchEvidence(evidence({answerRecorded:true,answerSha256:createHash('sha256').update(answer).digest('hex'),citations:[{sourceId:id,start:answer.indexOf(marker),end:answer.length}]}),'run')
 assert.equal(await citationContext(record,['different'],webcrypto.subtle),null)
 const context=await citationContext(record,['different',answer],webcrypto.subtle)
 assert.equal(context.segments[1].sourceId,id);assert.equal(context.segments.map(s=>s.text).join(''),answer)
 await assert.rejects(()=>citationContext({...record,citations:[{sourceId:id,start:1,end:10}]},[answer],webcrypto.subtle),/INVALID_CITATION_POSITION/)
 assert.equal(await citationContext(record,[answer],null),null)
})
test('overlapping references oversized excerpts and inconsistent disabled records fail closed',async()=>{
 const {normalizeResearchEvidence}=await utility
 assert.throws(()=>normalizeResearchEvidence(evidence({sources:[source({excerpt:'x'.repeat(1001)})]}),'run'))
 assert.throws(()=>normalizeResearchEvidence(evidence({enabled:false}),'run'))
 assert.throws(()=>normalizeResearchEvidence(evidence({answerRecorded:true,answerSha256:'a'.repeat(64),citations:[{sourceId:id,start:5,end:9},{sourceId:id,start:8,end:12}]}),'run'))
})
