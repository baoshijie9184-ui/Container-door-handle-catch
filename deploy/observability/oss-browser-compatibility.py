"""ECS browser step; run between OSS prepare and finally cleanup. No signed URLs in reports."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-manifest", required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--receipt", required=True)
    args = parser.parse_args()
    report = {"schemaVersion": 1, "browserCors": "FAIL", "presignedBrowserPut": False, "presignedBrowserGet": False}
    try:
        if os.name != "posix":
            raise ValueError("ECS only")
        origin = urlsplit(args.origin)
        if origin.scheme not in {"http", "https"} or not origin.hostname or origin.username or origin.password or origin.query or origin.fragment:
            raise ValueError("origin")
        private = Path(args.private_manifest)
        if private.stat().st_size > 16384 or private.stat().st_mode & 0o077:
            raise ValueError("private fixture")
        manifest = json.loads(private.read_text(encoding="utf-8"))
        if manifest.get("schemaVersion") != 1 or manifest.get("payload") != "doorhandle-oss-compatibility-fixture-v1":
            raise ValueError("fixture")
        urls = [manifest["browserPut"], manifest["browserGet"]]
        if any(urlsplit(url).scheme != "https" or not urlsplit(url).hostname for url in urls):
            raise ValueError("HTTPS storage required")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(args.origin, wait_until="domcontentloaded", timeout=30000)
                # No interception, disable-web-security or proxy: this is the browser's actual CORS path.
                result = page.evaluate("""async ({put,get,payload}) => {
                    try {
                        const upload=await fetch(put,{method:'PUT',mode:'cors',credentials:'omit',headers:{'Content-Type':'text/plain'},body:payload,signal:AbortSignal.timeout(15000)});
                        if(!upload.ok)return {put:false,get:false};
                        const download=await fetch(get,{mode:'cors',credentials:'omit',signal:AbortSignal.timeout(15000)});
                        return {put:true,get:download.ok && (await download.text())===payload};
                    } catch { return {put:false,get:false}; }
                }""", {"put": urls[0], "get": urls[1], "payload": manifest["payload"]})
                report["presignedBrowserPut"], report["presignedBrowserGet"] = result["put"], result["get"]
                if all(result.values()):
                    report["browserCors"] = "PASS"
            finally:
                browser.close()
    except Exception:
        report["failureCode"] = "OSS_BROWSER_COMPATIBILITY_FAILED"
    output = Path(args.receipt)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("OSS_BROWSER_COMPATIBILITY_" + report["browserCors"])
    return 0 if report["browserCors"] == "PASS" else 1

if __name__ == "__main__":
    raise SystemExit(main())
