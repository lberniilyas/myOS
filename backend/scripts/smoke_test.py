"""Check a running Personal OS from the outside. Read-only: it never creates or changes anything.

    python scripts/smoke_test.py https://personal-os-k8t0.onrender.com --production
    python scripts/smoke_test.py http://127.0.0.1:8000

--release SHA   also wait until the server reports this commit (used right after a deploy)
--wait SECONDS  how long to wait for the server to wake up or the deploy to land (default 180)
--production    also check what only a public deployment does: sign-up closed, API docs hidden

Exits 0 when every check passes, 1 otherwise. Uses only the standard library.
"""

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

TIMEOUT = 30


def request(
    url: str, method: str = "GET", body: dict | None = None, token: str | None = None
) -> tuple[int, dict, bytes]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json", "User-Agent": "personal-os-smoke-test"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def as_json(raw: bytes) -> dict:
    try:
        return json.loads(raw)
    except ValueError:
        return {}


def is_newer_or_same(expected: str, reported: str) -> bool:
    """True when the server runs the expected commit or one that contains it (a later push)."""
    if reported.startswith(expected) or expected.startswith(reported):
        return True
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", expected, reported], capture_output=True
    )
    return result.returncode == 0


def wait_for_server(base: str, release: str | None, wait: float) -> dict:
    deadline = time.monotonic() + wait
    last = "no answer yet"
    while time.monotonic() < deadline:
        try:
            status, _, raw = request(f"{base}/health")
            health = as_json(raw)
            if status == 200 and health.get("status") == "ok":
                if not release or is_newer_or_same(release, health.get("release", "")):
                    return health
                last = f"still running {health.get('release')}, waiting for {release[:12]}"
            else:
                last = f"HTTP {status}"
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            last = f"{type(error).__name__}: {error}"
        print(f"  waiting for {base} ({last})", flush=True)
        time.sleep(10)
    raise SystemExit(f"FAIL  the server didn't come up within {wait:.0f} s ({last})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base_url")
    parser.add_argument("--release")
    parser.add_argument("--wait", type=float, default=180)
    parser.add_argument("--production", action="store_true")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    health = wait_for_server(base, args.release, args.wait)
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail and not ok else ''}")
        if not ok:
            failures.append(name)

    check(
        "health check answers",
        True,
    )
    print(f"      release {health.get('release')}, AI provider {health.get('ai_provider')}")
    if args.production:
        check(
            "the real AI is configured",
            health.get("ai_provider") in ("gemini", "anthropic"),
            str(health.get("ai_provider")),
        )

    status, headers, raw = request(f"{base}/")
    page = raw.decode("utf-8", "replace")
    check(
        "the app's page loads",
        status == 200 and "<title>Personal OS</title>" in page,
        f"HTTP {status}",
    )
    scripts = re.findall(r'src="(/assets/[^"]+\.js)"', page)
    asset_status = request(f"{base}{scripts[0]}")[0] if scripts else None
    check("its script loads", asset_status == 200, f"{scripts[:1]} -> {asset_status}")
    for path in ("/manifest.webmanifest", "/sw.js", "/icons/apple-touch-icon.png"):
        check(f"{path} is served", request(f"{base}{path}")[0] == 200)

    lowered = {k.lower(): v for k, v in headers.items()}
    check(
        "content security policy",
        "frame-ancestors 'none'" in lowered.get("content-security-policy", ""),
    )
    check("nosniff header", lowered.get("x-content-type-options") == "nosniff")
    check("clickjacking header", lowered.get("x-frame-options") == "DENY")

    status, _, raw = request(f"{base}/v1/does-not-exist")
    check(
        "unknown API paths are JSON 404s",
        status == 404 and as_json(raw).get("error", {}).get("code") == "NOT_FOUND",
        f"HTTP {status}",
    )
    status, _, raw = request(f"{base}/v1/me")
    check(
        "signed-out requests are refused",
        status == 401 and as_json(raw).get("error", {}).get("code") == "NOT_AUTHENTICATED",
        f"HTTP {status}",
    )
    status, _, raw = request(
        f"{base}/v1/auth/login",
        "POST",
        {"email": "smoke-test@example.invalid", "password": "not-a-real-password"},
    )
    check(
        "the server reads its database (unknown sign-in is refused)",
        status == 401 and as_json(raw).get("error", {}).get("code") == "INVALID_CREDENTIALS",
        f"HTTP {status} {raw[:120]!r}",
    )

    status, _, raw = request(f"{base}/v1/review/weekly")
    check(
        "the weekly review exists and needs signing in",
        status == 401 and as_json(raw).get("error", {}).get("code") == "NOT_AUTHENTICATED",
        f"HTTP {status}",
    )
    status, _, raw = request(
        f"{base}/v1/captures?background=true",
        "POST",
        {"content": "smoke test", "input_type": "VOICE"},
        token="pos_key_smoke-test-not-a-real-key-0000000000000000",
    )
    check(
        "Shortcut keys are checked (a made-up key is refused)",
        status == 401 and as_json(raw).get("error", {}).get("code") == "INVALID_KEY",
        f"HTTP {status} {raw[:120]!r}",
    )

    if args.production:
        status, _, raw = request(
            f"{base}/v1/auth/register",
            "POST",
            {"email": "smoke-test@example.invalid", "password": "correct horse battery"},
        )
        check(
            "sign-up is closed to strangers",
            status == 403 and as_json(raw).get("error", {}).get("code") == "REGISTRATION_CLOSED",
            f"HTTP {status}",
        )
        status, _, raw = request(f"{base}/openapi.json")
        check("API docs are hidden", b'"openapi"' not in raw, f"HTTP {status}")

    print(f"\n{'All checks passed.' if not failures else f'{len(failures)} check(s) failed.'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
