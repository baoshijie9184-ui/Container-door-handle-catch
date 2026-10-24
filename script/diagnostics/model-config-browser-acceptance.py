"""Browser contract checks only. Production suppliers and credentials are never used."""
import copy
import json
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

OUT=Path(__file__).resolve().parents[2]/'work/model-config-browser'
OUT.mkdir(parents=True,exist_ok=True)
checks=[]
errors=[]
document={'models':[{'id':'dashscope:fixture','enabled':True},{'id':'deepseek:fixture','enabled':True}],
          'defaultModel':'dashscope:fixture','fallbackModels':['deepseek:fixture'],'fallbackEnabled':True,
          'timeoutMs':60000,'firstTokenTimeoutMs':15000,'maxOutputTokens':2048,'memoryModel':'dashscope:fixture'}

def reply(route,body,status=200):route.fulfill(status=status,content_type='application/json',body=json.dumps(body,ensure_ascii=False))

with sync_playwright() as playwright:
    browser=playwright.chromium.launch(headless=True)
    for label,viewport in [('desktop',{'width':1440,'height':1100}),('mobile',{'width':390,'height':844})]:
        state={'activeRevision':1,'versions':[{'revision':1,'baseRevision':0,'status':'PUBLISHED','document':copy.deepcopy(document),'credentials':{'dashscope':True,'deepseek':True,'openai':False},'memoryState':'ENVIRONMENT','jsonProbes':[]}]}
        writes=[]
        failure={'enabled':False,'body':None}
        role={'value':'SUPERVISOR'}
        def api(route):
            path=urlparse(route.request.url).path
            if not path.startswith('/api/'):return route.continue_()
            if path=='/api/auth/check':return reply(route,{'code':200,'data':{'username':'supervisor.demo','role':role['value']}})
            if path=='/api/agent/model-config' and route.request.method=='GET':return reply(route,failure['body'] if failure['enabled'] else state)
            if path.startswith('/api/agent/model-config'):
                body=route.request.post_data_json
                assert route.request.headers.get('x-model-action')=='update'
                assert body.get('requestId') and route.request.headers.get('x-request-id')==body['requestId']
                writes.append((path,body))
                if path.endswith('/drafts'):
                    assert body['baseRevision']==state['activeRevision']
                    version={'revision':len(state['versions'])+1,'baseRevision':body['baseRevision'],'status':'DRAFT','document':body['document'],
                             'credentials':state['versions'][0]['credentials'],'memoryState':'PENDING','jsonProbes':[]}
                    state['versions'].insert(0,version)
                    return reply(route,version)
                revision=int(path.split('/')[-2])
                version=next(v for v in state['versions'] if v['revision']==revision)
                if path.endswith('/validate'):version['status']='VALIDATED'
                if path.endswith('/publish'):
                    for old in state['versions']:
                        if old['revision']==state['activeRevision']:old['status']='RETIRED'
                    version['status']='PUBLISHED';version['memoryState']='APPLIED';state['activeRevision']=revision
                return reply(route,version)
            return reply(route,{'code':200,'data':[]})
        context=browser.new_context(viewport=viewport,reduced_motion='reduce')
        context.route('**/api/**',api)
        page=context.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto('http://127.0.0.1:3011/#/agent/model-config');page.wait_for_load_state('networkidle')
        expect(page.get_by_role('heading',name='Agent 模型配置')).to_be_visible()
        expect(page.get_by_text('生效版本',exact=False).first).to_be_visible()
        expect(page.get_by_label('百炼 新 API Key',exact=True)).to_have_attribute('type','password')
        page.get_by_label('百炼 新 API Key',exact=True).fill('fixture-browser-new-key')
        page.get_by_label('新模型名称',exact=True).fill('added-fixture')
        page.get_by_role('button',name='加入列表',exact=True).click()
        expect(page.get_by_label('启用 dashscope:added-fixture',exact=True)).to_be_visible()
        page.get_by_role('button',name='保存为新草稿',exact=True).click()
        expect(page.get_by_text('草稿已保存，校验并确认发布后生效',exact=True)).to_be_visible()
        assert len(writes)==1 and writes[0][1]['apiKeys']=={'dashscope':'fixture-browser-new-key'}
        assert page.evaluate("JSON.stringify([localStorage,sessionStorage])").find('fixture-browser-new-key')<0
        assert 'fixture-browser-new-key' not in page.locator('body').inner_text()
        checks.append(label+' versioned draft with write-only in-memory credential')
        page.get_by_role('button',name='校验草稿',exact=True).click()
        expect(page.get_by_role('button',name='发布此版本',exact=True)).to_be_visible()
        assert state['activeRevision']==1
        page.get_by_role('button',name='发布此版本',exact=True).click()
        dialog=page.get_by_role('dialog')
        expect(dialog).to_contain_text('发布 V2')
        dialog.get_by_role('button',name='确定',exact=True).click()
        expect(page.get_by_text('模型配置已发布，请核对记忆配置应用状态',exact=True)).to_be_visible()
        assert state['activeRevision']==2 and len(writes)==3
        checks.append(label+' validation plus explicit publish confirmation')
        page.get_by_role('button',name='编辑生效版本',exact=True).click()
        expect(page.get_by_label('百炼 新 API Key',exact=True)).to_have_value('')
        page.get_by_role('button',name='核对版本状态',exact=True).click()
        expect(page.get_by_text('已核对服务器配置状态，未重复提交操作',exact=True)).to_be_visible()
        assert len(writes)==3
        page.reload();page.wait_for_load_state('networkidle')
        expect(page.get_by_label('百炼 新 API Key',exact=True)).to_have_value('')
        checks.append(label+' read-only reconciliation and refresh do not replay mutations or retain keys')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.keyboard.press('Tab');assert page.evaluate('document.activeElement.tagName')!='BODY'
        assert page.locator('.model-config-page').evaluate("el=>getComputedStyle(el).animationName")=='none'
        page.screenshot(path=str(OUT/(label+'.png')),full_page=True)
        checks.append(label+' keyboard focus, no horizontal overflow and reduced motion')
        original_writes=len(writes)
        for invalid in [{'code':404,'message':'请求的资源不存在'},None,{},
                        {'activeRevision':1,'versions':[{'revision':1,'document':{}}]},
                        '<html>gateway response</html>']:
            failure.update(enabled=True,body=invalid)
            page.get_by_role('button',name='核对版本状态',exact=True).click()
            expect(page.get_by_role('alert').filter(has_text='模型管理暂不可用')).to_be_visible()
            expect(page.get_by_label('百炼 新 API Key',exact=True)).not_to_be_visible()
            assert page.locator('.global-error-bar').count()==0
            assert len(writes)==original_writes
        failure['enabled']=False
        page.get_by_role('button',name='核对版本状态',exact=True).click()
        expect(page.get_by_label('百炼 新 API Key',exact=True)).to_have_value('')
        assert len(writes)==original_writes
        checks.append(label+' malformed HTTP 200, absent route and broken nested DTO fail closed without render exception')
        checks.append(label+' read-only refresh recovers after unavailability without replaying mutations')
        role['value']='INSPECTOR';page.reload();page.wait_for_load_state('networkidle')
        assert '/agent/model-config' not in page.url
        assert page.get_by_role('menuitem',name='Agent 模型配置').count()==0
        checks.append(label+' employee navigation guard')
        context.close()
    browser.close()
assert not errors,errors
(OUT/'results.json').write_text(json.dumps({'scope':'isolated browser contract; not real backend or supplier acceptance','checks':checks,'pageErrors':errors},ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'passed':len(checks),'pageErrors':len(errors)},ensure_ascii=False))
