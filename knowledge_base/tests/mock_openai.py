"""Minimal mock of an OpenAI-compatible /v1/chat/completions server (vLLM, Ollama, LM Studio, llama.cpp,
DeepSeek and OpenAI all speak this protocol). Used by the tests – no real API is ever called."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class MockOpenAIServer:
    """``script``: list of actions consumed per request (the last one repeats):
    ("ok", text) | ("status", code) | ("sleep", seconds) | ("sse", text) | ("empty", None)."""

    def __init__(self, script=None, model="mock-model"):
        self.script = list(script or [("ok", "جواب (جلد دوم، صفحہ 127)")])
        self.model = model
        self.requests: list[dict] = []
        srv = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silence
                pass

            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                srv.requests.append({"path": self.path, "body": body, "auth": self.headers.get("Authorization")})
                kind, arg = srv.script[min(len(srv.requests) - 1, len(srv.script) - 1)]
                if kind == "sleep":
                    time.sleep(arg)
                    kind, arg = "ok", "late"
                if kind == "status":
                    self._json(arg, {"error": {"message": f"mock error {arg}", "type": "mock"}})
                elif kind == "sse":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    for word in arg.split(" "):
                        chunk = {"id": "c1", "object": "chat.completion.chunk", "created": 0, "model": srv.model,
                                 "choices": [{"index": 0, "delta": {"content": word + " "}, "finish_reason": None}]}
                        self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode())
                    self.wfile.write(b"data: [DONE]\n\n")
                else:
                    text = "" if kind == "empty" else arg
                    self._json(200, {"id": "c1", "object": "chat.completion", "created": 0, "model": srv.model,
                                     "choices": [{"index": 0, "finish_reason": "stop",
                                                  "message": {"role": "assistant", "content": text}}],
                                     "usage": {"prompt_tokens": 42, "completion_tokens": 7, "total_tokens": 49}})

            def _json(self, code, obj):
                data = json.dumps(obj, ensure_ascii=False).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"

    def __enter__(self):
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
