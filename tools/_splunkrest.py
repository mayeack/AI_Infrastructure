#!/usr/bin/env python3
"""Shared Splunk REST helper for the ai_infra_monitoring tools (stdlib only, Python 3.9+).

Auth contract: SPLUNK_TOKEN (bearer) preferred, else SPLUNK_USERNAME / SPLUNK_PASSWORD (basic).
SPLUNK_MGMT_URL defaults to https://127.0.0.1:8090. TLS is not verified (local demo box).
"""
import argparse
import base64
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

APP = "ai_infra_monitoring"


def load_env(path=".env"):
    """Read KEY=VALUE lines from a .env file into os.environ (existing vars win)."""
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and v and not os.environ.get(k):
                os.environ[k] = v


class RestError(Exception):
    def __init__(self, status, body, url=""):
        super().__init__("HTTP %s on %s: %s" % (status, url, body[:400]))
        self.status = status
        self.body = body


class Mgmt:
    """Minimal management-port client: GET/POST with json output, blocking searches, dispatch."""

    def __init__(self, base=None, token=None, username=None, password=None, env_file=".env"):
        load_env(env_file)
        self.base = (base or os.environ.get("SPLUNK_MGMT_URL") or "https://127.0.0.1:8090").rstrip("/")
        self.token = token or os.environ.get("SPLUNK_TOKEN") or ""
        self.username = username or os.environ.get("SPLUNK_USERNAME") or ""
        self.password = password or os.environ.get("SPLUNK_PASSWORD") or ""
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE

    def has_creds(self):
        return bool(self.token or (self.username and self.password))

    def _auth_header(self):
        if self.token:
            return "Bearer " + self.token
        if self.username and self.password:
            raw = ("%s:%s" % (self.username, self.password)).encode("utf-8")
            return "Basic " + base64.b64encode(raw).decode("ascii")
        raise RestError(0, "no credentials: set SPLUNK_TOKEN or SPLUNK_USERNAME/SPLUNK_PASSWORD in .env")

    def request(self, method, path, params=None, data=None, timeout=120, raw=False):
        url = self.base + path
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
        body = None
        headers = {"Authorization": self._auth_header()}
        if data is not None:
            body = urllib.parse.urlencode(data, doseq=True).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, context=self.ctx, timeout=timeout) as resp:
                text = resp.read().decode("utf-8", "replace")
                status = resp.status
        except urllib.error.HTTPError as e:
            raise RestError(e.code, e.read().decode("utf-8", "replace"), url)
        if raw:
            return text
        try:
            return json.loads(text) if text else {}
        except ValueError:
            return {"raw": text, "status": status}

    def get(self, path, params=None, **kw):
        p = {"output_mode": "json"}
        p.update(params or {})
        return self.request("GET", path, p, **kw)

    def post(self, path, data=None, params=None, **kw):
        p = {"output_mode": "json"}
        p.update(params or {})
        return self.request("POST", path, p, data or {}, **kw)

    # ----------------------------------------------------------------- apps
    def app_exists(self, app):
        try:
            self.get("/services/apps/local/%s" % app)
            return True
        except RestError as e:
            if e.status == 404:
                return False
            raise

    def indexes(self, prefix=""):
        r = self.get("/services/data/indexes", {"count": 0, "search": prefix} if prefix else {"count": 0})
        return {e["name"]: e.get("content", {}) for e in r.get("entry", [])}

    # -------------------------------------------------------------- search
    def search(self, spl, earliest="-24h", latest="now", timeout=300, app=APP, count=0):
        """Run a blocking search in the app namespace. Returns (rows, messages)."""
        q = spl.strip()
        if not q.startswith("|") and not q.lower().startswith("search "):
            q = "search " + q
        data = {
            "search": q,
            "exec_mode": "blocking",
            "earliest_time": earliest,
            "latest_time": latest,
            "adhoc_search_level": "fast",
            "timeout": timeout,
        }
        r = self.post("/servicesNS/nobody/%s/search/jobs" % app, data, timeout=timeout + 30)
        sid = r.get("sid")
        if not sid:
            raise RestError(0, "no sid in response: %s" % json.dumps(r)[:300])
        res = self.get("/servicesNS/nobody/%s/search/jobs/%s/results" % (app, sid), {"count": count}, timeout=timeout)
        rows = res.get("results", [])
        messages = res.get("messages", [])
        try:
            job = self.get("/servicesNS/nobody/%s/search/jobs/%s" % (app, sid))
            for e in job.get("entry", []):
                for m in e.get("content", {}).get("messages", []):
                    if m not in messages:
                        messages.append(m)
        except RestError:
            pass
        return rows, messages

    def search_value(self, spl, earliest="-24h", latest="now", field="value"):
        rows, msgs = self.search(spl, earliest, latest)
        if not rows:
            return None, msgs
        v = rows[0].get(field)
        try:
            return float(v), msgs
        except (TypeError, ValueError):
            return v, msgs

    # ------------------------------------------------------------ dispatch
    def dispatch_saved_search(self, name, app=APP, **params):
        """POST .../saved/searches/<name>/dispatch; returns sid."""
        path = "/servicesNS/nobody/%s/saved/searches/%s/dispatch" % (app, urllib.parse.quote(name, safe=""))
        r = self.post(path, params)
        return r.get("sid")

    def wait_job(self, sid, app=APP, timeout=300):
        t0 = time.time()
        while time.time() - t0 < timeout:
            job = self.get("/servicesNS/nobody/%s/search/jobs/%s" % (app, sid))
            c = job.get("entry", [{}])[0].get("content", {})
            if c.get("isDone"):
                return c
            time.sleep(2)
        raise RestError(0, "job %s did not finish in %ss" % (sid, timeout))

    def saved_searches(self, app=APP):
        r = self.get("/servicesNS/nobody/%s/saved/searches" % app, {"count": 0, "search": "eai:acl.app=%s" % app})
        return {e["name"]: e.get("content", {}) for e in r.get("entry", [])}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Splunk REST helper checks (used by the Makefile)")
    ap.add_argument("--env-file", default=".env")
    ap.add_argument("--check-indexes", help="comma-separated index names that must exist")
    ap.add_argument("--check-app", help="app id that must be installed")
    ap.add_argument("--reload-inputs", action="store_true", help="POST data/inputs/script/_reload")
    ap.add_argument("--run", help="run one SPL and print rows as JSON")
    ap.add_argument("--earliest", default="-24h")
    ap.add_argument("--latest", default="now")
    a = ap.parse_args(argv)
    m = Mgmt(env_file=a.env_file)
    if not m.has_creds():
        print("WARNING: no credentials in %s (SPLUNK_TOKEN or SPLUNK_USERNAME/SPLUNK_PASSWORD); skipping REST checks" % a.env_file)
        return 0
    rc = 0
    if a.check_app:
        ok = m.app_exists(a.check_app)
        print("app %s: %s" % (a.check_app, "installed" if ok else "MISSING"))
        rc |= 0 if ok else 1
    if a.check_indexes:
        have = m.indexes()
        for ix in a.check_indexes.split(","):
            ok = ix in have
            dt = have.get(ix, {}).get("datatype", "event") if ok else "-"
            print("index %-18s %s (%s)" % (ix, "present" if ok else "MISSING", dt))
            rc |= 0 if ok else 1
    if a.reload_inputs:
        m.post("/servicesNS/nobody/%s/data/inputs/script/_reload" % APP)
        print("scripted inputs reloaded")
    if a.run:
        rows, msgs = m.search(a.run, a.earliest, a.latest)
        print(json.dumps({"rows": rows, "messages": msgs}, indent=1))
    return rc


if __name__ == "__main__":
    sys.exit(main())
