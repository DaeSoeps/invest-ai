from __future__ import annotations

import json
import mimetypes
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent
REPORT_PATH = ROOT / "data" / "report.json"
ANALYZE_COOLDOWN_SECONDS = 30
_analyze_lock = threading.Lock()
_last_analyze_at: float | None = None


class InvestAIHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/api/report":
            self.send_json_file(REPORT_PATH)
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
        if self.path != "/api/analyze":
            self.send_error(404)
            return

        global _last_analyze_at
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
            [sys.executable, str(ROOT / "src" / "generate_report.py")],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=180,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            message = "AI 분석 실행에 실패했습니다."
            if "insufficient_quota" in stderr or "exceeded your current quota" in stderr:
                message = "OpenAI API 할당량 또는 결제 설정을 확인해야 합니다."
            elif "OPENAI_API_KEY" in stderr:
                message = "OPENAI_API_KEY가 설정되지 않았습니다."
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
        self.send_json({"ok": True, "message": "AI 분석이 완료되었습니다.", "report": report})

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
