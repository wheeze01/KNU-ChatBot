from dotenv import load_dotenv
import os
from google import genai
import pandas as pd
import json
import re
import pytesseract
from PIL import Image

pytesseract.pytesseract.tesseract_cmd = r"C:/Program Files/Tesseract-OCR/tesseract.exe"
custom_config = r'--oem 3 --psm 6 -l kor+eng'

def extract_text_from_images(image_paths):
    ocr_texts = []
    for image_path in image_paths:
        print("image_path: " + image_path)
        full_image_path = os.path.join("data/", image_path)
        if os.path.exists(full_image_path):
            try:
                image = Image.open(full_image_path)
                text = pytesseract.image_to_string(image, config=custom_config)
                print(f"[OCR TEXT] {image_path}:\n{text.strip()}\n")  # OCR 결과 출력
                ocr_texts.append(text.strip())
            except Exception as e:
                print(f"[OCR ERROR] {image_path} - {e}")
        else:
            print(f"[IMAGE NOT FOUND] {image_path}")
    return "\n".join(ocr_texts)

# API 키 로드
load_dotenv()
GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_ID = "gemini-2.5-flash-preview-04-17"

client = genai.Client(api_key=GOOGLE_API_KEY)

# 프롬프트 템플릿 불러오기
with open("scripts/llm/prompt_template.txt", "r", encoding="utf-8") as f:
    prompt_template = f.read()

# CSV 데이터 불러오기
df = pd.read_csv("data/통합 크롤링 코드.csv", encoding="utf-8")

# 결과 저장용 리스트
results = []

# 한 행씩 프롬프트에 넣어 결과 생성
for i, row in df.sample(n=10).iterrows():
    title = row.get("제목", "")
    body = row.get("본문내용", "")  
    
    image_paths_str = str(row.get("사진", "")).strip()
    
    # image_paths = image_paths_str.split(",") if image_paths_str.lower() != "nan" else []
    
    #NaN 방지 + 공백 제거 + 쉼표 분리 
    if image_paths_str.lower() != "nan" and image_paths_str != "":
        image_paths = [p.strip() for p in image_paths_str.split(";") if p.strip()]
    else:
        image_paths = []

    ocr_text = extract_text_from_images(image_paths)
    print("ocr_text: " + ocr_text)
    
    # # 여러 이미지 처리리
    # uploaded_files = []
    # for image_path in image_paths:
    #     image_path = image_path.strip()
    #     full_image_path = os.path.join("data/images_content", image_path)
    #     if os.path.exists(full_image_path):
    #          uploaded_file = client.files.upload(file=full_image_path)
    #          uploaded_files.append(uploaded_file)
    #     else:
    #         print(f"[NOTICE] index {i} - Image not found or invalid path: {image_path}")



    prompt = prompt_template.format(title=title, body=body, ocr=ocr_text)
    contents = [prompt]
    
    # 토큰 수 사전 측정
    try:
        token_info = client.models.count_tokens(model=MODEL_ID, contents=contents)
        pre_token_count = token_info.total_tokens
    except Exception as e:
        print(f"[TOKEN COUNT ERROR] index {i} - {e}")
        pre_token_count = None
    
    # 출력 텍스트를 파싱
    try:
        # Gemini API 요청
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=contents
        )

        # 토큰 사용량 확인
        usage = response.usage_metadata
        prompt_token_count = usage.prompt_token_count if usage else None
        response_token_count = usage.candidates_token_count if usage else None
        total_token_count = usage.total_token_count if usage else None
        
        # 응답에서 텍스트 추출
        answer = response.candidates[0].content.parts[0].text.strip()
        print(f"\n [LLM RAW RESPONSE - index {i}]:\n{answer}\n")
        
        # 백틱 감싼 부분 제거
        if answer.startswith("```"):
            # 백틱으로 감싸진 JSON만 추출
            answer = re.sub(r"^```(?:json)?\n?", "", answer)
            answer = re.sub(r"\n?```$", "", answer)

        #  JSON 파싱
        parsed = json.loads(answer)
        results.append(parsed)

        # Pre_token: contents에 들어간 입력(prompt+이미지등)을 기준으로 LLM이 생성 전에 사전 계산한 토큰 수
        # Prompt_token: 실체 요청 시 사용된 입력의 토큰 수; pre_token_count와 거의 일치하지만, 가끔 내부 처리 차이로 미세한 차이가 날 수도 있음
        # Response_token: 모델이 생성한 출력의 토큰 수
        # Total_token: 입력+출력을 합친 총 토큰 수 (요금 청구구 기준)
        print(f"[Token Summary] index {i}")
        print(f"  pre_token_count       : {pre_token_count}")
        print(f"  prompt_token_count    : {prompt_token_count}")
        print(f"  response_token_count  : {response_token_count}")
        print(f"  total_token_count     : {total_token_count}")

    except Exception as e:
        print(f"[PARSE ERROR] index {i} - {e}")
        continue

# CSV로 저장
output_df = pd.DataFrame(results)
output_df.to_csv("data/llm_classified_results.csv", index=False, encoding="utf-8-sig")
print("분류 결과 저장 완료!")
