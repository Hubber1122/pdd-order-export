# -*- coding: utf-8 -*-
"""
拼多多买家订单导出 —— 图形界面（本地网页版）

双击 start_gui.bat（或运行 `python app.py`）即可启动：
  1. 自动打开浏览器登录界面
  2. 输入多多号 + PDDAccessToken → 登录验证
  3. 选择导出选项 → 一键导出 → 进度实时展示
  4. 完成后一键打开导出文件夹

零额外 GUI 依赖：仅用 Python 标准库 http.server + 已装的 requests/openpyxl。
"""

import os
import re
import sys
import json
import time
import threading
import webbrowser
import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

from field_mapping import FIELD_MAPPING
from pdd_client import PddOrderClient, extract_order, MOBILE_UA
from pdd_order_export import (select_fields, filter_by_time, write_xlsx,
                              write_csv, parse_time, _raw_time)

HOST = "127.0.0.1"
PORT = 8765
# 资源定位：兼容 PyInstaller 打包（_MEIPASS）与源码运行
BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
INDEX_FILE = os.path.join(BASE_DIR, "webui", "index.html")
# 输出目录：优先写到可执行文件所在目录（便于 U 盘便携运行）
EXE_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else BASE_DIR
OUTPUT_ROOT = EXE_DIR

# 导出任务状态（task_id -> dict）
TASKS = {}
TASKS_LOCK = threading.Lock()
_task_seq = 0


# --------------------------------------------------------------------------- #
# 凭证验证（还原原软件 pddInfo 逻辑）
# --------------------------------------------------------------------------- #
def verify_credentials(pdduid, token):
    """请求 personal_profile.html 并解析昵称，验证凭证有效性。"""
    url = "https://mobile.yangkeduo.com/personal_profile.html"
    headers = {
        "User-Agent": MOBILE_UA,
        "Cookie": f"PDDAccessToken={token}",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        text = resp.text
    except Exception as e:
        return False, None, f"网络请求失败: {e}"

    m = re.search(r"window\.rawData\s*=\s*(\{.*?\})\s*;?\s*</script>", text, re.S)
    if not m:
        m = re.search(r"window\.rawData\s*=\s*(\{.*\})", text, re.S)
    if not m:
        return False, None, "未获取到用户信息，凭证可能已失效"

    try:
        raw = json.loads(m.group(1))
        ui = (raw.get("stores", {}).get("store", {})
              .get("userInfo", {}))
        nickname = ui.get("nickname") or ""
        if not nickname:
            # 兜底：多多号
            nickname = pdduid
        return True, nickname, ""
    except Exception as e:
        return False, None, f"解析用户信息失败: {e}"


# --------------------------------------------------------------------------- #
# 后台导出
# --------------------------------------------------------------------------- #
def _task_get(task_id):
    with TASKS_LOCK:
        return TASKS.get(task_id)


def _task_set(task_id, **kw):
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if t:
            t.update(kw)


def do_export(task_id, cfg):
    try:
        mapping = select_fields(cfg.get("fields") or [])
        client = PddOrderClient(
            pdduid=cfg["pdduid"],
            access_token=cfg["access_token"],
            verify_auth_token=cfg.get("verify_auth_token") or None,
            anti_content=cfg.get("anti_content") or None,
            anti_token=cfg.get("anti_token") or None,
        )

        def progress(page, total):
            _task_set(task_id, phase="fetch", page=page, total=total,
                      message=f"正在拉取第 {page} 页，已获取 {total} 条订单")

        _task_set(task_id, phase="fetch", message="开始拉取订单...")
        outdir = os.path.join(OUTPUT_ROOT, cfg.get("output_dir") or "output")
        debug_dir = os.path.join(outdir, "debug")
        raw_sink = []
        orders, meta = client.fetch_all(
            order_type=cfg.get("order_type", "all"),
            start_offset=cfg.get("start_offset") or None,
            max_pages=int(cfg.get("max_pages") or 0),
            page_size=int(cfg.get("page_size") or 10),
            keyword=cfg.get("keyword") or None,
            progress=progress,
            debug_dir=debug_dir,
            raw_sink=raw_sink,
        )
        # 保存原始响应供界面下载校准
        if raw_sink:
            _task_set(task_id, raw_pages=raw_sink[:5])
        if not orders:
            _task_set(task_id, phase="error", message="未获取到订单（凭证失效或无订单）")
            return

        _task_set(task_id, phase="parse", message=f"共获取 {len(orders)} 条，正在解析字段...")
        need_decrypt = bool(cfg.get("need_decrypt"))
        rows = []
        for o in orders:
            row = extract_order(o, mapping=mapping, need_decrypt=need_decrypt)
            row["_raw_order_time"] = _raw_time(o)
            rows.append(row)

        rows = filter_by_time(rows, mapping, cfg.get("time_from"), cfg.get("time_to"))

        outdir = os.path.join(OUTPUT_ROOT, cfg.get("output_dir") or "output")
        os.makedirs(outdir, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
        base = os.path.join(outdir, f"{cfg['pdduid']}-多多订单-{stamp}")

        fmt = (cfg.get("output_format") or "xlsx").lower()
        files = []
        _task_set(task_id, phase="write", message=f"正在生成文件...")
        if fmt in ("xlsx", "both"):
            files.append(write_xlsx(base + ".xlsx", rows, mapping))
        if fmt in ("csv", "both"):
            files.append(write_csv(base + ".csv", rows, mapping))

        _task_set(task_id, phase="done", total=len(rows), files=files,
                  message=f"导出完成，共 {len(rows)} 条订单（原始响应已存 output/debug/，若条数异常请把 page_1.json 发给开发者校准）")
    except Exception as e:
        _task_set(task_id, phase="error", message=f"导出失败: {e}")


def start_export(cfg):
    global _task_seq
    with TASKS_LOCK:
        _task_seq += 1
        task_id = str(_task_seq)
        TASKS[task_id] = {"id": task_id, "phase": "init", "message": "任务已创建",
                          "page": 0, "total": 0, "files": []}
    t = threading.Thread(target=do_export, args=(task_id, cfg), daemon=True)
    t.start()
    return task_id


# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
            body = body.encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            if os.path.exists(INDEX_FILE):
                with open(INDEX_FILE, "r", encoding="utf-8") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            else:
                self._send(500, {"ok": False, "message": "index.html 缺失"})
            return
        if path == "/api/progress":
            task_id = _qs(self.path, "task_id")
            t = _task_get(task_id)
            self._send(200, t if t else {"phase": "notfound"})
            return
        if path == "/api/debug":
            task_id = _qs(self.path, "task_id")
            idx = int(_qs(self.path, "page") or 1) - 1
            t = _task_get(task_id)
            pages = (t or {}).get("raw_pages") or []
            if 0 <= idx < len(pages):
                self._send(200, pages[idx])
            else:
                self._send(404, {"error": "no debug data"})
            return
        self._send(404, {"ok": False, "message": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(body.decode("utf-8"))
        except Exception:
            data = {}

        if path == "/api/verify":
            pdduid = (data.get("pdduid") or "").strip()
            token = (data.get("token") or "").strip()
            if not pdduid or not token:
                self._send(200, {"ok": False, "message": "请填写多多号和登录凭证"})
                return
            ok, nickname, msg = verify_credentials(pdduid, token)
            self._send(200, {"ok": ok, "nickname": nickname, "message": msg})
            return

        if path == "/api/export":
            pdduid = (data.get("pdduid") or "").strip()
            token = (data.get("token") or "").strip()
            if not pdduid or not token:
                self._send(200, {"ok": False, "message": "请先登录"})
                return
            cfg = {
                "pdduid": pdduid,
                "access_token": token,
                "verify_auth_token": data.get("verify_auth_token") or "",
                "anti_token": data.get("anti_token") or "",
                "anti_content": data.get("anti_content") or "",
                "order_type": data.get("order_type") or "all",
                "page_size": int(data.get("page_size") or 10),
                "max_pages": int(data.get("max_pages") or 0),
                "start_offset": data.get("start_offset") or "",
                "keyword": data.get("keyword") or "",
                "time_from": data.get("time_from") or "",
                "time_to": data.get("time_to") or "",
                "output_format": data.get("output_format") or "xlsx",
                "output_dir": data.get("output_dir") or "output",
                "need_decrypt": bool(data.get("need_decrypt")),
                "fields": data.get("fields") or [],
            }
            task_id = start_export(cfg)
            self._send(200, {"ok": True, "task_id": task_id})
            return

        if path == "/api/open_folder":
            outdir = os.path.join(OUTPUT_ROOT, data.get("output_dir") or "output")
            os.makedirs(outdir, exist_ok=True)
            try:
                os.startfile(outdir)  # Windows
            except Exception:
                pass
            self._send(200, {"ok": True})
            return

        self._send(404, {"ok": False, "message": "not found"})


def _qs(url, key):
    if "?" not in url:
        return None
    qs = url.split("?", 1)[1]
    for kv in qs.split("&"):
        if "=" in kv:
            k, v = kv.split("=", 1)
            if k == key:
                from urllib.parse import unquote
                return unquote(v)
    return None


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}/"
    print(f"拼多多订单导出界面已启动：{url}")
    print("浏览器未自动打开时，请手动访问上面的地址。按 Ctrl+C 退出。")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
