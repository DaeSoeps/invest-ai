# invest-ai

Python으로 관심 종목 데이터를 모으고 OpenAI API에 분석을 요청한 뒤, 생성된 JSON을 웹 대시보드에서 보여주는 투자 테마 분석 MVP입니다.

## 구조

```text
config/watchlist.csv     관심 종목 목록
server.py                대시보드 서버 + 분석 실행 API
src/generate_report.py   데이터 수집 + OpenAI 분석 + JSON 생성
data/report.json         프론트가 읽는 분석 결과
index.html               대시보드 화면
app.js                   report.json 로드와 필터/탭 UI
styles.css               화면 스타일
```

## 실행

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env`에 사용할 AI 제공자와 키를 넣은 뒤:

```bash
AI_PROVIDER=gemini
GEMINI_API_KEY=your-gemini-key
GEMINI_MODEL=gemini-2.5-flash
```

```bash
python server.py
```

브라우저에서 `http://localhost:5173`을 열면 됩니다.

화면을 여는 것만으로는 AI API를 호출하지 않습니다. 대시보드의 `AI 분석 실행` 버튼을 눌렀을 때만 새 분석을 요청하고 `data/report.json`을 갱신합니다. 분석 API는 30초에 한 번만 실행되도록 서버와 버튼 양쪽에서 제한합니다.

가격, 52주 위치, PER, RSI, 20일선, 60일선 같은 정량 지표는 로컬 파이썬 코드가 전체 관심 종목에 대해 계산합니다. AI에는 사전 점수가 높은 일부 종목과 핵심 뉴스만 보내며, AI 응답이 늦거나 실패하면 정량 지표 중심의 임시 리포트를 바로 표시합니다.

Gemini 응답 대기 시간은 기본 25초입니다. 필요하면 `.env`에 `GEMINI_TIMEOUT=30`처럼 조정할 수 있습니다.

API 키 없이 기존 샘플 결과만 확인하려면:

```bash
python src/generate_report.py --sample
python server.py
```

## 주의

이 앱은 투자 판단을 자동화하는 도구가 아니라 리서치 보조 도구입니다. 수집 데이터의 지연, 누락, 오류가 있을 수 있으므로 실제 투자 전 원천 데이터를 다시 확인해야 합니다.
