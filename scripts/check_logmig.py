#!/usr/bin/env python3
"""Check one service's hl_log -> harbor_obs migration against docs/LOGGING_STANDARD.md.

Usage: python scripts/check_logmig.py <service> [--base origin/main]

Runs the test suite twice, once on the base revision and once on the working tree, and
records every log line each test emits. It then checks:
  * scope: no hl_log imports left in the service, and no other service, hl_log/ or
    docs/AUDIT.md changed
  * standard: every line is JSON with ts (UTC), level, service, a fixed snake_case
    event and request_id; every log call in the service is exercised by a test
  * personal data: no emails, phone numbers or name-like fields, at any nesting depth;
    emails and phone numbers are redacted from the checker's own output
  * audit: every hl_log.audit() record a base test wrote is still written, unchanged
  * nothing lost: each test writes as many lines as before, and each old message's values
    (including every key=value value) appear as fields of its own new line, which keeps
    the old line's request id
  * alerts: for every base test (which must still run), each alert fires as many times as
    before (rule `XJson` counts as rule `X`); rules are only added, never edited or removed,
    and an `XJson` rule keeps X's threshold and page
  * baseline: the base revision's tests pass, so the replay is meaningful
Exit 0 = pass, 1 = fail, 2 = could not run.
"""
import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import yaml

REQUIRED = ("ts", "level", "service", "event", "request_id")
LEVELS = {"info", "warning", "error"}
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
EVENT_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"\+?\d[\d \-()]{8,}\d")
PII_KEYS = {"email", "email_address", "phone", "phone_number", "mobile", "name",
            "first_name", "last_name", "full_name", "contact_name", "address"}
VALUE_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-]*")
KV_RE = re.compile(r"""\b[A-Za-z_]\w*=["']?([^\s,;()"']+)""")
REDACT_PHONE_RE = re.compile(r"(?<![\w-])\+?\d[\d \-()]{8,}\d(?![\w-])")
LOG_METHODS = {"debug", "info", "warning", "warn", "error", "critical", "exception"}
JSON_RULE_SUFFIX = "Json"


def sh(cmd, cwd, env=None):
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)


def capture(root, tests):
    """Run pytest in `root` with the capture plugin; return recorded entries."""
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    env = dict(os.environ, LOGMIG_CAPTURE=path,
               PYTHONPATH=os.pathsep.join([str(Path(__file__).resolve().parent), str(root)]))
    res = sh([sys.executable, "-m", "pytest", "-q", "-p", "logmig_capture",
              "-p", "no:cacheprovider", *tests], cwd=root, env=env)
    entries = [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]
    os.unlink(path)
    return res, entries


def load_rules(root, rules_path):
    p = Path(root) / rules_path
    return yaml.safe_load(p.read_text()) or [] if p.exists() else []


def fired(line, rules):
    return {r["name"] for r in rules if str(r["match"]).lower() in line.lower()}


def norm1(name):
    return name[: -len(JSON_RULE_SUFFIX)] if name.endswith(JSON_RULE_SUFFIX) else name


def redact(text):
    return REDACT_PHONE_RE.sub("<phone>", EMAIL_RE.sub("<email>", text))


def pii_problems(value, line, path=""):
    out = []
    if isinstance(value, dict):
        for k, v in value.items():
            p = f"{path}.{k}" if path else str(k)
            if str(k).lower() in PII_KEYS:
                out.append(f"personal data: field '{p}' is not allowed (log an id instead): {line}")
            else:
                out += pii_problems(v, line, p)
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            out += pii_problems(v, line, f"{path}[{i}]")
    elif isinstance(value, str) and (EMAIL_RE.search(value) or PHONE_RE.search(value)):
        out.append(f"personal data: field '{path}' looks like an email/phone: {line}")
    return out


def service_of(entry):
    if entry["kind"] in ("hl_log", "audit"):
        return entry["service"]
    try:
        return json.loads(entry["line"]).get("service")
    except ValueError:
        return None


def static_scan(service_dir):
    """Return (hl_log imports, event literals, problems) from the service's source."""
    imports, events, problems = [], set(), []
    for py in sorted(Path(service_dir).rglob("*.py")):
        tree = ast.parse(py.read_text(), filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(a.name.split(".")[0] == "hl_log" for a in node.names):
                imports.append(f"{py}:{node.lineno}")
            elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "hl_log":
                imports.append(f"{py}:{node.lineno}")
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                  and node.func.attr in LOG_METHODS
                  and isinstance(node.func.value, ast.Name) and node.func.value.id != "hl_log"):
                if node.func.attr not in {"info", "warning", "error"}:
                    problems.append(f"{py}:{node.lineno}: level '{node.func.attr}' is not allowed (info/warning/error)")
                first = node.args[0] if node.args else None
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    events.add(first.value)
                else:
                    problems.append(f"{py}:{node.lineno}: event name must be a fixed string literal")
    return imports, events, problems


def value_tokens(msg):
    """Values in an old message: tokens containing a digit or an uppercase letter."""
    out = set()
    for t in VALUE_TOKEN_RE.findall(msg):
        t = t.rstrip(".-")
        if t and (any(c.isdigit() for c in t) or any(c.isupper() for c in t)):
            if not (EMAIL_RE.search(t) or PHONE_RE.fullmatch(t)):
                out.add(t)
    for v in KV_RE.findall(msg):
        v = v.rstrip(".-")
        if v and not (EMAIL_RE.search(v) or PHONE_RE.fullmatch(v)):
            out.add(v)
    return out


def field_tokens(obj):
    out = set()
    for k, v in obj.items():
        if k in ("ts", "level", "service"):
            continue
        out.add(str(v))
        if isinstance(v, str):
            out.update(t.rstrip(".-") for t in VALUE_TOKEN_RE.findall(v))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("service")
    ap.add_argument("--base", default=os.environ.get("LOGMIG_BASE", "origin/main"))
    ap.add_argument("--services-dir", default="services")
    ap.add_argument("--rules", default="alerts/rules.yaml")
    ap.add_argument("--protected", nargs="*", default=["hl_log/", "docs/AUDIT.md"],
                    help="paths a migration PR must not change")
    ap.add_argument("--json", dest="json_out", help="write the report as JSON to this path")
    ap.add_argument("tests", nargs="*", help="pytest args (default: whole suite)")
    a = ap.parse_args()

    head = Path(sh(["git", "rev-parse", "--show-toplevel"], cwd=".").stdout.strip() or ".")
    svc, svc_dir = a.service, head / a.services_dir / a.service
    fails, warns = [], []
    prefix = f"{a.services_dir}/"
    if not svc_dir.is_dir():
        print(f"no such service directory: {svc_dir}")
        return 2

    # Scope
    changed = sh(["git", "diff", "--name-only", f"{a.base}...HEAD"], cwd=head).stdout.split()
    changed += sh(["git", "diff", "--name-only", "HEAD"], cwd=head).stdout.split()
    changed += sh(["git", "ls-files", "--others", "--exclude-standard"], cwd=head).stdout.split()
    changed = sorted(set(changed))
    for f in changed:
        if f.startswith(prefix) and not f.startswith(f"{prefix}{svc}/"):
            fails.append(f"scope: {f} belongs to another service (one service per PR)")
        if any(f == p or f.startswith(p) for p in a.protected):
            fails.append(f"scope: {f} is protected and must not change in a migration PR")

    imports, events, problems = static_scan(svc_dir)
    fails += [f"hl_log import left: {i}" for i in imports]
    fails += [f"source: {p}" for p in problems]

    # Base run (old lines)
    with tempfile.TemporaryDirectory() as tmp:
        wt = Path(tmp) / "base"
        res = sh(["git", "worktree", "add", "--detach", str(wt), a.base], cwd=head)
        if res.returncode:
            print(f"could not check out base {a.base}: {res.stderr}")
            return 2
        try:
            base_res, base_entries = capture(wt, a.tests)
            base_rules = load_rules(wt, a.rules)
        finally:
            sh(["git", "worktree", "remove", "--force", str(wt)], cwd=head)
    if base_res.returncode:
        fails.append("baseline: pytest failed on the base revision, so the old lines and alerts "
                     "can't be replayed (fix main first)\n" + base_res.stdout[-2000:])

    # Head run (new lines)
    res, head_entries = capture(head, a.tests)
    if res.returncode:
        fails.append("tests: pytest failed on the working tree\n" + res.stdout[-2000:])
    head_rules = load_rules(head, a.rules)

    def belongs(e):
        stack = e.get("stack") or ([e["caller"]] if e.get("caller") else [])
        if any(f.startswith(f"{prefix}{svc}/") for f in stack):
            return True
        return not any(f.startswith(prefix) for f in stack) and service_of(e) == svc

    head_tests = {e["test"] for e in head_entries if e["kind"] == "test"}
    old = [e for e in base_entries if e["kind"] == "hl_log" and belongs(e)]
    new = [e for e in head_entries if e["kind"] in ("hl_log", "harbor_obs") and belongs(e)]
    if not old:
        warns.append("baseline: no hl_log lines from this service in the base run (nothing to compare)")
    if not new:
        fails.append("standard: the tests produced no log lines for this service")

    # Standard + personal data, per line
    seen_events, by_test_new, samples = set(), defaultdict(list), {}
    for e in new:
        line = e["line"]
        if e["kind"] == "hl_log":
            fails.append(f"standard: line still written by hl_log: {line}")
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            obj = None
        if not isinstance(obj, dict):
            fails.append(f"standard: not JSON ({e.get('caller')}): {line}")
            by_test_new[e["test"]].append((line, {}))
            continue
        by_test_new[e["test"]].append((line, obj))
        missing = [k for k in REQUIRED if k not in obj]
        if missing:
            fails.append(f"standard: missing {missing}: {line}")
        if not TS_RE.match(str(obj.get("ts", ""))):
            fails.append(f"standard: ts is not UTC ISO-8601 ending in Z: {line}")
        if obj.get("level") not in LEVELS:
            fails.append(f"standard: level must be one of {sorted(LEVELS)}: {line}")
        if obj.get("service") != svc:
            fails.append(f"standard: service must be '{svc}': {line}")
        ev = obj.get("event")
        if not isinstance(ev, str) or not EVENT_RE.match(ev):
            fails.append(f"standard: event must be short snake_case: {line}")
        elif events and ev not in events:
            fails.append(f"standard: event '{ev}' is not a fixed name from the source: {line}")
        seen_events.add(ev)
        samples.setdefault(ev, line)
        if obj.get("request_id") is None:
            warns.append(f"standard: request_id is null: {line}")
        fails += pii_problems({k: v for k, v in obj.items() if k != "ts"}, line)
    for ev in sorted(events - seen_events):
        fails.append(f"coverage: event '{ev}' is never emitted by the tests (add a test for that path)")

    def alert_counts(lines, rules):
        counts = Counter()
        for line in lines:
            counts.update(norm1(n) for n in fired(line, rules))
        return counts

    # Nothing lost (line by line) + alerts (counts), per baseline test
    by_test_old = defaultdict(list)
    for e in old:
        by_test_old[e["test"]].append(e)
    alert_rows = []
    for test in sorted(by_test_old):
        if test not in head_tests:
            fails.append(f"baseline: test {test} from the base revision no longer runs; keep existing "
                         "test names so its lines and alerts can be replayed")
            continue
        old_lines, new_lines = by_test_old[test], by_test_new.get(test, [])
        if len(old_lines) != len(new_lines):
            fails.append(f"nothing lost: {test} wrote {len(old_lines)} line(s) before and {len(new_lines)} after")
        for e, (_, obj) in zip(old_lines, new_lines):
            if e.get("rid") and obj.get("request_id") is None:
                fails.append(f"standard: request_id is null but the old line had rid={e['rid']} ({test})")
            lost = sorted(value_tokens(e["msg"]) - field_tokens(obj))
            if lost:
                fails.append(f"nothing lost: {lost} from old line '{e['msg']}' are not fields of its new line ({test})")
        before = alert_counts([e["line"] for e in old_lines], base_rules)
        after = alert_counts([l for l, _ in new_lines], head_rules)
        alert_rows.append({"test": test, "before": dict(before), "after": dict(after)})
        for name in sorted(set(before) | set(after)):
            b, n = before[name], after[name]
            if b != n:
                kind = "missed page" if n < b else "false page"
                fails.append(f"alerts: {name} fired {b} time(s) before but {n} after ({test}) - {kind}")
    for test, lines in by_test_new.items():
        if test not in by_test_old:
            old_fired = alert_counts([e["line"] for e in old], base_rules)
            for name in sorted(alert_counts([l for l, _ in lines], head_rules)):
                if name not in old_fired:
                    fails.append(f"alerts: {name} fires in new test {test} but no old line fired it - false page")

    # Audit trail (docs/AUDIT.md): every record a base test wrote must still be written
    def audits(entries):
        out = defaultdict(list)
        for e in entries:
            if e["kind"] == "audit" and belongs(e):
                out[e["test"]].append([e["service"], e["action"], e["fields"]])
        return out
    base_tests = {e["test"] for e in base_entries if e["kind"] == "test"}
    base_audit, head_audit = audits(base_entries), audits(head_entries)
    for test in sorted(set(base_audit) | (set(head_audit) & base_tests)):
        if base_audit.get(test, []) != head_audit.get(test, []):
            fails.append(f"audit: {test} wrote {base_audit.get(test, [])} to the audit trail before and "
                         f"{head_audit.get(test, [])} after; docs/AUDIT.md says it must not change")

    # Rule changes: only additions; an XJson rule must keep X's threshold and page
    base_by, head_by = {r["name"]: r for r in base_rules}, {r["name"]: r for r in head_rules}
    for name in sorted(set(base_by) - set(head_by)):
        fails.append(f"alerts: rule {name} was removed; keep it until every instance runs the new code")
    for name in sorted(set(base_by) & set(head_by)):
        if base_by[name] != head_by[name]:
            fails.append(f"alerts: rule {name} was edited; migration PRs may only add rules")
    for name in sorted(set(head_by) - set(base_by)):
        if not name.endswith(JSON_RULE_SUFFIX):
            continue
        orig = base_by.get(name[: -len(JSON_RULE_SUFFIX)])
        if orig is None:
            warns.append(f"alerts: {name} has no base rule {name[: -len(JSON_RULE_SUFFIX)]} to mirror")
            continue
        for key in ("threshold", "page"):
            if head_by[name].get(key) != orig.get(key):
                fails.append(f"alerts: {name} {key} '{head_by[name].get(key)}' differs from "
                             f"{orig['name']} '{orig.get(key)}'; the replacement must page the same way")
    touched = sorted(n for n in set(base_by) | set(head_by) if base_by.get(n) != head_by.get(n))

    fails, warns = [redact(f) for f in fails], [redact(w) for w in warns]
    samples = {ev: redact(line) for ev, line in samples.items()}
    report = {"service": svc, "passed": not fails, "failures": fails, "warnings": warns,
              "alerts_touched": touched, "alert_replay": alert_rows, "samples": samples,
              "changed_files": changed}
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(report, indent=2))

    print(f"logmig check: {svc} -> {'PASS' if not fails else 'FAIL'}")
    for f in fails:
        print(f"  FAIL {f}")
    for w in warns:
        print(f"  WARN {w}")
    print(f"  alerts touched: {', '.join(touched) or 'none'}")
    for row in alert_rows:
        print(f"  alert replay {row['test']}: before={row['before']} after={row['after']}")
    for ev, line in sorted(samples.items()):
        print(f"  sample {ev}: {line}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
