from __future__ import annotations

import argparse
import csv
import json
import os
import re
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
WATCHLIST_PATH = ROOT / "config" / "watchlist.csv"
OUTPUT_PATH = ROOT / "data" / "report.json"
SAMPLE_PATH = ROOT / "data" / "report.json"


REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "market_summary": {"type": "string"},
        "stocks": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "code": {"type": "string"},
                    "theme": {"type": "string"},
                    "score": {"type": "integer", "minimum": 0, "maximum": 100},
                    "conviction": {"type": "string", "enum": ["상", "중", "하"]},
                    "note": {"type": "string"},
                    "risk": {"type": "string"},
                    "foreign": {"type": "number"},
                    "foreign_streak": {"type": "integer"},
                    "ownership": {"type": "number"},
                    "institution": {"type": "number"},
                    "institution_streak": {"type": "integer"},
                    "signal": {"type": "string"},
                    "position_52": {"type": "number", "minimum": 0, "maximum": 100},
                    "drawdown": {"type": "number"},
                    "market_cap": {"type": "string"},
                    "per": {"type": "string"},
                    "impact_news": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "title": {"type": "string"},
                            "source": {"type": "string"},
                            "published_at": {"type": "string"},
                            "url": {"type": "string"},
                            "reason": {"type": "string"},
                        },
                        "required": ["title", "source", "published_at", "url", "reason"],
                    },
                },
                "required": [
                    "name",
                    "code",
                    "theme",
                    "score",
                    "conviction",
                    "note",
                    "risk",
                    "foreign",
                    "foreign_streak",
                    "ownership",
                    "institution",
                    "institution_streak",
                    "signal",
                    "position_52",
                    "drawdown",
                    "market_cap",
                    "per",
                    "impact_news",
                ],
            },
        },
        "themes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "rank": {"type": "integer"},
                    "name": {"type": "string"},
                    "score": {"type": "number"},
                    "status": {"type": "string"},
                    "reason": {"type": "string"},
                    "names": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["rank", "name", "score", "status", "reason", "names"],
            },
        },
        "news": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "time": {"type": "string"},
                    "date": {"type": "string"},
                    "published_at": {"type": "string"},
                    "tag": {"type": "string"},
                    "title": {"type": "string"},
                    "source": {"type": "string"},
                    "url": {"type": "string"},
                },
                "required": ["time", "date", "published_at", "tag", "title", "source", "url"],
            },
        },
    },
    "required": ["market_summary", "stocks", "themes", "news"],
}


def load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        env_path = ROOT / ".env"
        if not env_path.is_file():
            return
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        return
    load_dotenv(ROOT / ".env")


def read_watchlist(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:
        return None
    return result


def round_optional(value: float | None, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None else None


def calculate_rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) <= period:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(closes[-period - 1 : -1], closes[-period:]):
        change = current - previous
        gains.append(max(change, 0))
        losses.append(abs(min(change, 0)))
    average_gain = sum(gains) / period
    average_loss = sum(losses) / period
    if average_loss == 0:
        return 100.0
    rs = average_gain / average_loss
    return round(100 - (100 / (1 + rs)), 1)


def fetch_price_snapshot(symbol: str, price_scale: float = 1.0) -> dict[str, Any]:
    try:
        import yfinance as yf
    except ImportError:
        return {}

    try:
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        history = ticker.history(period="1y", auto_adjust=False)
        raw_closes = [float(value) for value in history["Close"].dropna().tolist()] if not history.empty else []
        closes = [value * price_scale for value in raw_closes]
        last_price = (as_float(info.get("last_price")) or (raw_closes[-1] if raw_closes else 0.0)) * price_scale
        year_high = (as_float(info.get("year_high")) or (max(raw_closes) if raw_closes else 0.0)) * price_scale
        year_low = (as_float(info.get("year_low")) or (min(raw_closes) if raw_closes else 0.0)) * price_scale
        previous_close = (as_float(info.get("previous_close")) or (raw_closes[-2] if len(raw_closes) > 1 else 0.0)) * price_scale
        ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None
        ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else None
        rsi14 = calculate_rsi(closes)
    except Exception:
        return {}

    change_percent = 0.0
    if previous_close:
        change_percent = round((last_price - previous_close) / previous_close * 100, 2)

    position_52 = 50.0
    drawdown = 0.0
    if year_high and year_low and year_high > year_low:
        position_52 = round((last_price - year_low) / (year_high - year_low) * 100, 1)
    if year_high:
        drawdown = round((last_price - year_high) / year_high * 100, 1)

    return {
        "current_price": round_optional(last_price, 0),
        "last_price": round_optional(last_price, 0),
        "change_percent": change_percent,
        "year_high": round_optional(year_high, 0),
        "year_low": round_optional(year_low, 0),
        "position_52": max(0.0, min(100.0, position_52)),
        "drawdown": drawdown,
        "ma20": round_optional(ma20, 0),
        "ma60": round_optional(ma60, 0),
        "rsi14": rsi14,
    }


def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    return text.replace("&quot;", '"').replace("&amp;", "&").strip()


def parse_rss_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        from email.utils import parsedate_to_datetime

        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone()


def format_news_date(value: str) -> tuple[str, str]:
    parsed = parse_rss_datetime(value)
    if not parsed:
        return "", ""
    return parsed.strftime("%Y-%m-%d"), parsed.strftime("%H:%M")


def fetch_google_news(query: str, limit: int = 4) -> list[dict[str, str]]:
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=ko&gl=KR&ceid=KR:ko"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=8) as response:
            xml = response.read()
    except Exception:
        return []

    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return []

    items: list[dict[str, str]] = []
    for item in root.findall("./channel/item")[:limit]:
        title = strip_html(item.findtext("title", default=""))
        link = item.findtext("link", default="")
        pub_date = item.findtext("pubDate", default="")
        source = item.findtext("source", default="Google News")
        date_text, time_text = format_news_date(pub_date)
        items.append(
            {
                "title": title,
                "url": link,
                "published_at": pub_date,
                "date": date_text,
                "time": time_text,
                "source": source,
            }
        )
    return items


def collect_inputs(watchlist: list[dict[str, str]], news_limit: int) -> dict[str, Any]:
    stocks: list[dict[str, Any]] = []
    news: list[dict[str, str]] = []

    for item in watchlist:
        snapshot = fetch_price_snapshot(item["yahoo_symbol"], as_float(item.get("price_scale")) or 1.0)
        stocks.append(
            {
                "name": item["name"],
                "code": item["code"],
                "symbol": item["yahoo_symbol"],
                "theme": item["theme"],
                "market_cap": item["market_cap"],
                "per": item["per"],
                "price": snapshot,
            }
        )
        news.extend(fetch_google_news(f'{item["name"]} 주식', limit=news_limit))

    return {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "stocks": stocks,
        "news": news[: max(8, news_limit * len(watchlist))],
    }


def sample_report() -> dict[str, Any]:
    with SAMPLE_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    data["generated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    data["source"] = {
        "mode": "sample",
        "description": "OPENAI_API_KEY가 없어 샘플 분석 데이터를 사용했습니다.",
    }
    return data


def analyze_with_openai(inputs: dict[str, Any], model: str) -> dict[str, Any]:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("openai 패키지가 설치되어 있지 않습니다. pip install -r requirements.txt 를 실행하세요.") from exc

    client = OpenAI()
    response = client.responses.create(
        model=model,
        instructions=(
            "너는 한국 주식 테마/수급 리포트를 만드는 분석 엔진이다. "
            "투자 조언이나 매수 확정 표현은 피하고, 제공된 데이터와 뉴스만 근거로 점수화한다. "
            "수급 데이터가 없으면 가격 위치와 뉴스 모멘텀 중심으로 보수적으로 추정하고, "
            "각 종목 note와 risk에는 근거와 위험을 한 문장씩 한국어로 쓴다."
        ),
        input=json.dumps(inputs, ensure_ascii=False),
        text={
            "format": {
                "type": "json_schema",
                "name": "investment_report",
                "schema": REPORT_SCHEMA,
                "strict": False,
            }
        },
    )
    return json.loads(response.output_text)


def clean_json_text(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
    return text


def request_gemini_once(inputs: dict[str, Any], model: str, api_key: str) -> dict[str, Any]:
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    prompt = {
        "role": "system",
        "task": (
            "너는 한국 주식 테마/수급 리포트를 만드는 분석 엔진이다. "
            "투자 조언이나 매수 확정 표현은 피하고, 제공된 데이터와 뉴스만 근거로 점수화한다. "
            "수급 데이터가 없으면 가격 위치와 뉴스 모멘텀 중심으로 보수적으로 추정한다. "
            "각 종목 impact_news에는 제공된 뉴스 중 해당 종목 점수에 가장 큰 영향을 준 기사 1개를 넣는다. "
            "뉴스를 새로 만들지 말고 title, source, published_at, url은 입력 뉴스 값을 그대로 사용한다. "
            "반드시 JSON 객체만 출력한다."
        ),
        "output_schema": REPORT_SCHEMA,
        "input_data": inputs,
    }
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": json.dumps(prompt, ensure_ascii=False)}],
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
        },
    }
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=45) as response:
            body = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini API 요청 실패: HTTP {exc.code} {detail}") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise RuntimeError("Gemini API 요청 시간 초과") from exc

    try:
        text = body["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"Gemini API 응답에서 텍스트를 찾지 못했습니다: {body}") from exc
    return json.loads(clean_json_text(text))


def analyze_with_gemini(inputs: dict[str, Any], model: str, api_key: str) -> dict[str, Any]:
    fallback_model = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash-lite")
    models = [model]
    if fallback_model and fallback_model not in models:
        models.append(fallback_model)

    last_error: Exception | None = None
    for candidate in models:
        for attempt in range(2):
            try:
                return request_gemini_once(inputs, candidate, api_key)
            except RuntimeError as exc:
                last_error = exc
                message = str(exc)
                if "HTTP 503" not in message and "UNAVAILABLE" not in message and "시간 초과" not in message:
                    raise
                if attempt < 1:
                    time.sleep(2 + attempt)
        if candidate != models[-1]:
            print(f"{candidate} 사용량이 높아 {models[-1]}로 재시도합니다.", file=sys.stderr)
    if last_error:
        raise last_error
    raise RuntimeError("Gemini API 요청 실패")


def merge_computed_fields(report: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    source_by_code = {item["code"]: item for item in inputs.get("stocks", [])}
    for stock in report.get("stocks", []):
        source = source_by_code.get(stock.get("code"))
        if not source:
            continue
        price = source.get("price", {})
        stock["market_cap"] = source.get("market_cap", stock.get("market_cap", "-"))
        stock["per"] = source.get("per", stock.get("per", "-"))
        stock["current_price"] = price.get("current_price")
        stock["change_percent"] = price.get("change_percent")
        stock["year_high"] = price.get("year_high")
        stock["year_low"] = price.get("year_low")
        stock["position_52"] = price.get("position_52", stock.get("position_52", 0))
        stock["drawdown"] = price.get("drawdown", stock.get("drawdown", 0))
        stock["ma20"] = price.get("ma20")
        stock["ma60"] = price.get("ma60")
        stock["rsi14"] = price.get("rsi14")

        # We do not have a reliable investor-flow data source yet, so never let the model invent it.
        stock["flow_data_available"] = False
        stock["foreign"] = 0
        stock["foreign_streak"] = 0
        stock["ownership"] = 0
        stock["institution"] = 0
        stock["institution_streak"] = 0
        stock["signal"] = "수급 데이터 없음"
    return report


def build_fallback_report(inputs: dict[str, Any], reason: str) -> dict[str, Any]:
    news = []
    for item in inputs.get("news", []):
        news.append(
            {
                "time": item.get("time", ""),
                "date": item.get("date", ""),
                "published_at": item.get("published_at", ""),
                "tag": item.get("tag", ""),
                "title": item.get("title", ""),
                "source": item.get("source", ""),
                "url": item.get("url", ""),
            }
        )

    stocks = []
    for item in inputs.get("stocks", []):
        price = item.get("price", {})
        related_news = next(
            (
                news_item
                for news_item in news
                if item["name"] in news_item.get("title", "") or news_item.get("tag") == item["name"]
            ),
            {},
        )
        position = as_float(price.get("position_52")) or 0
        rsi = as_float(price.get("rsi14"))
        score = 50
        if position >= 35:
            score += 8
        if position >= 80:
            score -= 6
        if rsi is not None and 40 <= rsi <= 70:
            score += 8
        elif rsi is not None and (rsi >= 80 or rsi <= 30):
            score -= 8
        score = max(0, min(100, score))
        stocks.append(
            {
                "name": item["name"],
                "code": item["code"],
                "theme": item["theme"],
                "score": score,
                "conviction": "중" if score >= 55 else "하",
                "note": "AI 분석이 지연되어 가격 지표와 수집 뉴스 기준으로 임시 산출했습니다.",
                "risk": "AI 요약 미반영. 원천 뉴스와 가격 지표를 직접 확인하세요.",
                "foreign": 0,
                "foreign_streak": 0,
                "ownership": 0,
                "institution": 0,
                "institution_streak": 0,
                "signal": "수급 데이터 없음",
                "position_52": price.get("position_52", 0),
                "drawdown": price.get("drawdown", 0),
                "market_cap": item.get("market_cap", "-"),
                "per": item.get("per", "-"),
                "impact_news": {
                    "title": related_news.get("title", ""),
                    "source": related_news.get("source", ""),
                    "published_at": related_news.get("published_at", ""),
                    "url": related_news.get("url", ""),
                    "reason": "종목명과 매칭된 최신 수집 기사입니다." if related_news else "",
                },
            }
        )

    return {
        "market_summary": f"AI 제공자가 일시적으로 응답하지 않아 정량 지표 중심 임시 리포트를 표시합니다. 원인: {reason}",
        "stocks": sorted(stocks, key=lambda stock: stock["score"], reverse=True),
        "themes": [],
        "news": news,
        "source": {
            "mode": "fallback",
            "description": "AI 호출 실패로 가격 지표와 수집 뉴스만 사용한 임시 결과입니다.",
        },
    }


def write_report(report: dict[str, Any], output_path: Path, source_mode: str) -> None:
    report["generated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    report.setdefault("source", {})
    descriptions = {
        "openai": "Python 수집기와 OpenAI Responses API로 생성한 분석 결과입니다.",
        "gemini": "Python 수집기와 Gemini API로 생성한 분석 결과입니다.",
        "fallback": "AI 호출 실패로 가격 지표와 수집 뉴스만 사용한 임시 결과입니다.",
    }
    report["source"].update(
        {
            "mode": source_mode,
            "description": descriptions.get(source_mode, report["source"].get("description", "")),
        }
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="투자 리포트 JSON 생성")
    parser.add_argument("--watchlist", type=Path, default=WATCHLIST_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--news-limit", type=int, default=2)
    parser.add_argument("--sample", action="store_true", help="OpenAI 호출 없이 샘플 리포트 생성")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_env()

    if args.sample:
        report = sample_report()
        write_report(report, args.output, "sample")
        print(f"sample report written: {args.output}")
        return 0

    provider = os.getenv("AI_PROVIDER", "").strip().lower()
    gemini_key = os.getenv("GEMINI_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    if not provider:
        provider = "gemini" if gemini_key else "openai"

    if provider == "gemini" and not gemini_key:
        print("GEMINI_API_KEY가 없습니다. .env에 키를 넣거나 --sample로 실행하세요.", file=sys.stderr)
        return 2
    if provider == "openai" and not openai_key:
        print("OPENAI_API_KEY가 없습니다. .env에 키를 넣거나 --sample로 실행하세요.", file=sys.stderr)
        return 2
    if provider not in {"gemini", "openai"}:
        print("AI_PROVIDER는 gemini 또는 openai만 지원합니다.", file=sys.stderr)
        return 2

    watchlist = read_watchlist(args.watchlist)
    inputs = collect_inputs(watchlist, args.news_limit)
    if provider == "gemini":
        model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        try:
            report = analyze_with_gemini(inputs, model, gemini_key)
        except RuntimeError as exc:
            report = build_fallback_report(inputs, str(exc).splitlines()[0])
            report = merge_computed_fields(report, inputs)
            write_report(report, args.output, "fallback")
            print(f"fallback report written: {args.output}", file=sys.stderr)
            return 0
    else:
        model = os.getenv("OPENAI_MODEL", "gpt-5-mini")
        report = analyze_with_openai(inputs, model)
    report = merge_computed_fields(report, inputs)
    write_report(report, args.output, provider)
    print(f"{provider} report written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
