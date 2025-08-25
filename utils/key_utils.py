import hashlib
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

def normalize_url(u: str) -> str:
    if not u:
        return ""
    parts = urlsplit(u.strip())
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, query, ""))

def sha256_hex(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()