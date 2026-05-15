# Hunter Email Server - JSON Action Version

GPT가 업로드된 엑셀을 직접 읽고, 첫 번째 열의 웹사이트 목록만 서버로 보냅니다.
서버는 JSON으로 받은 웹사이트 목록을 Hunter API로 조회하고 우선 영업 대상 연락처를 반환합니다.

업로드 파일을 Action에 직접 전달하지 않기 때문에 GPT 파일 전달 오류를 피할 수 있습니다.

Render 설정:
Build Command:
pip install --only-binary=:all: -r requirements.txt

Start Command:
gunicorn app:app

GPT Actions Schema URL:
https://hunter-email-server.onrender.com/openapi.json
