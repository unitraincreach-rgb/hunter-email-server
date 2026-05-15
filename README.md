# Hunter Full Email XLSX Server

전체 이메일 추출용 서버입니다.

- Hunter Domain Search pagination 적용
- limit=100, offset 반복 조회
- 전체 FOUND 이메일 저장
- 서버가 직접 hunter_all_emails.xlsx 생성
- Priority Contacts 시트도 함께 생성

Render Build Command:

pip install --only-binary=:all: -r requirements.txt

Render Start Command:

gunicorn app:app

GPT Actions Schema URL:

https://hunter-email-server.onrender.com/openapi.json
