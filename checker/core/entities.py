"""Identity clues and timestamps found in OCR text (plan.md §6.4)."""

import re
from datetime import datetime

from checker.config import get_settings

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
WIN_PATH = re.compile(r"[a-z]:\\users\\([^\\\s:*?\"<>|]+)[^\s\"<>|]*", re.I)
UNIX_PATH = re.compile(r"/(?:home|users)/([\w.-]+)[^\s\"'<>]*", re.I)
PROMPT = re.compile(r"\b([a-z_][\w.-]{1,31})@([a-z][\w-]{1,62})(?=[:\s$#~])", re.I)
TIME = r"\d{1,2}:\d{2}(?::\d{2})?(?:\s?[ap]\.?m\.?)?"
DATE = (r"(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/.]\d{1,2}[/.]\d{2,4}|"
        r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\b,?(?:\s+\d{4})?)")
TIMESTAMP = re.compile(rf"(?:{DATE}[\sT,]+{TIME}|{TIME}[\s,]+{DATE}|{DATE})", re.I)
# Usernames that are not identities.
GENERIC_USERS = {"root", "admin", "user", "public", "default", "administrator", "ubuntu", "pi", "runner", "git"}


def parse_timestamp(raw: str) -> datetime | None:
    import dateparser
    return dateparser.parse(raw, settings={"STRICT_PARSING": False, "PREFER_DAY_OF_MONTH": "first",
                                           "RETURN_AS_TIMEZONE_AWARE": False})


def extract_entities(text: str) -> list[dict]:
    """-> [{type, raw, normalized}] for usernames, hostnames, paths, emails, student IDs, timestamps."""
    if not text:
        return []
    out = []

    def add(type_, raw, norm=None):
        norm = (norm if norm is not None else raw).strip().lower()
        if norm:
            out.append({"type": type_, "raw": raw.strip(), "normalized": norm})

    for m in EMAIL.finditer(text):
        add("email", m.group())
    for m in PROMPT.finditer(text):
        if m.group(2).lower() not in {"gmail", "outlook", "yahoo"}:
            add("username", m.group(1))
            add("hostname", m.group(2))
    for rx in (WIN_PATH, UNIX_PATH):
        for m in rx.finditer(text):
            add("path", m.group())
            add("username", m.group(1))
    for m in re.finditer(get_settings().student_id_regex, text):
        add("student_id", m.group())
    for m in TIMESTAMP.finditer(text):
        raw = m.group()
        if not re.search(r"\d", raw):
            continue
        dt = parse_timestamp(raw)
        if dt:
            has_time = re.search(TIME, raw) is not None
            add("timestamp", raw, dt.isoformat(timespec="minutes") if has_time else dt.date().isoformat())
    out = [e for e in out if not (e["type"] == "username" and e["normalized"] in GENERIC_USERS)]
    seen, uniq = set(), []
    for e in out:
        if (e["type"], e["normalized"]) not in seen:
            seen.add((e["type"], e["normalized"]))
            uniq.append(e)
    return uniq


if __name__ == "__main__":
    ents = extract_entities("PS C:\\Users\\jdoe42\\Desktop\\hw> python a.py\nalice@lab-pc:~$ ls\n"
                            "mail bob.smith@uni.edu 2024-03-05 14:22 id S1234567")
    got = {(e["type"], e["normalized"]) for e in ents}
    for want in [("username", "jdoe42"), ("username", "alice"), ("hostname", "lab-pc"),
                 ("email", "bob.smith@uni.edu"), ("timestamp", "2024-03-05t14:22"), ("student_id", "s1234567")]:
        assert want in got, (want, got)
    print("ok")
