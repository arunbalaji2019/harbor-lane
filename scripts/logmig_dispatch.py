"""Start or stop logmig sessions through the Devin v3 API (the "Run/Stop migration" workflows).

    python scripts/logmig_dispatch.py run  --services all --max-acu 10 --issue 4 [--dry-run]
    python scripts/logmig_dispatch.py stop --services all --issue 4 [--dry-run]

run:  one session per selected service, following .agents/skills/logmig/SKILL.md. Skips a service
      that is already migrated (no hl_log import left), has an open `[logmig] <service>:` PR, has a
      running tagged session, or (unless --include-needs-human) is marked `needs human` in the
      tracking issue. Each session is tagged, capped at --max-acu ACUs, and linked in its row.
stop: terminates the running tagged sessions and marks their rows `stopped`.

Env: DEVIN_API_KEY (service-user key, cog_...), DEVIN_ORG_ID (org-...), GH_TOKEN, GITHUB_REPOSITORY.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from logmig_progress import END, START, build_body, gh, row_of

API = "https://api.devin.ai/v3"
BASE_TAG = "logmig"
ACTIVE = {"new", "claimed", "running", "resuming", "suspended"}
ROOT = Path(__file__).resolve().parents[1]
SERVICE_RE = re.compile(r"^[a-z0-9_]+$")
HL_LOG_IMPORT_RE = re.compile(r"^\s*(import\s+hl_log\b|from\s+hl_log\b)", re.M)
RESULT_SCHEMA = {
    "type": "object",
    "required": ["repo", "service", "status"],
    "properties": {
        "repo": {"type": "string"},
        "service": {"type": "string"},
        "status": {"enum": ["pr_opened", "needs_human", "nothing_to_do", "already_open"]},
        "pr_url": {"type": ["string", "null"]},
        "checker_passed": {"type": ["boolean", "null"]},
        "ci_passed": {"type": ["boolean", "null"]},
        "alerts_touched": {"type": "array", "items": {"type": "string"}},
        "needs_human_reason": {"type": ["string", "null"]},
    },
}


def repo_tag(repo):
    return f"{BASE_TAG}-{repo.split('/')[-1]}"


def service_tag(repo, svc):
    return f"{repo_tag(repo)}-{svc}"


def row_key(repo, svc):
    return f"{repo.split('/')[-1]}/{svc}"


def cell(text):
    return str(text).replace("|", "\\|").replace("<", "").replace(">", "")


def row_text(repo, svc, status, pr="", checker="", session_url=""):
    link = f"[session]({session_url})" if session_url else ""
    cells = [row_key(repo, svc), status, pr, checker, link]
    return "<!-- logmig-row -->\n| " + " | ".join(cell(c) for c in cells) + " |"


def discover(services_dir=ROOT / "services"):
    return sorted(p.name for p in services_dir.iterdir()
                  if p.is_dir() and SERVICE_RE.match(p.name) and any(p.glob("*.py")))


def select(spec, available):
    if spec.strip().lower() in ("", "all"):
        return list(available)
    wanted = list(dict.fromkeys(s for s in re.split(r"[,\s]+", spec.strip()) if s))
    unknown = [s for s in wanted if s not in available]
    if unknown:
        raise SystemExit(f"unknown service(s): {', '.join(unknown)} (known: {', '.join(available)})")
    return wanted


def still_uses_hl_log(svc, services_dir=ROOT / "services"):
    return any(HL_LOG_IMPORT_RE.search(p.read_text()) for p in (services_dir / svc).rglob("*.py"))


def plan(selected, unmigrated, open_pr_titles, running, row_status, include_needs_human=False):
    """Return [(service, 'start' | 'skip', reason)] for each selected service."""
    out = []
    for svc in selected:
        pr = next((t for t in open_pr_titles if t.startswith(f"[logmig] {svc}:")), None)
        status = row_status.get(svc, "")
        if svc not in unmigrated:
            out.append((svc, "skip", "already migrated (no hl_log import)"))
        elif pr:
            out.append((svc, "skip", f"open PR: {pr}"))
        elif svc in running:
            out.append((svc, "skip", f"session already running: {running[svc]}"))
        elif status.startswith("needs human") and not include_needs_human:
            out.append((svc, "skip", f"tracking issue says '{status}'"))
        else:
            out.append((svc, "start", ""))
    return out


def prompt(repo, svc, issue, comment_id):
    return f"""Migrate the `{svc}` service in {repo} from hl_log to harbor_obs.

Follow `.agents/skills/logmig/SKILL.md` exactly; the rules in `AGENTS.md` override it. You run
unattended: never wait for approval (commit messages included). If you are blocked, report
`needs_human` with the reason and stop.

Tracking issue: {repo}#{issue}. Your progress row is issue comment {comment_id}. Edit that
comment when your status changes (keep `<!-- logmig-row -->` as its first line and keep the
session link); don't post another row comment.

Finish with the structured output described in the skill."""


def session_body(repo, svc, issue, comment_id, max_acu):
    return {
        "title": f"[logmig] {row_key(repo, svc)}",
        "prompt": prompt(repo, svc, issue, comment_id),
        "repos": [repo],
        "tags": [BASE_TAG, repo_tag(repo), service_tag(repo, svc)],
        "max_acu_limit": max_acu,
        "structured_output_schema": RESULT_SCHEMA,
    }


class Devin:
    def __init__(self, key, org):
        self.key, self.org = key, org

    def call(self, method, path, body=None, query=None):
        url = f"{API}/organizations/{self.org}{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query, doseq=True)
        req = urllib.request.Request(url, method=method,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {self.key}",
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as res:
                data = res.read()
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{method} {path} -> HTTP {e.code}: {e.read().decode()[:300]}") from None
        return json.loads(data) if data else {}

    def sessions(self, tags):
        items, after = [], None
        while True:
            query = {"tags": tags, "first": 100, **({"after": after} if after else {})}
            page = self.call("GET", "/sessions", query=query)
            items += [s for s in page.get("items", []) if set(tags) <= set(s.get("tags") or [])]
            after = page.get("end_cursor")
            if not page.get("has_next_page") or not after:
                return items

    def create(self, body):
        return self.call("POST", "/sessions", body)

    def terminate(self, session_id):
        sid = session_id if session_id.startswith("devin-") else f"devin-{session_id}"
        return self.call("DELETE", f"/sessions/{sid}")


def tagged_service(session, repo):
    prefix = repo_tag(repo) + "-"
    return next((t[len(prefix):] for t in session.get("tags") or [] if t.startswith(prefix)), None)


class Issue:
    def __init__(self, repo, number):
        self.repo, self.number = repo, number

    def comments(self):
        pages = json.loads(gh("--paginate", "--slurp", f"repos/{self.repo}/issues/{self.number}/comments?per_page=100"))
        return [c for page in pages for c in page]

    def rows(self):
        """{service key: (comment, cells)} for the latest row comment per service."""
        out = {}
        for c in sorted(self.comments(), key=lambda c: c.get("updated_at") or ""):
            row = row_of(c)
            if row:
                cells = [x.strip() for x in re.split(r"(?<!\\)\|", row[1:-1])]
                out[cells[0]] = (c, cells)
        return out

    def require_table(self):
        body = json.loads(gh(f"repos/{self.repo}/issues/{self.number}"))["body"] or ""
        if START not in body or END not in body:
            raise SystemExit(f"tracking issue #{self.number} has no {START} ... {END} markers; add them first")

    def upsert_row(self, existing, body):
        if existing:
            try:
                gh("-X", "PATCH", f"repos/{self.repo}/issues/comments/{existing['id']}", "-f", f"body={body}")
                return existing["id"]
            except Exception as e:
                print(f"  could not edit comment {existing['id']} ({e}); posting a new row")
        made = json.loads(gh(f"repos/{self.repo}/issues/{self.number}/comments", "-f", f"body={body}"))
        return made["id"]

    def rebuild(self):
        issue = json.loads(gh(f"repos/{self.repo}/issues/{self.number}"))
        new = build_body(issue["body"], self.comments())
        if new != issue["body"]:
            gh("-X", "PATCH", f"repos/{self.repo}/issues/{self.number}", "-f", f"body={new}")


def summary(lines):
    print("\n".join(lines))
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as f:
            f.write("\n".join(lines) + "\n")


def open_pr_titles(repo):
    prs = json.loads(gh("--paginate", "--slurp", f"repos/{repo}/pulls?state=open&per_page=100"))
    return [p["title"] for page in prs for p in page]


def run(a, repo, devin, issue):
    issue.require_table()
    selected = select(a.services, discover())
    unmigrated = {s for s in selected if still_uses_hl_log(s)}
    titles = open_pr_titles(repo)
    rows = issue.rows()
    running = {}
    if devin:
        for s in devin.sessions([BASE_TAG, repo_tag(repo)]):
            svc = tagged_service(s, repo)
            if svc and s.get("status") in ACTIVE:
                running[svc] = s.get("url") or s.get("session_id")
    else:
        print("WARN no DEVIN_API_KEY/DEVIN_ORG_ID: running sessions not checked (dry run only)")
    status = {svc: rows[row_key(repo, svc)][1][1] for svc in selected if row_key(repo, svc) in rows}
    decisions = plan(selected, unmigrated, titles, running, status, a.include_needs_human)

    lines = [f"## Run migration{' (dry run)' if a.dry_run else ''}: {repo}, max {a.max_acu} ACUs/session", "",
             "| service | action | reason |", "|---|---|---|"]
    lines += [f"| {svc} | {act} | {cell(why)} |" for svc, act, why in decisions]
    summary(lines)
    if a.dry_run:
        return 0

    failed = 0
    for svc, act, _ in decisions:
        if act != "start":
            continue
        existing = rows.get(row_key(repo, svc), (None, None))[0]
        cid = issue.upsert_row(existing, row_text(repo, svc, "in progress (starting)"))
        try:
            s = devin.create(session_body(repo, svc, a.issue, cid, a.max_acu))
        except Exception as e:
            failed += 1
            issue.upsert_row({"id": cid}, row_text(repo, svc, "needs human: dispatch failed", checker=str(e)[:120]))
            print(f"FAILED {svc}: {e}")
            continue
        print(f"started {svc}: {s['url']}")
        try:
            issue.upsert_row({"id": cid}, row_text(repo, svc, "in progress", session_url=s["url"]))
        except Exception as e:
            print(f"WARN {svc}: session started ({s['url']}) but its row could not be updated: {e}")
    issue.rebuild()
    return 1 if failed else 0


def stop(a, repo, devin, issue):
    issue.require_table()
    selected = set(select(a.services, discover()))
    targets = [s for s in devin.sessions([BASE_TAG, repo_tag(repo)])
               if s.get("status") not in ("exit", "error") and tagged_service(s, repo) in selected]
    lines = [f"## Stop migration{' (dry run)' if a.dry_run else ''}: {repo}", "",
             "| service | session | status |", "|---|---|---|"]
    lines += [f"| {tagged_service(s, repo)} | {s.get('url')} | {s.get('status')} |" for s in targets]
    summary(lines if targets else lines[:1] + ["", "No running logmig sessions."])
    if a.dry_run:
        return 0
    rows = issue.rows()
    for s in targets:
        svc = tagged_service(s, repo)
        devin.terminate(s["session_id"])
        existing, cells = rows.get(row_key(repo, svc), (None, None))
        pr, checker = (cells[2], cells[3]) if cells else ("", "")
        issue.upsert_row(existing, row_text(repo, svc, "stopped", pr.replace("\\|", "|"),
                                            checker.replace("\\|", "|"), s.get("url", "")))
        print(f"stopped {svc}: {s.get('url')}")
    issue.rebuild()
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["run", "stop"])
    ap.add_argument("--services", default="all")
    ap.add_argument("--issue", type=int, required=True)
    ap.add_argument("--max-acu", type=int, default=10)
    ap.add_argument("--include-needs-human", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.max_acu < 1:
        raise SystemExit("--max-acu must be at least 1")
    repo = os.environ.get("GITHUB_REPOSITORY") or "arunbalaji2019/harbor-lane"
    key, org = os.environ.get("DEVIN_API_KEY"), os.environ.get("DEVIN_ORG_ID")
    devin = Devin(key, org) if key and org else None
    if devin is None and (a.command == "stop" or not a.dry_run):
        raise SystemExit("DEVIN_API_KEY and DEVIN_ORG_ID must be set (see the workflow's setup notes)")
    issue = Issue(repo, a.issue)
    return (run if a.command == "run" else stop)(a, repo, devin, issue)


if __name__ == "__main__":
    sys.exit(main())
