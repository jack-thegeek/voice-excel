"""FunASR 流式语音识别封装（paraformer-zh-streaming）。

模型与参数说明：
- chunk_size = [0, 10, 5] 表示 600ms 实时出字粒度 + 300ms 前瞻
- 每 600ms（9600 采样点 @16kHz）跑一次 generate，输出增量文本
- is_final=True 触发尾部 flush
"""
from __future__ import annotations

import threading
import numpy as np

# 流式配置（来自 FunASR 官方示例）
CHUNK_SIZE = [0, 10, 5]                 # 600ms 粒度
ENCODER_CHUNK_LOOK_BACK = 4
DECODER_CHUNK_LOOK_BACK = 1
CHUNK_STRIDE = CHUNK_SIZE[1] * 960      # 9600 采样点 = 600ms @ 16kHz
SAMPLE_RATE = 16000
CHUNK_BYTES = CHUNK_STRIDE * 2          # Int16 单声道，每 chunk 的字节数

_model = None
_lock = threading.Lock()


def get_model():
    """惰性加载单例模型（首次调用会联网下载 ~数百 MB 模型）。"""
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from funasr import AutoModel
                _model = AutoModel(model="paraformer-zh-streaming", disable_update=True)
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
