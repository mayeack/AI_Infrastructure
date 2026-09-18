#!/usr/bin/env python3
"""Print (and, when playwright is importable, capture) the ten dashboard URLs in dark theme.

Without playwright it prints the URLs and exits 0 so `make screenshots` never blocks a build.
With playwright it logs in with the .env credentials and saves dist/screenshots/<view>.png.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _splunkrest import load_env  # noqa: E402

VIEWS = [
    "ai_stack_overview", "ai_infrastructure_health", "ai_network_fabric", "ai_platform_workloads",
    "ai_applications", "model_performance_quality", "ai_agents", "ai_cost_unit_economics",
    "ai_security_posture", "ai_operations_executive_overview",
]


def urls(base, app):
    return [(v, "%s/app/%s/%s?theme=dark" % (base.rstrip("/"), app, v)) for v in VIEWS]


def capture(base, app, out_dir, width, height, settle_ms):
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError:
        return False
    user = os.environ.get("SPLUNK_USERNAME", "")
    pw = os.environ.get("SPLUNK_PASSWORD", "")
    os.makedirs(out_dir, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        page.goto("%s/en-US/account/login" % base.rstrip("/"))
        if user and pw:
            page.fill("input[name=username]", user)
            page.fill("input[name=password]", pw)
            page.click("input[type=submit], button[type=submit]")
            page.wait_for_load_state("networkidle")
        for view, url in urls(base, app):
            page.goto(url)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(settle_ms)
            path = os.path.join(out_dir, view + ".png")
            page.screenshot(path=path, full_page=True)
            print("saved %s" % path)
        browser.close()
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description="Dashboard URLs / screenshots for ai_infra_monitoring")
    ap.add_argument("--base", default=os.environ.get("SPLUNK_WEB_URL", "http://localhost:8002"))
    ap.add_argument("--app", default="ai_infra_monitoring")
    ap.add_argument("--out", default="dist/screenshots")
    ap.add_argument("--env-file", default=".env")
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=1100)
    ap.add_argument("--settle-ms", type=int, default=12000, help="wait after networkidle for searches to render")
    ap.add_argument("--print-only", action="store_true")
    a = ap.parse_args(argv)
    load_env(a.env_file)
    for view, url in urls(a.base, a.app):
        print("%-36s %s" % (view, url))
    if a.print_only:
        return 0
    if capture(a.base, a.app, a.out, a.width, a.height, a.settle_ms):
        return 0
    print("playwright is not importable under this Python; open the URLs above in a browser (dark theme) and save PNGs to %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
