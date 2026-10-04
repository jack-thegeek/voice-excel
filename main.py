"""FastAPI 应用：语音文本解析 + Excel 成绩修改 + 静态前端。"""
from __future__ import annotations

import os

# 规避 PyInstaller 冻结环境下 torch/numpy/scipy 各自携带 OpenMP 导致的重复加载硬崩溃
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import asyncio
import json
import sys
import threading
import time
import traceback as _traceback
import webbrowser
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import asr
import excel_editor
from parser import parse as parse_text


def _resource_dir() -> str:
    """静态资源目录：打包后用 sys._MEIPASS（即 _internal），源码运行用脚本目录。"""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = _resource_dir()
STATIC_DIR = os.path.join(BASE_DIR, "static")


def _app_dir() -> str:
    """可写目录：打包后为 exe 所在目录，源码运行时为脚本目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


DEBUG_LOG = os.path.join(_app_dir(), "debug.log")

app = FastAPI(title="语音修改 Excel 成绩表")


def _log(msg: str) -> None:
    try:
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        print(line, flush=True)
    except Exception:
        pass


def _dump_excepthook(exc_type, exc_value, exc_tb):
    try:
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(f"[EXCEPTHOOK] {exc_type.__name__}: {exc_value}\n")
            _traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)


sys.excepthook = _dump_excepthook


def _venv_excepthook(args):  # threading.excepthook 签名
    _log(f"[THREAD-EXC] {args.exc_type.__name__}: {args.exc_value}")


threading.excepthook = _venv_excepthook


def _preload_model_worker() -> None:
    """后台加载模型，分阶段写日志，便于定位冻结环境下的崩溃点。"""
    try:
        _log("preload[a]: importing numpy ...")
        import numpy as np
        _log(f"preload[b]: numpy {np.__version__} OK")
        _log("preload[c]: importing scipy ...")
        import scipy  # noqa: F401
        _log(f"preload[d]: scipy {scipy.__version__} OK")
        _log("preload[e]: importing torch ...")
        import torch
        _log(f"preload[f]: torch {torch.__version__} OK, cuda={torch.cuda.is_available()}")
        # 触发一次 tensor 运算（会用到 OpenMP）
        _ = torch.zeros(4) @ torch.ones(4)
        _log("preload[g]: torch matmul OK")
        _log("preload[h]: importing torchaudio ...")
        import torchaudio  # noqa: F401
        _log("preload[i]: torchaudio OK")
        _log("preload[j]: importing funasr ...")
        import funasr  # noqa: F401
        _log(f"preload[k]: funasr {getattr(funasr, '__version__', '?')} OK")
        from funasr import AutoModel  # noqa: F401
        _log("preload[l]: AutoModel symbol ready")
        spec = asr._resolve_model_path()
        _log(f"preload[m]: model spec = {spec}")
        model = AutoModel(model=spec, disable_update=True)
        _log("preload[n]: AutoModel constructed OK")
        asr._model = model
        _log("preload[o]: model ready")
    except BaseException as e:  # noqa: BLE001
        _log(f"preload EXC: {type(e).__name__}: {e}")
        try:
            with open(DEBUG_LOG, "a", encoding="utf-8") as f:
                _traceback.print_exc(file=f)
        except Exception:
            pass


@app.on_event("startup")
async def _preload_asr() -> None:
    """启动时后台预加载 FunASR 模型，避免首次录音卡顿。"""
    _log("startup hook fired")
    if os.environ.get("SKIP_MODEL_PRELOAD") == "1":
        _log("preload skipped (SKIP_MODEL_PRELOAD=1)")
        return
    threading.Thread(target=_preload_model_worker, daemon=True).start()


class ParseReq(BaseModel):
    text: str
    col_name: str = excel_editor.DEFAULT_COL_NAME


class ApplyReq(BaseModel):
    seq: int
    col_name: str
    score: float
    sheet_name: str = ""       # 班级（sheet 名），空串表示用第一个 sheet


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/students")
def students(sheet: str | None = None):
    sheets = excel_editor.list_sheets()
    # 未指定 sheet 时用第一个
    cur = sheet if sheet else (sheets[0] if sheets else "")
    if not cur:
        raise HTTPException(status_code=400, detail="Excel 中无任何 sheet")
    return {
        "sheet": cur,
        "sheets": sheets,
        "students": [_student_to_dict(s) for s in excel_editor.list_students(cur)],
        "cols": list(excel_editor.SCORE_COLS.keys()),
        "default_col": excel_editor.DEFAULT_COL_NAME,
    }


@app.post("/api/parse")
def api_parse(req: ParseReq):
    try:
        r = parse_text(req.text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # 查找对应学生，便于前端预览
    stu = excel_editor.find_student(r.seq)
    return {
        "ok": True,
        "seq": r.seq,
        "expression": r.expression,
        "score": r.score,
        "is_direct": r.is_direct,
        "note": r.note,
        "student": _student_to_dict(stu) if stu else None,
        "student_found": stu is not None,
    }


@app.post("/api/apply")
def api_apply(req: ApplyReq):
    try:
        sheet = req.sheet_name or None
        stu = excel_editor.update_score(req.seq, req.col_name, req.score, sheet)
    except excel_editor.ExcelError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "student": _student_to_dict(stu)}


def _student_to_dict(s) -> dict[str, Any]:
    # 分数里把 None 转成空字符串、保留其余
    scores = {}
    for k, v in s.scores.items():
        scores[k] = "" if v is None else v
    return {"row": s.row, "seq": s.seq, "name": s.name, "scores": scores}


# ---------- ASR WebSocket ----------
@app.websocket("/ws/asr")
async def ws_asr(ws: WebSocket) -> None:
    """流式语音识别（FunASR）。

    协议：
      - 客户端发 JSON {"action":"start"}  开始会话（确认连接）
      - 客户端发 binary frame            16kHz mono Int16 PCM chunk
      - 客户端发 JSON {"action":"stop"}   结束并 flush 尾部
    返回：
      - JSON {"text":"增量文本","final":false}  每个出字粒度的增量
      - JSON {"text":"尾部文本","final":true}   stop 后的最终增量
      - JSON {"error":"..."}                    模型未就绪/推理失败
    """
    await ws.accept()
    try:
        if asr._model is None:
            await ws.send_json({"status": "loading"})
            # 在后台线程加载，这里等待最多 ~120s
            try:
                await asyncio.wait_for(asyncio.to_thread(asr.get_model), timeout=120)
            except asyncio.TimeoutError:
                await ws.send_json({"error": "模型加载超时"})
                await ws.close()
                return
        else:
            asr.get_model()  # 确保已加载
        await ws.send_json({"status": "ready", "engine": "funasr"})

        cache = asr.new_cache()
        buf = bytearray()
        while True:
            msg = await ws.receive()
            if msg.get("text"):
                try:
                    payload = json.loads(msg.get("text"))
                except (TypeError, ValueError):
                    payload = {}
                if payload.get("action") == "stop":
                    # flush 尾部
                    if buf:
                        text = await asyncio.to_thread(asr.recognize_chunk, bytes(buf), cache, True)
                        buf.clear()
                        if text:
                            await ws.send_json({"text": text, "final": True})
                    await ws.send_json({"status": "done"})
                    break
                continue
            data = msg.get("bytes")
            if not data:
                continue
            buf.extend(data)
            # 攒满一个 chunk_size 就推一次
            while len(buf) >= asr.CHUNK_BYTES:
                chunk = bytes(buf[:asr.CHUNK_BYTES])
                del buf[:asr.CHUNK_BYTES]
                text = await asyncio.to_thread(asr.recognize_chunk, chunk, cache, False)
                if text:
                    await ws.send_json({"text": text, "final": False})
    except WebSocketDisconnect:
        return
    except Exception as e:
        try:
            await ws.send_json({"error": str(e)})
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass


# 静态文件（如后续需要）
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ---------- 启动时自动打开浏览器 ----------
def _open_browser(host: str, port: int) -> None:
    time.sleep(1.2)
    url = f"http://{host}:{port}/"
    try:
        webbrowser.open(url)
        print(f"[浏览器已打开] {url}")
    except Exception as e:
        print(f"[打开浏览器失败] {e}; 请手动访问 {url}")


def _find_free_port(host: str, start: int, attempts: int = 20) -> int:
    """从 start 开始找一个可绑定的端口；找不到就回退到 start（让 uvicorn 报原错误）。"""
    import socket

    for off in range(attempts):
        port = start + off
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((host, port))
                return port
        except OSError:
            continue
    return start  # 全被占用，回退，让 uvicorn 抛出真实错误


def main():
    import uvicorn

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8899"))
    # 默认端口可能被输入法等第三方软件占用，自动找一个可用端口
    port = _find_free_port(host, port)
    _log(f"starting on http://{host}:{port}")
    # 后台开浏览器
    threading.Thread(target=_open_browser, args=(host, port), daemon=True).start()
    try:
        uvicorn.run(app, host=host, port=port, log_level="info")
    except Exception as e:
        _log(f"uvicorn exited with error: {e}")
        raise


if __name__ == "__main__":
    main()
