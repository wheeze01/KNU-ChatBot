import re
import requests
from io import BytesIO
from dotenv import load_dotenv
import urllib.parse
import os
import time
from azure.cognitiveservices.vision.computervision import ComputerVisionClient
from azure.cognitiveservices.vision.computervision.models import OperationStatusCodes
from msrest.exceptions import HttpOperationError
from msrest.authentication import CognitiveServicesCredentials
from utils.log_utils import (
    PHASE, init_runtime_logger, capture_exception,
    capture_unhandled_exception, append_failed_index,
    extract_azure_error_fields
)
from utils.throttle_utils import TokenBucket
from utils.retry_utils import (
    retry_with_backoff,
    is_retryable_http_error, 
    parse_retry_after,
    jitter
)
from utils.image_guard import ensure_ocr_safe_bytes

load_dotenv()
subscription_key = os.getenv("VISION_KEY")
endpoint = os.getenv("VISION_ENDPOINT")
computervision_client = ComputerVisionClient(endpoint, CognitiveServicesCredentials(subscription_key))

logger = init_runtime_logger()

# 무료(F0): 2초당 1건 수준이 안전 → rate=0.5, burst=1 권장
GLOBAL_BUCKET = TokenBucket(rate_per_sec=0.5, capacity=1)

def _cv_read_once(url_or_stream, use_stream: bool):
    """한 번의 Read 호출. 호출 직전에 전역 레이트 리미터로 속도 제한."""
    GLOBAL_BUCKET.acquire() # 전역 QPS 캡
    if use_stream:
        return computervision_client.read_in_stream(url_or_stream, raw=True)
    else:
        return computervision_client.read(url_or_stream, raw=True)
    
def _cv_read_with_retry(url_or_stream, use_stream:bool):
    """
    retry_utils.py의 retry_with_backoff로 감싼 안전 호출
    429/5xx만 자동 재시도
    """

    def _call():
        return _cv_read_once(url_or_stream, use_stream)
    
    safe_call = retry_with_backoff(
        func=_call,
        should_retry=is_retryable_http_error,
        base=2.0, factor=2.0, max_delay=32.0, max_retries=5,
        jitter_ratio=0.2
    )
    return safe_call()

def _poll_read_result_with_backoff(operation_id: str, max_wait_s: float = 120.0):
    """
    v3.2 비동기 폴링 최적화:
    - 처음 1초, 이후 2→3→4→5초(상한 5초)로 점진 증가 → 폴링 호출 수 절감
    - 폴링도 API 호출이므로 GLOBAL_BUCKET로 QPS 제한
    - 429 발생 시 Retry-After 우선, 없으면 현재 delay에 지터 넣어 대기
    """
    delay = 1.0   # 시작 1초
    waited = 0.0
    while True:
        try:
            GLOBAL_BUCKET.acquire()
            read_result = computervision_client.get_read_result(operation_id)

            if read_result.status not in ['notStarted', 'running']:
                return read_result  # succeeded/failed 중 하나면 종료

            # 아직 처리 중 → 점진 대기 (최대 5초)
            sleep_s = min(delay, 5.0)
            time.sleep(jitter(sleep_s, 0.2))
            waited += sleep_s
            delay = min(delay + 1.0, 5.0)

            if waited >= max_wait_s:
                return read_result  # 타임아웃 성격으로 상태 반환

        except HttpOperationError as e:
            status = getattr(getattr(e, 'response', None), 'status_code', None)
            if status == 429:
                # Retry-After 헤더 우선, 없으면 현재 delay 사용
                headers = getattr(getattr(e, "response", None), "headers", None)
                ra = parse_retry_after(headers) if headers else None
                sleep_s = ra if ra is not None else delay
                time.sleep(jitter(sleep_s, 0.2))
                # 다음 루프에서 다시 폴링(필요시 delay를 조금 늘릴 수도 있음)
                delay = min(max(delay, 2.0) * 1.5, 8.0)
                continue
            else:
                raise


def extract_text_from_images(image_urls: list[str], use_stream: bool = False) -> str:
    ocr_texts = []

    for idx, url in enumerate(image_urls):
        try:
            # --- 입력 준비: 전처리 가드 적용 ---
            safe_bytes, safe_type = ensure_ocr_safe_bytes(url)
            url_or_stream = BytesIO(safe_bytes)   # 항상 바이트 스트림으로 OCR 호출
            use_stream = True                     # 강제로 stream 모드 사용
            
            # --- Read 호출 “레이트 리미터 + 재시도” 로 감싸기 ---
            read_response = _cv_read_with_retry(url_or_stream, use_stream=use_stream)

            read_operation_location = read_response.headers.get("Operation-Location")
            if not read_operation_location:
                raise RuntimeError("Missing Operation-Location")
            operation_id = read_operation_location.split("/")[-1]

            # --- 폴링 최적화 + 429 대응 ---
            read_result = _poll_read_result_with_backoff(operation_id, max_wait_s=120.0)

            if read_result.status == OperationStatusCodes.succeeded:
                for text_result in read_result.analyze_result.read_results:
                    for line in text_result.lines:
                        ocr_texts.append(line.text.strip())
            else:
                capture_exception(
                    index=idx, phase=PHASE["OCR"], url=url,
                    message=f"OCR polling ended with status={read_result.status}"
                )
                append_failed_index(idx)
                logger.warning(f"OCR failed @idx={idx}, status={read_result.status}")
                print(f"[OCR FAILED] {url} - Status: {read_result.status}")

        except HttpOperationError as e:
            status = getattr(getattr(e, 'response', None), 'status_code', None)
            body = None
            try:
                body_attr = getattr(getattr(e, 'response', None), 'text', None)
                body = body_attr() if callable(body_attr) else body_attr
            except Exception:
                pass
            code, msg = extract_azure_error_fields(body)
            capture_exception(
                index=idx, phase=PHASE["OCR"], url=url,
                status_code=status, error_code=code, message=msg or str(e),
                response_body=body
            )
            append_failed_index(idx)
            logger.error(f"OCR HttpError @idx={idx} status={status} code={code} msg={msg}")
        except Exception as e:
            capture_unhandled_exception(index=idx, phase=PHASE["OCR"], url=url, exc=e)
            append_failed_index(idx)
            logger.exception(f"OCR UnknownError @idx={idx}")

    return "\n".join(ocr_texts)

def clean_ocr_text(text: str) -> str:
    # 줄바꿈, 탭 제거 → 공백으로 치환
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    # 연속된 공백 → 하나로 축소
    text = re.sub(r'\s{2,}', ' ', text)
    # 앞뒤 공백 제거
    return text.strip()



