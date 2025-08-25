# scripts/db_tasks/notice_repo.py
from __future__ import annotations
from typing import Optional, Tuple, Iterable
import pyodbc

from utils.db_utils import get_connection
from utils.log_utils import init_runtime_logger

logger = init_runtime_logger()

def _maybe_open(conn: Optional[pyodbc.Connection]):
    if conn is not None:
        return conn, False
    return get_connection(), True

# 1) 공지사항 테이블에서 url_hash 기준으로 upsert (insert or update)
def upsert_notice_keys(conn: Optional[pyodbc.Connection], title: str, url: str, url_hash: str) -> Tuple[int, bool]:
    sql = """
    MERGE dbo.notice AS t
    USING (SELECT ? AS url_hash) AS s
    ON t.url_hash = s.url_hash
    WHEN NOT MATCHED THEN
      INSERT (title, url, url_hash, llm_status,created_at)
      VALUES (?,     ?,   ?,       0,          SYSUTCDATETIME())
    WHEN MATCHED THEN
      UPDATE SET
        title = COALESCE(NULLIF(LTRIM(RTRIM(?)), ''), t.title),
        url   = COALESCE(NULLIF(LTRIM(RTRIM(?)), ''), t.url)
    OUTPUT inserted.id, $action;
    """
    c, close_after = _maybe_open(conn) # 연결 준비
    try:
        cur = c.cursor()
        cur.execute(sql, (url_hash, title, url, url_hash, title, url))  #url_hash: MERGE source / title, url, url_hash: INSERT 값 / title, url: UPDATE 값
        rid, action = cur.fetchone()
        c.commit()
        return int(rid), (action == "INSERT") # 리턴: (notice_id, inserted여부)
    finally:
        if close_after: c.close()

# 2) 공지(notice)의 LLM 처리 상태(llm_status)를 조회하는 함수
def get_llm_status(conn: Optional[pyodbc.Connection], notice_id: int) -> Optional[int]:
    c, close_after = _maybe_open(conn)
    try:
        cur = c.cursor()
        cur.execute("SELECT llm_status FROM dbo.notice WHERE id = ?;", (notice_id,))
        row = cur.fetchone()
        return None if row is None else int(row[0])
    finally:
        if close_after: c.close()

# 3) 공지 테이블에 LLM이 분석한 결과(분류값)을 반영하는 역할
def apply_llm_result(conn: Optional[pyodbc.Connection], notice_id: int,
                     topic: Optional[str], oneline: Optional[str],
                     deadline: Optional[str], new_title: Optional[str] = None) -> None:
    sql = """
    UPDATE dbo.notice
    SET topic = ?, oneline = ?, deadline = ?,
        llm_status = 1,
        title = COALESCE(NULLIF(LTRIM(RTRIM(?)), ''), title)
    WHERE id = ?;
    """
    c, close_after = _maybe_open(conn)
    try:
        cur = c.cursor()
        cur.execute(sql, (topic, oneline, deadline, new_title, notice_id))
        c.commit()
    finally:
        if close_after: c.close()

# 4) 실패/재처리 마킹
def mark_failed(conn: Optional[pyodbc.Connection], notice_id: int, to_retry_queue: bool=False) -> None:
    st = 3 if to_retry_queue else 2
    c, close_after = _maybe_open(conn)
    try:
        cur = c.cursor()
        cur.execute("UPDATE dbo.notice SET llm_status = ? WHERE id = ?;", (st, notice_id))
        c.commit()
    finally:
        if close_after: c.close()

# 5) 부서(다대다) — 중복 방지 삽입
def add_departments(conn: Optional[pyodbc.Connection], notice_id: int, departments: Iterable[str]) -> None:
    c, close_after = _maybe_open(conn)
    try:
        cur = c.cursor()
        for d in departments or []:
            dept = (str(d) if d is not None else "").strip()
            if not dept: continue
            cur.execute("""
                IF NOT EXISTS (
                  SELECT 1 FROM dbo.notice_department WHERE notice_id = ? AND department = ?
                )
                INSERT INTO dbo.notice_department (notice_id, department)
                VALUES (?, ?);
            """, (notice_id, dept, notice_id, dept))
        c.commit()
    finally:
        if close_after: c.close()

# 6) 첨부(1:N) — 중복 방지 삽입 (URL 기준)
def add_attachments(conn: Optional[pyodbc.Connection], notice_id: int, image_urls: Iterable[str]) -> None:
    c, close_after = _maybe_open(conn)
    try:
        cur = c.cursor()
        for order, url in enumerate(image_urls or []):
            furl = (str(url) if url is not None else "").strip()
            if not furl: continue
            cur.execute("""
                IF NOT EXISTS (
                  SELECT 1 FROM dbo.notice_attachment
                  WHERE notice_id = ? AND file_url = ?
                )
                INSERT INTO dbo.notice_attachment (notice_id, file_url, file_order)
                VALUES (?, ?, ?);
            """, (notice_id, furl, notice_id, furl, order))
        c.commit()
    finally:
        if close_after: c.close()

# 7) OCR 텍스트 — 1:1로 관리(없으면 INSERT, 있으면 UPDATE)
def upsert_ocr_text(conn: Optional[pyodbc.Connection], notice_id: int, ocr_text: str) -> None:
    text = (ocr_text or "").strip()
    if not text: return
    c, close_after = _maybe_open(conn)
    try:
        cur = c.cursor()
        cur.execute("""
            MERGE dbo.notice_ocr_text AS t
            USING (SELECT ? AS notice_id) AS s
            ON t.notice_id = s.notice_id
            WHEN NOT MATCHED THEN
              INSERT (notice_id, ocr_text) VALUES (?, ?)
            WHEN MATCHED THEN
              UPDATE SET ocr_text = ?;
        """, (notice_id, notice_id, text, text))
        c.commit()
    finally:
        if close_after: c.close()
