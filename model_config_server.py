import json
import os
import tempfile
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import RLock
from urllib.parse import urlsplit, urlunsplit

from local_api_security import LocalAPIHandler

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "model_config.json"
CONFIG_LOCK = RLock()
HOST = "127.0.0.1"
PORT = 8085
EMBEDDING_BASE_URL = "https://api.siliconflow.cn/v1"
EMBEDDING_MODEL = "BAAI/bge-m3"


def read_config():
    if not CONFIG_FILE.exists():
        return {"provider": "OpenAI-compatible", "base_url": "", "model": "", "api_key": ""}
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Invalid config")
        return data
    except Exception:
        raise RuntimeError("模型配置文件无法读取，请检查 model_config.json。") from None


def write_config(data):
    fd, tmp = tempfile.mkstemp(prefix="model_config.json.", suffix=".tmp", dir=str(CONFIG_FILE.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(data, output, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_FILE)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def normalize_base_url(value):
    if not isinstance(value, str) or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("API Base URL 必须是有效的 HTTP 或 HTTPS 地址。")
    value = value.strip()
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or any(char.isspace() for char in value)
        ):
            raise ValueError
        host = parsed.hostname.encode("idna").decode("ascii").lower()
        if ":" in host:
            host = "[" + host + "]"
        port = parsed.port
        default_port = 443 if parsed.scheme == "https" else 80
        authority = host + (":" + str(port) if port is not None and port != default_port else "")
        return urlunsplit((parsed.scheme, authority, parsed.path.rstrip("/"), "", ""))
    except (ValueError, UnicodeError):
        raise ValueError("API Base URL 必须是 HTTP 或 HTTPS 地址，且不能包含用户名、密码、查询参数或片段。") from None


def resolve_key(body, old, base_url, embedding):
    key = str(body.get("api_key") or "").strip()
    if key:
        return key
    old_base = old.get("embedding_base_url" if embedding else "base_url")
    if not old_base and embedding:
        old_base = EMBEDDING_BASE_URL
    try:
        same_endpoint = normalize_base_url(old_base) == base_url
    except ValueError:
        same_endpoint = False
    if not same_endpoint:
        raise ValueError("API 地址已改变，请重新填写对应的 API Key。原有 Key 不会发送到新地址。")
    key = str(old.get("embedding_key" if embedding else "api_key") or "").strip()
    if not key:
        raise ValueError("请先填写 API Key。")
    return key


def prepare_settings(body, old, embedding):
    if embedding:
        base_url = normalize_base_url(body.get("base_url") or old.get("embedding_base_url") or EMBEDDING_BASE_URL)
        model = str(body.get("model") or old.get("embedding_model") or EMBEDDING_MODEL).strip()
    else:
        base_url = normalize_base_url(body.get("base_url") or "")
        model = str(body.get("model") or "").strip()
    if not model:
        raise ValueError("请填写 API Base URL 和模型名称。")
    key = resolve_key(body, old, base_url, embedding)
    if embedding:
        return {"embedding_base_url": base_url, "embedding_model": model, "embedding_key": key}
    return {"provider": str(body.get("provider") or "OpenAI-compatible").strip(), "base_url": base_url, "model": model, "api_key": key}


def chat_url(base_url):
    return base_url if base_url.endswith("/chat/completions") else base_url + "/chat/completions"


class NoCredentialRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward an authenticated test request to a redirected endpoint."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "Model API redirects are disabled", headers, fp)


def open_model_request(request):
    return urllib.request.build_opener(NoCredentialRedirect()).open(request, timeout=25)


class Handler(LocalAPIHandler):
    def log_message(self, fmt, *args):
        print("[model-config] " + (fmt % args))

    def do_GET(self):
        if not self.validate_request("GET"):
            return
        if self.path not in {"/api/config", "/api/embedding-config"}:
            self.send_json(404, {"ok": False, "message": "Not found"})
            return
        try:
            with CONFIG_LOCK:
                cfg = read_config()
            embedding = self.path == "/api/embedding-config"
            self.send_json(200, {
                "ok": True,
                "provider": "OpenAI-compatible" if embedding else cfg.get("provider", "OpenAI-compatible"),
                "base_url": cfg.get("embedding_base_url") or EMBEDDING_BASE_URL if embedding else cfg.get("base_url", ""),
                "model": cfg.get("embedding_model") or EMBEDDING_MODEL if embedding else cfg.get("model", ""),
                "has_api_key": bool(cfg.get("embedding_key" if embedding else "api_key")),
            })
        except Exception:
            self.send_json(500, {"ok": False, "message": "模型配置文件无法读取，请检查 model_config.json。"})

    def read_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > 100000:
            raise ValueError("请求内容为空或过大。")
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(body, dict):
            raise ValueError("请求内容必须是 JSON 对象。")
        return body

    def do_POST(self):
        if not self.validate_request("POST"):
            return
        if self.path not in {"/api/apply", "/api/test", "/api/embedding-config", "/api/embedding-test"}:
            self.send_json(404, {"ok": False, "message": "Not found"})
            return
        try:
            body = self.read_body()
            embedding = self.path in {"/api/embedding-config", "/api/embedding-test"}
            save = self.path in {"/api/apply", "/api/embedding-config"}
            # Keep read/merge/write in one transaction so the two forms cannot overwrite each other.
            with CONFIG_LOCK:
                old = read_config()
                cfg = prepare_settings(body, old, embedding)
                if save:
                    write_config({**old, **cfg})
            if save:
                self.send_json(200, {"ok": True, "message": "配置已保存在本机。"})
                return
        except ValueError as exc:
            self.send_json(400, {"ok": False, "message": str(exc)})
            return
        except Exception:
            self.send_json(500, {"ok": False, "message": "模型配置无法读取或保存，请检查本机配置文件。"})
            return

        if embedding:
            endpoint = cfg["embedding_base_url"] + "/embeddings"
            key = cfg["embedding_key"]
            payload = {"model": cfg["embedding_model"], "input": ["Ally embedding connection test"]}
        else:
            endpoint = chat_url(cfg["base_url"])
            key = cfg["api_key"]
            payload = {"model": cfg["model"], "messages": [{"role": "user", "content": "Reply with OK only."}], "max_tokens": 10, "stream": False}
        try:
            request = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers={
                "Authorization": "Bearer " + key, "Content-Type": "application/json",
            }, method="POST")
            with open_model_request(request) as response:
                if embedding:
                    result = json.loads(response.read(1024 * 1024).decode("utf-8"))
                    if not result.get("data") or not result["data"][0].get("embedding"):
                        raise ValueError("Invalid embedding response")
                else:
                    response.read(4096)
            self.send_json(200, {"ok": True, "message": "Connection test successful."})
        except urllib.error.HTTPError as exc:
            self.send_json(502, {"ok": False, "message": "服务商返回 HTTP %s。请检查 API 地址、Key、模型名和账户权限；连接测试不会跟随重定向。" % exc.code})
        except Exception:
            # Provider errors may contain request headers or URLs; never return their raw text.
            self.send_json(502, {"ok": False, "message": "连接失败、超时或响应无效。请检查网络、API 地址和服务商状态。"})


if __name__ == "__main__":
    print("Ally model config service: http://127.0.0.1:%s" % PORT)
    print("Config file:", CONFIG_FILE)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
