"""Two chat entrances: private multitype previews using isolated API responses.

PDF pages come from the real Java PDFBox renderer test, not a browser PDF plug-in.
Run WorkspaceFileContentTest first, then use Vite on 3011 and 5175.
"""
import io,json
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from PIL import Image
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'work/workspace-file-formats';OUT.mkdir(parents=True,exist_ok=True)
namespace={'__file__':str(ROOT/'script/diagnostics/conversation-control-acceptance.py')}
exec((ROOT/'script/diagnostics/conversation-control-acceptance.py').read_text(encoding='utf8').split('with sync_playwright() as p:')[0],namespace)
namespace['run'].update(phase='IDLE',runId=None,local=False,text='');namespace['inputs'].clear()
fixture=ROOT/'doorhandle-module-app/target'
pdf=(fixture/'pdf-preview-acceptance.pdf').read_bytes()
pages=[(fixture/f'pdf-preview-page{i}.png').read_bytes() for i in [1,2]]
files=[];contents={};checks=[];errors=[];requests=[];denied=False;hold=False;held=[]
for index,extension in enumerate(['png','jpg','webp','pdf','csv','json','html','svg']):
    fid=f'01234567-0123-4567-89ab-{index:012d}'
    if extension in ['png','jpg','webp']:
        output=io.BytesIO();Image.new('RGB',(240,160),(35,95,160)).save(output,format={'jpg':'JPEG'}.get(extension,extension.upper()))
        body=output.getvalue();mime={'jpg':'image/jpeg'}.get(extension,'image/'+extension)
    elif extension=='pdf':body=pdf;mime='application/pdf'
    else:
        body={'csv':'编号,缺陷数\n演示批次,2\n','json':'{"批次":"演示","缺陷数":2}',
              'html':'<script>window.attachmentExecuted=true</script>',
              'svg':'<svg onload="window.attachmentExecuted=true"/>\n'+'中'*22000}[extension].encode('utf8');mime='text/plain; charset=utf-8'
    files.append({'id':fid,'name':'验收.'+extension,'contentType':mime,'bytes':len(body),'folder':'uploads'})
    contents[fid]=body
namespace['session']['messages']=[{'id':1,'role':'user','messageType':'TEXT','content':'查看资料\n'+'\n'.join('@file:'+file['id'] for file in files),'createdAt':'2026-10-18 01:10:00'},
    {'id':2,'role':'assistant','messageType':'TEXT','content':'文件能力验收样本','createdAt':'2026-10-18 01:10:01'}]

def api(route):
    global denied
    parsed=urlparse(route.request.url);path=parsed.path;reply=namespace['reply']
    if path.endswith('/workbench'):return reply(route,{'files':files,'items':[],'limits':{'previewBytes':64000},'lineage':{}})
    if '/files/' in path and path.endswith(('/content','/preview')):
        requests.append({'path':path,'query':parsed.query,'cache':route.request.headers.get('cache-control')})
        if denied:return reply(route,{'message':'denied'},status=403)
        fid=path.split('/')[-2]
        if path.endswith('/preview'):
            page=int(parse_qs(parsed.query).get('page',['1'])[0]);assert 1<=page<=2
            if hold:held.append((route,page));return
            return route.fulfill(status=200,content_type='image/png',headers={'X-PDF-Page':str(page),'X-PDF-Pages':'2','Cache-Control':'no-store'},body=pages[page-1])
        file=next(file for file in files if file['id']==fid)
        return route.fulfill(status=200,content_type=file['contentType'],body=contents[fid])
    if path=='/api/agent/workbench/capabilities':return reply(route,{'enabled':True,'files':True})
    if path.endswith('/model-selection'):return reply(route,{'modelId':'','revision':0})
    return namespace['api'](route)

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    for kind,url in [('vue','http://127.0.0.1:3011/#/agent/chat'),('react','http://127.0.0.1:5175/')]:
        context=browser.new_context(viewport={'width':1500,'height':1050},timezone_id='America/Los_Angeles',reduced_motion='reduce',accept_downloads=True)
        context.route('**/api/**',api);context.route('**/agui/**',api)
        page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)));page.goto(url);page.wait_for_load_state('networkidle')
        rail=page.get_by_role('region',name='消息附件');expect(rail.locator('article')).to_have_count(8)
        for file in files:
            print(kind,file['name'],flush=True)
            card=rail.locator('article').filter(has_text=file['name']);card.get_by_role('button',name='预览',exact=True).click()
            dialog=page.get_by_role('dialog',name='消息附件预览',exact=True);expect(dialog).to_be_visible()
            extension=file['name'].split('.')[-1]
            if extension in ['png','jpg','webp','pdf']:
                expect(dialog.locator('img')).to_be_visible();page.wait_for_function("[...document.querySelectorAll('[role=dialog] img')].some(i=>i.complete&&i.naturalWidth>0)")
                assert dialog.locator('iframe,object,embed').count()==0
                if extension=='pdf':
                    expect(dialog).to_contain_text('第 1 / 2 页');dialog.get_by_role('button',name='下一页').click();expect(dialog).to_contain_text('第 2 / 2 页');expect(dialog.get_by_role('button',name='下一页')).to_be_disabled()
                    page.screenshot(path=str(OUT/(kind+'-pdf-desktop.png')),full_page=True)
                    page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                    page.screenshot(path=str(OUT/(kind+'-pdf-mobile.png')),full_page=True);page.set_viewport_size({'width':1500,'height':1050})
                    # A slow page request must remain cancellable by keyboard, and its late reply cannot reopen the dialog.
                    hold=True
                    with page.expect_request('**/preview?page=1'):dialog.get_by_role('button',name='上一页').click()
                    expect(dialog.get_by_role('button',name='上一页')).to_be_disabled()
                    page.keyboard.press('Escape');expect(dialog).not_to_be_visible()
                    assert len(held)==1
                    route,number=held.pop();route.fulfill(status=200,content_type='image/png',headers={'X-PDF-Page':str(number),'X-PDF-Pages':'2'},body=pages[number-1]);hold=False
                    expect(card.get_by_role('button',name='预览',exact=True)).to_be_enabled();expect(dialog).not_to_be_visible()
                    checks.append(kind+' pending PDF request can be closed with Escape and late reply stays closed')
                    card.get_by_role('button',name='预览',exact=True).click();expect(dialog).to_be_visible()
            else:
                expect(dialog.locator('pre')).to_be_visible()
                if extension=='svg':expect(dialog).to_contain_text('内容已按预览上限截断');assert '\ufffd' not in dialog.locator('pre').inner_text()
                assert dialog.locator('pre script,pre svg').count()==0
            assert not page.evaluate('window.attachmentExecuted===true');checks.append(kind+' '+extension+' preview renders without embedded execution')
            page.keyboard.press('Escape')
            try:expect(dialog).not_to_be_visible()
            except Exception:
                page.screenshot(path=str(OUT/(kind+'-escape-failure.png')),full_page=True)
                print('focused element',page.evaluate('({tag:document.activeElement.tagName,role:document.activeElement.getAttribute("role"),label:document.activeElement.getAttribute("aria-label")})'),flush=True)
                raise
            with page.expect_download() as event:card.get_by_role('button',name='下载',exact=True).click()
            download=event.value;assert download.suggested_filename==file['name'];assert Path(download.path()).read_bytes()==contents[file['id']]
            checks.append(kind+' '+extension+' authorized download preserves original bytes')
        # The same safe PDF page flow is available from the workbench file tree.
        if kind=='vue':page.get_by_role('button',name='展开工作面板',exact=True).click()
        elif page.get_by_role('button',name='查看助手信息',exact=True).is_visible():page.get_by_role('button',name='查看助手信息',exact=True).click()
        workbench=page.get_by_role('region',name='Agent 持久工作台');expect(workbench).to_be_visible();workbench.get_by_role('button',name='文件产物',exact=True).click()
        workbench.locator('article').filter(has_text='验收.pdf').get_by_role('button',name='预览',exact=True).click()
        dialog=page.get_by_role('dialog',name='文件预览' if kind=='vue' else '验收.pdf',exact=True);expect(dialog).to_contain_text('第 1 / 2 页');dialog.get_by_role('button',name='下一页').click();expect(dialog).to_contain_text('第 2 / 2 页')
        denied=True;dialog.get_by_role('button',name='上一页').click();expect(dialog).not_to_be_visible();checks.append(kind+' workbench PDF navigation rechecks permission and closes revoked preview');denied=False
        card=rail.locator('article').filter(has_text='验收.pdf');card.get_by_role('button',name='预览',exact=True).click();dialog=page.get_by_role('dialog',name='消息附件预览',exact=True);expect(dialog).to_contain_text('第 1 / 2 页')
        denied=True;dialog.get_by_role('button',name='下一页').click();expect(dialog).not_to_be_visible();expect(card).not_to_be_visible();checks.append(kind+' message PDF page revocation removes filename and actions');denied=False
        context.close()
    browser.close()
assert not errors,errors
(OUT/'results.json').write_text(json.dumps({'checks':checks,'javascriptErrors':errors,'privateReads':requests,'apiMode':'isolated; Java PDFBox raster fixtures'},ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'passed':len(checks),'javascriptErrors':errors}))
