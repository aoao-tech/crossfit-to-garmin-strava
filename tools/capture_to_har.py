"""Convert an HTTP Toolkit MCP dump into a sanitized HAR file.

Usage: python tools/capture_to_har.py captures/raw/arbox_raw.json captures/clean.har

Everything personal or secret is replaced with synthetic values, so the
output can be fed to mitmproxy2swagger and its examples stay safe.
The raw dump and the HAR are both gitignored; only the curated spec is committed.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

API_HOST = "apiappv2.arboxapp.com"

DROP_HEADERS = {
    "accesstoken", "refreshtoken", "authorization", "cookie", "set-cookie",
    "baggage", "sentry-trace", "x-forwarded-for",
}
SECRET_KEYS = {"password", "token", "refreshtoken", "accesstoken", "devicetoken", "pushtoken"}
PERSONAL_KEYS = {
    "email", "first_name", "last_name", "full_name", "last_name_shorten", "full_name_shorten",
    "phone", "image", "cloudinary_image", "address", "birthday", "city",
}
TEXT_KEYS = {"comment", "description", "notes"}
ID_KEY = re.compile(r"(^id$|_id$|_fk$|^fk_)", re.IGNORECASE)
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")

SYNTHETIC = {
    "email": "member@example.com",
    "password": "REDACTED",
    "comment": "SAMPLE SECTION TEXT\n10 SAMPLE REPS",
}


def scrub(value: Any, key: str = "") -> Any:
    """Return a sanitized copy of a JSON value. Never mutates the input."""
    lowered = key.lower()
    if isinstance(value, dict):
        return {k: scrub(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v, key) for v in value]
    if value is None or isinstance(value, bool):
        return value
    if lowered in SECRET_KEYS:
        return SYNTHETIC.get(lowered, "REDACTED")
    if lowered in PERSONAL_KEYS:
        return SYNTHETIC.get(lowered, "REDACTED")
    if lowered in TEXT_KEYS:
        return SYNTHETIC["comment"]
    if isinstance(value, (int, float)) and ID_KEY.search(key):
        return 1000
    if isinstance(value, str) and lowered == "name" and not ISO_DATE.match(value):
        return "Sample Name"
    return value


def scrub_body(text: str) -> str:
    if not text:
        return ""
    try:
        return json.dumps(scrub(json.loads(text)), ensure_ascii=False)
    except json.JSONDecodeError:
        return "REDACTED-NON-JSON"


def scrub_path(url: str) -> str:
    """Replace numeric path segments (IDs) with a fixed number."""
    return re.sub(r"/\d+(?=/|$)", "/1000", url)


def to_headers(raw: dict[str, Any]) -> list[dict[str, str]]:
    headers = []
    for name, val in (raw or {}).items():
        if name.lower() in DROP_HEADERS:
            continue
        values = val if isinstance(val, list) else [val]
        headers.extend({"name": name, "value": str(v)} for v in values)
    return headers


def to_entry(item: dict[str, Any]) -> dict[str, Any]:
    outline, event = item["outline"], item["event"]
    req, res = outline.get("request") or {}, outline.get("response") or {}
    req_body = scrub_body((item.get("request_body") or {}).get("body") or "")
    res_body = scrub_body((item.get("response_body") or {}).get("body") or "")
    return {
        "startedDateTime": "2026-01-01T00:00:00.000Z",
        "time": 0,
        "request": {
            "method": event["method"], "url": scrub_path(event["url"]), "httpVersion": "HTTP/1.1",
            "headers": to_headers(req.get("headers")), "queryString": [], "cookies": [],
            "headersSize": -1, "bodySize": len(req_body),
            **({"postData": {"mimeType": "application/json", "text": req_body}} if req_body else {}),
        },
        "response": {
            "status": event["status"], "statusText": "", "httpVersion": "HTTP/1.1",
            "headers": to_headers(res.get("headers")), "cookies": [],
            "content": {"size": len(res_body), "mimeType": "application/json", "text": res_body},
            "redirectURL": "", "headersSize": -1, "bodySize": len(res_body),
        },
        "cache": {}, "timings": {"send": 0, "wait": 0, "receive": 0},
    }


def build_har(dump: list[dict[str, Any]]) -> dict[str, Any]:
    entries = [to_entry(x) for x in dump if API_HOST in x["event"]["url"]]
    return {"log": {"version": "1.2", "creator": {"name": "capture_to_har", "version": "1"}, "entries": entries}}


def find_leaks(text: str, forbidden: list[str]) -> list[str]:
    lowered = text.lower()
    return [f for f in forbidden if f and f.lower() in lowered]


def main(src: str, dst: str, patterns_file: str = ".personal-patterns") -> int:
    dump = json.loads(Path(src).read_text(encoding="utf-8"))
    har_text = json.dumps(build_har(dump), ensure_ascii=False, indent=1)
    patterns = Path(patterns_file)
    forbidden = [
        line.strip() for line in patterns.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ] if patterns.exists() else []
    leaks = find_leaks(har_text, forbidden)
    if leaks or re.search(r"eyJ[A-Za-z0-9_-]{10,}", har_text):
        print(f"ABORT: sanitized HAR still contains {len(leaks)} personal value(s) or a JWT. Nothing written.")
        return 1
    Path(dst).write_text(har_text, encoding="utf-8")
    print(f"wrote {dst} with {len(json.loads(har_text)['log']['entries'])} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
