"""Verify removal against the running monolith without changing user data or calling models."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

root = Path(__file__).resolve().parents[2]
base = 'http://127.0.0.1:3001'
checks = []
errors = []

def passed(name):
    checks.append({'name': name, 'passed': True})

def login(page, account):
    page.goto(base + '/#/login', wait_until='networkidle')
    page.get_by_placeholder('请输入用户名').fill(account)
    page.get_by_placeholder('请输入密码').fill('123456')
    page.get_by_role('button', name='登录系统', exact=True).click()
    page.wait_for_url('**/#/home')
    page.goto(base + '/#/agent/skills', wait_until='networkidle')
    expect(page.get_by_role('heading', name='Agent 技能演化', exact=True)).to_be_visible()
    expect(page.locator('.skills-page .el-loading-mask')).to_be_hidden()

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={'width':1440, 'height':1000}, reduced_motion='reduce')
    page = context.new_page()
    page.on('pageerror', lambda error: errors.append(str(error)))
    login(page, 'inspector.demo')
    page.screenshot(path=str(root / 'work/skill-upload-removed-desktop.png'), full_page=True, animations='disabled')
    assert page.locator('input[type=file]').count() == 0
    assert page.get_by_role('button', name='上传 Skill ZIP', exact=True).count() == 0
    assert page.get_by_text('导入外部 Skill', exact=True).count() == 0
    expect(page.get_by_role('heading', name='本人经验来源', exact=True)).to_be_visible()
    expect(page.get_by_role('button', name='编写技能草稿', exact=True)).to_be_visible()
    passed('upload_removed_and_business_experience_controls_remain')

    for route in ('/api/agent/skills', '/api/agent/skills/sources'):
        response = context.request.get(base + route)
        assert response.ok and response.headers.get('cache-control') == 'no-store'
    records = context.request.get(base + '/api/agent/skills').json()
    passed('authenticated_skill_history_and_source_queries_remain_available')

    upload = context.request.post(base + '/api/agent/skills/imports', headers={'X-Skill-Action':'update'}, multipart={'file':{'name':'removed.zip','mimeType':'application/zip','buffer':b'PK\x03\x04'}, 'sourceUrl':'https://example.org/skill','sourceVersion':'v1','requestId':'removed-zip-request','licenseAcknowledged':'true'})
    assert upload.status == 410, upload.status
    assert context.request.get(base + '/api/agent/skills/imports').status == 410
    assert context.request.get(base + '/api/agent/skills/imports/tool-options').status == 410
    passed('upload_source_list_and_tool_mapping_routes_are_removed')

    rejected = context.request.post(base + '/api/agent/skills', headers={'X-Skill-Action':'update'}, data={'name':'blocked-upload','targetRole':'INSPECTOR','description':'查询任务时使用的经验步骤','instructions':'先确认用户提供的任务编号 再调用已授权任务查询工具 核对处理图片数量和复核状态 无数据依据时明确说明 不将查询结果视为审批或放行','tools':['get_task_detail'],'sourceRunId':'source-1','sourceImportId':'import-00000000-0000-0000-0000-000000000000','requestId':'blocked-upload-request'})
    assert rejected.status == 400, rejected.status
    assert context.request.get(base + '/api/agent/skills').json() == records
    passed('ordinary_draft_endpoint_rejects_external_import_without_data_changes')

    legacy = next((row for row in records if row['ownerUserId']==18 and any(v['evidence'].get('sourceType')=='EXTERNAL_UPLOAD' for v in row['versions'])), None)
    if legacy:
        row = page.locator('.el-table__row').filter(has_text=legacy['name']).first
        row.get_by_role('button', name='查看与管理', exact=True).click()
        dialog = page.get_by_role('dialog', name='技能详情与审核', exact=True)
        expect(dialog.get_by_text('外部上传功能已移除 此记录仅供历史查看或停用', exact=True)).to_be_visible()
        assert dialog.get_by_role('button', name='修订新版本', exact=True).count() == 0
        assert dialog.get_by_role('button', name='运行规则 Eval', exact=True).count() == 0
        assert dialog.get_by_role('button', name='审核并发布', exact=True).count() == 0
        passed('existing_uploaded_history_remains_visible_without_enable_or_revision_controls')
        page.keyboard.press('Escape')
        expect(dialog).to_be_hidden()

    page.goto(base + '/#/agent/markets', wait_until='networkidle')
    expect(page.get_by_role('link', name='管理经验技能')).to_be_visible()
    assert page.get_by_text('Skill 支持上传与独立审核', exact=False).count() == 0
    expect(page.get_by_role('link', name='管理本人本地 MCP')).to_be_visible()
    state = context.request.get(base + '/api/agent/mcp/fetch')
    assert state.ok and state.json()['status']=='INSTALLED' and not state.json()['enabled']
    passed('market_navigation_and_existing_local_mcp_are_preserved')

    mobile = browser.new_context(viewport={'width':390, 'height':844}, reduced_motion='reduce')
    mobile_page = mobile.new_page()
    mobile_page.on('pageerror', lambda error: errors.append(str(error)))
    login(mobile_page, 'supervisor.demo')
    assert mobile_page.locator('input[type=file]').count() == 0
    assert mobile.request.get(base + '/api/agent/skills/sources').ok
    mobile_page.screenshot(path=str(root / 'work/skill-upload-removed-mobile.png'), full_page=True, animations='disabled')
    passed('supervisor_mobile_page_loads_without_upload_controls')

    anonymous = browser.new_context()
    assert anonymous.request.get(base + '/api/agent/skills').status in (401,403)
    passed('anonymous_skill_history_remains_protected')
    assert not errors, errors
    browser.close()

(root / 'work/skill-upload-removal-acceptance.json').write_text(json.dumps({'checks':checks,'javascriptErrors':errors,'paidModelsCalled':False,'businessDataMutated':False}, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'checks':len(checks),'allPassed':True,'javascriptErrors':errors,'paidModelsCalled':False}))
