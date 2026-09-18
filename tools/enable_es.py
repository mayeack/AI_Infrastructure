#!/usr/bin/env python3
"""Enable the four Enterprise Security correlation-search twins of ai_infra_monitoring.

Checks that Splunk Enterprise Security (SplunkEnterpriseSecuritySuite) is installed via
the management REST API, writes local/savedsearches.conf with disabled=0 for the four
"<title> - Rule" stanzas, and asks splunkd to reload savedsearches.conf.

Auth (env or <app>/.env): SPLUNK_MGMT_URL (default https://127.0.0.1:8090), SPLUNK_TOKEN
or SPLUNK_USERNAME + SPLUNK_PASSWORD. Stdlib only; runs on Python 3.9 and 3.13.

Usage: enable_es.py [--disable] [--dry-run] [--insecure]
"""
import argparse
import base64
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

APP = "ai_infra_monitoring"
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES = [
    "AI Security - First-seen access to model weights - Rule",
    "AI Security - Credential misuse on an AI cluster - Rule",
    "AI Security - Anomalous data movement from an AI data store - Rule",
    "AI Security - Prompt-injection campaign from a single source - Rule",
]


def load_env():
    """Merge <app>/.env into os.environ without overriding values already set."""
    path = os.path.join(APP_DIR, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and val and key not in os.environ:
                os.environ[key] = val


def auth_header():
    token = os.environ.get("SPLUNK_TOKEN")
    if token:
        return "Bearer " + token
    user, pw = os.environ.get("SPLUNK_USERNAME"), os.environ.get("SPLUNK_PASSWORD")
    if user and pw:
        return "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()
    sys.exit("error: set SPLUNK_TOKEN or SPLUNK_USERNAME/SPLUNK_PASSWORD (env or .env)")


def rest(method, path, ctx, data=None):
    base = os.environ.get("SPLUNK_MGMT_URL", "https://127.0.0.1:8090").rstrip("/")
    url = base + path + ("&" if "?" in path else "?") + "output_mode=json"
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", auth_header())
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        return resp.status, json.loads(resp.read().decode() or "{}")


def es_installed(ctx):
    try:
        status, payload = rest("GET", "/services/apps/local/SplunkEnterpriseSecuritySuite", ctx)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False, None
        raise
    entry = (payload.get("entry") or [{}])[0]
    content = entry.get("content", {})
    return status == 200 and not content.get("disabled", False), content.get("version")


def write_local(disabled):
    local_dir = os.path.join(APP_DIR, "local")
    os.makedirs(local_dir, exist_ok=True)
    path = os.path.join(local_dir, "savedsearches.conf")
    existing = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            existing = fh.read()
    # Rewrite our four stanzas; keep everything else in the file untouched.
    kept, skip = [], False
    for line in existing.splitlines():
        if line.startswith("["):
            skip = line.strip("[]") in RULES
        if not skip:
            kept.append(line)
    block = "\n".join(f"[{name}]\ndisabled = {disabled}\n" for name in RULES)
    content = ("\n".join(kept).rstrip() + "\n\n" if "".join(kept).strip() else "") + block
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--disable", action="store_true", help="write disabled=1 instead of enabling the rules")
    ap.add_argument("--dry-run", action="store_true", help="check ES and print the plan without writing or reloading")
    ap.add_argument("--insecure", action="store_true", default=True, help="skip TLS verification (default for the local management port)")
    args = ap.parse_args()
    load_env()
    ctx = ssl._create_unverified_context() if args.insecure else ssl.create_default_context()

    try:
        installed, version = es_installed(ctx)
    except urllib.error.HTTPError as exc:
        sys.exit(f"error: management API returned HTTP {exc.code} (check credentials in .env)")
    except (urllib.error.URLError, OSError) as exc:
        sys.exit(f"error: cannot reach {os.environ.get('SPLUNK_MGMT_URL', 'https://127.0.0.1:8090')}: {exc}")
    if not installed and not args.disable:
        sys.exit("Splunk Enterprise Security is not installed (or is disabled) on this instance; "
                 "the ai:security:finding events stand in. Nothing written.")
    print(f"Enterprise Security detected (version {version or 'unknown'})" if installed else "Disabling rules")
    disabled = 1 if args.disable else 0
    for name in RULES:
        print(f"  {'disable' if disabled else 'enable '} {name}")
    if args.dry_run:
        print("dry run: no files written")
        return
    path = write_local(disabled)
    print(f"wrote {path}")
    try:
        rest("POST", f"/servicesNS/nobody/{APP}/admin/savedsearch/_reload", ctx, {})
        print("reloaded savedsearches.conf")
    except urllib.error.HTTPError as exc:
        print(f"warning: reload returned HTTP {exc.code}; restart Splunk or run 'splunk reload' to apply", file=sys.stderr)
    for name in RULES:
        try:
            _, payload = rest("GET", f"/servicesNS/nobody/{APP}/saved/searches/{urllib.parse.quote(name, safe='')}", ctx)
            state = (payload.get("entry") or [{}])[0].get("content", {}).get("disabled")
            print(f"  {name}: disabled={state}")
        except urllib.error.HTTPError as exc:
            print(f"  {name}: HTTP {exc.code}", file=sys.stderr)


if __name__ == "__main__":
    main()
