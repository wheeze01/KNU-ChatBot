from __future__ import annotations
import random
import time
from typing import Callable, Iterable, Optional, Type, Any, Tuple

def jitter(seconds: float, ratio: float = 0.2) -> float:
    """
    지터(±ratio) 적용한 대기 시간 생성.
    ratio=0.2면 [0.8x, 1.2x] 범위로 흔들어줌.
    """
    if seconds <= 0:
        return 0.0
    low = seconds * (1 - ratio)
    high = seconds * (1 + ratio)
    return random.uniform(low, high)

def parse_retry_after(headers: Optional[dict]) -> Optional[float]:
    """
    HTTP 응답 헤더에서 Retry-After(초)를 float로 파싱.
    날짜 형식의 Retry-After는 이 함수에서 처리하지 않음(필요시 확장).
    """
    if not headers:
        return None
    val = headers.get("Retry-After")
    if not val:
        return None
    try:
        return float(val)
    except Exception:
        return None

def exponential_backoff(
    base: float = 1.0,
    factor: float = 2.0,
    max_delay: float = 32.0,
    max_retries: int = 5,
) -> Iterable[float]:
    """
    1, 2, 4, ... 형태의 지수 증가 대기시간(상한 max_delay) 생성기.
    max_retries 횟수만큼 값을 생성한다.
    """
    delay = max(base, 0.0)
    for _ in range(max_retries):
        yield min(delay, max_delay)
        delay = delay * factor if delay > 0 else base

def retry_with_backoff(
    func: Callable[..., Any],
    should_retry: Callable[[Exception], bool],
    *,
    base: float = 1.0,
    factor: float = 2.0,
    max_delay: float = 32.0,
    max_retries: int = 5,
    jitter_ratio: float = 0.2,
    on_retry: Optional[Callable[[int, Exception, float], None]] = None,
) -> Callable[..., Any]:
    """
    임의 함수를 지수 백오프 + 지터로 감싸 재시도하는 헬퍼.
    사용:
        safe_call = retry_with_backoff(api_call, should_retry=is_retryable_azure_error)
        resp = safe_call(url=..., headers=...)
    - should_retry(e): 재시도 대상 예외인지 True/False 반환
    - on_retry(attempt, exc, sleep): 로깅용 콜백(선택)
    """
    def wrapper(*args, **kwargs):
        attempt = 0
        for delay in exponential_backoff(base, factor, max_delay, max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                attempt += 1
                if not should_retry(e) or attempt > max_retries:
                    raise
                sleep_s = jitter(delay, jitter_ratio)
                if on_retry:
                    try:
                        on_retry(attempt, e, sleep_s)
                    except Exception:
                        pass
                time.sleep(sleep_s)
        # 마지막 한 번 더 시도
        return func(*args, **kwargs)
    return wrapper

def is_retryable_http_error(exc: Exception) -> bool:
    """
    Azure SDK의 HttpOperationError/HttpResponseError에서
    429, 500, 502, 503, 504 상태코드만 재시도 대상으로 취급
    """
    status = getattr(getattr(exc, "response", None), "status_code", None) \
             or getattr(getattr(exc, "response", None), "status", None)
    return status in (429, 500, 502, 503, 504)
