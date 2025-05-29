# ChatBot
KNU CHATBOT
강원대학교 챗봇 서비스
공모전, 학사 일정, 비교과 활동 등의 정보를 제공

# ngkrok 설치하기
Linux 기준

```
brew install ngrok/ngrok/ngrok
```
windows 기준
```
sudo snap install ngrok
```
## ngrok 인증 토큰 등록

- ngrok 대시보드 로그인 후 토큰 발급 후 복사
```
ngrok config add-authtoken <YOUR_AUTH_TOKEN>
```
- chat_server_beta.py 실행
- default port 5000
- ngrok http 5000 으로 외부 접속 주소 생성

