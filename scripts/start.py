"""复用本机环境，确认应用就绪后再打开网页。"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import build_opener, ProxyHandler
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8009"
HTTP = build_opener(ProxyHandler({}))


def listening():
    try:
        with socket.create_connection(("127.0.0.1", 8009), timeout=1):
            return True
    except OSError:
        return False


def ready():
    try:
        with HTTP.open(URL + "/openapi.json", timeout=1) as response:
            spec = json.load(response)
        return spec.get("info", {}).get("title") == "MongoDB 问卷系统" and {
            "/api/session", "/api/surveys", "/api/fill/{token}/submit",
            "/api/question-banks", "/api/shared-question-versions",
            "/api/question-versions/{vid}/stats"
        } <= spec.get("paths", {}).keys()
    except (OSError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    os.chdir(ROOT)
    if listening():
        if not ready():
            raise RuntimeError("端口 8009 被其他服务占用或网页尚未就绪；请检查端口后重试。")
        print("问卷服务已经运行，复用现有服务。", flush=True)
        if not args.no_browser:
            webbrowser.open(URL)
        return 0

    from pymongo import MongoClient

    uri = os.environ.get("MONGODB_URI", "mongodb://127.0.0.1:27019")
    if uri == "mongodb://127.0.0.1:27019":
        subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-File", str(ROOT / "scripts" / "start-db.ps1")], check=True)
    # 自定义连接串使用用户指定的实例，不另行启动本机数据库。
    with MongoClient(uri, serverSelectionTimeoutMS=1000) as client:
        until = time.monotonic() + 15
        while True:
            try:
                client.admin.command("ping")
                break
            except Exception:
                if time.monotonic() >= until:
                    raise RuntimeError("数据库连接失败，请检查 MONGODB_URI 和 .local/mongodb.log。") from None
                time.sleep(0.3)

    process = subprocess.Popen([sys.executable, "-X", "utf8", "-m", "uvicorn", "app.main:app",
                                "--host", "127.0.0.1", "--port", "8009"], cwd=ROOT)
    try:
        until = time.monotonic() + 30
        while not ready():
            if process.poll() is not None:
                raise RuntimeError("网页服务启动失败，请查看上方错误信息。")
            if time.monotonic() >= until:
                raise RuntimeError("网页启动等待超时，请查看上方错误信息。")
            time.sleep(0.3)
        if process.poll() is not None:
            raise RuntimeError("网页进程已退出；请检查端口占用。")
        print(f"已启动：{URL}\n保持窗口打开；按 Ctrl+C 停止网页。数据库独立运行。", flush=True)
        if not args.no_browser:
            webbrowser.open(URL)
        return process.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"启动失败：{exc}", file=sys.stderr, flush=True)
        sys.exit(1)
