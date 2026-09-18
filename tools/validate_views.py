#!/usr/bin/env python3
"""Structural validation of the ai_infra_monitoring Dashboard Studio views, nav, wording and palette.

Per view: XML parses; version="2" theme="dark"; <label>/<description> equal the JSON title/description;
no "]]>" inside the JSON; every visualization/input dataSource id exists; every layout item exists;
every globalInputs entry is an input; every $token$ is defined by an input token, a defaults entry or
is a row/result/click token; every drilldown.linkToDashboard target view file exists.
Also: nav/default.xml lists all ten views in spec order; the forbidden-wording grep
over default/, lookups/, docs/, bin/, README/CHANGELOG is empty; every hex colour is in the palette.
Exit 1 on any error.
"""
import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

VIEW_ORDER = [
    "ai_stack_overview", "ai_infrastructure_health", "ai_network_fabric", "ai_platform_workloads",
    "ai_applications", "model_performance_quality", "ai_agents", "ai_cost_unit_economics",
    "ai_security_posture", "ai_operations_executive_overview",
]
PALETTE = {
    "#7B56DB", "#009CEB", "#00CDAF", "#DD9900", "#FF677B", "#CB2196",   # series
    "#53A051", "#F8BE34", "#F1813F", "#E0453A",                         # status
    "#FFFFFF", "#7F8A95",                                               # neutral text / target line
    "#171D21", "#1A1C20", "#212527", "#2B3033", "#31373D", "#3C444D", "#000000",  # dark card fills
}
WORDING = re.compile("|".join(["sam" "ple", "illus" "trative", "mock" "up"]), re.I)
TOKEN_RE = re.compile(r"\$([A-Za-z0-9_.:|]+)\$")
HEX_RE = re.compile(r"#[0-9A-Fa-f]{6}\b")
TEXT_EXT = (".conf", ".xml", ".csv", ".md", ".py", ".sh", ".txt", ".json", ".html", ".spec")


def walk_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from walk_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_strings(v)


def validate_view(path, views_dir, errors, warnings, strict_palette):
    name = os.path.splitext(os.path.basename(path))[0]
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        errors.append("%s: XML parse error: %s" % (name, e))
        return
    if root.tag != "dashboard":
        errors.append("%s: root element is <%s>, expected <dashboard>" % (name, root.tag))
    if root.get("version") != "2":
        errors.append("%s: version=%r, expected \"2\"" % (name, root.get("version")))
    if root.get("theme") != "dark":
        errors.append("%s: theme=%r, expected \"dark\"" % (name, root.get("theme")))
    d = root.find("definition")
    if d is None or not (d.text or "").strip():
        errors.append("%s: missing <definition>" % name)
        return
    raw = d.text
    if "]]>" in raw:
        errors.append("%s: JSON contains ']]>'" % name)
    try:
        defn = json.loads(raw)
    except json.JSONDecodeError as e:
        errors.append("%s: JSON parse error: %s" % (name, e))
        return
    label = (root.findtext("label") or "").strip()
    desc = (root.findtext("description") or "").strip()
    if label != (defn.get("title") or "").strip():
        errors.append("%s: <label> %r != title %r" % (name, label, defn.get("title")))
    if desc != (defn.get("description") or "").strip():
        errors.append("%s: <description> differs from JSON description" % name)
    ds = defn.get("dataSources") or {}
    inputs = defn.get("inputs") or {}
    vizs = defn.get("visualizations") or {}
    for kind, coll in (("visualization", vizs), ("input", inputs)):
        for vid, v in coll.items():
            for role, ref in (v.get("dataSources") or {}).items():
                if ref not in ds:
                    errors.append("%s: %s %s references missing dataSource %r" % (name, kind, vid, ref))
    layout = defn.get("layout") or {}
    for item in layout.get("structure") or []:
        iid = item.get("item")
        if iid not in vizs and iid not in inputs:
            errors.append("%s: layout item %r is not a visualization or input" % (name, iid))
    for gi in layout.get("globalInputs") or []:
        if gi not in inputs:
            errors.append("%s: globalInputs entry %r is not an input" % (name, gi))
    if inputs and not layout.get("globalInputs"):
        warnings.append("%s: inputs defined but layout.globalInputs is empty" % name)
    # tokens
    defined = set()
    for _, inp in inputs.items():
        tok = (inp.get("options") or {}).get("token")
        if tok:
            defined.add(tok)
            if inp.get("type") == "input.timerange":
                defined.update({tok + ".earliest", tok + ".latest"})
    for tokdef in (defn.get("defaults") or {}).get("tokens", {}).get("default", {}) if isinstance((defn.get("defaults") or {}).get("tokens"), dict) else {}:
        defined.add(tokdef)
    for s in walk_strings({"dataSources": ds, "visualizations": vizs, "inputs": inputs}):
        for tk in TOKEN_RE.findall(s):
            base = tk.split("|")[0]
            if base.startswith(("row.", "result.", "click.", "name", "value", "trellis.", "form.")):
                continue
            if base not in defined:
                errors.append("%s: token $%s$ is not defined by any input" % (name, base))
    # drilldown targets
    for vid, v in vizs.items():
        for h in v.get("eventHandlers") or []:
            if h.get("type") == "drilldown.linkToDashboard":
                target = (h.get("options") or {}).get("dashboard")
                if target and not os.path.isfile(os.path.join(views_dir, target + ".xml")):
                    errors.append("%s: linkToDashboard target %r has no view file" % (name, target))
    # palette
    bad = sorted({c.upper() for c in HEX_RE.findall(raw) if c.upper() not in PALETTE})
    if bad:
        (errors if strict_palette else warnings).append("%s: colours outside the palette: %s" % (name, ", ".join(bad)))
    # wording
    for s in walk_strings(defn):
        if WORDING.search(s):
            errors.append("%s: wording violation in %r" % (name, s[:80]))
            break


def validate_nav(app_dir, views_dir, errors, warnings):
    nav = os.path.join(app_dir, "default", "data", "ui", "nav", "default.xml")
    if not os.path.isfile(nav):
        errors.append("nav: default/data/ui/nav/default.xml is missing")
        return
    try:
        root = ET.parse(nav).getroot()
    except ET.ParseError as e:
        errors.append("nav: XML parse error: %s" % e)
        return
    listed = [v.get("name") for v in root.iter("view") if v.get("name")]
    for name in listed:
        if name != "search" and not os.path.isfile(os.path.join(views_dir, name + ".xml")):
            errors.append("nav: view %r has no XML file" % name)
    ours = [v for v in listed if v in VIEW_ORDER]
    if ours != VIEW_ORDER:
        errors.append("nav: view order is %s, expected %s" % (ours, VIEW_ORDER))
    dflt = [v.get("name") for v in root.iter("view") if v.get("default") == "true"]
    if dflt != ["ai_stack_overview"]:
        warnings.append("nav: default view is %s, expected ai_stack_overview" % dflt)


def check_wording(app_dir, errors):
    scan = ["default", "lookups", "docs", "bin", "static", "README.md", "CHANGELOG.md", "LICENSE"]
    for rel in scan:
        p = os.path.join(app_dir, rel)
        if os.path.isfile(p):
            files = [p]
        elif os.path.isdir(p):
            files = [os.path.join(dp, f) for dp, _, fs in os.walk(p) for f in fs]
        else:
            continue
        for f in files:
            if not f.endswith(TEXT_EXT) and os.path.basename(f) != "LICENSE":
                continue
            try:
                with open(f, encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh, 1):
                        if WORDING.search(line):
                            errors.append("wording: %s:%d: %s" % (os.path.relpath(f, app_dir), i, line.strip()[:80]))
                            break
            except OSError:
                pass


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate ai_infra_monitoring views, nav, wording and palette")
    ap.add_argument("views", nargs="?", default=None, help="views directory (default: <app-dir>/default/data/ui/views)")
    ap.add_argument("--app-dir", default=".")
    ap.add_argument("--views", dest="views_opt", default=None)
    ap.add_argument("--strict-palette", action="store_true", help="treat off-palette colours as errors")
    ap.add_argument("--no-wording", action="store_true")
    a = ap.parse_args(argv)
    app_dir = os.path.abspath(a.app_dir)
    views_dir = a.views_opt or a.views or os.path.join(app_dir, "default", "data", "ui", "views")
    if not os.path.isabs(views_dir):
        views_dir = os.path.join(app_dir, views_dir) if not os.path.isdir(views_dir) else os.path.abspath(views_dir)
    errors, warnings = [], []
    files = sorted(f for f in os.listdir(views_dir) if f.endswith(".xml")) if os.path.isdir(views_dir) else []
    if not files:
        errors.append("views: no XML files in %s" % views_dir)
    for f in files:
        n_before = len(errors)
        validate_view(os.path.join(views_dir, f), views_dir, errors, warnings, a.strict_palette)
        print("%-40s %s" % (f, "OK" if len(errors) == n_before else "%d error(s)" % (len(errors) - n_before)))
    present = {os.path.splitext(f)[0] for f in files}
    for v in VIEW_ORDER:
        if v not in present:
            errors.append("views: expected view %s.xml is missing" % v)
    validate_nav(app_dir, views_dir, errors, warnings)
    if not a.no_wording:
        check_wording(app_dir, errors)
    for w in warnings:
        print("WARNING: " + w)
    for e in errors:
        print("ERROR: " + e)
    print("validate_views: %d error(s), %d warning(s)" % (len(errors), len(warnings)))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
