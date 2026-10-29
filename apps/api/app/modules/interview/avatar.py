from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
from collections.abc import Mapping
from urllib.parse import quote

ALGORITHM = "HMAC-SHA256"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def _encode(value: str) -> str:
    return quote(str(value), safe="-_.~")


def _hmac_sha256(key: bytes, value: str) -> bytes:
    return hmac.new(key, value.encode(), hashlib.sha256).digest()


def _canonical_query(params: Mapping[str, str]) -> str:
    return "&".join(f"{_encode(key)}={_encode(value)}" for key, value in sorted(params.items()))


def create_avatar_wss_token(
    access_key_id: str,
    secret_access_key: str,
    *,
    request_time: dt.datetime | None = None,
) -> str:
    """Create the Base64-encoded signed config required by Avatar Web SDK."""
    host = "visual.volcengineapi.com"
    region = "cn-beijing"
    service = "cv"
    params = {"Action": "ConnectWebsocket", "Version": "2022-08-31"}
    query = _canonical_query(params)
    now = request_time or dt.datetime.now(dt.UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.UTC)
    now = now.astimezone(dt.UTC)
    long_date = now.strftime("%Y%m%dT%H%M%SZ")
    short_date = long_date[:8]
    scope = f"{short_date}/{region}/{service}/request"
    signed_headers = "host;x-date"
    canonical_headers = f"host:{host}\nx-date:{long_date}"
    canonical_request = f"GET\n/\n{query}\n{canonical_headers}\n\n{signed_headers}\n{EMPTY_SHA256}"
    string_to_sign = "\n".join(
        [ALGORITHM, long_date, scope, hashlib.sha256(canonical_request.encode()).hexdigest()]
    )
    key = _hmac_sha256(secret_access_key.encode(), short_date)
    key = _hmac_sha256(key, region)
    key = _hmac_sha256(key, service)
    key = _hmac_sha256(key, "request")
    signature = hmac.new(key, string_to_sign.encode(), hashlib.sha256).hexdigest()
    authorization = (
        f"{ALGORITHM} Credential={access_key_id}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    signed_config = {
        "url": f"https://{host}?{query}",
        "header": {"X-Date": long_date, "Authorization": authorization, "Host": host},
    }
    compact_json = json.dumps(signed_config, separators=(",", ":"), ensure_ascii=False)
    return base64.b64encode(compact_json.encode()).decode()
