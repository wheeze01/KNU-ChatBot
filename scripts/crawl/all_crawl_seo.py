# 통합 크롤링 코드 (강원대 전 기관 + 전 학과)
import os
import csv
import time
import re
import random
import unicodedata
from datetime import datetime
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from tqdm import tqdm
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

HEADERS = {"User-Agent": "Mozilla/5.0"}
SAVE_FOLDER = "강원대_공지_이미지"
CSV_FILE = "강원대_공지_통합.csv"
os.makedirs(SAVE_FOLDER, exist_ok=True)

session = requests.Session()
retry = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retry)
session.mount("http://", adapter)
session.mount("https://", adapter)

all_data = []
existing_notice_keys = set()

def sanitize_filename(name):
    return re.sub(r'[^\w\s_.-]', '_', name).strip()

def save_image(img_url, folder, prefix, idx, original_name="image.jpg"):
    try:
        os.makedirs(folder, exist_ok=True)
        ext = os.path.splitext(original_name)[1]
        if not ext or len(ext) > 5:
            ext = '.jpg'
        filename = sanitize_filename(f"{prefix}_{idx}{ext}")
        filepath = os.path.join(folder, filename)

        res = session.get(img_url, headers=HEADERS, timeout=10)
        time.sleep(random.uniform(0.5, 1.2))
        if res.status_code == 200 and len(res.content) > 1024:
            with open(filepath, "wb") as f:
                f.write(res.content)
            return filepath.replace("\\", "/")
    except:
        pass
    return None

def clean_html_keep_table(raw_html):
    soup = BeautifulSoup(raw_html, 'html.parser')
    output = ''
    for table in soup.find_all('table'):
        output += extract_table_text(table) + '\n'
        table.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for elem in soup.find_all(['p', 'div', 'span']):
        text = elem.get_text(strip=True, separator="\n")
        if text:
            output += text + '\n'
    return output.strip()

def extract_table_text(table):
    rows = table.find_all('tr')
    return '\n'.join(
        ' | '.join(col.get_text(strip=True) for col in row.find_all(['td', 'th']) if col.get_text(strip=True))
        for row in rows if row.find_all(['td', 'th'])
    )

def extract_written_date(soup):
    text = soup.get_text(" ", strip=True)
    match = re.search(r'20\d{2}[.\-/년\s]+[01]?\d[.\-/월\s]+[0-3]?\d[일\s]*', text)
    if match:
        raw = match.group().replace(" ", "").replace("년", ".").replace("월", ".").replace("일", "")
        return raw.strip(".")
    return "(작성일 없음)"

def generate_notice_key(title, date):
    while re.search(r'(\[[^\]]*\]|\{[^\}]*\}|<[^>]*>)', title):
        title = re.sub(r'(\[[^\]]*\]|\{[^\}]*\}|<[^>]*>)', '', title)
    title = re.sub(r'[^가-힣a-z0-9()]', '', unicodedata.normalize('NFKC', title.lower()))
    date = date.replace('.', '').replace('-', '').replace('/', '').replace(' ', '').lower()
    return f"{title}_{date}"

def add_notice_if_not_duplicate(title, date, content, link, images):
    key = generate_notice_key(title, date)
    if key not in existing_notice_keys:
        existing_notice_keys.add(key)
        all_data.append({
            "제목": title,
            "작성일": date,
            "본문내용": content,
            "링크": link,
            "사진": images
        })
    else:
        print(f"⛔ 중복으로 건너뜀: {title[:40]} ({date})")


def get_soup(url):
    try:
        response = session.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        response.encoding = response.apparent_encoding
        return BeautifulSoup(response.text, 'html.parser')
    except:
        return None

def extract_notice_board_urls(college_pages_list):
    from urllib.parse import urljoin

    department_boards_dict = {}
    base_wwwk_url = "https://wwwk.kangwon.ac.kr"

    for college in tqdm(college_pages_list, desc="단과대학 페이지 처리 중"):
        soup = get_soup(college['url'])
        if not soup:
            continue
        blocks = soup.select("div.box.temp_titbox")
        for block in blocks:
            dept = block.select_one("h4.h0")
            link = block.select_one("ul.shortcut li:last-child a")
            if dept and link:
                name = dept.text.strip().split('\n')[0]

                # ✅ 수동 매핑에 있는 학과는 자동 등록하지 않음
                if name in manual_board_mapping:
                    continue

                href = link.get("href")
                if href:
                    url = urljoin(base_wwwk_url, href)
                    url = url.replace("wwwk.kangwon.ac.kr/wwwk.kangwon.ac.kr", "wwwk.kangwon.ac.kr")
                    department_boards_dict[name] = url
        time.sleep(0.1)

    # ✅ 수동 매핑 학과 추가
    for dept_name, manual_url in manual_board_mapping.items():
        department_boards_dict[dept_name] = manual_url

    return department_boards_dict



def crawl_all_departments(board_dict, max_page=None):
    def append_offset(url, offset):
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        query['article.offset'] = [str(offset)]
        new_query = urlencode(query, doseq=True)
        return urlunparse(parsed._replace(query=new_query))

    for dept, url in tqdm(board_dict.items(), desc="학과별 진행"):
        print(f"\n📘 [{dept}] 시작: {url}")
        count = 0
        page = 0
        while True:
            if max_page is not None and page >= max_page:
                print(f"  🔚 최대 페이지({max_page}) 도달 → 종료")
                break

            page_url = append_offset(url, page * 10)
            soup = get_soup(page_url)
            if not soup:
                print(f"  ❌ 페이지 요청 실패 (page={page + 1})")
                break

            rows = soup.select("tbody tr")
            if not rows:
                print("  🔚 더 이상 행 없음 → 종료")
                break

            has_general_post = False

            for row in rows:
                no_td = row.select_one("td")
                is_notice = no_td and "공지" in no_td.text

                a_tag = row.select_one("a")
                if not a_tag:
                    continue

                title = a_tag.get_text(strip=True)
                href = urljoin(url, a_tag.get("href"))

                try:
                    detail_soup = get_soup(href)
                    if not detail_soup:
                        continue
                    content_div = detail_soup.select_one("div.fr-view") or detail_soup.select_one("div.view-content")
                    content = clean_html_keep_table(str(content_div)) if content_div else "(본문 없음)"
                    date = extract_written_date(detail_soup)

                    imgs = []

                    img_tags = detail_soup.find_all("img")
                    for i, img in enumerate(img_tags):
                        src = img.get("src") or img.get("data-src") or img.get("srcset", "").split()[0]
                        if not src or src.startswith("data:image"):
                            continue

                        src_lower = src.lower()
                        if any(keyword in src_lower for keyword in ['logo', 'favicon', '/common/', '/img/', '/images/', '/static/', 'knu_ci']):
                            continue
                        if not any(path in src_lower for path in ['/upload/', '/editor/', '/bbs/', '/board/', '/notice/', '/file/', '/attach/']):
                            continue

                        full_img_url = urljoin(href, src)
                        saved = save_image(full_img_url, os.path.join(SAVE_FOLDER, "college_depts", dept), dept, i)
                        if saved:
                            imgs.append(saved)

                    for i, a in enumerate(detail_soup.select("a.file-down-btn")):
                        href_file = a.get("href", "")
                        name = a.get_text(strip=True)
                        if href_file and name.lower().endswith(('.jpg', '.jpeg', '.png')):
                            full_img_url = urljoin(href, href_file)
                            saved = save_image(full_img_url, os.path.join(SAVE_FOLDER, "college_depts", dept), dept, i + 100)
                            if saved:
                                imgs.append(saved)

                    add_notice_if_not_duplicate(title, date, content, href, ";".join(filter(None, imgs)))
                    print(f"    📄 [{page + 1}p] {'[공지] ' if is_notice else ''}{title[:40]}")
                    count += 1
                    if not is_notice:
                        has_general_post = True
                except Exception as e:
                    print(f"    ❌ 상세 페이지 실패: {title[:30]} ({e})")

            if not has_general_post:
                print(f"  🔚 더 이상 일반 글 없음 (page {page + 1}), 종료")
                break

            page += 1
            time.sleep(random.uniform(0.5, 1.2))
        print(f"✅ [{dept}] 총 수집: {count}건")







def crawl_mainpage():
    print("\n📂 [메인페이지] 시작")
    BASE_URL = "https://www.kangwon.ac.kr"
    PATH_PREFIX = "/www"
    categories = [
        {"name": "공지사항", "bbsNo": "81", "key": "277", "last_page": 5},
        {"name": "행사안내", "bbsNo": "38", "key": "279", "last_page": 2},
        {"name": "공모모집", "bbsNo": "345", "key": "1959", "last_page": 2},
        {"name": "장학게시판", "bbsNo": "34", "key": "232", "last_page": 2},
    ]
    for cat in categories:
        for page in range(1, cat['last_page'] + 1):
            list_url = f"{BASE_URL}{PATH_PREFIX}/selectBbsNttList.do?bbsNo={cat['bbsNo']}&pageUnit=10&key={cat['key']}&pageIndex={page}"
            res = session.get(list_url, headers=HEADERS)
            time.sleep(random.uniform(0.5, 1.2))
            soup = BeautifulSoup(res.text, 'html.parser')
            rows = soup.select("tbody tr")
            for row in rows:
                if row.select_one(".notice"):
                    continue
                a_tag = row.select_one("td.subject a")
                if not a_tag:
                    continue
                title = a_tag.text.strip()
                href = a_tag.get("href", "")
                if "fnSelectBbsNttView" in href:
                    match = re.search(r"fnSelectBbsNttView\('(\d+)',\s*'(\d+)',\s*'(\d+)'\)", href)
                    if not match:
                        continue
                    bbs_no, ntt_no, key_param = match.groups()
                    detail_url = f"{BASE_URL}{PATH_PREFIX}/selectBbsNttView.do?bbsNo={bbs_no}&nttNo={ntt_no}&key={key_param}"
                else:
                    detail_url = urljoin(f"{BASE_URL}{PATH_PREFIX}/", href)
                try:
                    r = session.get(detail_url, headers=HEADERS)
                    time.sleep(random.uniform(0.5, 1.2))
                    s = BeautifulSoup(r.text, 'html.parser')
                    content_div = s.select_one("div#bbs_ntt_cn_con") or s.select_one("td.bbs_content") or s.select_one("div.bbs_content")
                    content = content_div.get_text("\n", strip=True) if content_div else "(본문 없음)"
                    date = extract_written_date(s)
                    img_tags = content_div.select("img") if content_div else []
                    photo_div = s.select_one("div.photo_area")
                    if photo_div:
                        img_tags += photo_div.select("img")
                    images = [urljoin(detail_url, img.get("src")) for img in img_tags if img.get("src")]
                    img_files = [save_image(link, os.path.join(SAVE_FOLDER, "main"), cat['bbsNo'], i) for i, link in enumerate(images)]
                    img_files = list(filter(None, img_files))
                    add_notice_if_not_duplicate(title, date, content, detail_url, ";".join(img_files))
                except Exception as e:
                    print(f"❌ 메인페이지 상세 실패: {title[:30]} ({e})")


def crawl_library():
    print("\n📂 [도서관] 시작")
    base_url = "https://library.kangwon.ac.kr"
    list_api = f"{base_url}/pyxis-api/1/bulletin-boards/24/bulletins"
    detail_api = f"{base_url}/pyxis-api/1/bulletins/24/{{id}}"
    per_page = 10
    seen_ids = set()
    for page in range(0, 5):
        offset = page * per_page
        params = {"offset": offset, "max": 10, "bulletinCategoryId": 1}
        try:
            res = session.get(list_api, headers=HEADERS, params=params)
            time.sleep(random.uniform(0.5, 1.2))
            data = res.json().get("data", {})
            for item in data.get("list", []):
                id_ = item['id']
                if id_ in seen_ids:
                    continue
                seen_ids.add(id_)
                title = item['title']
                detail_url = f"{base_url}/community/bulletin/notice/{id_}"
                try:
                    detail = session.get(detail_api.format(id=id_), headers=HEADERS).json().get("data", {})
                    time.sleep(random.uniform(0.5, 1.2))
                    raw_date = detail.get("dateCreated", "작성일 없음")[:10]
                    date = raw_date.replace("-", ".")
                    html = detail.get("content", "")
                    soup = BeautifulSoup(html, "html.parser")
                    content = soup.get_text("\n", strip=True)
                    images = [urljoin(base_url, img['src']) for img in soup.find_all("img") if "/pyxis-api/attachments/" in img.get('src', '')]
                    img_files = [save_image(link, os.path.join(SAVE_FOLDER, "library"), id_, i) for i, link in enumerate(images)]
                    add_notice_if_not_duplicate(title, date, content, detail_url, ";".join(filter(None, img_files)))
                except Exception as e:
                    print(f"❌ 도서관 상세 실패: {title[:30]} ({e})")
        except Exception as e:
            print(f"❌ 도서관 목록 실패 (offset={offset}): {e}")


def crawl_administration():
    print("\n📂 [행정학과] 시작")
    base_url = "https://padm.kangwon.ac.kr"
    for offset in range(0, 200, 10):  # 필요시 범위 확장
        url = f"{base_url}/padm/life/notice-department.do?article.offset={offset}"
        try:
            res = session.get(url, headers=HEADERS)
            time.sleep(random.uniform(0.5, 1.2))
            soup = BeautifulSoup(res.text, 'html.parser')
        except Exception as e:
            print(f"❌ 목록 요청 실패 (offset={offset}): {e}")
            continue

        for idx, row in enumerate(soup.select("td.b-td-left.b-td-title")):
            a_tag = row.select_one("a")
            if not a_tag:
                continue
            title = a_tag.text.strip()
            if "공지" in title:
                continue  # 공지 제외
            relative = a_tag.get("href", "")
            detail_link = f"{base_url}/padm/life/notice-department.do{relative[relative.find('?'):]}" if '?' in relative else f"{base_url}/padm/life/notice-department.do"

            try:
                r = session.get(detail_link, headers=HEADERS)
                time.sleep(random.uniform(0.5, 1.2))
                s = BeautifulSoup(r.text, 'html.parser')
                content_div = s.select_one("div.b-content-box div.fr-view") or s.select_one("div.b-content-box")
                content = clean_html_keep_table(str(content_div)) if content_div else "(본문 없음)"
                date_tag = s.select_one("li.b-date-box span:nth-of-type(2)")
                date = date_tag.text.strip() if date_tag else "(작성일 없음)"

                img_links = []
                for a in s.select("div.b-file-box a.file-down-btn"):
                    name = a.text.strip()
                    file_href = a.get("href", "")
                    if not file_href:
                        continue
                    full_link = base_url + "/padm/life/notice-department.do" + file_href if file_href.startswith('?') else file_href
                    if name.lower().endswith(('.png', '.jpg', '.jpeg')):
                        img_links.append(full_link)

                img_files = [save_image(link, os.path.join(SAVE_FOLDER, "admin"), offset + idx, i) for i, link in enumerate(img_links)]
                img_files = list(filter(None, img_files))
                add_notice_if_not_duplicate(title, date, content, detail_link, ";".join(img_files))

            except Exception as e:
                print(f"❌ 행정학과 상세 실패: {title[:30]} ({e})")


def crawl_engineering():
    print("\n📂 [공학교육혁신센터] 시작")
    base_url = "https://icee.kangwon.ac.kr"
    for page in range(1, 10):  # 필요시 범위 확장
        url = f"{base_url}/index.php?mt=page&mp=5_1&mm=oxbbs&oxid=1&cpage={page}"
        try:
            res = session.get(url, headers=HEADERS)
            time.sleep(random.uniform(0.5, 1.2))
            soup = BeautifulSoup(res.text, 'html.parser')
        except Exception as e:
            print(f"❌ 목록 요청 실패 (page={page}): {e}")
            continue

        for row in soup.select("table.bbs_list tbody tr"):
            a_tag = row.select_one("td.tit a")
            if not a_tag:
                continue
            title = a_tag.text.strip()
            href = urljoin(base_url, a_tag['href'])
            raw_date = row.select_one("td.dt").text.strip().replace("-", ".")

            try:
                r = session.get(href, headers=HEADERS)
                time.sleep(random.uniform(0.5, 1.2))
                s = BeautifulSoup(r.text, 'html.parser')
                content_div = s.select_one("div.view_cont") or s.select_one("div.note")
                content = content_div.get_text("\n", strip=True) if content_div else "(본문 없음)"

                imgs = content_div.find_all("img") if content_div else []
                img_files = []
                for i, img in enumerate(imgs):
                    src = img.get("src")
                    if src and not src.startswith("data:image"):
                        img_files.append(save_image(
                            urljoin(href, src),
                            os.path.join(SAVE_FOLDER, "engineering"),
                            page, i
                        ))
                img_files = list(filter(None, img_files))
                add_notice_if_not_duplicate(title, raw_date, content, href, ";".join(img_files))

            except Exception as e:
                print(f"❌ 공학교육혁신센터 상세 실패: {title[:30]} ({e})")


def crawl_international():
    print("\n📂 [국제교류처] 시작")
    base_url = "https://oiaknu.kangwon.ac.kr"
    for offset in range(0, 30, 10):
        url = f"{base_url}/oiaknu/notice.do?article.offset={offset}"
        try:
            res = session.get(url, headers=HEADERS)
            time.sleep(random.uniform(0.5, 1.2))
            soup = BeautifulSoup(res.text, 'html.parser')
        except Exception as e:
            print(f"❌ 목록 요청 실패 (offset={offset}): {e}")
            continue

        rows = soup.select("td.b-td-left.b-td-title")
        if not rows:
            break

        for idx, row in enumerate(rows):
            a_tag = row.select_one("a")
            if not a_tag:
                continue
            title = a_tag.get("title", "").replace("자세히 보기", "").strip()
            relative = a_tag.get("href", "")
            detail_link = f"{base_url}/oiaknu/notice.do{relative[relative.find('?'):]}" if '?' in relative else f"{base_url}/oiaknu/notice.do"

            try:
                r = session.get(detail_link, headers=HEADERS)
                time.sleep(random.uniform(0.5, 1.2))
                s = BeautifulSoup(r.text, 'html.parser')
                content_div = s.select_one("div.b-content-box div.fr-view") or s.select_one("div.b-content-box")
                content = clean_html_keep_table(str(content_div)) if content_div else "(본문 없음)"
                date_tag = s.select_one("li.b-date-box span:nth-of-type(2)")
                date = date_tag.text.strip() if date_tag else "(작성일 없음)"

                img_links = []
                for a in s.select("div.b-file-box a.file-down-btn"):
                    name = a.text.strip()
                    file_href = a.get("href", "")
                    if not file_href:
                        continue
                    full_link = (
                        base_url + "/oiaknu/notice.do" + file_href
                        if file_href.startswith('?') else file_href
                    )
                    if name.lower().endswith(('.png', '.jpg', '.jpeg')):
                        img_links.append(full_link)

                img_files = [
                    save_image(link, os.path.join(SAVE_FOLDER, "international"), offset + idx, i)
                    for i, link in enumerate(img_links)
                ]
                img_files = list(filter(None, img_files))
                add_notice_if_not_duplicate(title, date, content, detail_link, ";".join(img_files))

            except Exception as e:
                print(f"❌ 국제교류처 상세 실패: {title[:30]} ({e})")


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


# 추가 매핑: 학과 이름 -> 공지사항 URL
manual_board_mapping = {
    "AI융합학과": "https://ai.kangwon.ac.kr/ai/community/notice.do",
    "디지털밀리터리학과": "https://military.kangwon.ac.kr/military/professor/notice.do",
    "자유전공학부": "https://liberal.kangwon.ac.kr/liberal/community/notice.do",
    "글로벌융합학부": "https://globalconvergence.kangwon.ac.kr/globalconvergence/info/undergraduate-community.do",
    "미래융합가상학과": "https://multimajor.kangwon.ac.kr/multimajor/community/notice.do",
    "동물산업융합학과": "https://animal.kangwon.ac.kr/animal/community/notice.do"
    # 필요시 여기에 추가
}


if __name__ == "__main__":
    print("\n🚀 강원대 전체 공지 크롤링 시작")
    # crawl_mainpage()
    # crawl_library()
    # crawl_engineering()
    # crawl_administration()
    # crawl_international()

    boards = extract_notice_board_urls(college_intro_pages)
    if boards:
        crawl_all_departments(boards)



    with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["제목", "작성일", "본문내용", "링크", "사진"])
        writer.writeheader()
        writer.writerows(all_data)
    print(f"\n✅ 저장 완료: {CSV_FILE}")