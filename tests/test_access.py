"""Trial passwords: valid until their expiry, tamper-proof, cancelled by a new main password."""
import datetime as dt

from punctualiti.access import IST, check, make_trial

MASTER = "main-secret-for-tests"
NOW = dt.datetime(2026, 11, 12, 19, 30, tzinfo=IST)


def test_main_password():
    assert check(MASTER, MASTER).ok
    assert check(f"  {MASTER}  ", MASTER).ok
    assert not check("nope", MASTER).ok


def test_open_when_no_password_configured():
    assert check("", "").ok


def test_trial_valid_then_expires():
    pw, expires = make_trial(MASTER, 24, now=NOW)
    assert pw.startswith("trial-202611131931-")
    assert check(pw, MASTER, now=NOW).ok
    assert check(pw, MASTER, now=expires - dt.timedelta(minutes=1)).ok
    late = check(pw, MASTER, now=expires + dt.timedelta(seconds=1))
    assert not late.ok and "expired" in late.message


def test_trial_cannot_be_extended_by_editing():
    pw, _ = make_trial(MASTER, 24, now=NOW)
    forged = pw.replace("trial-20261113", "trial-20261213")
    assert not check(forged, MASTER, now=NOW).ok


def test_new_main_password_cancels_trials():
    pw, _ = make_trial(MASTER, 24, now=NOW)
    assert not check(pw, "rotated-main-password", now=NOW).ok
