from scripts.llm_tasks.prompt_template import TEST_PROMPT_KR
from scripts.llm_tasks.api_client import CLIENT, MODEL_ID
from scripts.llm_tasks.exceptions import LLMCallError, LLMTimeoutError, LLMParseError
import re
import json
from utils.log_utils import init_runtime_logger, capture_unhandled_exception

logger = init_runtime_logger()

def generate_llm_response(title: str, body: str, ocr_text: str) -> dict:
    """
    주어진 공지 제목, 본문, OCR 텍스트를 기반으로 LLM 분류 결과를 반환합니다.

    Args:
        title (str): 공지 제목
        body (str): 본문 텍스트
        ocr_text (str): 이미지 OCR 결과 텍스트

    Returns:
        dict | None: LLM이 반환한 JSON 파싱 결과 (분류 정보), 실패 시 None
    """

    # --- 프롬프트 구성 ---
    prompt = TEST_PROMPT_KR.format(
        title=title, 
        body=body, 
        ocr_text=ocr_text
    )
    contents = [prompt]
    
    try:
        # --- LLM 호출 ---
        response = CLIENT.models.generate_content(
            model=MODEL_ID,
            contents=contents
        )
    except TimeoutError as e:
        raise LLMTimeoutError(f"[Timeout] LLM 응답 지연: {e.__class__.__name__} - {e}\n")
    except Exception as e:
        raise LLMCallError(f"[Call Failed] LLM 호출 실패: {e.__class__.__name__} - {e}\n")

    # --- 응답 추출 ---
    try:
        raw_text = response.candidates[0].content.parts[0].text.strip()
    except (AttributeError, IndexError, KeyError) as e:
        raise LLMCallError(f"[Invalid Response] LLM 결과 형식 오류: {e}")

    logger.debug("[LLM RAW RESPONSE]: %s", raw_text)
        
    # --- 백틱 제거 ---
    if raw_text.startswith("```"):
        raw_text = re.sub(r"^```(?:json)?\n?", "", raw_text)
        raw_text = re.sub(r"\n?```$", "", raw_text)

    # --- JSON 파싱 ---
    try:
        parsed = json.loads(raw_text)
        parsed.pop("reasoning", None)
        return parsed
    except json.JSONDecodeError as e:
        capture_unhandled_exception(
            index=None,
            phase="LLM",
            url=None,
            exc=e,
            extra={"raw_text": raw_text[:1000]}  # 앞부분만 남김
        )
        raise LLMParseError(raw_text)