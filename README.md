# Hunter Email Server

웹사이트가 들어 있는 엑셀 파일을 업로드하면 Hunter API로 이메일을 조회하고,
영업 관련성이 높은 연락처만 우선 선별한 엑셀 파일을 반환하는 서버입니다.

## GitHub 업로드 파일

- app.py
- requirements.txt
- render.yaml
- README.md

## Render 설정

Build Command:
pip install -r requirements.txt

Start Command:
gunicorn app:app

Environment Variable:
HUNTER_API_KEY = 대표님 Hunter API Key

## 테스트 주소

서버 생성 후 아래 주소를 확인하세요.

https://서버주소.onrender.com/health

정상이라면 다음과 비슷하게 나옵니다.

{
  "status": "ok",
  "hunter_api_key_loaded": true
}

## GPT Actions용 Schema

https://서버주소.onrender.com/openapi.json
