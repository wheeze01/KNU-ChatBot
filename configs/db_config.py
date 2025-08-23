from dotenv import load_dotenv
import os

load_dotenv()

# DB 설정 불러오기
DB_CONFIG = {
    'host': os.getenv("DB_SERVER"),
    'port': int(os.getenv("DB_PORT", 1433)),  # 기본값 1433
    'user': os.getenv("DB_USER"),
    'password': os.getenv("DB_PASSWORD"),
    'database': os.getenv("DB_NAME"),
}