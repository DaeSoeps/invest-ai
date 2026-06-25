from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
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


def fetch_price_snapshot(symbol: str) -> dict[str, Any]:
    try:
        import yfinance as yf
    except ImportError:
        return {}

    try:
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        last_price = float(info.get("last_price") or 0)
        year_high = float(info.get("year_high") or 0)
        year_low = float(info.get("year_low") or 0)
        previous_close = float(info.get("previous_close") or 0)
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
        "last_price": last_price,
        "change_percent": change_percent,
        "year_high": year_high,
        "year_low": year_low,
        "position_52": max(0.0, min(100.0, position_52)),
        "drawdown": drawdown,
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
        snapshot = fetch_price_snapshot(item["yahoo_symbol"])
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


def analyze_with_gemini(inputs: dict[str, Any], model: str, api_key: str) -> dict[str, Any]:
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
        with urlopen(request, timeout=90) as response:
            body = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini API 요청 실패: HTTP {exc.code} {detail}") from exc

    try:
        text = body["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"Gemini API 응답에서 텍스트를 찾지 못했습니다: {body}") from exc
    return json.loads(clean_json_text(text))


def write_report(report: dict[str, Any], output_path: Path, source_mode: str) -> None:
    report["generated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    report.setdefault("source", {})
    descriptions = {
        "openai": "Python 수집기와 OpenAI Responses API로 생성한 분석 결과입니다.",
        "gemini": "Python 수집기와 Gemini API로 생성한 분석 결과입니다.",
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
        report = analyze_with_gemini(inputs, model, gemini_key)
    else:
        model = os.getenv("OPENAI_MODEL", "gpt-5-mini")
        report = analyze_with_openai(inputs, model)
    write_report(report, args.output, provider)
    print(f"{provider} report written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
