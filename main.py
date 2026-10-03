"""FastAPI 应用：语音文本解析 + Excel 成绩修改 + 静态前端。"""
from __future__ import annotations

import asyncio
import os
import threading
import time
import webbrowser
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import asr
import excel_editor
from parser import parse as parse_text

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = FastAPI(title="语音修改 Excel 成绩表")


@app.on_event("startup")
async def _preload_asr() -> None:
    """启动时后台预加载 FunASR 模型，避免首次录音卡顿。"""
    threading.Thread(target=asr.get_model, daemon=True).start()


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
    """流式语音识别。

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
    # 模型未就绪时，先发提示但仍允许等待（前端可展示"模型加载中"）
    ready = False
    try:
        # 先尝试触发加载（非阻塞），并通知前端状态
        if asr._model is None:
            await ws.send_json({"status": "loading"})
            # 在后台线程加载，这里等待最多 ~60s
            try:
                await asyncio.wait_for(asyncio.to_thread(asr.get_model), timeout=120)
            except asyncio.TimeoutError:
                await ws.send_json({"error": "模型加载超时"})
                await ws.close()
                return
        else:
            asr.get_model()  # 确保已加载
        ready = True
        await ws.send_json({"status": "ready"})

        cache = asr.new_cache()
        buf = bytearray()
        while True:
            msg = await ws.receive()
            if msg.get("text"):
                try:
                    ctrl = msg.get("text")
                    import json as _json
                    payload = _json.loads(ctrl)
                except Exception:
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


def main():
    import uvicorn

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8765"))
    # 后台开浏览器
    threading.Thread(target=_open_browser, args=(host, port), daemon=True).start()
    print(f"[启动] http://{host}:{port}/  （Ctrl+C 退出）")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
