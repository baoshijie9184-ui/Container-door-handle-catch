# -*- coding: utf-8 -*-
"""使用 Element Plus 选择器调试登录页面结构。"""
import time

from playwright.sync_api import sync_playwright


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel="chrome")
        page = browser.new_page(viewport={"width": 1400, "height": 900})

        page.goto("http://localhost:3001/login")
        page.wait_for_load_state("networkidle")
        time.sleep(2)

        print(f"URL: {page.url}")
        print(f"Title: {page.title()}")

        # 截图
        page.screenshot(path="/tmp/debug_login.png", full_page=True)

        # 查找所有可见的输入框
        all_inputs = page.locator("input:visible").all()
        print(f"可见 input 数: {len(all_inputs)}")

        # 查找 el-input
        el_inputs = page.locator(".el-input__inner").all()
        print(f"el-input 数: {len(el_inputs)}")
        for i, inp in enumerate(el_inputs):
            placeholder = inp.get_attribute("placeholder") or ""
            input_type = inp.get_attribute("type") or "text"
            print(f"  el-input[{i}]: type={input_type}, placeholder={placeholder}")

        browser.close()


if __name__ == "__main__":
    main()
