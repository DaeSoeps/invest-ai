# invest-ai

Python으로 관심 종목 데이터를 모으고 정량 스캔 결과를 웹 대시보드에서 보여주는 투자 테마 분석 MVP입니다. AI는 전체 실행마다 호출하지 않고, 사용자가 종목별 상세 분석을 요청할 때만 사용합니다.

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

화면을 여는 것만으로는 AI API를 호출하지 않습니다. 상승 기대 탭에서 `핫한 후보 스캔` 버튼을 누르면 AI 없이 가격, PER, RSI, 20일선, 60일선, 뉴스 기준으로 상위 후보를 계산하고 `data/report.json`을 갱신합니다. 종목 카드의 `상세 AI 분석` 버튼을 눌렀을 때만 해당 종목 하나를 AI에 요청합니다.

`Top 종목` 탭에서는 같은 버튼이 `Top 종목 분석 실행`으로 바뀌며, 오늘 상한가/하한가 종목 Top 10과 최근 뉴스 기반 한줄 평가를 불러옵니다.

분석 API는 30초에 한 번만 실행되도록 서버와 버튼 양쪽에서 제한합니다. AI 응답이 늦거나 실패하면 정량 지표 중심의 임시 상세 분석을 바로 표시합니다.

Gemini 응답 대기 시간은 기본 25초입니다. 필요하면 `.env`에 `GEMINI_TIMEOUT=30`처럼 조정할 수 있습니다.

API 키 없이 기존 샘플 결과만 확인하려면:

```bash
python src/generate_report.py --sample
python server.py
```

## 주의

이 앱은 투자 판단을 자동화하는 도구가 아니라 리서치 보조 도구입니다. 수집 데이터의 지연, 누락, 오류가 있을 수 있으므로 실제 투자 전 원천 데이터를 다시 확인해야 합니다.
