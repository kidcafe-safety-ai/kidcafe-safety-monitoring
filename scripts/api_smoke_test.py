"""실행 중인 Backend API를 빠르게 점검한다 (Final Phase).

Docker Compose나 로컬 uvicorn을 띄운 뒤 실행한다. 표준 라이브러리만 사용하므로
Vision AI 의존성 없이 어느 환경에서나 돌릴 수 있다.

    python scripts/api_smoke_test.py
    python scripts/api_smoke_test.py --base-url http://localhost:8000
    python scripts/api_smoke_test.py --write   # 테스트 Event 1건을 실제 DB에 저장

기본은 읽기 전용이다. `--write`는 `video_source="api-smoke-test"`인 Event를 한 건
저장하고 같은 event_id 재전송이 409인지 확인한다. 저장된 Event는 Report·Summary
집계에 포함되므로 시연·제출용 DB에서는 쓰지 않는다.

모든 항목이 통과하면 종료 코드 0, 하나라도 실패하면 1이다.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple
from uuid import uuid4

DEFAULT_BASE_URL = "http://localhost:8000"
SMOKE_VIDEO_SOURCE = "api-smoke-test"

# (method, path, body, headers) -> (status_code, headers, body)
RequestFn = Callable[
    [str, str, Optional[bytes], Dict[str, str]],
    Tuple[int, Dict[str, str], bytes],
]


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def make_urllib_request_fn(base_url: str, timeout: float = 5.0) -> RequestFn:
    base = base_url.rstrip("/")

    def request(
        method: str,
        path: str,
        body: Optional[bytes],
        headers: Dict[str, str],
    ) -> Tuple[int, Dict[str, str], bytes]:
        req = urllib.request.Request(
            f"{base}{path}", data=body, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers or {}), exc.read()

    return request


def _json_body(body: bytes) -> Optional[dict]:
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _check_envelope(
    request: RequestFn,
    name: str,
    path: str,
    validate: Callable[[dict], Optional[str]],
) -> CheckResult:
    status, _, body = request("GET", path, None, {})
    if status != 200:
        return CheckResult(name, False, f"status={status} body={body[:200]!r}")
    payload = _json_body(body)
    if payload is None or payload.get("status") != "success":
        return CheckResult(name, False, f"success envelope 아님: {body[:200]!r}")
    problem = validate(payload["data"])
    if problem:
        return CheckResult(name, False, problem)
    return CheckResult(name, True, "200")


def _require_keys(*keys: str) -> Callable[[dict], Optional[str]]:
    def validate(data) -> Optional[str]:
        if not isinstance(data, dict):
            return f"data가 object가 아님: {type(data).__name__}"
        missing = [key for key in keys if key not in data]
        return f"누락 필드: {missing}" if missing else None

    return validate


def _require_list(data) -> Optional[str]:
    return None if isinstance(data, list) else f"data가 list가 아님: {type(data).__name__}"


def _check_live_frame(request: RequestFn) -> CheckResult:
    status, headers, body = request("GET", "/live/frame", None, {})
    lowered = {key.lower(): value for key, value in headers.items()}
    if status == 204:
        return CheckResult("GET /live/frame", True, "204 (현재 프레임 없음)")
    if status == 200 and lowered.get("content-type", "").startswith("image/jpeg"):
        if body.startswith(b"\xff\xd8"):
            return CheckResult("GET /live/frame", True, f"200 jpeg {len(body)} bytes")
    return CheckResult("GET /live/frame", False, f"status={status}")


def _write_checks(request: RequestFn) -> List[CheckResult]:
    event_id = f"smoke-{uuid4()}"
    payload = {
        "event_id": event_id,
        "timestamp": "00:00:00.000",
        "event_type": "ENTER",
        "track_id": 0,
        "zone_id": "smoke_zone",
        "bbox": [0.0, 0.0, 1.0, 1.0],
        "foot_point": [0.5, 1.0],
        "frame_number": 0,
        "video_source": SMOKE_VIDEO_SOURCE,
        "event_confidence": 0.5,
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}

    results = []
    status, _, resp_body = request("POST", "/events", body, headers)
    created = _json_body(resp_body) or {}
    stored = created.get("data") or {}
    ok = status == 201 and stored.get("event_id") == event_id
    results.append(CheckResult("POST /events", ok, f"status={status}"))

    status, _, _ = request("POST", "/events", body, headers)
    results.append(
        CheckResult("POST /events (중복 event_id)", status == 409, f"status={status}")
    )

    status, _, resp_body = request("POST", "/events", b"{}", headers)
    results.append(
        CheckResult("POST /events (잘못된 요청)", status == 422, f"status={status}")
    )
    return results


def run_checks(request: RequestFn, write: bool = False) -> List[CheckResult]:
    results = [
        _check_envelope(
            request, "GET /health", "/health", _require_keys("service", "healthy")
        ),
        _check_envelope(
            request,
            "GET /events",
            "/events?limit=1",
            _require_keys("items", "total", "limit", "offset", "count"),
        ),
        _check_envelope(request, "GET /events/recent", "/events/recent?limit=1", _require_list),
        _check_envelope(
            request,
            "GET /summary",
            "/summary",
            _require_keys("total_events", "today_event_count", "recent_10min_event_count"),
        ),
        _check_envelope(
            request,
            "GET /status/current",
            "/status/current",
            _require_keys("source", "active_track_count", "zone_occupancy", "updated_at"),
        ),
        _check_envelope(
            request, "GET /zones", "/zones", _require_keys("version", "updated_at", "zones")
        ),
        _check_live_frame(request),
    ]
    if write:
        results.extend(_write_checks(request))
    return results


def print_results(results: List[CheckResult]) -> None:
    width = max(len(result.name) for result in results)
    for result in results:
        mark = "PASS" if result.ok else "FAIL"
        print(f"[{mark}] {result.name.ljust(width)}  {result.detail}")
    passed = sum(result.ok for result in results)
    print(f"\n{passed}/{len(results)} passed  ({datetime.now(timezone.utc).isoformat()})")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="KidCafe Backend API smoke test")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument(
        "--write",
        action="store_true",
        help="테스트 Event를 실제 DB에 1건 저장해 POST 경로까지 확인한다.",
    )
    args = parser.parse_args(argv)

    request = make_urllib_request_fn(args.base_url, timeout=args.timeout)
    try:
        results = run_checks(request, write=args.write)
    except (urllib.error.URLError, OSError) as exc:
        print(f"[FAIL] API에 연결할 수 없습니다: {args.base_url} ({exc})")
        return 1

    print_results(results)
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
