"""Explicit real HTTP and two-UI file acceptance against a retained isolated candidate only."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import time
import uuid

from PIL import Image
import requests
from playwright.sync_api import sync_playwright, expect
from candidate_environment import candidate_identity, probe_source, timestamp

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-report', required=True)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--execute', action='store_true', help='Create private candidate sessions/files; never performs detection or approval')
    args = parser.parse_args()
    assert args.execute, 'Explicit --execute is required'
    candidate = json.loads(Path(args.candidate_report).read_text(encoding='utf-8-sig'))
    project = candidate_identity(candidate)
    port = candidate.get('port', 18089)
    assert port == 18089
    out = Path(args.directory).resolve()
    assert out.is_relative_to(ROOT/'work') and out != ROOT/'work'
    out.mkdir(parents=True, exist_ok=False)
    pdf = ROOT/'work/file-formats-verify/doorhandle-module-app/target/pdf-preview-acceptance.pdf'
    assert pdf.is_file(), 'Run WorkspaceFileContentTest in the isolated Maven workspace first'
    ssh = ['ssh', '-F', str(ROOT/'work/cloud/ssh-config'), '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10']
    probe = subprocess.run(ssh+['doorhandle-bj', 'python3 -'], input=probe_source(candidate), capture_output=True, text=True, timeout=25)
    assert probe.returncode == 0 and probe.stdout.strip() == 'owned-candidate-ready', 'Candidate identity/listener differs'
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', port))
    report = {'startedAt': timestamp(), 'project': project, 'release': candidate['release'], 'sourceSha256': candidate['sourceSha256'], 'passed': False, 'checks': [], 'pageErrors': [], 'sessions': {}}
    def save():
        (out/'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    def check(name, condition):
        assert condition, name
        report['checks'].append(name)
        save()
    save()
    base = 'http://127.0.0.1:'+str(port)
    session = requests.Session()
    session.trust_env = False
    session.headers['X-Agent-Action'] = 'workbench'
    password = os.environ.get('DOORHANDLE_DEMO_PASSWORD', '123456')
    def api(method, path, **kwargs):
        response = session.request(method, base+path, timeout=30, **kwargs)
        response.raise_for_status()
        value = response.json()
        if 'code' in value:
            assert value['code'] == 200
            return value['data']
        return value
    bodies = {}
    for extension in ('png', 'jpg', 'webp'):
        stream = io.BytesIO()
        Image.new('RGB', (180, 100), (40, 100, 170)).save(stream, format={'jpg': 'JPEG'}.get(extension, extension.upper()))
        bodies[extension] = stream.getvalue()
    bodies.update(pdf=pdf.read_bytes(), txt='文字层验收 𠀀'.encode(), md='# 验收\n\nCPU PTH 检测'.encode(),
                  csv='任务,缺陷数\n正常图,0\n'.encode(), json='{"批次":"联调","缺陷数":2}'.encode(),
                  html=b'<script>window.candidateAttachmentExecuted=true</script>',
                  svg=b'<svg xmlns="http://www.w3.org/2000/svg" onload="window.candidateAttachmentExecuted=true"/>')
    tunnel = None
    try:
        with (out/'ssh.log').open('wb') as log:
            tunnel = subprocess.Popen(ssh+['-o', 'ExitOnForwardFailure=yes', '-N', '-L', f'127.0.0.1:{port}:127.0.0.1:{port}', 'doorhandle-bj'], stdout=log, stderr=log)
        (out/'tunnel.pid').write_text(str(tunnel.pid))
        for _ in range(40):
            assert tunnel.poll() is None, 'Owned SSH tunnel ended'
            try:
                if session.get(base+'/nginx-health', timeout=1).ok:
                    break
            except requests.RequestException:
                time.sleep(.25)
        else:
            raise AssertionError('Candidate tunnel did not become ready')
        for entry, account in [('vue', 'inspector.demo'), ('react', 'supervisor.demo')]:
            api('POST', '/api/auth/login', json={'username': account, 'password': password})
            sid = api('POST', '/api/chat-assistant/sessions')['sessionId']
            report['sessions'][entry] = {'id': sid, 'account': account, 'files': []}
            save()
            prefix = '/api/agent/conversations/'+sid
            for extension, body in bodies.items():
                request_id = uuid.uuid4().hex
                name = '真实联调-𠀀.'+extension
                file = api('POST', prefix+'/files', data={'requestId': request_id}, files={'file': (name, body)})
                report['sessions'][entry]['files'].append(file)
                save()
                repeated = api('POST', prefix+'/files', data={'requestId': request_id}, files={'file': (name, body)})
                check(entry+' '+extension+' upload request is idempotent', repeated['id'] == file['id'])
                response = session.get(base+prefix+'/files/'+file['id']+'/content', timeout=25)
                response.raise_for_status()
                check(entry+' '+extension+' original bytes, name and hash retained',
                      response.content == body and file['name'] == name and file['sha256'] == hashlib.sha256(body).hexdigest() and
                      all(value.strip().lower() == 'nosniff' for value in response.headers.get('X-Content-Type-Options', '').split(',')) and
                      'no-store' in {value.strip().lower() for value in response.headers.get('Cache-Control', '').split(',')})
                if extension == 'pdf':
                    response = session.get(base+prefix+'/files/'+file['id']+'/preview?page=1', timeout=25)
                    check(entry+' real PDFBox preview is a rendered PNG', response.status_code == 200 and response.content.startswith(b'\x89PNG') and response.headers.get('X-PDF-Pages') == '2')
            other = 'inspector.demo2' if entry == 'vue' else 'supervisor.demo2'
            api('POST', '/api/auth/login', json={'username': other, 'password': password})
            statuses = [session.get(base+prefix+'/files/'+file['id']+'/content', timeout=15).status_code for file in report['sessions'][entry]['files']]
            check(entry+' all ten files refuse another account', all(code in (403, 404) for code in statuses))
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                for entry, state in report['sessions'].items():
                    context = browser.new_context(viewport={'width': 1500, 'height': 1050}, reduced_motion='reduce', timezone_id='America/Los_Angeles', accept_downloads=True)
                    page = context.new_page()
                    page.on('pageerror', lambda error: report['pageErrors'].append(str(error)))
                    response = context.request.post(base+'/api/auth/login', data={'username': state['account'], 'password': password})
                    assert response.ok
                    path = '/#/agent/chat?sessionId='+state['id'] if entry == 'vue' else '/agent-ui/?sessionId='+state['id']
                    page.goto(base+path, wait_until='networkidle')
                    check(entry+' uses standards mode and a mobile viewport', page.evaluate('document.compatMode==="CSS1Compat"&&document.querySelector("meta[name=viewport]")?.content.includes("width=device-width")'))
                    toggle = page.get_by_role('button', name='展开工作面板' if entry == 'vue' else '查看助手信息', exact=True)
                    if toggle.count() and toggle.is_visible():
                        toggle.click()
                    workbench = page.get_by_role('region', name='Agent 持久工作台', exact=True)
                    expect(workbench).to_be_visible()
                    files_button = workbench.get_by_role('navigation', name='工作台视图').get_by_role('button', name=re.compile('文件'))
                    files_button.click()
                    for file in state['files']:
                        card = workbench.locator('article').filter(has_text=file['name'])
                        expect(card).to_have_count(1)
                        card.get_by_role('button', name='预览', exact=True).click()
                        dialog = page.get_by_role('dialog', name=file['name'], exact=True)
                        expect(dialog).to_be_visible()
                        extension = file['name'].split('.')[-1]
                        if extension in ('png', 'jpg', 'webp', 'pdf'):
                            expect(dialog.locator('img')).to_be_visible()
                            page.wait_for_function('(node)=>node.complete&&node.naturalWidth>0', arg=dialog.locator('img').element_handle())
                        else:
                            expect(dialog.locator('pre')).not_to_be_empty()
                        if extension == 'pdf':
                            dialog.get_by_role('button', name='下一页', exact=True).click()
                            expect(dialog.get_by_text('第 2 / 2 页')).to_be_visible()
                        check(entry+' '+extension+' browser preview uses the real authorized API', not page.evaluate('Boolean(window.candidateAttachmentExecuted)'))
                        page.screenshot(path=str(out/(entry+'-'+extension+'-preview.png')), full_page=True, animations='disabled')
                        page.keyboard.press('Escape')
                        expect(dialog).not_to_be_visible()
                        with page.expect_download() as download:
                            card.get_by_role('button', name='下载', exact=True).click()
                        item = download.value
                        check(entry+' '+extension+' browser download retains original bytes', Path(item.path()).read_bytes() == bodies[extension])
                    select = page.get_by_role('combobox', name='使用模型', exact=True)
                    expect(select).to_be_enabled()
                    options = select.locator('option').evaluate_all('(nodes)=>nodes.map(n=>({value:n.value,label:n.textContent}))')
                    model = next(item['value'] for item in options if item['value'] == 'dashscope:qwen3.8-flash')
                    select.select_option(model)
                    expect(select).to_be_enabled()
                    expect(select).to_have_value(model)
                    name = '加号上传-'+entry+'.txt'
                    with page.expect_file_chooser() as chooser:
                        page.get_by_role('button', name='添加附件', exact=True).click()
                    chooser.value.set_files({'name': name, 'mimeType': 'text/plain', 'buffer': '真实加号上传与刷新保留'.encode()})
                    pending = page.get_by_role('list', name='本条消息的附件引用', exact=True)
                    expect(pending.get_by_text(name, exact=True)).to_be_visible()
                    page.reload(wait_until='networkidle')
                    expect(page.get_by_role('combobox', name='使用模型', exact=True)).to_have_value(model)
                    expect(page.get_by_role('list', name='本条消息的附件引用', exact=True).get_by_text(name, exact=True)).to_be_visible()
                    saved = context.request.get(base+'/api/agent/conversations/'+state['id']+'/model-selection').json()
                    check(entry+' explicit model selection persists in MySQL', saved['modelId'] == model)
                    check(entry+' plus upload and attachment draft survive refresh', True)
                    before_inputs=context.request.get(base+'/api/agent/conversations/'+state['id']+'/control').json()['inputs']
                    draft='DEMO-OFFLINE-'+uuid.uuid4().hex+' 本条保留为未发送草稿'
                    composer=page.locator('textarea')
                    expect(composer).to_have_count(1)
                    context.set_offline(True)
                    expect(page.get_by_text('浏览器报告网络离线，当前输入保留；恢复连接后请手动发送，不会自动重发。',exact=True)).to_be_visible()
                    composer.fill(draft)
                    context.set_offline(False)
                    expect(page.get_by_text('浏览器报告网络离线，当前输入保留；恢复连接后请手动发送，不会自动重发。',exact=True)).not_to_be_visible()
                    page.reload(wait_until='networkidle')
                    expect(page.locator('textarea')).to_have_value(draft)
                    expect(page.get_by_role('list',name='本条消息的附件引用',exact=True).get_by_text(name,exact=True)).to_be_visible()
                    after_inputs=context.request.get(base+'/api/agent/conversations/'+state['id']+'/control').json()['inputs']
                    check(entry+' offline text and attachment draft survive reconnect and refresh',True)
                    check(entry+' reconnect never submits the unsent draft',before_inputs==after_inputs)
                    check(entry+' no queued messages means no queue panel', page.get_by_role('list', name='待处理消息', exact=True).count() == 0)
                    page.set_viewport_size({'width': 390, 'height': 844})
                    check(entry+' reduced motion preference is active', page.evaluate('matchMedia("(prefers-reduced-motion: reduce)").matches'))
                    check(entry+' mobile page has no horizontal overflow', page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'))
                    page.screenshot(path=str(out/(entry+'-mobile.png')), full_page=True, animations='disabled')
                    context.close()
                check('Both entries have no JavaScript runtime errors', not report['pageErrors'])
            finally:
                browser.close()
        report['passed'] = True
    finally:
        report['finishedAt'] = timestamp()
        save()
        if tunnel is not None and tunnel.poll() is None:
            tunnel.terminate()
            tunnel.wait(timeout=15)
    print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'directory': str(out)}))


if __name__ == '__main__':
    main()
