"""SnapTrade request-signature auth.

The signature must byte-match the official SDK's scheme: HMAC-SHA256 over a
compact, sorted-key JSON of {"content": body_or_None, "path", "query"}, keyed on
the consumer_key, base64-encoded. A drift here (dropping sort_keys, changing the
separators, or signing body={} as {} instead of None) fails auth silently, so
this pins both the exact output bytes and the algorithm.
"""

import base64
import hashlib
import hmac
import json

from trading_clients.snaptrade_client import compute_signature

CONSUMER = "test-consumer-key"


def _reference(path_with_query: str, consumer_key: str, body) -> str:
    """Independent re-derivation of the documented algorithm."""
    subpath, _, query = path_with_query.partition("?")
    obj = {"content": None if body is None or body == {} else body, "path": subpath, "query": query}
    content = json.dumps(obj, separators=(",", ":"), sort_keys=True)
    return base64.b64encode(
        hmac.new(consumer_key.encode(), content.encode(), hashlib.sha256).digest()
    ).decode()


def test_matches_independent_reference_get_and_post():
    get_path = "/accounts?clientId=ABC&userId=u&userSecret=s&timestamp=1700000000"
    post_path = "/snapTrade/registerUser?clientId=ABC&timestamp=1700000000"
    assert compute_signature(get_path, CONSUMER, None) == _reference(get_path, CONSUMER, None)
    assert compute_signature(post_path, CONSUMER, {"userId": "u1"}) == _reference(
        post_path, CONSUMER, {"userId": "u1"}
    )


def test_known_good_vectors():
    # Regression lock — these bytes must not change.
    assert (
        compute_signature(
            "/accounts?clientId=ABC&userId=u&userSecret=s&timestamp=1700000000", CONSUMER, None
        )
        == "cH45SLeRT6NmpT7jrh2USYGgMAPBlDAn6yt6mXLAcDQ="
    )
    assert (
        compute_signature(
            "/snapTrade/registerUser?clientId=ABC&timestamp=1700000000", CONSUMER, {"userId": "u1"}
        )
        == "w3MxiftF1xpl/n+NaI377XCo2I5rCFZz3I+u/RGnCf4="
    )


def test_empty_body_signs_as_null_content():
    path = "/snapTrade/login?clientId=ABC&timestamp=1700000000"
    # body={} must sign identically to body=None (content -> null), else login auth fails.
    assert compute_signature(path, CONSUMER, {}) == compute_signature(path, CONSUMER, None)
    assert compute_signature(path, CONSUMER, {}) == "a2S8ph7KaYeGBWSIhJfgwVlPv3tnd2/i8w5R2oeeLtM="
