#!/usr/bin/env python3
"""Create or update the HEC token `ai_infra_demo` for the ai_infra_monitoring demo (idempotent).

Steps: enable the global HEC input, create/update the token scoped to the nine demo indexes,
write AI_DEMO_HEC_TOKEN and HEC_URL into .env (other lines preserved), then send a one-event
probe with gzip and identity encodings. `--file-provision` writes the token into
$SPLUNK_HOME/etc/apps/splunk_httpinput/local/inputs.conf between BEGIN/END markers instead
(for boxes without management-port credentials); a restart is needed afterwards.
"""
import argparse
import gzip
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _splunkrest import Mgmt, RestError, load_env  # noqa: E402

HTTPINPUT = "/servicesNS/nobody/splunk_httpinput/data/inputs/http"
MARK_BEGIN = "# BEGIN ai-infra-monitoring"
MARK_END = "# END ai-infra-monitoring"


def write_env(path, updates):
    """Rewrite KEY=VALUE lines for the given keys, keep every other line, append what is missing."""
    lines = []
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    seen = set()
    out = []
    for line in lines:
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if m and m.group(1) in updates:
            out.append("%s=%s" % (m.group(1), updates[m.group(1)]))
            seen.add(m.group(1))
        else:
            out.append(line)
    for k, v in updates.items():
        if k not in seen:
            out.append("%s=%s" % (k, v))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    os.chmod(path, 0o600)


def ensure_token(m, name, indexes, default_index):
    """Return (token, hec_url) after creating/updating the HEC input via REST."""
    g = m.get(HTTPINPUT + "/http")
    gc = g["entry"][0]["content"]
    if str(gc.get("disabled", "0")) in ("1", "true", "True"):
        m.post(HTTPINPUT + "/http", {"disabled": "0"})
        print("enabled the global HEC input")
    port = int(gc.get("port", 8088))
    scheme = "https" if str(gc.get("enableSSL", "1")) in ("1", "true", "True") else "http"
    body = {"index": default_index, "indexes": ",".join(indexes), "disabled": "0", "sourcetype": ""}
    existing = m.get(HTTPINPUT, {"count": 0})
    match = [e for e in existing.get("entry", []) if e["name"] == "http://" + name]
    if match:
        r = m.post(HTTPINPUT + "/" + urllib.parse.quote("http://" + name, safe=""), body)
        print("updated HEC token %s" % name)
    else:
        body["name"] = name
        r = m.post(HTTPINPUT, body)
        print("created HEC token %s" % name)
    token = r["entry"][0]["content"]["token"]
    host = urllib.parse.urlsplit(m.base).hostname or "localhost"
    if host == "127.0.0.1":
        host = "localhost"
    return token, "%s://%s:%d" % (scheme, host, port)


def probe(hec_url, token, use_gzip):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    payload = json.dumps({"event": "hec_probe", "index": "ai_summary", "sourcetype": "ai:hec_probe",
                          "host": "ai-demo-generator", "source": "ai_demo_generator"}).encode("utf-8")
    headers = {"Authorization": "Splunk " + token, "Content-Type": "application/json"}
    if use_gzip:
        payload = gzip.compress(payload)
        headers["Content-Encoding"] = "gzip"
    req = urllib.request.Request(hec_url + "/services/collector/event", data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return False, "HTTP %s %s" % (e.code, e.read().decode("utf-8", "replace")[:200])
    except (urllib.error.URLError, OSError) as e:
        return False, str(e)
    return body.get("code") == 0, json.dumps(body)


def file_provision(splunk_home, name, indexes, default_index):
    path = os.path.join(splunk_home, "etc", "apps", "splunk_httpinput", "local", "inputs.conf")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    existing = open(path, encoding="utf-8").read() if os.path.isfile(path) else ""
    token = None
    m = re.search(re.escape(MARK_BEGIN) + r".*?token\s*=\s*([0-9a-fA-F-]{36}).*?" + re.escape(MARK_END), existing, re.S)
    if m:
        token = m.group(1)
    token = token or str(uuid.uuid4())
    block = "\n".join([MARK_BEGIN, "[http://%s]" % name, "disabled = 0", "index = %s" % default_index,
                       "indexes = %s" % ",".join(indexes), "token = %s" % token, MARK_END, ""])
    if m or (MARK_BEGIN in existing and MARK_END in existing):
        new = re.sub(re.escape(MARK_BEGIN) + r".*?" + re.escape(MARK_END) + r"\n?", block, existing, count=1, flags=re.S)
    else:
        new = existing.rstrip("\n") + ("\n\n" if existing.strip() else "") + block
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(new)
    print("wrote %s (restart Splunk to activate the token)" % path)
    return token


def main(argv=None):
    ap = argparse.ArgumentParser(description="Provision the ai_infra_demo HEC token and record it in .env")
    ap.add_argument("--name", default="ai_infra_demo")
    ap.add_argument("--indexes", default="ai_infra_metrics,ai_infra,ai_network,ai_platform,ai_application,ai_model_eval,ai_cost,ai_security,ai_summary")
    ap.add_argument("--default-index", default="ai_infra")
    ap.add_argument("--env-file", default=".env")
    ap.add_argument("--hec-url", help="override the HEC base URL written to .env and used for the probe")
    ap.add_argument("--file-provision", action="store_true",
                    help="write the token into splunk_httpinput/local/inputs.conf instead of using REST")
    ap.add_argument("--splunk-home", default=os.environ.get("SPLUNK_HOME", "/opt/splunk104"))
    ap.add_argument("--no-probe", action="store_true")
    a = ap.parse_args(argv)
    indexes = [x.strip() for x in a.indexes.split(",") if x.strip()]
    load_env(a.env_file)

    if a.file_provision:
        token = file_provision(a.splunk_home, a.name, indexes, a.default_index)
        hec_url = a.hec_url or os.environ.get("HEC_URL") or "https://localhost:8088"
        write_env(a.env_file, {"AI_DEMO_HEC_TOKEN": token, "HEC_URL": hec_url})
        print("recorded AI_DEMO_HEC_TOKEN and HEC_URL in %s; probe skipped until restart" % a.env_file)
        return 0

    m = Mgmt(env_file=a.env_file)
    if not m.has_creds():
        print("ERROR: no credentials in %s; add SPLUNK_TOKEN or SPLUNK_USERNAME/SPLUNK_PASSWORD, "
              "or rerun with --file-provision" % a.env_file)
        return 2
    try:
        token, hec_url = ensure_token(m, a.name, indexes, a.default_index)
    except RestError as e:
        print("ERROR: %s" % e)
        return 1
    hec_url = a.hec_url or hec_url
    write_env(a.env_file, {"AI_DEMO_HEC_TOKEN": token, "HEC_URL": hec_url})
    print("recorded AI_DEMO_HEC_TOKEN and HEC_URL=%s in %s" % (hec_url, a.env_file))
    if a.no_probe:
        return 0
    ok_id, msg_id = probe(hec_url, token, use_gzip=False)
    ok_gz, msg_gz = probe(hec_url, token, use_gzip=True)
    print("probe identity: %s %s" % ("ok" if ok_id else "FAIL", msg_id))
    print("probe gzip:     %s %s" % ("ok" if ok_gz else "FAIL", msg_gz))
    return 0 if (ok_id and ok_gz) else 1


if __name__ == "__main__":
    sys.exit(main())
