from typing import Optional
import numpy as np
from utils.db_utils import insert_and_return_id, insert_data
from utils.parsing_utils import parse_image_paths, parse_department
from utils.key_utils import normalize_url, sha256_hex
from utils.log_utils import init_runtime_logger, capture_unhandled_exception
from utils.db_utils import get_connection
import pandas as pd
from scripts.db_tasks.notice_repo import(
    upsert_notice_keys, apply_llm_result,
    add_departments, add_attachments, upsert_ocr_text
)
import time

logger = init_runtime_logger()

def clean_row(row):
    raw_deadline = row.get("deadline", "")
    deadline = None if pd.isna(raw_deadline) or str(raw_deadline).strip() == "" else str(raw_deadline)
    
    try:
        department = parse_department(row.get("department", ""))
    except Exception as e:
        capture_unhandled_exception(
            index=None,
            phase="INGEST",
            url=None,
            exc=e,
            extra={"row": str(row), "field": "department"}
        )
        raise

    return {
        "title": str(row.get("title", "")),
        "deadline": deadline,
        "topic": str(row.get("topic", "")),
        "oneline": str(row.get("oneline", "")),
        "department": department,
        "url": str(row.get("url", "")),
        "image_paths": str(row.get("image_paths", "")),
        "ocr_text": str(row.get("ocr_text", ""))
    }

def insert_notice(parsed: dict, conn: Optional = None) -> int:
    own = False
    if conn is None:
        conn = get_connection(); own = True
    try:
        title = str(parsed.get("title", "") or "")
        url   = str(parsed.get("url", "") or "")
        url_hash = sha256_hex(normalize_url(url))
        notice_id, _created = upsert_notice_keys(conn, title, url, url_hash)  # 업서트
        # LLM 결과 반영(완료 마킹)
        topic   = (parsed.get("topic") or None)
        oneline = (parsed.get("oneline") or None)
        deadline= (parsed.get("deadline") or None)
        apply_llm_result(conn, notice_id, topic, oneline, deadline, new_title=title)
        return notice_id
    finally:
        if own: conn.close()

def insert_notice_department(notice_id: int, departments, conn: Optional = None):
    own = False
    if conn is None:
        conn = get_connection(); own = True
    try:
        if not isinstance(departments, list):
            departments = list(departments)
        add_departments(conn, notice_id, departments)
    finally:
        if own: conn.close()

def insert_notice_attachment(notice_id: int, image_paths, conn: Optional = None):
    own = False
    if conn is None:
        conn = get_connection(); own = True
    try:
        urls = parse_image_paths(image_paths)
        add_attachments(conn, notice_id, urls)
    finally:
        if own: conn.close()

def insert_notice_ocr_text(notice_id: int, ocr_text: str, conn: Optional = None):
    text = (ocr_text or "").strip()
    if not text:
        return
    own = False
    if conn is None:
        conn = get_connection(); own = True
    try:
        upsert_ocr_text(conn, notice_id, text)
    finally:
        if own: conn.close()

def insert_notice_all(parsed: dict, conn: Optional = None) -> int:
    parsed = clean_row(parsed)

    own = False
    if conn is None:
        conn = get_connection()
        own = True
    try:
        notice_id = insert_notice(parsed, conn=conn)

        depts = parsed.get("department", [])
        if not isinstance(depts, list):
            try:
                depts = parse_department(depts)
            except Exception as e:
                capture_unhandled_exception(index=None, phase="DB", url=parsed.get("url"),
                                            exc=e, extra={"field": "department"})
                depts = []
        if depts:
            insert_notice_department(notice_id, depts, conn=conn)

        img_paths = parsed.get("image_paths", "")
        if img_paths:
            insert_notice_attachment(notice_id, img_paths, conn=conn)

        ocr_text = (parsed.get("ocr_text") or "").strip()
        if ocr_text:
            insert_notice_ocr_text(notice_id, ocr_text, conn=conn)

        return notice_id
    finally:
        if own:
            try:
                conn.close()
            except Exception:
                capture_unhandled_exception(
                    index=None, phase="DB", url=parsed.get("url"),
                    exc=RuntimeError("connection close failed"), extra={}
                )