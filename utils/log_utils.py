import os, json, time, logging, traceback
from dataclasses import dataclass, asdict
from logging.handlers import RotatingFileHandler
from typing import Optional, Dict, Any

# ====== 공용 설정 ======
DEFAULT_LOG_DIR = "logs"
DEFAULT_ERR_JSONL = "failures.jsonl"
DEFAULT_FAILED_IDX = "failed_indices.txt"
DEFAULT_RUNTIME_LOG = "runtime.log"

PHASE = {
    "OCR": "OCR",
    "DB": "DB",
    "LLM": "LLM",
    "INGEST": "INGEST",
    "OTHER": "OTHER",
}

@dataclass
class ErrorRecord:
    index: Optional[int]             # 몇 번째 인덱스(없으면 None)
    phase: str                       # OCR/DB/…
    url: Optional[str]               # 관련 자원(URL) 없으면 None
    status_code: Optional[int]       # HTTP 코드 등
    error_code: Optional[str]        # 공급자 에러 코드(Azure 등)
    message: str                     # 핵심 메시지 (사람이 보기 좋게)
    response_body: Optional[str]     # 원문(길면 잘라 쓰기 권장)
    extra: Optional[Dict[str, Any]]  # 쿼리/파라미터 등 부가정보
    timestamp: float                 # epoch seconds

def _ensure_dir(path: str):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)

def init_runtime_logger(log_dir: str = DEFAULT_LOG_DIR,
                        filename: str = DEFAULT_RUNTIME_LOG,
                        level=logging.INFO,
                        max_bytes=5_000_000,
                        backup_count=3) -> logging.Logger:
    """
    회전 로그 파일(logger) 셋업. 일반 정보/진행/경고용.
    """
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger("app.runtime")
    if logger.handlers:
        return logger  # 중복 셋업 방지
    logger.setLevel(level)
    handler = RotatingFileHandler(
        os.path.join(log_dir, filename),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8"
    )
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger

def log_error_record(err: ErrorRecord,
                     log_dir: str = DEFAULT_LOG_DIR,
                     filename: str = DEFAULT_ERR_JSONL):
    """
    정형화된 실패 레코드(JSON Lines)로 저장.
    """
    path = os.path.join(log_dir, filename)
    _ensure_dir(path)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(err), ensure_ascii=False) + "\n")

def append_failed_index(idx: int,
                        log_dir: str = DEFAULT_LOG_DIR,
                        filename: str = DEFAULT_FAILED_IDX):
    """
    실패 인덱스를 별도 파일로 모아 재처리에 사용.
    """
    path = os.path.join(log_dir, filename)
    _ensure_dir(path)
    with open(path, "a", encoding="utf-8") as f:
        f.write(str(idx) + "\n")

def capture_exception(index: Optional[int],
                      phase: str,
                      url: Optional[str] = None,
                      status_code: Optional[int] = None,
                      error_code: Optional[str] = None,
                      message: Optional[str] = None,
                      response_body: Optional[str] = None,
                      extra: Optional[Dict[str, Any]] = None,
                      log_dir: str = DEFAULT_LOG_DIR):
    """
    예외 상황을 ErrorRecord로 만들어 바로 기록.
    """
    if response_body and len(response_body) > 4000:
        response_body = response_body[:4000]  # 과도한 길이 방지
    err = ErrorRecord(
        index=index,
        phase=phase,
        url=url,
        status_code=status_code,
        error_code=error_code,
        message=message or "",
        response_body=response_body,
        extra=extra,
        timestamp=time.time(),
    )
    log_error_record(err, log_dir=log_dir)

def capture_unhandled_exception(index: Optional[int],
                                phase: str,
                                url: Optional[str],
                                exc: Exception,
                                log_dir: str = DEFAULT_LOG_DIR,
                                extra: Optional[Dict[str, Any]] = None):
    """
    미분류/일반 예외를 traceback 포함해 기록.
    """
    tb = traceback.format_exc()
    capture_exception(
        index=index,
        phase=phase,
        url=url,
        status_code=None,
        error_code=type(exc).__name__,
        message=str(exc),
        response_body=tb,
        extra=extra,
        log_dir=log_dir,
    )

# (선택) Azure의 {"error": {"code": "...", "message": "..."}} 파싱 유틸
def extract_azure_error_fields(resp_text: Optional[str]):
    if not resp_text:
        return None, None
    try:
        data = json.loads(resp_text)
        err = data.get("error") or {}
        return err.get("code"), err.get("message") or resp_text
    except Exception:
        return None, resp_text
