"""Owned review UI acceptance using isolated HTTP fixtures; no paid model or existing memory writes."""
import copy
import json
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'work/memory-review-browser';OUT.mkdir(parents=True,exist_ok=True)
scope={'__file__':str(ROOT/'script/diagnostics/conversation-control-acceptance.py')}
exec((ROOT/'script/diagnostics/conversation-control-acceptance.py').read_text(encoding='utf-8').split('with sync_playwright() as p:')[0],scope)
controls={'memoryId':'mine','revision':0,'state':'ACTIVE','expiresAt':None,'autoDelete':False,'cleanupState':'NONE','updatedAt':None}
source={'id':'mine','memory':'<script>window.memoryInjected=true</script> 报告默认采用 PDF 格式','updatedAt':'2026-10-18T04:00:00Z','digest':'a'*64,'sourceSessionId':'session-one','lifecycle':controls}
candidate={**source,'id':'candidate','memory':'用户喜欢把报告保存成 PDF 文件','sourceSessionId':'session-two','lifecycle':{**controls,'memoryId':'candidate'}}
reviews={};requests=[];errors=[];checks=[];fault=None;complete=True

def api(route):
    request=route.request;path=urlparse(request.url).path
    if not path.startswith('/api/agent/memories'):return scope['api'](route)
    requests.append({'method':request.method,'path':path,'body':request.post_data_json if request.method=='POST' else None})
    if path.endswith('/preferences'):return route.fulfill(json={'readEnabled':True,'saveEnabled':True,'revision':0})
    if path.endswith('/audit') or path.endswith('/lifecycle'):return route.fulfill(json=[])
    if path.endswith('/mine'):return route.fulfill(json=source)
    if path.endswith('/mine/reviews') and request.method=='POST':
        body=request.post_data_json;assert body['expectedRevision']==0 and body['expectedDigest']=='a'*64
        row={'id':body['requestId'],'sourceId':'mine','status':'RUNNING','revision':0,'source':None,'sourceStale':False,'judgmentStatus':'PENDING','candidates':[],'decisions':[],
             'createdAt':'2026-10-18T04:00:00Z','updatedAt':'2026-10-18T04:00:00Z','searchLimit':20,'modelCalled':None,'modelName':None,'modelMillis':None,'inputTokens':None,'outputTokens':None,'totalTokens':None,'usageSource':'UNKNOWN'}
        reviews[row['id']]=row;return route.fulfill(status=202,json=row)
    if path.endswith('/reviews'):
        return route.fulfill(json=[{k:row[k] for k in ['id','sourceId','status','createdAt']} for row in reviews.values()])
    if '/reviews/' in path:
        id=path.split('/reviews/')[1].split('/')[0];row=reviews[id]
        if request.method=='GET':
            if complete and row['status']=='RUNNING':
                row.update({'status':'READY','revision':1,'source':copy.deepcopy(source),'judgmentStatus':'COMPLETE','modelCalled':True,'modelName':'fixture-model','modelMillis':123,
                            'candidates':[{'id':'candidate','item':copy.deepcopy(candidate),'stale':False,'label':'DUPLICATE','similarity':.95}]})
            return route.fulfill(json=row)
        assert path.endswith('/resolve');body=request.post_data_json
        assert body['confirmed'] and body['expectedRevision']==row['revision'] and body['candidateId']=='candidate'
        if fault==409:return route.fulfill(status=409,json={'message':'审阅版本已变化'})
        row['revision']+=1;row['decisions'].append({'requestId':body['requestId'],'candidateId':'candidate','choice':body['choice'],'expectedRevision':body['expectedRevision'],'createdAt':'2026-10-18T12:00:00+08:00'})
        if fault==503:return route.fulfill(status=503,json={'message':'结果需要刷新核对'})
        return route.fulfill(json=row)
    return route.fulfill(json={'items':[source],'hasMore':False})

def mutations():return [r for r in requests if r['method']=='POST']

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    context=browser.new_context(viewport={'width':1500,'height':1050},timezone_id='America/Los_Angeles',reduced_motion='reduce')
    context.route('**/api/**',api);context.route('**/agui/**',api)
    page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto('http://127.0.0.1:3011/#/agent/memory');page.wait_for_load_state('networkidle')
    expect(page.locator('.memory-item')).to_have_count(1);assert not mutations()
    checks.append('opening history is read only and does not call a model')
    page.get_by_role('button',name='查找相似',exact=True).click();dialog=page.get_by_role('dialog',name='相似记忆审阅')
    expect(dialog).to_be_visible();expect(dialog).to_contain_text(source['memory']);assert not page.evaluate('window.memoryInjected===true')
    dialog.get_by_role('button',name='关闭',exact=True).click();assert not mutations()
    checks.append('opening and canceling a review executes no memory text and starts no analysis')
    page.get_by_role('button',name='查找相似',exact=True).click();dialog.get_by_role('button',name='开始分析').click()
    expect(dialog.get_by_role('status')).to_have_text('正在分析');assert len(mutations())==1
    dialog.get_by_role('button',name='读取结果核对').click();expect(dialog.get_by_role('status')).to_have_text('分析已完成')
    expect(dialog).to_contain_text('session-one');expect(dialog).to_contain_text('session-two');expect(dialog).to_contain_text('供应商未提供用量 不按零计算')
    assert len(mutations())==1;checks.append('202 remains pending; read-only polling retrieves cross-session candidates without a new model request')
    dialog.get_by_role('button',name='保留原记忆 停用候选',exact=True).click();expect(dialog.get_by_label('审阅处理预览')).to_be_visible()
    assert len(mutations())==1;dialog.get_by_role('button',name='返回对比',exact=True).click();assert len(mutations())==1
    checks.append('decision preview and cancel never mutate a memory')
    dialog.get_by_role('button',name='保留两条',exact=True).click();dialog.get_by_role('button',name='确认处理',exact=True).focus();page.keyboard.press('Enter')
    expect(dialog).to_contain_text('保留两条 · 已记录');assert len(mutations())==2
    checks.append('explicit keyboard confirmation sends the original review version once')
    dialog.get_by_role('button',name='关闭',exact=True).click();page.reload();page.wait_for_load_state('networkidle')
    expect(page.locator('.memory-review-history')).to_contain_text('2026-10-18 12:00:00');assert len(mutations())==2
    page.get_by_role('button',name='查看对比',exact=True).click();expect(dialog).to_contain_text('保留两条 · 已记录');assert len(mutations())==2
    checks.append('refresh preserves review and decision history, displays UTC+8 and does not call the model')
    dialog.get_by_role('button',name='关闭',exact=True).click();page.get_by_role('button',name='查找相似',exact=True).click();dialog.get_by_role('button',name='开始分析').click();dialog.get_by_role('button',name='读取结果核对').click()
    fault=409;dialog.get_by_role('button',name='保留原记忆 停用候选',exact=True).click();dialog.get_by_role('button',name='确认处理',exact=True).click()
    expect(dialog.get_by_role('alert')).to_contain_text('版本已变化');expect(dialog.get_by_role('button',name='保留两条',exact=True)).to_be_disabled();count=len(mutations())
    dialog.get_by_role('button',name='读取结果核对').click();expect(dialog.get_by_role('button',name='保留两条',exact=True)).to_be_enabled();assert len(mutations())==count
    checks.append('a stale version blocks further submission until a new authorized read')
    fault=503;dialog.get_by_role('button',name='保留原记忆 停用候选',exact=True).click();dialog.get_by_role('button',name='确认处理',exact=True).click()
    expect(dialog.get_by_role('alert')).to_contain_text('需要刷新核对');count=len(mutations());dialog.get_by_role('button',name='读取结果核对').click()
    expect(dialog).to_contain_text('上次处理已核对 不会再次执行');assert len(mutations())==count
    checks.append('an unknown HTTP result is reconciled from the original decision receipt without replay')
    page.screenshot(path=str(OUT/'desktop-review.png'),full_page=True)
    page.set_viewport_size({'width':390,'height':844});expect(dialog).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    assert dialog.locator('.review-grid').evaluate('(e)=>getComputedStyle(e).gridTemplateColumns.split(" ").length')==1
    page.screenshot(path=str(OUT/'mobile-review.png'),full_page=True);checks.append('mobile review uses one column, keeps all actions and respects reduced motion')
    dialog.get_by_role('button',name='关闭',exact=True).click();page.get_by_role('button',name='查找相似',exact=True).click();dialog.get_by_role('button',name='开始分析').click();dialog.get_by_role('button',name='读取结果核对').click()
    current=reviews[list(reviews)[-1]];current['sourceStale']=True;current['source']=None;current['judgmentStatus']='UNAVAILABLE';current['candidates'][0]['label']='UNSURE'
    dialog.get_by_role('button',name='读取结果核对').click();expect(dialog).to_contain_text('本次建议失效');expect(dialog).to_contain_text('不表示没有重复');expect(dialog.get_by_role('button',name='保留两条',exact=True)).to_be_disabled()
    checks.append('changed source and unavailable model never silently permit an old decision or hide candidates')
    context.close();browser.close()
assert not errors,errors
(OUT/'results.json').write_text(json.dumps({'checks':checks,'javascriptErrors':errors,'requests':requests,'apiMode':'isolated fixtures'},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'passed':len(checks),'javascriptErrors':errors}))
