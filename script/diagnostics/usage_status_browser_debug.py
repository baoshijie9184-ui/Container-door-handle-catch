# -*- coding: utf-8 -*-
"""测试设备使用记录的状态筛选功能"""
from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, channel="chrome")
    context = browser.new_context(viewport={"width": 1400, "height": 900})
    page = context.new_page()

    # 1. 登录
    page.goto("http://localhost:3001/#/login")
    page.wait_for_load_state("networkidle")
    time.sleep(2)

    el_inputs = page.locator(".el-input__inner").all()
    if len(el_inputs) >= 2:
        el_inputs[0].fill("admin")
        el_inputs[1].fill("admin123")
        login_btn = page.locator('button:has-text("登录")').first
        if login_btn.count() > 0:
            login_btn.click()
            page.wait_for_load_state("networkidle")
            time.sleep(2)

    print(f"登录后URL: {page.url}")

    # 2. 导航到设备使用记录页面
    page.goto("http://localhost:3001/#/device-records")
    page.wait_for_load_state("networkidle")
    time.sleep(3)

    # 3. 截图：初始状态
    page.screenshot(path="/tmp/test_01_initial.png", full_page=True)
    rows = page.locator(".el-table__body tr").all()
    print(f"初始记录数: {len(rows)}")

    # 4. 找到状态筛选下拉框（第4个input，index=3）
    status_input = page.locator(".el-input__inner").nth(3)
    status_input.click()
    time.sleep(1)

    # 5. 选择"使用中" - 使用更精确的选择器
    # 找到可见的下拉面板中的选项
    visible_dropdown = page.locator(".el-select-dropdown:visible").first
    if visible_dropdown.count() > 0:
        use_option = visible_dropdown.locator('.el-select-dropdown__item:has-text("使用中"), .el-select-dropdown__item:has-text("IN_USE")').first
        if use_option.count() > 0:
            use_option.click()
            time.sleep(0.5)
            print("选择了使用中")
        else:
            print("未找到使用中选项")
    else:
        # 尝试直接点击包含"使用中"文本的可见选项
        page.locator('.el-select-dropdown__item:visible:has-text("使用中")').first.click()
        time.sleep(0.5)
        print("选择了使用中(直接)")

    # 6. 点击查询
    query_btn = page.locator('button:has-text("查询")').first
    query_btn.click()
    page.wait_for_load_state("networkidle")
    time.sleep(2)

    # 7. 截图：筛选使用中
    page.screenshot(path="/tmp/test_02_in_use.png", full_page=True)
    rows_in_use = page.locator(".el-table__body tr").all()
    print(f"筛选使用中后记录数: {len(rows_in_use)}")

    empty = page.locator(".el-empty").count()
    if empty > 0:
        print("警告: 显示了空状态!")
    else:
        print("成功: 有记录显示")

    # 8. 重置
    reset_btn = page.locator('button:has-text("重置")').first
    reset_btn.click()
    page.wait_for_load_state("networkidle")
    time.sleep(1)

    # 9. 选择"已归还"
    status_input = page.locator(".el-input__inner").nth(3)
    status_input.click()
    time.sleep(1)

    visible_dropdown = page.locator(".el-select-dropdown:visible").first
    if visible_dropdown.count() > 0:
        returned_option = visible_dropdown.locator('.el-select-dropdown__item:has-text("已归还"), .el-select-dropdown__item:has-text("RETURNED")').first
        if returned_option.count() > 0:
            returned_option.click()
            time.sleep(0.5)
            print("选择了已归还")

    query_btn.click()
    page.wait_for_load_state("networkidle")
    time.sleep(2)

    page.screenshot(path="/tmp/test_03_returned.png", full_page=True)
    rows_returned = page.locator(".el-table__body tr").all()
    print(f"筛选已归还后记录数: {len(rows_returned)}")

    empty2 = page.locator(".el-empty").count()
    if empty2 > 0:
        print("警告: 显示了空状态!")
    else:
        print("成功: 有记录显示")

    # 10. 结果
    print("\n=== 测试结果 ===")
    print(f"初始记录: {len(rows)}")
    print(f"筛选使用中: {len(rows_in_use)}")
    print(f"筛选已归还: {len(rows_returned)}")
    if len(rows_in_use) > 0 and len(rows_returned) > 0:
        print("通过: 状态筛选功能正常")
    else:
        print("失败: 状态筛选功能异常")

    browser.close()
