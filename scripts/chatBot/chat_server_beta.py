from flask import Flask, request, jsonify, send_from_directory
import pandas as pd
import os
from datetime import datetime

app = Flask(__name__)

# CSV 및 이미지 폴더 설정
CSV_PATH = '../../data/icee_crawl_with_posted.csv'
IMAGE_FOLDER = os.path.abspath('../../data/images')
NGROK_BASE_URL = 'https://a1c8-175-206-174-9.ngrok-free.app'

# CSV 불러오기
df = pd.read_csv(CSV_PATH)

@app.route('/images/<path:filename>')
def serve_image(filename):
    return send_from_directory(IMAGE_FOLDER, filename)

@app.route('/message', methods=['POST'])
def message():
    data = request.get_json()
    utterance = data.get('action', {}).get('params', {}).get('utterance', '').strip()

    # 인사말 처리 (채팅방 입장 또는 입력 없음)
    if not utterance:
        return jsonify({
            "version": "2.0",
            "template": {
                "outputs": [
                    {
                        "simpleText": {
                            "text": "안녕하세요! 강원대 챗봇에 오신 것을 환영합니다! 😊\n찾고 싶은 정보를 말씀해 주세요!\n예: 공모전, 컴퓨터공학과, 마감순"
                        }
                    }
                ]
            }
        })

    # 사용자 입력 처리
    try:
        parts = [s.strip() for s in utterance.split(',')]
        if len(parts) < 2:
            raise ValueError
        topic = parts[0]
        department = parts[1]
        sort_option = parts[2] if len(parts) >= 3 else '마감순'
    except ValueError:
        return jsonify({
            "version": "2.0",
            "template": {
                "outputs": [
                    {
                        "simpleText": {
                            "text": "입력 형식은 '주제, 학과[, 정렬옵션]'처럼 콤마로 구분해주세요.\n예: 공모전, 컴퓨터공학과, 마감순"
                        }
                    }
                ]
            }
        })

    required_columns = {'department', 'topic', 'deadline', 'posted_date'}
    if not required_columns.issubset(df.columns):
        return jsonify({
            "version": "2.0",
            "template": {
                "outputs": [
                    {
                        "simpleText": {
                            "text": f"CSV에 {', '.join(required_columns)} 열이 포함되어 있는지 확인해주세요."
                        }
                    }
                ]
            }
        })

    today = pd.to_datetime(datetime.today().date())
    df['deadline'] = pd.to_datetime(df['deadline'], errors='coerce')
    df['posted_date'] = pd.to_datetime(df['posted_date'], errors='coerce')

    topic = topic.replace(' ', '').lower()
    department = department.replace(' ', '').lower()

    df['정규과'] = df['department'].fillna('').str.replace(' ', '').str.lower()
    df['정규토픽'] = df['topic'].fillna('').str.replace(' ', '').str.lower()

    matches = df[
        df['정규토픽'].str.contains(topic, na=False) &
        df['정규과'].str.contains(department, na=False) &
        df['deadline'].notna() & (df['deadline'] >= today)
    ]

    sort_map = {
        '마감순': ('deadline', True),
        '최신순': ('deadline', False),
        '오래된순': ('posted_date', True),
        '게시일순': ('posted_date', False),
        '게시일오래된순': ('posted_date', True)
    }

    sort_col, ascending = sort_map.get(sort_option, ('deadline', True))
    matches = matches.sort_values(by=sort_col, ascending=ascending)

    if matches.empty:
        return jsonify({
            "version": "2.0",
            "template": {
                "outputs": [
                    {
                        "simpleText": {
                            "text": f"'{topic}, {department}' 관련 마감 기한이 지난 정보이거나 검색 결과가 없습니다."
                        }
                    }
                ]
            }
        })

    cards = []
    for _, row in matches.head(3).iterrows():
        title = row['title']
        one_line = row['one_line'] if pd.notna(row['one_line']) else '요약 없음'
        deadline = row['deadline'].strftime('%Y-%m-%d') if pd.notna(row['deadline']) else '정보 없음'
        # = row['posted_date'].strftime('%Y-%m-%d') if pd.notna(row['posted_date']) else '정보 없음'
        description = f"마감일: {deadline}\n{one_line}"

        link = row['link']
        raw_path = row['image']
        first_image = raw_path.split(';')[0] if isinstance(raw_path, str) else ''
        image_url = f"{NGROK_BASE_URL}/images/{os.path.basename(first_image)}" if first_image else None

        card = {
            "title": title,
            "description": description,
            "thumbnail": {"imageUrl": image_url} if image_url else {},
            "buttons": [
                {
                    "action": "webLink",
                    "label": "자세히 보기",
                    "webLinkUrl": link
                }
            ]
        }
        cards.append(card)

    return jsonify({
        "version": "2.0",
        "template": {
            "outputs": [
                {
                    "carousel": {
                        "type": "basicCard",
                        "items": cards
                    }
                }
            ]
        }
    })

if __name__ == '__main__':
    app.run(port=5000)
