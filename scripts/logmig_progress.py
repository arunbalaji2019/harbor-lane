"""Rebuild the `logmig progress` issue table from per-service row comments.

Each migration session owns ONE comment on the tracking issue:

    <!-- logmig-row -->
    | harbor-lane/bookings | PR open | owner/repo#1 | PASS | [session](https://...) |

Sessions never edit the issue body, so concurrent sessions can't overwrite each other.
The `logmig progress` workflow runs this script on every comment change on any issue whose
body has the table markers (one run at a time per issue) and regenerates the table between
the markers from all row comments. It refuses to touch an issue without the markers.

    python scripts/logmig_progress.py --repo owner/repo --issue 4
"""
import argparse
import json
import re
import subprocess

ROW_MARKER = "<!-- logmig-row -->"
START, END = "<!-- logmig-table:start -->", "<!-- logmig-table:end -->"
HEADER = "| service | status | PR | checker result | session |\n|---|---|---|---|---|"
TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}


def row_of(comment):
    body = (comment.get("body") or "").strip()
    trusted = comment.get("author_association") in TRUSTED or (comment.get("user") or {}).get("type") == "Bot"
    if not trusted or not body.startswith(ROW_MARKER):
        return None
    for line in body.splitlines()[1:]:
        line = line.strip()
        if not (line.startswith("|") and line.endswith("|")):
            continue
        # Dropping < and > keeps a row from injecting markers or HTML into the body.
        # Cells escape pipes as \|; a row that still doesn't split into 5 cells is shown
        # as malformed rather than dropped or shifted into the wrong columns.
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", re.sub(r"[<>]", "", line)[1:-1])]
        if len(cells) != 5:
            cells = [cells[0], "needs human: malformed progress row", "", "", ""]
        return "| " + " | ".join(cells) + " |"
    return None


def build_body(body, comments):
    rows = {}
    for c in sorted(comments, key=lambda c: c.get("updated_at") or ""):
        row = row_of(c)
        if row:
            rows[row.split("|")[1].strip()] = row
    table = "\n".join([START, HEADER, *(rows[k] for k in sorted(rows)), END])
    body = body or ""
    if START not in body or END not in body:
        raise ValueError(f"issue body has no {START} ... {END} markers; add them where the table goes")
    before, rest = body.split(START, 1)
    return before + table + rest.split(END, 1)[1]


def gh(*args):
    return subprocess.run(["gh", "api", *args], check=True, capture_output=True, text=True).stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--issue", required=True, type=int)
    a = ap.parse_args()
    issue = json.loads(gh(f"repos/{a.repo}/issues/{a.issue}"))
    comments = json.loads(gh("--paginate", "--slurp", f"repos/{a.repo}/issues/{a.issue}/comments"))
    comments = [c for page in comments for c in page]
    new = build_body(issue["body"], comments)
    if new != issue["body"]:
        gh("-X", "PATCH", f"repos/{a.repo}/issues/{a.issue}", "-f", f"body={new}")
        print("table updated")
    else:
        print("table unchanged")


if __name__ == "__main__":
    main()
