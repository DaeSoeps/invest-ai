from __future__ import annotations

import json
import mimetypes
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent
REPORT_PATH = ROOT / "data" / "report.json"


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

        result = subprocess.run(
            [sys.executable, str(ROOT / "src" / "generate_report.py")],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=180,
        )
        if result.returncode != 0:
            self.send_json(
                {
                    "ok": False,
                    "message": "AI 분석 실행에 실패했습니다.",
                    "stderr": result.stderr.strip(),
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

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
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
