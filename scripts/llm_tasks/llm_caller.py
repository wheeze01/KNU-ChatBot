from scripts.llm_tasks.prompt_template import TEST_PROMPT_KR
from scripts.llm_tasks.api_client import CLIENT, MODEL_ID
from scripts.llm_tasks.exceptions import LLMCallError, LLMTimeoutError, LLMParseError
import re, json
from utils.log_utils import init_runtime_logger, capture_unhandled_exception



# 콘솔 출력 옵션 (원하면 둘 중 하나만 True)
PRINT_LLM_RAW    = True   # 모델이 돌려준 원문 그대로 보고 싶을 때
PRINT_LLM_PARSED = True   # 파싱된 JSON을 보기 좋게 출력

def _pp(label: str, text: str):
    # 한글 깨짐 방지: 터미널에서 set PYTHONIOENCODING=utf-8 권장
    print(f"\n[LLM {label}]")
    try:
        print(text if text is not None else "")
    except Exception:
        # 혹 encoding 문제시 억지로라도 출력
        print(str(text))
    print("-" * 60)

def generate_llm_response(title: str, body: str, ocr_text: str) -> dict:
    # --- 프롬프트 구성 ---
    prompt = TEST_PROMPT_KR.format(
        title=title or "", 
        body=body or "", 
        ocr_text=ocr_text or ""
    )

    # 교체
    try:
        response = CLIENT.models.generate_content(
            model=MODEL_ID,
            contents=[prompt],
            generation_config={"response_mime_type": "application/json"},  # 있으면 사용
        )
    except TypeError:
        response = CLIENT.models.generate_content(  # 없으면 폴백
            model=MODEL_ID,
            contents=[prompt]
        )

    # --- 응답 텍스트 안전 추출 ---
    try:
        # 통합 text 우선 → 없으면 candidates/parts 탐색
        t = getattr(response, "text", None)
        if isinstance(t, str) and t.strip():
            raw_text = t.strip()
        else:
            raw_text = None
            for cand in (getattr(response, "candidates", None) or []):
                content = getattr(cand, "content", None)
                for part in (getattr(content, "parts", None) or []):
                    pt = getattr(part, "text", None)
                    if isinstance(pt, str) and pt.strip():
                        raw_text = pt.strip()
                        break
                if raw_text:
                    break
            if not raw_text:
                raise LLMCallError("[Invalid Response] 텍스트 없음")
    except Exception as e:
        raise LLMCallError(f"[Invalid Response] {e}")

    if PRINT_LLM_RAW:
        _pp("RAW", raw_text)

    # --- 코드펜스 제거 ---
    s = raw_text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*\n?", "", s, flags=re.IGNORECASE)
    if s.endswith("```"):
        s = re.sub(r"\n?```$", "", s)

    # --- JSON 파싱 ---
    try:
        parsed = json.loads(s)
    except Exception:
        # { ... } 덩어리만 잘라 파싱 한번 더 시도 (깨진 JSON 방어—옵션)
        i, j = s.find("{"), s.rfind("}")
        if i != -1 and j != -1 and j > i:
            parsed = json.loads(s[i:j+1])
        else:
            # 실패 시 원문 일부 보여주고 예외
            _pp("PARSE_FAIL RAW", s[:1000])
            raise LLMParseError("JSON 파싱 실패")

    # 필요 없으면 이유 제거
    parsed.pop("reasoning", None)

    if PRINT_LLM_PARSED:
        _pp("PARSED", json.dumps(parsed, ensure_ascii=False, indent=2))

    return parsed

