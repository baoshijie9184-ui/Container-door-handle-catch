"""前端页面自动化测试脚本"""
import os
from playwright.sync_api import sync_playwright

SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), 'screenshots')
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

BASE_URL = 'http://localhost:3001'

def screenshot(page, name):
    path = os.path.join(SCREENSHOT_DIR, f'{name}.png')
    page.screenshot(path=path, full_page=True)
    print(f'[截图] {path}')

def test_login_page(page):
    """测试登录页面"""
    print('\n=== 测试登录页面 ===')
    page.goto(f'{BASE_URL}/#/login')
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(1000)

    screenshot(page, '01_login_page')

    # 检查页面标题
    title = page.title()
    print(f'页面标题: {title}')

    # 检查登录表单元素
    inputs = page.locator('input').all()
    print(f'输入框数量: {len(inputs)}')

    buttons = page.locator('button').all()
    print(f'按钮数量: {len(buttons)}')

    # 检查是否有用户名/密码输入框
    username_input = page.locator('input[type="text"], input[placeholder*="用户"], input[placeholder*="账号"]').first
    password_input = page.locator('input[type="password"]').first

    if username_input.is_visible():
        print('[OK] 用户名输入框存在')
    else:
        print('[FAIL] 用户名输入框未找到')

    if password_input.is_visible():
        print('[OK] 密码输入框存在')
    else:
        print('[FAIL] 密码输入框未找到')

    # 检查登录按钮
    login_btn = page.locator('button:has-text("登录"), button:has-text("Login"), button[type="submit"]').first
    if login_btn.is_visible():
        print('[OK] 登录按钮存在')
    else:
        print('[FAIL] 登录按钮未找到')

def test_home_page(page):
    """测试首页（未登录状态会跳转到登录页）"""
    print('\n=== 测试首页 ===')
    page.goto(f'{BASE_URL}/#/home')
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(1000)

    screenshot(page, '02_home_page')

    # 检查是否被重定向到登录页
    current_url = page.url
    print(f'当前URL: {current_url}')

    if 'login' in current_url:
        print('[OK] 未登录状态正确重定向到登录页')
    else:
        print('[OK] 首页已加载')
        # 检查侧边栏
        sidebar = page.locator('.el-aside, .sidebar, [class*="sidebar"]').first
        if sidebar.is_visible():
            print('[OK] 侧边栏存在')

def test_login_flow(page, username=None, password=None):
    username = username or os.environ.get('E2E_USERNAME', '')
    password = password or os.environ.get('E2E_PASSWORD', '')
    assert username and password, 'Set E2E_USERNAME and E2E_PASSWORD before running login E2E tests'
    """测试登录流程"""
    print('\n=== 测试登录流程 ===')
    page.goto(f'{BASE_URL}/#/login')
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(1000)

    # 尝试登录
    username_input = page.locator('input[type="text"], input[placeholder*="用户"], input[placeholder*="账号"]').first
    password_input = page.locator('input[type="password"]').first

    if username_input.is_visible() and password_input.is_visible():
        username_input.fill(username)
        password_input.fill(password)
        screenshot(page, '03_login_filled')

        login_btn = page.locator('button:has-text("登录"), button:has-text("Login"), button[type="submit"]').first
        if login_btn.is_visible():
            login_btn.click()
            page.wait_for_timeout(2000)
            page.wait_for_load_state('networkidle')

            screenshot(page, '04_after_login')

            current_url = page.url
            print(f'登录后URL: {current_url}')

            if 'login' not in current_url:
                print('[OK] 登录成功')
                return True
            else:
                print('[FAIL] 登录失败，仍在登录页')
                # 检查错误信息
                error_msg = page.locator('.el-message--error, .ant-message-error, .error-msg').first
                if error_msg.is_visible():
                    print(f'错误信息: {error_msg.text_content()}')
                return False
    else:
        print('[FAIL] 未找到输入框')
        return False

def test_home_after_login(page):
    """登录后测试首页"""
    print('\n=== 登录后测试首页 ===')
    page.goto(f'{BASE_URL}/#/home')
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(1000)

    screenshot(page, '05_home_logged_in')

    # 检查页面内容
    body_text = page.locator('body').text_content()
    if '首页' in body_text or '总览' in body_text or 'Dashboard' in body_text:
        print('[OK] 首页内容已加载')
    else:
        print('首页内容: ' + body_text[:200] if body_text else '空')

    # 检查侧边栏菜单
    menu_items = page.locator('.el-menu-item, .ant-menu-item, [class*="menu-item"]').all()
    print(f'菜单项数量: {len(menu_items)}')

def test_other_pages(page, logged_in=False):
    """测试其他页面"""
    pages_to_test = [
        ('upload', '图片上传'),
        ('detection', '图像检测'),
        ('devices', '设备管理'),
        ('employees', '人员管理'),
    ]

    for route, name in pages_to_test:
        print(f'\n=== 测试{name}页面 ===')
        page.goto(f'{BASE_URL}/#/{route}')
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(1000)

        screenshot(page, f'06_{route}_page')

        current_url = page.url
        if 'login' in current_url and not logged_in:
            print(f'[OK] {name}需要登录，正确重定向')
        else:
            # 检查页面是否有内容
            body_text = page.locator('body').text_content()
            if body_text and len(body_text.strip()) > 50:
                print(f'[OK] {name}页面已加载')
            else:
                print(f'[FAIL] {name}页面内容为空或加载失败')

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        try:
            # 1. 测试登录页面
            test_login_page(page)

            # 2. 测试首页（未登录）
            test_home_page(page)

            # 3. 测试登录流程
            login_success = test_login_flow(page)

            # 4. 登录后测试首页
            if login_success:
                test_home_after_login(page)
                test_other_pages(page, logged_in=True)
            else:
                print('\n登录失败，跳过需要登录的页面测试')
                test_other_pages(page, logged_in=False)

        except Exception as e:
            print(f'\n测试出错: {e}')
            screenshot(page, 'error')
        finally:
            browser.close()

    print('\n=== 测试完成 ===')
    print(f'截图保存在: {SCREENSHOT_DIR}')

if __name__ == '__main__':
    main()
