import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from logmig_progress import END, ROW_MARKER, START, build_body  # noqa: E402

BOOKINGS = "| harbor-lane/bookings | PR open | owner/repo#1 | PASS | [session](s1) |"
PAYMENTS = "| harbor-lane/payments | in progress | | | [session](s2) |"


def comment(row, updated="2026-11-04T10:00:00Z", assoc="NONE", user_type="Bot"):
    return {"body": f"{ROW_MARKER}\n{row}", "updated_at": updated,
            "author_association": assoc, "user": {"type": user_type}}


def test_rows_from_concurrent_sessions_are_all_kept():
    body = build_body(f"intro\n\n{START}\nstale\n{END}\nfooter", [comment(BOOKINGS), comment(PAYMENTS)])
    assert BOOKINGS in body and PAYMENTS in body
    assert body.startswith("intro\n\n") and body.endswith("footer") and "stale" not in body


def test_latest_comment_for_a_service_wins():
    old = comment(BOOKINGS.replace("PR open", "in progress"), updated="2026-11-04T09:00:00Z")
    body = build_body("", [comment(BOOKINGS), old])
    assert BOOKINGS in body and "in progress" not in body


def test_untrusted_and_unmarked_comments_are_ignored():
    stranger = comment(PAYMENTS, assoc="NONE", user_type="User")
    unmarked = {"body": BOOKINGS, "updated_at": "x", "author_association": "OWNER", "user": {"type": "User"}}
    body = build_body("", [stranger, unmarked])
    assert PAYMENTS not in body and BOOKINGS not in body


def test_rows_with_html_or_extra_cells_are_ignored():
    injected = comment(f"| harbor-lane/x | ok | | | {END} |")
    extra = comment("| harbor-lane/y | ok | | | | extra |")
    body = build_body(f"{START}\n{END}", [injected, extra, comment(BOOKINGS)])
    assert "harbor-lane/x" not in body and "harbor-lane/y" not in body and BOOKINGS in body
    assert body.count(END) == 1
