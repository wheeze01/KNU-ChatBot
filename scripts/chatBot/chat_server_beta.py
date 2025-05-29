from flask import Flask, request, jsonify, send_from_directory
import pandas as pd
import os
from datetime import datetime

app = Flask(__name__)

# CSV 및 이미지 폴더 설정
CSV_PATH = '../../data/icee_categorized_sample.csv'
IMAGE_FOLDER = os.path.abspath('../../data/images')
NGROK_BASE_URL = 'https://72ed-210-110-128-79.ngrok-free.app'

# CSV 불러오기
df = pd.read_csv(CSV_PATH)

@app.route('/images/<path:filename>')
def serve_image(filename):
    return send_from_directory(IMAGE_FOLDER, filename)

@app.route('/message', methods=['POST'])
def message():
    data = request.get_json()
    utterance = data.get('action', {}).get('params', {}).get('utterance', '').strip()

    # 입력을 'topic, 학과[, 정렬옵션]' 형식으로 분리
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

    if 'department' not in df.columns or 'topic' not in df.columns or 'deadline' not in df.columns:
        return jsonify({
            "version": "2.0",
            "template": {
                "outputs": [
                    {
                        "simpleText": {
                            "text": "'department', 'topic', 'deadline' 열이 CSV에 존재하는지 확인해주세요."
                        }
                    }
                ]
            }
        })

    today = pd.to_datetime(datetime.today().date())
    df['deadline'] = pd.to_datetime(df['deadline'], errors='coerce')

    topic = topic.replace(' ', '').lower()
    department = department.replace(' ', '').lower()

    df['정규과'] = df['department'].fillna('').str.replace(' ', '').str.lower()
    df['정규토픽'] = df['topic'].fillna('').str.replace(' ', '').str.lower()

    matches = df[
        df['정규토픽'].str.contains(topic, na=False) &
        df['정규과'].str.contains(department, na=False) &
        df['deadline'].notna() & (df['deadline'] >= today)
    ]

    if sort_option == '마감순':
        matches = matches.sort_values(by='deadline', ascending=True)
    elif sort_option == '최신순':
        matches = matches.sort_values(by='deadline', ascending=False)
    elif sort_option == '오래된순':
        matches = matches.sort_values(by='deadline', ascending=True)

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
        description = f"마감일: {deadline}\n요약: {one_line}"

        
        link = row['link']
        raw_path = row['image']
        image_url = f"{NGROK_BASE_URL}/images/{os.path.basename(raw_path)}" if pd.notna(raw_path) and raw_path else None


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
