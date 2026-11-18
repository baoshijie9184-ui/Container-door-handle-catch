"""Browser acceptance after organization_local_acceptance.py. Uses retained fixtures only."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

root = Path(__file__).resolve().parents[2]
fixture = json.loads((root / 'work/organization-local-acceptance.json').read_text(encoding='utf-8'))
username = fixture['usernames'][0]
employee_name = fixture['prefix'] + '-2'
checks = []
errors = []

def check(name, condition=True):
    assert condition, name
    checks.append({'name': name, 'passed': True})

def login(page, account):
    page.goto('http://127.0.0.1:3001/#/login', wait_until='networkidle')
    page.get_by_placeholder('请输入用户名').fill(account)
    page.get_by_placeholder('请输入密码').fill('123456')
    page.get_by_role('button', name='登录系统', exact=True).click()
    page.wait_for_url('**/#/home')

def search_account(page):
    search = page.get_by_placeholder('查找登录账号')
    expect(search).to_be_visible()
    search.fill(username)
    page.get_by_role('button', name='查询', exact=True).click()
    row = page.locator('.el-table__body tr').filter(has_text=username)
    expect(row).to_have_count(1)
    return row

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    boss_context = browser.new_context(viewport={'width':1440, 'height':1000})
    page = boss_context.new_page()
    page.on('pageerror', lambda error: errors.append(str(error)))
    changes = []
    page.on('request', lambda req: changes.append(req.url) if req.method == 'PUT' and '/api/organization/accounts/' in req.url else None)
    login(page, 'supervisor.demo')
    page.goto('http://127.0.0.1:3001/#/organization', wait_until='networkidle')
    row = search_account(page)
    row.get_by_role('button', name='关联员工').click()
    dialog = page.get_by_role('dialog')
    expect(dialog).to_be_visible()
    dialog.get_by_role('combobox').fill(employee_name)
    option = page.locator('.el-select-dropdown__item').filter(has_text=employee_name)
    expect(option).to_have_count(1); expect(option).to_be_visible(); option.click()
    with page.expect_response(lambda r: r.request.method == 'PUT' and '/api/organization/accounts/' in r.url) as saved:
        dialog.get_by_role('button', name='保存关联', exact=True).click()
    assert saved.value.status == 200 and saved.value.json()['data']['employeeId'] == fixture['employeeIds'][2]
    expect(page.get_by_role('dialog')).not_to_be_visible()
    expect(row).to_contain_text(employee_name)
    check('supervisor_saves_one_binding', len(changes) == 1)
    page.reload(wait_until='networkidle')
    row = search_account(page)
    expect(row).to_contain_text(employee_name)
    check('reload_preserves_binding_without_replay', len(changes) == 1)
    row.get_by_role('button', name='变更记录').click()
    audit = page.get_by_role('dialog')
    expect(audit).to_be_visible()
    expect(audit.locator('.el-table__body tr').first).to_contain_text('supervisor.demo')
    check('supervisor_views_audit')
    page.keyboard.press('Escape')
    expect(audit).not_to_be_visible()
    page.screenshot(path=str(root / 'work/organization-browser-supervisor.png'), full_page=True)

    staff_context = browser.new_context(viewport={'width':1440, 'height':1000})
    staff = staff_context.new_page(); staff.on('pageerror', lambda error: errors.append(str(error)))
    login(staff, username)
    staff.goto('http://127.0.0.1:3001/#/organization', wait_until='networkidle')
    identity = staff.get_by_role('region', name='我的身份') if staff.get_by_role('region', name='我的身份').count() else staff.locator('section[aria-label="我的身份"]')
    expect(identity).to_contain_text(employee_name)
    expect(identity).to_contain_text('本人及分派任务')
    expect(staff.get_by_placeholder('查找登录账号')).to_have_count(0)
    expect(staff.get_by_role('button', name='新增部门', exact=True)).to_have_count(0)
    check('employee_sees_own_identity_only')
    staff.screenshot(path=str(root / 'work/organization-browser-employee.png'), full_page=True)
    staff.set_viewport_size({'width':390, 'height':844})
    staff.emulate_media(reduced_motion='reduce')
    staff.reload(wait_until='networkidle')
    expect(staff.locator('section[aria-label="我的身份"]')).to_contain_text(employee_name)
    check('mobile_employee_has_no_horizontal_overflow', staff.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))
    staff.screenshot(path=str(root / 'work/organization-browser-mobile.png'), full_page=True)

    # 同一浏览器实际切换角色，验证清除上一账号角色和身份缓存。
    page.get_by_role('button', name='退出登录', exact=True).click()
    page.wait_for_url('**/#/login')
    login(page, username)
    page.goto('http://127.0.0.1:3001/#/organization', wait_until='networkidle')
    expect(page.locator('section[aria-label="我的身份"]')).to_contain_text(employee_name)
    expect(page.get_by_placeholder('查找登录账号')).to_have_count(0)
    check('same_browser_switches_supervisor_to_employee')
    assert not errors, errors
    check('no_javascript_errors')
    browser.close()

result = {'checks': checks, 'javascriptErrors': errors, 'fixturePrefix': fixture['prefix'], 'fixtureEmployeeBindingRetained': True}
(root / 'work/organization-browser-acceptance.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'checks':len(checks), 'allPassed':True, 'artifact':'work/organization-browser-acceptance.json'}))
