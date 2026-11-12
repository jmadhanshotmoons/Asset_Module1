"""Access control: the main APP_PASSWORD, plus self-expiring trial passwords.

A trial password looks like  trial-202611131930-3fa9c2d1e7
                                   └ expiry ┘   └ signature ┘
The expiry (India time, YYYYMMDDHHMM) is signed with APP_PASSWORD, so it can't be edited to
last longer, and nothing has to be stored or configured on the server. Changing APP_PASSWORD
cancels every trial password.

Create one:  python -m punctualiti.access --hours 24
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import os
import re
from dataclasses import dataclass

IST = dt.timezone(dt.timedelta(hours=5, minutes=30), "IST")
_TRIAL = re.compile(r"trial-(\d{12})-([0-9a-f]{10})")


@dataclass
class Access:
    ok: bool
    message: str = ""
    expires: dt.datetime | None = None   # set for trial passwords


def _signature(master: str, stamp: str) -> str:
    return hmac.new(master.encode(), f"trial:{stamp}".encode(), hashlib.sha256).hexdigest()[:10]


def make_trial(master: str, hours: float = 24, now: dt.datetime | None = None) -> tuple[str, dt.datetime]:
    """Return (password, expiry) for a trial lasting `hours` from now (rounded up to the minute)."""
    if not master:
        raise ValueError("APP_PASSWORD is not set; it is needed to sign trial passwords.")
    now = (now or dt.datetime.now(IST)).astimezone(IST)
    expires = (now + dt.timedelta(hours=hours)).replace(second=0, microsecond=0) + dt.timedelta(minutes=1)
    stamp = expires.strftime("%Y%m%d%H%M")
    return f"trial-{stamp}-{_signature(master, stamp)}", expires


def check(given: str, master: str | None = None, now: dt.datetime | None = None) -> Access:
    """Is `given` the main password, or a valid, unexpired trial password?"""
    master = os.environ.get("APP_PASSWORD", "") if master is None else master
    if not master:
        return Access(True)  # no password configured: open (local use)
    given = (given or "").strip()
    if given and hmac.compare_digest(given.encode(), master.encode()):
        return Access(True)

    m = _TRIAL.fullmatch(given)
    if m and hmac.compare_digest(m.group(2), _signature(master, m.group(1))):
        expires = dt.datetime.strptime(m.group(1), "%Y%m%d%H%M").replace(tzinfo=IST)
        if (now or dt.datetime.now(IST)) < expires:
            return Access(True, expires=expires)
        return Access(False, f"This trial password expired on {fmt(expires)}. "
                             "Please ask Madhan for a new one.", expires)
    return Access(False, "Wrong access password.")


def fmt(t: dt.datetime) -> str:
    return t.astimezone(IST).strftime("%d %b %Y, %I:%M %p IST")


def main(argv: list[str] | None = None) -> int:
    from .env import load_dotenv

    p = argparse.ArgumentParser(prog="python -m punctualiti.access", description="Create a self-expiring trial password.")
    p.add_argument("--hours", type=float, default=24, help="how long it stays valid (default 24)")
    args = p.parse_args(argv)
    load_dotenv()
    password, expires = make_trial(os.environ.get("APP_PASSWORD", ""), args.hours)
    print(password)
    print(f"Valid until {fmt(expires)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
