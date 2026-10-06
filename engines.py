"""语音识别引擎注册表：把 FunASR / sherpa-onnx 统一成一套接口。

新增引擎的步骤：
    1. 新建模块（如 asr_xxx.py），实现 asr.py 顶部「引擎统一接口」中列出的成员：
       ENGINE_ID / ENGINE_NAME / SAMPLE_RATE / CHUNK_BYTES
       available() / is_loaded() / preload() / new_cache() / recognize_chunk()
    2. 在下方 MODULES 里登记（顺序即前端下拉顺序）
    3. 前端 static/index.html 的引擎下拉会自动根据 /api/engines 渲染
"""
from __future__ import annotations

import os
import threading

import asr
import asr_sherpa

# 引擎加载顺序 = 前端下拉顺序；第一个为默认引擎。
# 默认引擎用 sherpa-onnx：轻量（内存约 0.5GB）、启动即就绪；
# FunASR 精度更高但内存约 3GB，留给需要更高的场合按需切换加载。
MODULES = (asr_sherpa, asr)
ENGINES = {m.ENGINE_ID: m for m in MODULES}
DEFAULT_ENGINE_ID = os.environ.get("ASR_ENGINE", MODULES[0].ENGINE_ID)

_avail_cache: dict[str, tuple[bool, str]] = {}
_avail_lock = threading.Lock()


def get_engine(engine_id: str | None):
    """按 id 取引擎模块。

    - 未传 id（老客户端不传 engine）时用默认引擎；默认引擎不可用时
      （例如本地没有 sherpa 模型且无法联网下载）自动退回第一个可用引擎，
      保证老客户端照样能识别
    - 显式传了 id 就按原样返回：不存在返回 None；不可用也照样返回，
      由调用方给出明确错误，而不是静默换成别的引擎（与前端下拉的
      「（不可用）」提示保持一致）
    """
    if not engine_id:
        engine_id = DEFAULT_ENGINE_ID
        mod = ENGINES.get(engine_id)
        if mod is not None and not check_available(mod.ENGINE_ID)[0]:
            for m in MODULES:
                if m is not mod and check_available(m.ENGINE_ID)[0]:
                    return m
        return mod
    return ENGINES.get(engine_id)


def check_available(engine_id: str) -> tuple[bool, str]:
    """依赖是否可用（带缓存，避免每次请求都 import 重库）。"""
    with _avail_lock:
        if engine_id not in _avail_cache:
            mod = ENGINES.get(engine_id)
            if mod is None:
                _avail_cache[engine_id] = (False, f"未知引擎 {engine_id}")
            else:
                try:
                    _avail_cache[engine_id] = mod.available()
                except Exception as e:  # noqa: BLE001
                    _avail_cache[engine_id] = (False, str(e))
        return _avail_cache[engine_id]


def list_engines() -> list[dict]:
    """给前端的引擎列表（含可用性与不可用原因）。"""
    out = []
    for m in MODULES:
        ok, why = check_available(m.ENGINE_ID)
        out.append({
            "id": m.ENGINE_ID,
            "name": m.ENGINE_NAME,
            "available": ok,
            "note": "" if ok else why,
        })
    return out


def check_all_available() -> None:
    """后台预热可用性缓存（import 检查较重，避免首个页面请求时卡住）。

    应在启动时的后台线程中调用，不要放在请求处理线程里同步执行。
    """
    for m in MODULES:
        try:
            check_available(m.ENGINE_ID)
        except Exception:  # noqa: BLE001
            pass


def preload_order() -> list[str]:
    """启动时要预加载的引擎 id 列表。

    默认只预加载默认引擎（即 sherpa，约 0.5GB），避免把 FunASR 大模型
    （约 3GB）也常驻内存；FunASR 在首次被选中时才按需加载
    （WebSocket 连接时会先返回 loading 状态）。

    可用环境变量 PRELOAD_ENGINES 覆盖：
      "all"                      全部可用引擎
      "funasr,sherpa"            只预加载指定引擎
      "none" / ""                全部不预加载
    """
    raw = os.environ.get("PRELOAD_ENGINES")
    if raw is None:
        return [DEFAULT_ENGINE_ID]
    ids = [s.strip() for s in raw.split(",") if s.strip()]
    if not ids or "none" in ids:
        return []
    if "all" in ids:
        return [m.ENGINE_ID for m in MODULES]
    return [i for i in ids if i in ENGINES]
