import pandas as pd
import os
from tqdm import tqdm
from scripts.llm_tasks.config import CSV_PATH, DAILY_LIMIT, BACKUP_CSV_PATH
from utils.ocr_utils import extract_text_from_images, clean_ocr_text
from utils.parsing_utils import parse_image_paths
from scripts.llm_tasks.llm_caller import generate_llm_response
from scripts.db_tasks.insertion import insert_notice_all
from utils.log_utils import init_runtime_logger, capture_unhandled_exception

logger = init_runtime_logger()

def get_checkpoint_index(path: str = "data/checkpoint_index.txt") -> int:
    if os.path.exists(path):
        with open(path, "r") as f:
            return int(f.read().strip())
    return 0 # 처음 시작할 경우

def save_checkpoint_index(index: int, path:str = "data/checkpoint_index.txt"):
    with open(path, "w") as f:
        f.write(str(index))

def append_to_backup_csv(parsed_data: dict, path: str = BACKUP_CSV_PATH):
    df_row = pd.DataFrame([parsed_data])
    if not os.path.exists(path):
        df_row.to_csv(path, index=False, encoding="utf-8-sig")
    else:
        df_row.to_csv(path, mode="a", index=False, header=False, encoding="utf-8-sig")

def run_ingestion():
    start_idx = get_checkpoint_index()
    logger.info("[INGEST] 시작 index=%s, daily_limit=%s", start_idx, DAILY_LIMIT)

    df = pd.read_csv(CSV_PATH, encoding="utf-8")
    df["작성일"] = pd.to_datetime(df["작성일"], errors="coerce") # 작성일을 datetime으로 변환 후 최신순 정렬
    df = df.sort_values(by="작성일", ascending=False).reset_index(drop=True)
    df = df.iloc[start_idx: start_idx + DAILY_LIMIT]

    for i, row in tqdm(df.iterrows(), total=len(df), desc="Ingestion 진행"):
            current_idx = start_idx + i
            try:
                save_checkpoint_index(current_idx + 1)

                title = row.get("제목", "")
                body = row.get("본문내용", "")
                image_paths_str = str(row.get("사진", "")).strip()

                if image_paths_str.lower() == "nan" or not image_paths_str:
                    image_paths = []
                    ocr_text = ""
                else:
                    image_paths = parse_image_paths(image_paths_str)
                    ocr_text_raw = extract_text_from_images(image_paths)
                    ocr_text = clean_ocr_text(ocr_text_raw)

                # --- LLM 호출 및 분류 ---
                parsed = generate_llm_response(title, body, ocr_text)
                parsed["url"] = row.get("링크", "")
                parsed["image_paths"] = row.get("사진", "")
                parsed["ocr_text"] = ocr_text

                append_to_backup_csv(parsed)

                # --- DB 삽입 ---
                insert_notice_all(parsed)
                logger.info("[✔] index=%s ingestion 성공 - title=%s", current_idx, parsed.get("title"))

            except Exception as e:
                capture_unhandled_exception(
                    index=current_idx,
                    phase="INGEST",
                    url=row.get("링크", None),
                    exc=e,
                    extra={"title": row.get("제목", "")}
                )
                logger.error("[X] index=%s ingestion 실패 - title=%s - error=%s",
                            current_idx, row.get("제목", ""), str(e))
                continue

if __name__ == "__main__":
    run_ingestion()

