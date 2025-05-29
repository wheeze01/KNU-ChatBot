# -*- coding: utf-8 -*-
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse
import os
import math
import time
import hashlib
import re
import pandas as pd
from tqdm import tqdm
import traceback

# --- 1. 기본 설정 ---
try:
    script_path = os.path.abspath(__file__)
    script_dir = os.path.dirname(script_path)
    project_root = os.path.abspath(os.path.join(script_dir, '..', '..'))
except NameError:
    print("⚠️ __file__ 변수를 찾을 수 없어 현재 작업 디렉토리 기준으로 경로 설정합니다.")
    project_root = os.getcwd()

DATA_FOLDER = os.path.join(project_root, 'data')
IMAGE_FOLDER_NAME = "images_content"
IMAGE_FOLDER = os.path.join(DATA_FOLDER, IMAGE_FOLDER_NAME)
CSV_FILENAME = "kangwon_all_dept_notices_beta_all_pages.csv"
CSV_FILEPATH = os.path.join(DATA_FOLDER, CSV_FILENAME)
os.makedirs(IMAGE_FOLDER, exist_ok=True)
print(f"ℹ️ 프로젝트 루트: {project_root}")
print(f"ℹ️ 데이터 폴더: {DATA_FOLDER}")
print(f"ℹ️ 이미지 폴더: {IMAGE_FOLDER}")
print(f"ℹ️ CSV 저장 경로: {CSV_FILEPATH}")

college_intro_pages = [
    {'college_name': '간호대학', 'url': 'https://wwwk.kangwon.ac.kr/www/contents.do?key=1782&'},
    {'college_name': '경영대학', 'url': 'https://wwwk.kangwon.ac.kr/www/contents.do?key=1752&'},
    {'college_name': '농업생명과학대학', 'url': 'https://wwwk.kangwon.ac.kr/www/contents.do?key=1758&'},
    {'college_name': '동물생명과학대학', 'url': 'https://wwwk.kangwon.ac.kr/www/contents.do?key=1761&'},
    {'college_name': '문화예술 공과대학', 'url': 'https://wwwk.kangwon.ac.kr/www/contents.do?key=1912&'},
    {'college_name': '사범대학', 'url': 'https://wwwk.kangwon.ac.kr/www/contents.do?key=1767&'},
    {'college_name': '사회과학대학', 'url': 'https://wwwk.kangwon.ac.kr/www/contents.do?key=1770&'},
    {'college_name': '산림환경과학대학', 'url': 'https://wwwk.kangwon.ac.kr/www/contents.do?key=1773&'},
    {'college_name': '수의과대학', 'url': 'https://wwwk.kangwon.ac.kr/www/contents.do?key=1776&'},
    {'college_name': '약학대학', 'url': 'https://wwwk.kangwon.ac.kr/www/contents.do?key=1779&'},
    {'college_name': '의과대학', 'url': 'https://wwwk.kangwon.ac.kr/www/contents.do?key=1975&'},
    {'college_name': '의생명과학대학', 'url': 'https://wwwk.kangwon.ac.kr/www/contents.do?key=1785&'},
    {'college_name': '인문대학', 'url': 'https://wwwk.kangwon.ac.kr/www/contents.do?key=1788&'},
    {'college_name': '자연과학대학', 'url': 'https://wwwk.kangwon.ac.kr/www/contents.do?key=1791&'},
    {'college_name': 'IT대학', 'url': 'https://wwwk.kangwon.ac.kr/www/contents.do?key=1794&'},
]
REQUEST_DELAY = 0.3
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
DEFAULT_ARTICLE_LIMIT = 10

# --- 실패/누락 추적용 ---
failed_college_extractions = []
departments_with_no_results = []
unknown_template_urls = set()
processed_hashes_global = set()

# --- 2. 헬퍼 함수 ---
def get_soup(url):
    """URL 요청 및 BeautifulSoup 객체 반환"""
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        response.encoding = response.apparent_encoding
        return BeautifulSoup(response.text, 'html.parser')
    except requests.exceptions.Timeout:
        print(f"      ❌ Timeout 에러: {url}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"      ❌ 요청 에러: {url} - {e}")
        return None
    except Exception as e:
        print(f"      ❌ 파싱 에러: {url} - {e}")
        return None

def normalize_text(text):
    """텍스트 정규화"""
    if not text:
        return ""
    text = text.lower().strip()
    return ' '.join(text.split())

def calculate_hash(text):
    """텍스트 SHA-256 해시 계산"""
    if not text:
        return ""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def download_image(img_url, base_post_url, save_folder):
    """이미지 다운로드 및 파일명 반환"""
    if not img_url or img_url.startswith('data:image') or not base_post_url :
        return None
    try:
        absolute_img_url = urljoin(base_post_url, img_url)
        if not absolute_img_url.startswith('http'):
            return None
        absolute_img_url = requests.utils.requote_uri(absolute_img_url)

        img_response = requests.get(absolute_img_url, headers=HEADERS, timeout=20, stream=True)
        img_response.raise_for_status()

        try:
            url_path = urlparse(absolute_img_url).path
            img_filename_base = os.path.basename(url_path) if url_path else None
        except Exception:
             img_filename_base = None

        if not img_filename_base:
             img_filename_base = hashlib.md5(absolute_img_url.encode()).hexdigest()

        valid_chars = "-_.() abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789가-힣"
        img_filename_base = ''.join(c for c in img_filename_base if c in valid_chars).strip()[:100]
        if not img_filename_base:
            img_filename_base = "image"

        content_type = img_response.headers.get('Content-Type')
        ext = '.jpg'
        if content_type:
            content_type = content_type.lower()
            if 'jpeg' in content_type: ext = '.jpg'
            elif 'png' in content_type: ext = '.png'
            elif 'gif' in content_type: ext = '.gif'
            elif 'bmp' in content_type: ext = '.bmp'
            elif 'webp' in content_type: ext = '.webp'
            base, original_ext = os.path.splitext(img_filename_base)
            if original_ext and len(original_ext) <= 5 and original_ext[1:].isalnum():
                 ext = original_ext.lower()
                 img_filename_base = base

        timestamp = int(time.time() * 1000)
        final_filename = f"{img_filename_base}_{timestamp}{ext}"
        save_path = os.path.join(save_folder, final_filename)
        with open(save_path, 'wb') as f:
            for chunk in img_response.iter_content(1024):
                f.write(chunk)
        return final_filename
    except:
        pass
    return None

# --- 3. URL 자동 추출 함수 ---
def extract_notice_board_urls(college_pages_list):
    """단과대학 소개 페이지에서 학과별 공지사항 URL 자동 추출"""
    global failed_college_extractions
    print("\n===== 1단계: 학과별 공지사항 URL 자동 추출 시작 =====")
    department_boards_dict = {}
    base_wwwk_url = "https://wwwk.kangwon.ac.kr"
    dept_block_selector = "div.box.temp_titbox"
    dept_name_selector = "h4.h0"
    notice_link_selector = "ul.shortcut li:last-child a"

    for college in tqdm(college_pages_list, desc="단과대학 페이지 처리 중"):
        college_name = college['college_name']
        page_url = college['url']
        soup = get_soup(page_url)
        if not soup:
            failed_college_extractions.append(f"{college_name}(로드실패)")
            continue

        dept_blocks = soup.select(dept_block_selector)
        if not dept_blocks:
            failed_college_extractions.append(f"{college_name}(블록({dept_block_selector}) 없음)")
            continue

        for block in dept_blocks:
            dept_name_element = block.select_one(dept_name_selector)
            notice_link = block.select_one(notice_link_selector)
            if dept_name_element and notice_link:
                dept_name_raw = dept_name_element.get_text(strip=True)
                dept_name_cleaned = dept_name_raw.split('\n')[0].strip()
                relative_or_absolute_url = notice_link.get('href')
                if relative_or_absolute_url:
                    absolute_url = urljoin(base_wwwk_url, relative_or_absolute_url)
                    absolute_url = absolute_url.replace("wwwk.kangwon.ac.kr/wwwk.kangwon.ac.kr", "wwwk.kangwon.ac.kr")
                    if dept_name_cleaned not in department_boards_dict:
                        department_boards_dict[dept_name_cleaned] = absolute_url
        time.sleep(0.1)

    print(f"\n===== URL 자동 추출 완료: 총 {len(department_boards_dict)}개 학과/전공 URL 확보 =====")
    if not department_boards_dict:
        print("🚨 자동 추출된 URL이 없습니다!")
        return None
    print("--- 추출된 URL 목록 (일부) ---")
    count = 0
    for name, url in department_boards_dict.items():
        print(f"  '{name}': '{url}'")
        count += 1
        if count >= 5:
            print("  ...")
            break
    print("--------------------------")
    return department_boards_dict

# --- 4. 핵심 크롤링 함수 ---
def crawl_post_detail(post_url):
    """게시글 상세 페이지 크롤링 (템플릿 D 추가 및 선택자 수정)"""
    global unknown_template_urls
    soup = get_soup(post_url)
    if not soup:
        return None
    title = "제목 없음"; body_raw = ""; body_hash = ""; image_filenames = []; content_element = None
    title_element = None; detected_template = "Unknown"
    try:
        content_element_A = soup.select_one("#bbs_ntt_cn_con")
        content_element_B = soup.select_one("div.view-comm-board")
        content_element_C = soup.select_one("div.view-content")
        content_element_D = soup.select_one("div.fr-view")

        if content_element_D:
            detected_template = "D"
            title_element = soup.select_one("p.b-title-box span")
            if not title_element: title_element = soup.select_one("div.view_title span")
            content_element = content_element_D
        elif content_element_A:
            detected_template = "A"; title_selector = "div.view_title > span.subject_01"; title_fallback_selector = "div.view_title > span"; content_element = content_element_A
            title_element = soup.select_one(title_selector)
            if not title_element: title_element = soup.select_one(title_fallback_selector)
        elif content_element_B:
            detected_template = "B"; title_selector = "div.view_title > span"; content_element = content_element_B
            title_element = soup.select_one(title_selector)
        elif content_element_C:
            detected_template = "C"; title_selector = "div.view-titbox > p.tit > span"; title_fallback_selector = "div.view-titbox > p.tit"; content_element = content_element_C
            title_element = soup.select_one(title_selector)
            if not title_element: title_element = soup.select_one(title_fallback_selector)
        else:
            unknown_template_urls.add(post_url)
            title_selectors_fallback = ["h1", "h2", "h3", "h4", ".title", "#title", ".view_title", ".subject", "td.td_subject", "p.b-title-box span"]
            content_selectors_fallback = ["#article_content", "#bbs_content", "#view_content", ".content", ".view_content", ".view_cont", ".dbdata", "article", "section", "td.td_content", "div.fr-view"]
            for ts in title_selectors_fallback:
                title_element = soup.select_one(ts)
                if title_element: break
            for cs in content_selectors_fallback:
                content_element = soup.select_one(cs)
                if content_element: break

        title = title_element.get_text(strip=True) if title_element else "제목 없음"
        if content_element:
            for unwanted in content_element.select('.reply_area, .related_posts'):
                 unwanted.decompose()
            body_raw = content_element.get_text(separator='\n', strip=True)
        else:
             body_raw = ""

        body_normalized = normalize_text(body_raw)
        body_hash = calculate_hash(body_normalized)
        image_filenames = []
        if content_element:
            img_tags = content_element.select("img")
            for img in img_tags:
                img_src = img.get('src')
                if img_src:
                    saved_filename = download_image(img_src, post_url, IMAGE_FOLDER)
                    if saved_filename:
                        image_filenames.append(saved_filename)

        return {'제목': title, '본문': body_raw, '해시': body_hash, '이미지파일명': ", ".join(image_filenames)}

    except Exception as e:
        print(f"      ❌ 상세 처리 예외 ({post_url}): {e}")
        traceback.print_exc()
        return None

def build_page_url(base_url, page_num, articles_per_page=DEFAULT_ARTICLE_LIMIT):
    """기본 URL, 페이지 번호, 페이지당 게시물 수를 받아 URL (offset 사용)을 생성"""
    try:
        parsed_url = urlparse(base_url)
        query_params = parse_qs(parsed_url.query, keep_blank_values=True)
        offset = (page_num - 1) * articles_per_page
        query_params['article.offset'] = [str(offset)]
        if 'articleLimit' not in query_params:
             query_params['articleLimit'] = [str(articles_per_page)]
        query_params.pop('mode', None)
        query_params.pop('articleNo', None)
        query_params.pop('pageIndex', None)
        new_query = urlencode(query_params, doseq=True)
        new_url_parts = parsed_url._replace(query=new_query)
        return urlunparse(new_url_parts)
    except Exception as e:
        print(f"      ⚠️ URL 생성 오류 (Base: {base_url}, Page: {page_num}): {e}")
        return None

def crawl_board_list(dept_name, board_url):
    """학과 게시판의 모든 페이지를 크롤링 (Offset 기반 총 페이지 계산, 선택자 수정)"""
    all_posts_data = []
    processed_hashes_in_dept = set()

    print(f"--- [{dept_name}] 게시판 크롤링 시작 ---")
    print(f"  시작 URL: {board_url}")

    print(f"  -> [{dept_name}] 첫 페이지 로드 시도 (총 페이지 확인용)...")
    initial_soup = get_soup(board_url)
    if not initial_soup:
        print(f"      ❌ [{dept_name}] 첫 페이지 로드 실패. 해당 학과 건너<0xEB><0x9B><0x81>니다.")
        departments_with_no_results.append(dept_name + "(첫 페이지 로드 실패)")
        return []

    totalPages = 1
    articles_per_page = DEFAULT_ARTICLE_LIMIT
    determined_total_pages = False
    try:
        # 페이지네이션 영역 찾기
        pagination_wrap = initial_soup.select_one('div.b-paging-wrap, div.paginate')
        if pagination_wrap:
            # "맨끝" 버튼의 href 속성에서 offset 찾기
            last_page_link_href = pagination_wrap.select_one('li.last a[href]')
            if not last_page_link_href: last_page_link_href = pagination_wrap.select_one('a.last[href]')
            if not last_page_link_href: last_page_link_href = pagination_wrap.select_one('a.next_end[href]')

            if last_page_link_href:
                href = last_page_link_href.get('href')
                parsed_href = urlparse(href)
                query_params = parse_qs(parsed_href.query)

                # articleLimit 값 추출
                temp_limit = articles_per_page
                if 'articleLimit' in query_params:
                    try:
                        temp_limit = int(query_params['articleLimit'][0])
                    except (ValueError, IndexError):
                        pass
                else:
                    any_page_link = pagination_wrap.select_one('a[href*="articleLimit="]')
                    if any_page_link:
                        parsed_any = urlparse(any_page_link.get('href'))
                        query_any = parse_qs(parsed_any.query)
                        if 'articleLimit' in query_any:
                           try:
                               temp_limit = int(query_any['articleLimit'][0])
                           except(ValueError, IndexError):
                               pass
                articles_per_page = temp_limit

                # article.offset 값 추출 및 총 페이지 계산
                if 'article.offset' in query_params:
                    try:
                        last_offset = int(query_params['article.offset'][0])
                        if articles_per_page > 0:
                            totalPages = (last_offset // articles_per_page) + 1
                            print(f"      ℹ️ '맨끝' 버튼 href offset에서 총 페이지 수 계산: {totalPages} (offset={last_offset}, limit={articles_per_page})")
                            determined_total_pages = True
                        else:
                             print(f"      ⚠️ articles_per_page가 0이어서 총 페이지 계산 불가.")
                    except (ValueError, IndexError):
                        print(f"      ⚠️ '맨끝' 버튼 href offset 파싱 실패: {href}")
                else:
                    print(f"      ⚠️ '맨끝' 버튼 href에 article.offset 없음: {href}")
            else:
                 print("      ℹ️ Offset 방식의 '맨끝' 버튼(li.last a, a.last, a.next_end) 없음.")

        if not determined_total_pages:
            print("      ℹ️ 총 페이지 수를 명확히 알 수 없어 기본 1페이지만 처리합니다. (Offset 방식 실패)")
            totalPages = 1
        elif totalPages <= 0 :
             print(f"      ⚠️ 계산된 총 페이지 수가 0 이하({totalPages})입니다. 1페이지만 처리합니다.")
             totalPages = 1

    except Exception as e:
        print(f"      ⚠️ 총 페이지 수 확인 중 오류 발생: {e}. 기본 1페이지만 처리.")
        totalPages = 1
        traceback.print_exc()

    # 페이지 루프
    for page_num in range(1, totalPages + 1):
        if page_num == 1:
            page_url = board_url
            soup = initial_soup
        else:
            page_url = build_page_url(board_url, page_num, articles_per_page)
            if not page_url:
                 print(f"      ❌ [{dept_name}] 페이지 {page_num} URL 생성 실패. 건너<0xEB><0x9B><0x81>니다.")
                 continue
            print(f"  -> [{dept_name}] 페이지 {page_num}/{totalPages} 크롤링 중: {page_url}")
            soup = get_soup(page_url)
            if not soup:
                print(f"      ❌ [{dept_name}] 페이지 {page_num} 로드 실패. 건너<0xEB><0x9B><0x81>니다.")
                continue

        # 페이지 내 게시글 처리
        post_rows_selector = "tbody > tr"
        post_rows = soup.select(post_rows_selector)
        if not post_rows and page_num == 1:
            print(f"      ⚠️ [{dept_name}] 페이지 {page_num}: 게시글 행({post_rows_selector}) 없음.")

        found_posts_on_page = 0
        for index, row in enumerate(post_rows):
            cells = row.select("td")
            is_sticky = False
            if len(cells) < 2:
                continue
            try:
                first_cell_content = cells[0]
                is_sticky_img = first_cell_content.find('img', alt=lambda x: x and '공지' in x) is not None
                first_cell_text = first_cell_content.get_text(strip=True)
                is_sticky_text = not first_cell_text.isdigit() if first_cell_text else False
                is_sticky = is_sticky_img or is_sticky_text
            except IndexError:
                continue
            if is_sticky and page_num > 1:
                continue

            # 날짜 추출 (수정됨)
            date_from_list = "날짜 없음"
            date_cell = row.select_one("td:nth-of-type(4)") # 4번째 td만 확인
            if date_cell:
                date_text = date_cell.get_text(strip=True)
                match = re.search(r'\d{4}[-./]\d{2}[-./]\d{2}', date_text)
                if match:
                    date_from_list = match.group().replace('-', '.').replace('/', '.')

            # 상세 URL 추출
            title_element = None
            title_cell_candidates = ["td:nth-of-type(2) a[href]", "td.title a[href]", "td.subject a[href]"]
            for selector in title_cell_candidates:
                 title_element = row.select_one(selector)
                 if title_element:
                     break
            if not title_element:
                continue

            post_relative_url = title_element.get('href')
            if not post_relative_url or post_relative_url.startswith('javascript:'):
                continue
            post_absolute_url = urljoin(page_url, post_relative_url)

            # 상세 크롤링 및 데이터 처리
            detail_data = crawl_post_detail(post_absolute_url) # 수정된 상세 함수 호출
            if not detail_data or not detail_data.get('해시'):
                continue
            post_hash = detail_data.get('해시')
            if post_hash in processed_hashes_in_dept:
                continue
            processed_hashes_in_dept.add(post_hash)

            final_data = {
                '학과': dept_name,
                '작성일': date_from_list, # 수정된 날짜
                '제목': detail_data.get('제목', '제목 없음'), # 수정된 제목
                '본문': detail_data.get('본문', ''), # 수정된 본문
                '해시': post_hash,
                '원본URL': post_absolute_url,
                '이미지파일명': detail_data.get('이미지파일명', '')
            }
            if final_data['제목'] != "제목 없음":
                 all_posts_data.append(final_data)
                 found_posts_on_page += 1

        print(f"      -> 페이지 {page_num}: {found_posts_on_page}개 신규 게시글 처리 완료.")
        if totalPages > 1 and page_num < totalPages :
             time.sleep(REQUEST_DELAY * 1.5) # 페이지 이동 딜레이

    print(f"--- [{dept_name}] 게시판 처리 완료: 총 {len(all_posts_data)}개 유효 데이터 수집 ({totalPages} 페이지 확인) ---")
    if not all_posts_data:
        departments_with_no_results.append(dept_name + f"({totalPages}p 확인,결과없음)")
    return all_posts_data

# --- 5. 메인 실행 로직 ---
if __name__ == "__main__":
    start_time_total = time.time()
    department_boards_result = extract_notice_board_urls(college_intro_pages)
    all_results_before_dedup = []
    df_final_output = pd.DataFrame()
    if not department_boards_result:
        print("\n🚨 URL 자동 추출 실패.")
    else:
        print("\n===== 2단계: 게시판별 *전체* 페이지 크롤링 시작 =====")
        start_time_crawl = time.time()
        print(f"총 {len(department_boards_result)}개 학과/전공 크롤링...")
        for dept_name, board_url in tqdm(department_boards_result.items(), desc="전체 학과 진행률"):
            results = crawl_board_list(dept_name, board_url) # 수정된 함수 호출
            if results:
                all_results_before_dedup.extend(results)
        crawl_end_time = time.time()
        print("\n===== 크롤링 완료 (중복 제거 전) =====")
        print(f"총 {len(all_results_before_dedup)}개 게시글 수집 완료.")
        print(f"크롤링 소요 시간: {crawl_end_time - start_time_crawl:.2f} 초")

        if all_results_before_dedup:
            try: # --- 3단계: 중복 제거 및 CSV 저장 ---
                df = pd.DataFrame(all_results_before_dedup)
                print("\n--- 3단계: 중복 제거 시작 ---")
                initial_count = len(df)
                df_deduplicated = pd.DataFrame()
                if '해시' in df.columns and '제목' in df.columns:
                    df_deduplicated = df.dropna(subset=['제목', '해시']).drop_duplicates(subset=['제목', '해시'], keep='first')
                else:
                    print("⚠️ 컬럼 부족. 제목 기준 중복 제거 시도.")
                    df_deduplicated = df.dropna(subset=['제목']).drop_duplicates(subset=['제목'], keep='first')
                removed_count = initial_count - len(df_deduplicated)
                print(f"중복 제거 후 {len(df_deduplicated)}개 고유 게시글 남음. ({removed_count}개 제거됨)")

                # CSV 저장 컬럼 (공지글 열 제외)
                final_columns_map = {'학과': '학과', '제목': '제목', '작성일': '작성일', '본문': '본문내용','원본URL': 'URL', '이미지파일명': '이미지'}
                df_to_save = df_deduplicated[[col for col in final_columns_map.keys() if col in df_deduplicated.columns]].rename(columns=final_columns_map)
                # CSV 저장 순서 (공지글 열 제외)
                desired_order = ['학과', '제목', '작성일', '본문내용', 'URL', '이미지']
                df_final_output = df_to_save[[col for col in desired_order if col in df_to_save.columns]]

                df_final_output.to_csv(CSV_FILEPATH, index=False, encoding='utf-8-sig')
                print(f"\n✅ 최종 결과를 '{CSV_FILEPATH}'에 저장.")
                print(f"  저장된 컬럼: {list(df_final_output.columns)}")
            except ImportError:
                print("\n❌ 'pandas' 필요")
                df_final_output = pd.DataFrame()
            except Exception as e:
                print(f"\n❌ CSV 저장/처리 오류: {e}")
                traceback.print_exc()
                df_final_output = pd.DataFrame()
        else:
             print("\n⚠️ 저장할 유효 데이터 없음.")

    # --- 4단계: 이미지 파일 정리 ---
    print("\n===== 4단계: 이미지 파일 정리 시작 =====")
    try:
        if not df_final_output.empty and os.path.exists(CSV_FILEPATH):
            print(f"'{CSV_FILEPATH}' 기준 이미지 정리...")
            if '이미지' not in df_final_output.columns:
                print("⚠️ '이미지' 컬럼 없음.")
            else:
                referenced_images = set()
                for image_cell in df_final_output['이미지'].dropna():
                    if isinstance(image_cell, str):
                        filenames = [img.strip() for img in image_cell.split(',') if img.strip()]
                        referenced_images.update(filenames)
                print(f"-> 최종 참조 이미지 {len(referenced_images)}개 확인.")
                try:
                    if not os.path.isdir(IMAGE_FOLDER):
                         print(f"⚠️ 이미지 폴더 '{IMAGE_FOLDER}' 없음.")
                    else:
                        actual_files_in_folder = [f for f in os.listdir(IMAGE_FOLDER) if os.path.isfile(os.path.join(IMAGE_FOLDER, f))]
                        print(f"-> 폴더 내 파일 {len(actual_files_in_folder)}개 확인.")
                        files_to_delete = [f for f in actual_files_in_folder if f not in referenced_images]
                        if not files_to_delete:
                            print("✅ 삭제할 불필요 이미지 없음.")
                        else:
                            print(f"-> 삭제 예정: {len(files_to_delete)}개")
                            if files_to_delete:
                                deleted_count = 0
                                error_count = 0
                                print("... 이미지 삭제 작업 진행 중 ...")
                                for filename in tqdm(files_to_delete, desc="불필요 이미지 삭제 중"):
                                    try:
                                        os.remove(os.path.join(IMAGE_FOLDER, filename))
                                        deleted_count += 1
                                    except OSError as e:
                                        print(f"\n  ❌ 삭제 실패: {filename} - {e}")
                                        error_count += 1
                                print(f"\n✅ 정리 완료: {deleted_count}개 삭제, {error_count}개 실패.")
                except Exception as e:
                    print(f"❌ 폴더 조회 오류: {e}")
        elif df_final_output.empty:
             print("ℹ️ 최종 데이터 없음.")
        else:
             print(f"ℹ️ CSV 파일 '{CSV_FILEPATH}' 없음.")
    except Exception as e:
        print(f"\n❌ 이미지 정리 중 오류: {e}")
        traceback.print_exc()

    # --- 최종 요약 및 누락 정보 출력 ---
    print("\n===== 크롤링 결과 요약 =====")
    final_post_count = 0
    if not df_final_output.empty:
        final_post_count = len(df_final_output)
    print(f"총 {len(department_boards_result) if department_boards_result else 0}개 학과/전공 URL 시도.")
    print(f"최종 수집된 고유 게시글 수: {final_post_count}")
    if failed_college_extractions:
        print("\n[🔴 1단계 URL 추출 실패/누락]")
        for college in failed_college_extractions:
            print(f"- {college}")

    departments_needing_analysis = set(departments_with_no_results)
    analyzed_dept_names_from_unknown = set()
    if department_boards_result:
        for url in unknown_template_urls:
            found_dept = None
            for name, board_url_from_dict in department_boards_result.items():
                try:
                    base_board_url = board_url_from_dict.split('?')[0]
                    if url.startswith(base_board_url) or url.startswith(board_url_from_dict):
                        found_dept = name
                        break
                except Exception: pass
            if found_dept:
                analyzed_dept_names_from_unknown.add(found_dept)
    departments_needing_analysis.update(analyzed_dept_names_from_unknown)

    if departments_needing_analysis:
        print("\n[🟡 2단계 상세 분석 필요 학과 목록]")
        print("  (원인: 첫 페이지 로드 실패, 게시글 없음, 템플릿 미인식 등)")
        for dept in sorted(list(departments_needing_analysis)):
            print(f"- {dept}")
        if unknown_template_urls:
            print("\n  미인식 상세 페이지 URL (일부):")
            for i, url in enumerate(list(unknown_template_urls)):
                 if i >= 5: print("  ..."); break
                 print(f"  - {url}")
        print("\n  => 위 학과 HTML 구조 분석 및 선택자 수정 필요.")
    elif unknown_template_urls:
         print("\n[⚠️ 상세 페이지 템플릿 미인식 URL 목록]")
         for i, url in enumerate(list(unknown_template_urls)):
             if i >= 10: print(" ..."); break
             print(f"- {url}")

    # --- 전체 프로세스 종료 시간 측정 ---
    total_end_time = time.time()
    print(f"\n===== 전체 프로세스 종료 (총 시간: {total_end_time - start_time_total:.2f} 초) =====")
    