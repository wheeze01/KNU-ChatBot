"""
utils/parsing_utils.py

문자열 기반의 컬럼(예: department, image_paths 등)을 파싱하기 위한 유틸 함수 모음입니다.
주요 기능:
- parse_department: 문자열로 인코딩된 리스트를 실제 파이썬 리스트로 변환
- parse_image_paths: 세미콜론(;)으로 구분된 이미지 경로 문자열을 리스트로 분리

LLM 전처리나 CSV 파싱 시 반복되는 문자열 처리 작업을 효율적으로 처리하기 위해 설계되었습니다.
"""

import pandas as pd
import ast
import numpy as np
from utils.log_utils import init_runtime_logger, capture_unhandled_exception

logger = init_runtime_logger()

def parse_image_paths(image_paths_str) -> list[str]:
    if pd.isna(image_paths_str) or str(image_paths_str).strip().lower() == "nan" or str(image_paths_str).strip() == "":
        return []

    # 혹시 Series나 ndarray가 들어오면 리스트로 변환
    if isinstance(image_paths_str, (pd.Series, np.ndarray)):
        image_paths_str = ";".join(map(str, image_paths_str)) # 원래 기대했던 문자열 형식으로 변환

    return [p.strip() for p in str(image_paths_str).split(";") if p.strip()]

def parse_department(row) -> list[str]:
    # 먼저 list/ndarray/pd.Series 인지 확인
    if isinstance(row, (list, np.ndarray, pd.Series)):
        return list(map(str, row))  # 문자열로 정규화

    # 그 다음에 NaN 체크
    if pd.isna(row):
        return []

    try:
        # 문자열을 리스트 형태로 변환 (예: "['컴공', '전자']")
        parsed = ast.literal_eval(str(row))
        if isinstance(parsed, list):
            return list(map(str, parsed))
        else:
            return [str(parsed)]
    except Exception as e:
        capture_unhandled_exception(
            index=None,
            phase="OTHER",   # 문자열 파싱 단계 → "OTHER" 로 분류
            url=None,
            exc=e,
            extra={"input_value": row}
        )
        # 상위 로직이 실패를 감지할 수 있도록 그대로 예외 재발생
        raise