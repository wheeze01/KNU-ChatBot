#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
강원대(단과대 rad) 학사일정 크롤러 - 리스트 뷰 전용 (Azure Blob 업로드 옵션)
대상 URL: https://cms.kangwon.ac.kr/rad/bachelor/calendar.do

저장 컬럼(초미니멀):
  - title
  - start_date (YYYY-MM-DD)
  - end_date   (YYYY-MM-DD)

사용 예:
  # 2025년 전체(월별 순회) 업로드
  python rad_calendar_crawler_blob.py --year 2025

  # 2025년 8~12월만 업로드
  python rad_calendar_crawler_blob.py --year 2025 --start-month 8 --end-month 12 \
      --container data --blob custom_name.csv

  # 2025년 전체를 1회 요청(allYn=Y)으로
  python rad_calendar_crawler_blob.py --year 2025 --all
"""

import os
import io
import re
import csv
import time
import argparse
from typing import List, Dict, Optional, Tuple
from datetime import datetime, date

import requests
from bs4 import BeautifulSoup

# --- Azure (선택) ---
from azure.storage.blob import BlobServiceClient, ContentSettings
from azure.core.exceptions import AzureError, ResourceExistsError
from dotenv import load_dotenv

# ----------------- 설정 -----------------
BASE_URL = "https://cms.kangwon.ac.kr/rad/bachelor/calendar.do"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# ----------------- 유틸 -----------------
def norm_text(s: str) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s).strip()

def month_to_int(text: str) -> Optional[int]:
    """'8월', '08월', '8' 등에서 숫자만 추출 → int"""
    if not text:
        return None
    m = re.search(r"(\d{1,2})", text)
    return int(m.group(1)) if m else None

def parse_component(comp: str, section_month: int) -> Optional[Tuple[int, int, bool]]:
    """
    날짜 컴포넌트 1개를 파싱.
      - 반환: (month, day, explicit_month)
        * '12.31' -> (12, 31, True)
        * '7'     -> (section_month, 7, False)
    """
    s = comp.strip()
    s = re.sub(r"\([^)]*\)", "", s)  # (요일) 제거
    s = s.strip()
    m = re.match(r"(?:(?P<M>\d{1,2})\.(?P<D>\d{1,2})|(?P<d>\d{1,2}))$", s)
    if not m:
        return None
    if m.group("M"):
        return int(m.group("M")), int(m.group("D")), True
    return section_month, int(m.group("d")), False

def parse_date_range(day_text: str, default_year: int, section_month: int) -> Optional[Tuple[str, str]]:
    """
    '일/요일' 문자열에서 시작~종료 날짜를 ISO로 파싱.
      예) '12.31(화) ~ 7(화)', '9(목) ~ 2.28(금)', '16(목) ~ 16(목)', '7(월)'
    연도 교차를 자동 보정.
    """
    txt = re.sub(r"\s+", " ", day_text or "").strip()
    if not txt:
        return None

    parts = [p.strip() for p in txt.split("~")]

    s_parsed = parse_component(parts[0], section_month)
    if not s_parsed:
        return None
    sm, sd, s_explicit = s_parsed

    if len(parts) >= 2:
        e_parsed = parse_component(parts[1], section_month)
        if not e_parsed:
            e_parsed = (sm, sd, s_explicit)
    else:
        e_parsed = (sm, sd, s_explicit)
    em, ed, e_explicit = e_parsed

    # 연도 결정
    sy = default_year
    if s_explicit and sm > section_month:
        # 1월 섹션에서 '12.x' 등: 전년도
        sy = default_year - 1

    ey = sy
    if e_explicit and em < sm:
        ey = sy + 1
    if (not e_explicit) and (em < sm) and s_explicit:
        ey = sy + 1

    try:
        sd_iso = date(sy, sm, sd).isoformat()
        ed_iso = date(ey, em, ed).isoformat()
    except ValueError:
        return None
    return sd_iso, ed_iso

# ----------------- 요청 -----------------
def fetch_list_page(year: int, month: Optional[int] = None, use_all: bool = False) -> BeautifulSoup:
    """
    리스트 보기 페이지 요청.
    구조: .b-cal-list-box > ( .b-cal-top-box, 월 섹션 div... )
    """
    params = {"mode": "list", "cYear": str(year)}
    if use_all:
        params["allYn"] = "Y"
    elif month is not None:
        params["month"] = f"{month:d}"

    resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")

# ----------------- 파싱 -----------------
def parse_list_box(soup: BeautifulSoup, default_year: int, month_hint: Optional[int] = None) -> List[Dict[str, str]]:
    """
    올려준 HTML 구조에 정확히 맞춰 파싱.
      .b-cal-list-box
        ├─ .b-cal-top-box (헤더)
        ├─ <div>                ← 월 섹션 컨테이너
        │   ├─ <p>1월</p>       ← 월
        │   └─ <div>            ← 이 안에 여러 .home
        │       ├─ <div class="home">
        │       │    <p>12.31(화) ~ 7(화)</p>
        │       │    <ul><li>...</li>...</ul>
        │       └─ ...
        └─ ...
    """
    out: List[Dict[str, str]] = []

    cal = soup.select_one("div.b-cal-list-box")
    if not cal:
        if "등록된 일정이 없습니다" in soup.get_text(" ", strip=True):
            return out
        raise RuntimeError("학사일정 컨테이너(.b-cal-list-box)를 찾지 못했습니다.")

    # 상단 헤더 제외한 월 섹션만 추출 (직계 자식만)
    sections = []
    for child in cal.find_all("div", recursive=False):
        # .b-cal-top-box 는 스킵
        if "class" in child.attrs and "b-cal-top-box" in child.get("class", []):
            continue
        sections.append(child)

    # 월 섹션 순회
    for sec in sections:
        # 월 텍스트와 .home들이 들어있는 내부 div 찾기
        month_p = sec.find("p", recursive=False)
        inner = None
        for div in sec.find_all("div", recursive=False):
            if div.select_one("div.home"):
                inner = div
                break
        if not (month_p and inner):
            # 혹시 구조가 한 단계 더 감싸져 있으면 보정
            month_p = sec.find("p")
            inner = sec.find("div")
            if not (month_p and inner and inner.select_one("div.home")):
                continue

        month_label = norm_text(month_p.get_text(" ", strip=True))
        section_month = month_to_int(month_label) or month_hint
        if not section_month:
            continue

        # 각 날짜 블록(.home) 순회
        for home in inner.select("div.home"):
            day_p = home.find("p")
            day_text = norm_text(day_p.get_text(" ", strip=True)) if day_p else ""

            rng = parse_date_range(day_text, default_year, section_month)
            if not rng:
                # 최소한 day 숫자라도 있으면 단일일 처리
                mday = re.search(r"(\d{1,2})", day_text or "")
                if not mday:
                    continue
                sd = date(default_year, section_month, int(mday.group(1))).isoformat()
                ed = sd
            else:
                sd, ed = rng

            # 각 li 를 개별 일정으로 저장
            li_texts = [norm_text(li.get_text(" ", strip=True)) for li in home.select("ul li")]
            li_texts = [t for t in li_texts if t and "등록된 일정이 없습니다" not in t]

            if li_texts:
                for t in li_texts:
                    out.append({"title": t, "start_date": sd, "end_date": ed})
            else:
                # li가 없으면 home 전체 텍스트를 한 건으로
                content = norm_text(home.get_text(" ", strip=True))
                if content and "등록된 일정이 없습니다" not in content:
                    out.append({"title": content, "start_date": sd, "end_date": ed})

    out.sort(key=lambda r: (r["start_date"], r["end_date"], r["title"]))
    return out

# ----------------- 수집 흐름 -----------------
def crawl_year_by_month(year: int, start_month: int = 1, end_month: int = 12, sleep_sec: float = 0.2) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for m in range(start_month, end_month + 1):
        try:
            soup = fetch_list_page(year, month=m, use_all=False)
            rows.extend(parse_list_box(soup, default_year=year, month_hint=m))
        except requests.RequestException as e:
            print(f"[경고] 요청 실패: {year}-{m:02d} → {e}")
        except Exception as e:
            print(f"[경고] 파싱 실패: {year}-{m:02d} → {e}")
        time.sleep(sleep_sec)
    return rows

def crawl_year_all_once(year: int) -> List[Dict[str, str]]:
    try:
        soup = fetch_list_page(year, month=None, use_all=True)
        return parse_list_box(soup, default_year=year, month_hint=None)
    except requests.RequestException as e:
        print(f"[경고] 전체 요청 실패: {year} → {e}")
        return []
    except Exception as e:
        print(f"[경고] 전체 파싱 실패: {year} → {e}")
        return []

# ----------------- CSV/업로드 -----------------
def rows_to_csv_bytes(rows: List[Dict[str, str]]) -> bytes:
    fieldnames = ["title", "start_date", "end_date"]
    sio = io.StringIO()
    w = csv.DictWriter(sio, fieldnames=fieldnames)
    w.writeheader()
    for r in rows:
        w.writerow({
            "title": r.get("title", ""),
            "start_date": r.get("start_date", ""),
            "end_date": r.get("end_date", ""),
        })
    return sio.getvalue().encode("utf-8-sig")

def upload_csv_to_azure(csv_bytes: bytes, container: str, blob_name: str) -> str:
    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if not conn_str:
        raise RuntimeError("환경변수 AZURE_STORAGE_CONNECTION_STRING 이 설정되지 않았습니다.")

    try:
        bsc = BlobServiceClient.from_connection_string(conn_str)
        try:
            bsc.create_container(container)
        except ResourceExistsError:
            pass

        blob_client = bsc.get_blob_client(container=container, blob=blob_name)
        blob_client.upload_blob(
            csv_bytes,
            overwrite=True,
            content_settings=ContentSettings(content_type="text/csv; charset=utf-8")
        )
        return blob_client.url
    except AzureError as e:
        raise RuntimeError(f"Azure Blob 업로드 실패: {e}") from e

# ----------------- 진입점 -----------------
def main():
    load_dotenv(override=True)

    this_year = int(datetime.now().strftime("%Y"))
    p = argparse.ArgumentParser(description="rad 학사일정 크롤러(리스트뷰) → CSV(초미니 3컬럼)")
    p.add_argument("--year", type=int, default=this_year, help="수집 연도 (기본: 올해)")
    p.add_argument("--start-month", type=int, default=1, help="시작 월 (기본 1)")
    p.add_argument("--end-month", type=int, default=12, help="종료 월 (기본 12)")
    p.add_argument("--all", action="store_true", help="allYn=Y로 해당 연도 전체를 1회 수집")
    p.add_argument("--container", type=str, default=os.environ.get("AZURE_CSV_CONTAINER_NAME", "data"))
    p.add_argument("--blob", type=str, default=None, help="Blob 파일명(미지정 시 자동)")
    args = p.parse_args()

    year = args.year
    sm = max(1, min(12, args.start_month))
    em = max(1, min(12, args.end_month))
    if sm > em:
        sm, em = em, sm

    if args.all:
        default_blob = f"academic_calendar_{year}_ALL.csv"
    else:
        default_blob = f"academic_calendar_{year}.csv" if (sm == 1 and em == 12) else f"academic_calendar_{year}_{sm:02d}-{em:02d}.csv"
    blob_name = args.blob or default_blob

    print(f"🚀 수집 시작: {year}년 {'ALL' if args.all else f'{sm}~{em}월'}")
    rows = crawl_year_all_once(year) if args.all else crawl_year_by_month(year, sm, em)

    print(f"🧾 CSV 변환 중 (총 {len(rows)}건)...")
    csv_bytes = rows_to_csv_bytes(rows)

    print(f"☁️ Azure 업로드: 컨테이너='{args.container}', Blob='{blob_name}'")
    try:
        url = upload_csv_to_azure(csv_bytes, container=args.container, blob_name=blob_name)
        print(f"✅ 업로드 완료: {url}")
    except Exception as e:
        print(f"❌ 업로드 실패: {e}")
        # 실패 시 로컬 백업
        try:
            with open(blob_name, "wb") as f:
                f.write(csv_bytes)
            print(f"📝 로컬 백업 저장 완료: {blob_name}")
        except Exception as e2:
            print(f"⚠️ 로컬 백업도 실패: {e2}")

if __name__ == "__main__":
    main()
