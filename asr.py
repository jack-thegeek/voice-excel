"""FunASR 流式语音识别封装（paraformer-zh-streaming）。

模型与参数说明：
- chunk_size = [0, 10, 5] 表示 600ms 实时出字粒度 + 300ms 前瞻
- 每 600ms（9600 采样点 @16kHz）跑一次 generate，输出增量文本
- is_final=True 触发尾部 flush
"""
from __future__ import annotations

import os
import sys
import threading
import zipfile

import numpy as np

# 流式配置（来自 FunASR 官方示例）
CHUNK_SIZE = [0, 10, 5]                 # 600ms 粒度
ENCODER_CHUNK_LOOK_BACK = 4
DECODER_CHUNK_LOOK_BACK = 1
CHUNK_STRIDE = CHUNK_SIZE[1] * 960      # 9600 采样点 = 600ms @ 16kHz
SAMPLE_RATE = 16000
CHUNK_BYTES = CHUNK_STRIDE * 2          # Int16 单声道，每 chunk 的字节数

# 本地模型相关：可把模型作为独立文件（funasr_model.zip）放到 exe 同目录，
# 或解压为 funasr_model/ 目录，或通过环境变量 FUNASR_MODEL_DIR 指定。
ONLINE_MODEL = "paraformer-zh-streaming"
MODEL_DIR_NAME = "funasr_model"
MODEL_ZIP_NAME = "funasr_model.zip"
# 模型目录内必须有该权重文件才算完整，避免误把空目录当模型
_MODEL_MARKER = "model.pt"

_model = None
_lock = threading.Lock()


def _app_dir() -> str:
    """应用根目录：打包后为可执行文件所在目录，源码运行时为本文件所在目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _extract_model_zip(zip_path: str, dest_dir: str) -> None:
    """把模型 zip 解压到目标目录（幂等，仅当缺少 model.pt 时执行）。"""
    if os.path.exists(os.path.join(dest_dir, _MODEL_MARKER)):
        return
    os.makedirs(dest_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest_dir)


def _resolve_model_path() -> str:
    """解析要交给 AutoModel 的 model 参数：本地目录 或 在线模型名。

    优先级：
      1. 环境变量 FUNASR_MODEL_DIR 指向的目录
      2. exe 同目录 / 其父目录 下已解压的 funasr_model/ 目录
      3. exe 同目录 / 其父目录 下的 funasr_model.zip（自动解压）
      4. 在线下载 paraformer-zh-streaming
    """
    # 1. 环境变量
    env = os.environ.get("FUNASR_MODEL_DIR")
    if env and os.path.isdir(env) and os.path.exists(os.path.join(env, _MODEL_MARKER)):
        return env

    # 搜索根：exe 目录 + 其父目录（模型可放在主程序文件夹同级的单独文件）
    app = _app_dir()
    parent = os.path.dirname(app)
    roots = [app] if parent == app else [app, parent]

    for root in roots:
        # 2. 已解压目录
        local_dir = os.path.join(root, MODEL_DIR_NAME)
        if os.path.isdir(local_dir) and os.path.exists(os.path.join(local_dir, _MODEL_MARKER)):
            return local_dir

    for root in roots:
        # 3. zip 单文件 → 解压
        local_zip = os.path.join(root, MODEL_ZIP_NAME)
        if os.path.isfile(local_zip):
            local_dir = os.path.join(root, MODEL_DIR_NAME)
            _extract_model_zip(local_zip, local_dir)
            if os.path.exists(os.path.join(local_dir, _MODEL_MARKER)):
                return local_dir

    # 4. 在线下载
    return ONLINE_MODEL


def get_model():
    """惰性加载单例模型（优先用本地目录/zip，否则联网下载）。"""
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from funasr import AutoModel
                model_spec = _resolve_model_path()
                _model = AutoModel(model=model_spec, disable_update=True)
    return _model


def new_cache() -> dict:
    """每个识别会话需要独立的 cache 字典，跨 chunk 复用。"""
    return {}


def _extract_text(res) -> str:
    """FunASR generate 返回结构兼容处理。"""
    if not res:
        return ""
    # res 通常是 list[dict]
    if isinstance(res, list):
        item = res[0] if res else {}
    elif isinstance(res, dict):
        item = res
    else:
        return ""
    text = item.get("text", "") if isinstance(item, dict) else ""
    # 有时 text 是 list
    if isinstance(text, list):
        text = "".join(str(x) for x in text)
    return text or ""


def recognize_chunk(pcm_int16: bytes, cache: dict, is_final: bool) -> str:
    """流式识别一个 PCM chunk（Int16 16kHz mono，little-endian）。

    返回本次新增的文本（增量）。最后一个 chunk 用 is_final=True flush。
    chunk 长度不要求正好等于 CHUNK_STRIDE，但非 final 时建议接近以保证实时性。
    """
    model = get_model()
    if len(pcm_int16) < 2:
        return ""
    audio = np.frombuffer(pcm_int16, dtype=np.int16).astype(np.float32) / 32768.0
    res = model.generate(
        input=audio,
        cache=cache,
        is_final=is_final,
        chunk_size=CHUNK_SIZE,
        encoder_chunk_look_back=ENCODER_CHUNK_LOOK_BACK,
        decoder_chunk_look_back=DECODER_CHUNK_LOOK_BACK,
    )
    return _extract_text(res)
