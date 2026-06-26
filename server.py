from __future__ import annotations

import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
from html import unescape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote
from urllib.request import Request, urlopen

from src.generate_report import (
    analyze_detail_with_gemini,
    analyze_detail_with_openai,
    fetch_google_news,
    load_env,
    remove_flow_claims,
)

ROOT = Path(__file__).resolve().parent
REPORT_PATH = ROOT / "data" / "report.json"
HISTORY_DIR = ROOT / "data" / "history"
ANALYZE_COOLDOWN_SECONDS = 30
_analyze_lock = threading.Lock()
_last_analyze_at: float | None = None
_last_stock_analyze_at: float | None = None


def strip_tags(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value)
    return unescape(value).replace("\xa0", " ").strip()


def parse_number_text(value: str) -> str:
    return re.sub(r"\s+", " ", strip_tags(value))


def history_id(prefix: str) -> str:
    return f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}"


def save_history(kind: str, payload: dict, title: str) -> dict:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = payload.get("generated_at") or time.strftime("%Y-%m-%dT%H:%M:%S%z")
    item_id = history_id(kind)
    record = {
        "id": item_id,
        "kind": kind,
        "title": title,
        "generated_at": generated_at,
        "payload": payload,
    }
    path = HISTORY_DIR / f"{item_id}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {key: record[key] for key in ("id", "kind", "title", "generated_at")}


def list_history(limit: int = 80) -> list[dict]:
    if not HISTORY_DIR.is_dir():
        return []
    items = []
    for path in sorted(HISTORY_DIR.glob("*.json"), reverse=True):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        items.append({key: record.get(key, "") for key in ("id", "kind", "title", "generated_at")})
        if len(items) >= limit:
            break
    return items


def read_history(item_id: str) -> dict | None:
    if not re.fullmatch(r"[a-z-]+-\d{8}-\d{6}", item_id):
        return None
    path = HISTORY_DIR / f"{item_id}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


THEME_RULES = [
    ("반도체/AI 인프라", ("반도체", "HBM", "패키징", "AI", "데이터센터", "광주", "전남", "호남", "첨단")),
    ("신재생/전력", ("신재생", "태양광", "풍력", "ESS", "전력", "RE100", "에너지", "인버터")),
    ("전기차/부품", ("전기차", "EV", "배터리", "2차전지", "콘덴서", "캐패시터", "커패시터")),
    ("자본재편", ("감자", "유상증자", "무상증자", "주식병합", "변경상장", "거래재개", "투자설명서", "신주")),
    ("수주/실적", ("수주", "공급계약", "실적", "흑자", "매출", "영업이익")),
]

RISK_RULES = [
    ("검토 단계", ("검토", "가능성", "거론", "추진", "예정", "기대")),
    ("재무 이벤트", ("감자", "유상증자", "결손", "채무", "적자", "주식병합")),
    ("단기 과열", ("상한가", "급등", "2연속", "연속", "가격제한폭")),
]


def find_keywords(text: str, keywords: tuple[str, ...]) -> list[str]:
    lowered = text.lower()
    return [keyword for keyword in keywords if keyword.lower() in lowered]


def classify_mover_reason(name: str, label: str, headline: str, source: str, streak: str, accumulated: str, per: str = "") -> dict:
    text = f"{name} {headline}"
    themes = []
    for theme, keywords in THEME_RULES:
        matched = find_keywords(text, keywords)
        if matched:
            themes.append({"name": theme, "keywords": matched[:4]})

    risks = []
    for risk, keywords in RISK_RULES:
        matched = find_keywords(text, keywords)
        if matched:
            risks.append(risk)
    if streak and streak not in {"-", "0", "1"}:
        risks.append(f"{streak}연속 {label}")
    if per.strip().startswith("-"):
        risks.append("PER 음수")

    if headline:
        reason = f"{headline} 재료가 {label} 배경으로 잡혔습니다."
    else:
        reason = f"{label} 종목이지만 직접 매칭된 최신 뉴스가 부족합니다."
    if themes:
        theme_names = ", ".join(theme["name"] for theme in themes[:2])
        reason = f"{theme_names} 테마가 붙었습니다. {reason}"

    signal = "관망"
    if label == "상한가" and themes:
        signal = "테마 급등"
    if "재무 이벤트" in risks:
        signal = "재무 이벤트 주의"
    if label == "하한가":
        signal = "급락 원인 확인"

    return {
        "reason": reason,
        "theme_tags": themes[:3],
        "risk_flags": list(dict.fromkeys(risks))[:4],
        "signal": signal,
        "source_hint": f"{source} 기사 기반" if source else "가격 제한폭 데이터 기반",
        "checklist": [
            "뉴스가 실제 회사 실적/수주로 연결되는지 확인",
            "공시와 유상증자/감자 같은 자본 이벤트 확인",
            "연속 상한가 이후 거래대금과 시초가 변동성 확인",
        ],
    }


def fetch_naver_movers(kind: str, limit: int = 10) -> list[dict]:
    path = "sise_upper.naver" if kind == "upper" else "sise_lower.naver"
    label = "상한가" if kind == "upper" else "하한가"
    url = f"https://finance.naver.com/sise/{path}"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=10) as response:
        html = response.read().decode("cp949", errors="ignore")

    rows: list[dict] = []
    for row_html in re.findall(r"<tr>\s*(.*?)\s*</tr>", html, flags=re.DOTALL):
        link = re.search(r'href="/item/main\.naver\?code=(\d+)">([^<]+)</a>', row_html)
        if not link:
            continue
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.DOTALL)
        if len(cells) < 7:
            continue
        name = strip_tags(link.group(2))
        news_query = f"{name} 주식 {label}"
        if kind == "upper":
            news_query = f"{name} 상한가 이유 반도체 신재생"
        news = fetch_google_news(news_query, limit=1)
        headline = news[0]["title"] if news else ""
        source = news[0]["source"] if news else ""
        news_url = news[0]["url"] if news else ""
        reason_detail = classify_mover_reason(
            name=name,
            label=label,
            headline=headline,
            source=source,
            streak=parse_number_text(cells[1]),
            accumulated=parse_number_text(cells[2]),
            per=parse_number_text(cells[11]) if len(cells) > 11 else "",
        )
        rows.append(
            {
                "kind": kind,
                "label": label,
                "code": link.group(1),
                "name": name,
                "streak": parse_number_text(cells[1]),
                "accumulated": parse_number_text(cells[2]),
                "price": parse_number_text(cells[4]),
                "change": parse_number_text(cells[5]),
                "change_rate": parse_number_text(cells[6]),
                "volume": parse_number_text(cells[7]) if len(cells) > 7 else "-",
                "per": parse_number_text(cells[11]) if len(cells) > 11 else "-",
                "reason": reason_detail["reason"],
                "theme_tags": reason_detail["theme_tags"],
                "risk_flags": reason_detail["risk_flags"],
                "signal": reason_detail["signal"],
                "source_hint": reason_detail["source_hint"],
                "checklist": reason_detail["checklist"],
                "news_title": headline,
                "news_source": source,
                "news_url": news_url,
                "url": f"https://finance.naver.com/item/main.naver?code={link.group(1)}",
            }
        )
        if len(rows) >= limit:
            break
    return rows


def fallback_stock_detail(stock: dict, news: list[dict]) -> dict:
    rsi = stock.get("rsi14")
    ma20 = stock.get("ma20")
    ma60 = stock.get("ma60")
    price = stock.get("current_price")
    per = stock.get("per") or "-"
    headline = news[0]["title"] if news else stock.get("impact_news", {}).get("title", "")
    return {
        "summary": f"{stock.get('name')}은 가격 지표와 최근 뉴스 기준으로만 임시 평가했습니다.",
        "technical": f"RSI {rsi if rsi is not None else '-'}, 현재가 {price if price is not None else '-'}, 20일선 {ma20 if ma20 is not None else '-'}, 60일선 {ma60 if ma60 is not None else '-'} 기준으로 추세 훼손 여부를 확인해야 합니다.",
        "news": f"가장 가까운 뉴스는 '{headline}'입니다." if headline else "매칭된 최신 뉴스가 부족합니다.",
        "valuation": f"PER은 {per}이며, 업종 평균과 성장 기대를 같이 비교해야 합니다.",
        "risk": "AI 응답 실패 시 표시되는 임시 분석이므로 원천 뉴스와 차트를 직접 확인하세요.",
        "source": {"mode": "fallback"},
    }


class InvestAIHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/api/report":
            self.send_json_file(REPORT_PATH)
            return
        if self.path == "/api/history":
            self.send_json({"ok": True, "items": list_history()})
            return
        if self.path.startswith("/api/history/"):
            item_id = unquote(self.path.rsplit("/", 1)[-1])
            record = read_history(item_id)
            if not record:
                self.send_json({"ok": False, "message": "기록을 찾지 못했습니다."}, status=404)
                return
            self.send_json({"ok": True, "record": record})
            return

        requested = self.path.split("?", 1)[0]
        if requested in {"", "/"}:
            requested = "/index.html"

        target = (ROOT / unquote(requested.lstrip("/"))).resolve()
        if not target.is_file() or ROOT not in target.parents:
            self.send_error(404)
            return

        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(target.read_bytes())

    def do_POST(self) -> None:
        if self.path == "/api/analyze":
            self.handle_analyze()
            return
        if self.path == "/api/analyze-stock":
            self.handle_analyze_stock()
            return
        if self.path == "/api/top-movers":
            self.handle_top_movers()
            return
        self.send_error(404)

    def read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def handle_analyze(self) -> None:
        global _last_analyze_at
        if self.path != "/api/analyze":
            self.send_error(404)
            return

        with _analyze_lock:
            now = time.monotonic()
            if _last_analyze_at is not None:
                retry_after = ANALYZE_COOLDOWN_SECONDS - (now - _last_analyze_at)
            else:
                retry_after = 0
            if retry_after > 0:
                self.send_json(
                    {
                        "ok": False,
                        "message": f"{int(retry_after) + 1}초 후 다시 분석할 수 있습니다.",
                        "retry_after": int(retry_after) + 1,
                    },
                    status=429,
                    headers={"Retry-After": str(int(retry_after) + 1)},
                )
                return
            _last_analyze_at = now

        result = subprocess.run(
            [sys.executable, str(ROOT / "src" / "generate_report.py"), "--scan-only"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=90,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            message = "AI 분석 실행에 실패했습니다."
            if "insufficient_quota" in stderr or "exceeded your current quota" in stderr:
                message = "OpenAI API 할당량 또는 결제 설정을 확인해야 합니다."
            elif "OPENAI_API_KEY" in stderr:
                message = "OPENAI_API_KEY가 설정되지 않았습니다."
            elif "GEMINI_API_KEY" in stderr:
                message = "GEMINI_API_KEY가 설정되지 않았습니다."
            elif "HTTP 503" in stderr or "UNAVAILABLE" in stderr:
                message = "Gemini 모델 사용량이 많습니다. 잠시 후 다시 시도하세요."
            elif "시간 초과" in stderr or "timed out" in stderr:
                message = "Gemini 응답이 지연되고 있습니다. 잠시 후 다시 시도하세요."
            elif "Gemini API 요청 실패" in stderr:
                message = "Gemini API 요청에 실패했습니다. 키, 무료 한도, 모델명을 확인하세요."
            self.send_json(
                {
                    "ok": False,
                    "message": message,
                    "stderr": stderr,
                    "stdout": result.stdout.strip(),
                },
                status=500,
            )
            return

        report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        history = save_history("scan", report, "핫한 후보 스캔")
        mode = report.get("source", {}).get("mode")
        message = "핫한 후보 스캔이 완료되었습니다."
        if mode == "fallback":
            message = "정량 지표 중심 임시 리포트를 표시합니다."
        self.send_json({"ok": True, "message": message, "report": report, "history": history})

    def handle_analyze_stock(self) -> None:
        global _last_stock_analyze_at
        payload = self.read_json_body()
        code = str(payload.get("code", "")).strip()
        if not code:
            self.send_json({"ok": False, "message": "종목 코드가 없습니다."}, status=400)
            return

        with _analyze_lock:
            now = time.monotonic()
            retry_after = ANALYZE_COOLDOWN_SECONDS - (now - _last_stock_analyze_at) if _last_stock_analyze_at else 0
            if retry_after > 0:
                self.send_json(
                    {"ok": False, "message": f"{int(retry_after) + 1}초 후 다시 분석할 수 있습니다.", "retry_after": int(retry_after) + 1},
                    status=429,
                    headers={"Retry-After": str(int(retry_after) + 1)},
                )
                return
            _last_stock_analyze_at = now

        report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        stock = next((item for item in report.get("stocks", []) if item.get("code") == code), None)
        if not stock:
            self.send_json({"ok": False, "message": "먼저 후보 스캔을 실행하세요."}, status=404)
            return

        related_news = [
            item
            for item in report.get("news", [])
            if item.get("tag") == stock.get("name") or stock.get("name", "") in item.get("title", "")
        ][:3]
        detail_stock = {
            key: stock.get(key)
            for key in (
                "name",
                "code",
                "theme",
                "score",
                "current_price",
                "change_percent",
                "position_52",
                "drawdown",
                "ma20",
                "ma60",
                "rsi14",
                "market_cap",
                "per",
                "impact_news",
            )
        }
        inputs = {"stock": detail_stock, "news": related_news}

        load_env()
        provider = os.getenv("AI_PROVIDER", "").strip().lower()
        gemini_key = os.getenv("GEMINI_API_KEY")
        openai_key = os.getenv("OPENAI_API_KEY")
        if not provider:
            provider = "gemini" if gemini_key else "openai"

        try:
            if provider == "gemini" and gemini_key:
                detail = analyze_detail_with_gemini(inputs, os.getenv("GEMINI_MODEL", "gemini-2.5-flash"), gemini_key)
                detail["source"] = {"mode": "gemini"}
            elif provider == "openai" and openai_key:
                detail = analyze_detail_with_openai(inputs, os.getenv("OPENAI_MODEL", "gpt-5-mini"))
                detail["source"] = {"mode": "openai"}
            else:
                detail = fallback_stock_detail(stock, related_news)
        except Exception as exc:
            detail = fallback_stock_detail(stock, related_news)
            detail["source"] = {"mode": "fallback", "description": str(exc).splitlines()[0]}

        for key in ("summary", "technical", "news", "valuation", "risk"):
            if isinstance(detail.get(key), str):
                detail[key] = remove_flow_claims(detail[key])
        history = save_history(
            "detail",
            {"code": code, "stock": stock, "detail": detail, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")},
            f"{stock.get('name')} 상세 분석",
        )
        self.send_json({"ok": True, "message": f"{stock.get('name')} 상세 분석 완료", "code": code, "detail": detail, "history": history})

    def handle_top_movers(self) -> None:
        try:
            upper = fetch_naver_movers("upper", 10)
            lower = fetch_naver_movers("lower", 10)
        except Exception as exc:
            self.send_json({"ok": False, "message": f"Top 종목 데이터를 가져오지 못했습니다: {exc}"}, status=500)
            return
        payload = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "upper": upper,
            "lower": lower,
        }
        history = save_history("top", payload, "상한가·하한가 Top 10")
        self.send_json({"ok": True, "message": "상한가/하한가 종목을 불러왔습니다.", **payload, "history": history})

    def send_json_file(self, path: Path) -> None:
        if not path.is_file():
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(path.read_bytes())

    def send_json(self, payload: dict, status: int = 200, headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5173
    server = ThreadingHTTPServer(("127.0.0.1", port), InvestAIHandler)
    print(f"invest-ai server: http://127.0.0.1:{port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
