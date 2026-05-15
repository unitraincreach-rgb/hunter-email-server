# Hunter Full Email Download URL Server

이 버전은 GPT Actions가 XLSX 바이너리 파일을 직접 받지 못하는 문제를 해결합니다.

작동 방식:
1. GPT가 엑셀 첫 번째 열에서 웹사이트 목록을 읽습니다.
2. extractAllEmailsFile 작업에 websites 배열을 전달합니다.
3. 서버가 Hunter API pagination으로 전체 이메일을 수집합니다.
4. 서버가 XLSX 파일을 직접 생성합니다.
5. GPT에는 download_url만 반환합니다.
6. 사용자는 download_url을 클릭해 엑셀을 다운로드합니다.

GPT Actions Schema URL:
https://hunter-email-server.onrender.com/openapi.json

GPT 지침:
사용자가 엑셀 파일을 업로드하면 첫 번째 열에서 웹사이트 URL 또는 도메인을 읽는다.
읽은 웹사이트 목록을 extractAllEmailsFile 작업의 websites 배열로 전달한다.
작업 결과의 download_url을 사용자에게 다운로드 링크로 제공한다.
priority_contacts가 아니라 전체 FOUND 이메일을 기준으로 추출한다.
