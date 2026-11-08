"""
Login logic for Basil BACnet Explorer (desktop and Android) - no GUI imports.

* Default account: admin / Basil@12345 (the password can be changed in File > Change password).
* Passwords are stored only as a salted PBKDF2-SHA256 hash in the settings file.
* "Remember me" (auto login) stores a token bound to this computer + Windows user and the
  current password hash: copying the settings file to another PC, or changing the password,
  cancels it.
"""
from __future__ import annotations

import getpass
import hashlib
import hmac
import os
import secrets
import socket
import sys
import time
from typing import Any, Dict, Optional

DEFAULT_USER = "admin"
DEFAULT_PASSWORD = "Basil@12345"
ITERATIONS = 200_000
MAX_TRIES = 5
LOCK_SECONDS = 30
EXTRA_MACHINE_ID = ""      # set by the Android app (ANDROID_ID) to bind auto login to the phone


def hash_password(password: str, salt: bytes, iterations: int = ITERATIONS) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations).hex()


def machine_key() -> str:
    """Identifies this computer + OS user (not secret, just binds the auto-login token)."""
    parts = []
    for fn in (getpass.getuser, socket.gethostname):
        try:
            parts.append(str(fn()))
        except Exception:          # Android has no passwd entry for the app user
            pass
    if EXTRA_MACHINE_ID:
        parts.append(EXTRA_MACHINE_ID)
    if sys.platform.startswith("win"):
        try:
            import winreg  # type: ignore
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,  # type: ignore
                                r"SOFTWARE\Microsoft\Cryptography") as k:
                parts.append(str(winreg.QueryValueEx(k, "MachineGuid")[0]))  # type: ignore
        except Exception:
            pass
    return "|".join(parts)


class Auth:
    def __init__(self, settings: Dict[str, Any]):
        self.settings = settings

    # ---- account record
    def record(self) -> Dict[str, Any]:
        rec = self.settings.get("auth")
        if not isinstance(rec, dict) or not {"user", "salt", "hash"} <= set(rec):
            salt = secrets.token_bytes(16)
            rec = {"user": DEFAULT_USER, "salt": salt.hex(), "iter": ITERATIONS,
                   "hash": hash_password(DEFAULT_PASSWORD, salt)}
            self.settings["auth"] = rec
        return rec

    def check(self, user: str, password: str) -> bool:
        rec = self.record()
        calc = hash_password(password, bytes.fromhex(rec["salt"]), int(rec.get("iter", ITERATIONS)))
        user_ok = hmac.compare_digest(user.strip().lower().encode(), str(rec["user"]).lower().encode())
        return user_ok and hmac.compare_digest(calc, rec["hash"])

    def change_password(self, old: str, new: str) -> Optional[str]:
        """Returns an error message, or None when changed."""
        rec = self.record()
        if not self.check(rec["user"], old):
            return "The current password is not correct."
        if len(new) < 8 or new.lower() == new or new.upper() == new or \
                not any(c.isdigit() for c in new):
            return "Use at least 8 characters with upper- and lower-case letters and a number."
        salt = secrets.token_bytes(16)
        rec.update(salt=salt.hex(), iter=ITERATIONS, hash=hash_password(new, salt))
        self.disable_autologin()          # old token was bound to the old password
        return None

    # ---- auto login
    def _token(self) -> str:
        rec = self.record()
        return hmac.new(bytes.fromhex(rec["hash"]), machine_key().encode(), "sha256").hexdigest()

    def enable_autologin(self):
        self.settings["autologin"] = self._token()

    def disable_autologin(self):
        self.settings.pop("autologin", None)

    def autologin_ok(self) -> bool:
        tok = self.settings.get("autologin")
        return isinstance(tok, str) and hmac.compare_digest(tok, self._token())

    # ---- restart without asking again (one-time token, valid 60 s)
    def make_restart_token(self) -> str:
        tok = secrets.token_hex(16)
        self.settings["restart_token"] = {"t": tok, "time": time.time()}
        return tok

    def use_restart_token(self, tok: Optional[str]) -> bool:
        rec = self.settings.pop("restart_token", None)
        return bool(tok and isinstance(rec, dict) and time.time() - float(rec.get("time", 0)) < 60
                    and hmac.compare_digest(str(rec.get("t", "")), tok))


# ---------------------------------------------------------------- 30-day trial
TRIAL_DAYS = 30
DAY = 86400.0
# activation password, stored only as a salted PBKDF2 hash (the password itself is not in the app)
_ACT_SALT = bytes.fromhex("e9e564a39205d4e00d2ee9555b3a03c8")
_ACT_HASH = "78139751316210e7fbbb00ece4aa6e685503e83ff8d1ef7f9365b4fdde09efd5"
_SIGN_KEY = bytes.fromhex("9313e40290df94da23108e2ac974a710")


class Trial:
    """The app runs for TRIAL_DAYS days from its first start; after that it stops until the
    activation password is entered once (then it is activated for good on this install).

    The record in the settings is signed, so editing the dates in the file ends the trial,
    and moving the phone's clock back does not give extra days (the latest time seen is kept)."""

    def __init__(self, settings: Dict[str, Any], days: int = TRIAL_DAYS):
        self.settings = settings
        self.days = days

    @staticmethod
    def _sig(*parts: Any) -> str:
        return hmac.new(_SIGN_KEY, "|".join(str(p) for p in parts).encode(), "sha256").hexdigest()

    def _rec(self) -> Dict[str, Any]:
        rec = self.settings.get("trial")
        if not isinstance(rec, dict) or "start" not in rec:
            now = round(time.time())
            rec = {"start": now, "last": now, "sig": self._sig("t", now, now)}
            self.settings["trial"] = rec
        return rec

    def _valid(self, rec: Dict[str, Any]) -> bool:
        return hmac.compare_digest(str(rec.get("sig", "")), self._sig("t", rec.get("start"), rec.get("last")))

    def activated(self) -> bool:
        rec = self._rec()
        return hmac.compare_digest(str(rec.get("act", "")), self._sig("activated", rec.get("start")))

    def touch(self):
        """Remember the latest time seen (call at start and from time to time)."""
        rec = self._rec()
        if not self._valid(rec):
            return
        last = max(int(rec["last"]), round(time.time()))
        if last != rec["last"]:
            rec["last"] = last
            rec["sig"] = self._sig("t", rec["start"], last)

    def days_used(self) -> float:
        rec = self._rec()
        if not self._valid(rec):
            return float(self.days)                      # edited record -> trial over
        now = max(time.time(), float(rec["last"]))       # clock moved back -> use latest seen
        return max(0.0, (now - float(rec["start"])) / DAY)

    def days_left(self) -> int:
        return max(0, int(-(-(self.days - self.days_used()) // 1)))   # rounded up

    def expired(self) -> bool:
        return not self.activated() and self.days_used() >= self.days

    def expiry_date(self) -> str:
        rec = self._rec()
        return time.strftime("%d %b %Y", time.localtime(float(rec["start"]) + self.days * DAY))

    def activate(self, password: str) -> bool:
        if not hmac.compare_digest(hash_password(password, _ACT_SALT), _ACT_HASH):
            return False
        rec = self._rec()
        if not self._valid(rec):                         # repair an edited record
            rec["last"] = max(int(rec.get("last") or 0), round(time.time()))
            rec["sig"] = self._sig("t", rec["start"], rec["last"])
        rec["act"] = self._sig("activated", rec["start"])
        return True
