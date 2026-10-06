"""sherpa-onnx 流式语音识别引擎（streaming-paraformer-zh，int8 量化）。

与 FunASR 引擎（asr.py）接口一致，见 engines.py。特点：
- 基于 onnxruntime，不需要 torch，内存占用远低于 FunASR（约 0.5GB vs 3GB）
- 使用 int8 量化模型（约 230MB），首帧延迟低
- 默认模型与 FunASR 的 paraformer-zh-streaming 同源（vocab8404，中文+英文）

模型文件（3 个，放在同一目录）：
    tokens.txt / encoder.int8.onnx / decoder.int8.onnx
来源：https://huggingface.co/csukuangfj/sherpa-onnx-streaming-paraformer-bilingual-zh-en

默认为 int8 量化（约 230MB，速度快）；如需更高精度可设环境变量
SHERPA_MODEL_QUANT=fp32 使用 fp32 权重（约 825MB）。

查找顺序（与 FunASR 引擎对称）：
    1. 环境变量 SHERPA_MODEL_DIR 指向的目录
    2. exe 同目录 / 其父目录 下已解压的 sherpa_model/ 目录
    3. exe 同目录 / 其父目录 下的 sherpa_model.zip（自动解压）
    4. 联网从 HuggingFace 下载 int8 模型到 sherpa_model/
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
import threading
import time
import zipfile

import numpy as np

# ---------- 引擎标识与流式参数 ----------
ENGINE_ID = "sherpa"
ENGINE_NAME = "sherpa-onnx（Paraformer int8，轻量快速）"

SAMPLE_RATE = 16000
CHUNK_SAMPLES = 3200                     # 200ms
CHUNK_BYTES = CHUNK_SAMPLES * 2          # Int16 单声道，每 chunk 的字节数

# 模型查找相关
MODEL_DIR_NAME = "sherpa_model"
MODEL_ZIP_NAME = "sherpa_model.zip"
# 目录内有 tokens.txt + 至少一个 encoder/decoder 才算完整模型
_MODEL_MARKER = "tokens.txt"

# 默认下载源（HuggingFace 单文件仓库，按需只取需要的权重文件）
DEFAULT_REPO = "csukuangfj/sherpa-onnx-streaming-paraformer-bilingual-zh-en"
HF_ENDPOINT = os.environ.get("SHERPA_HF_ENDPOINT", "https://huggingface.co")

# 精度档位：int8（约 230MB，快，默认）/ fp32（约 825MB，精度略高）
# 也可用环境变量 SHERPA_MODEL_QUANT=fp32 切换
_QUANT = (os.environ.get("SHERPA_MODEL_QUANT", "int8") or "int8").lower()
if _QUANT in ("fp32", "full", "float32"):
    MODEL_FILES = ("tokens.txt", "encoder.onnx", "decoder.onnx")
    _WEIGHT_ORDER = (("encoder.onnx", "encoder.int8.onnx"),
                     ("decoder.onnx", "decoder.int8.onnx"),
                     ("joiner.onnx", "joiner.int8.onnx"))
else:
    MODEL_FILES = ("tokens.txt", "encoder.int8.onnx", "decoder.int8.onnx")
    _WEIGHT_ORDER = (("encoder.int8.onnx", "encoder.onnx"),
                     ("decoder.int8.onnx", "decoder.onnx"),
                     ("joiner.int8.onnx", "joiner.onnx"))

_recognizer = None
_lock = threading.Lock()
_download_lock = threading.Lock()


def available() -> tuple[bool, str]:
    """依赖（sherpa-onnx）是否已安装。

    只查包装没装、不真正 import（与 asr.available 一致）：import sherpa_onnx
    会加载 onnxruntime 原生库，而我们只想低成本地回答"装没装"；真正切到
    sherpa 时才 import 并构造识别器，届时有问题会报明确错误。
    """
    try:
        found = importlib.util.find_spec("sherpa_onnx") is not None
    except Exception as e:  # noqa: BLE001
        return False, f"检查 sherpa-onnx 安装状态失败（{e}）"
    if not found:
        return False, "未安装 sherpa-onnx（uv pip install sherpa-onnx）"
    return True, ""


def is_loaded() -> bool:
    return _recognizer is not None


def _app_dir() -> str:
    """应用根目录：打包后为可执行文件所在目录，源码运行时为本文件所在目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _log(msg: str) -> None:
    print(f"[sherpa] {msg}", flush=True)


def _pick_model_file(model_dir: str, candidates: tuple[str, ...]) -> str | None:
    """按精度档位顺序挑选权重文件（_WEIGHT_ORDER 已按 SHERPA_MODEL_QUANT 排好序）。"""
    for name in candidates:
        p = os.path.join(model_dir, name)
        if os.path.isfile(p):
            return p
    return None


def _resolve_model_dir() -> str:
    """解析模型目录，必要时解压 zip 或联网下载。返回目录路径。"""
    # 1. 环境变量
    env = os.environ.get("SHERPA_MODEL_DIR")
    if env and os.path.isdir(env) and os.path.exists(os.path.join(env, _MODEL_MARKER)):
        return env

    # 搜索根：exe 目录 + 其父目录
    app = _app_dir()
    parent = os.path.dirname(app)
    roots = [app] if parent == app else [app, parent]

    # 2. 已解压目录
    for root in roots:
        local_dir = os.path.join(root, MODEL_DIR_NAME)
        if os.path.isdir(local_dir) and os.path.exists(os.path.join(local_dir, _MODEL_MARKER)):
            return local_dir

    # 3. zip 单文件 → 解压
    for root in roots:
        local_zip = os.path.join(root, MODEL_ZIP_NAME)
        if os.path.isfile(local_zip):
            local_dir = os.path.join(root, MODEL_DIR_NAME)
            _extract_zip(local_zip, local_dir)
            if os.path.exists(os.path.join(local_dir, _MODEL_MARKER)):
                return local_dir

    # 4. 联网下载到应用目录
    return _download_model(os.path.join(app, MODEL_DIR_NAME))


def _extract_zip(zip_path: str, dest_dir: str) -> None:
    """解压模型 zip（幂等）。zip 内的文件可能在顶层，也可能在某个子目录下。"""
    if os.path.exists(os.path.join(dest_dir, _MODEL_MARKER)):
        return
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        # 若文件都在某个唯一子目录下，则解压后把该子目录内容提升为模型目录
        prefixes = {n.split("/", 1)[0] for n in names if "/" in n}
        nested = len(prefixes) == 1
        tmp = tempfile.mkdtemp(prefix="sherpa_zip_")
        try:
            zf.extractall(tmp)
            src = tmp
            if nested:
                candidate = os.path.join(tmp, next(iter(prefixes)))
                if os.path.isdir(candidate) and os.path.exists(
                    os.path.join(candidate, _MODEL_MARKER)
                ):
                    src = candidate
            os.makedirs(dest_dir, exist_ok=True)
            for name in os.listdir(src):
                s = os.path.join(src, name)
                d = os.path.join(dest_dir, name)
                if os.path.isfile(s) and not os.path.exists(d):
                    shutil.copy2(s, d)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    _log(f"已解压 {os.path.basename(zip_path)} → {dest_dir}")


def _download_file(url: str, dest: str, label: str) -> None:
    """下载单个文件（带进度、原子替换）。"""
    import urllib.request

    _log(f"下载 {label} ← {url}")
    tmp = dest + ".part"
    last = [0.0]

    def _hook(block_num, block_size, total_size):
        done = block_num * block_size
        now = time.time()
        if now - last[0] < 2 and done < total_size:
            return
        last[0] = now
        if total_size > 0:
            print(f"       {label}: {done / 1e6:.1f} / {total_size / 1e6:.1f} MB", flush=True)

    try:
        urllib.request.urlretrieve(url, tmp, _hook)
    except Exception as e:  # noqa: BLE001
        if os.path.exists(tmp):
            os.remove(tmp)
        raise RuntimeError(f"下载 {label} 失败：{e}") from e
    os.replace(tmp, dest)


def _download_model(dest_dir: str) -> str:
    """从 HuggingFace 下载默认流式中文模型（tokens + int8 权重，约 230MB）。"""
    repo = os.environ.get("SHERPA_MODEL_REPO", DEFAULT_REPO)
    with _download_lock:
        if os.path.exists(os.path.join(dest_dir, _MODEL_MARKER)):
            return dest_dir
        os.makedirs(dest_dir, exist_ok=True)
        _log(f"未找到本地模型，开始联网下载（{repo}）到 {dest_dir}")
        base = f"{HF_ENDPOINT}/{repo}/resolve/main"
        for name in MODEL_FILES:
            dest = os.path.join(dest_dir, name)
            if os.path.exists(dest):
                continue
            _download_file(f"{base}/{name}", dest, name)
        if not os.path.exists(os.path.join(dest_dir, _MODEL_MARKER)):
            raise RuntimeError(f"模型下载不完整：{dest_dir}")
        return dest_dir


def _build_recognizer(model_dir: str):
    """根据目录内容构造 OnlineRecognizer（支持 paraformer / transducer 两种流式模型）。"""
    import sherpa_onnx

    tokens = os.path.join(model_dir, _MODEL_MARKER)
    if not os.path.isfile(tokens):
        raise FileNotFoundError(f"模型目录缺少 {_MODEL_MARKER}: {model_dir}")

    encoder = _pick_model_file(model_dir, _WEIGHT_ORDER[0])
    decoder = _pick_model_file(model_dir, _WEIGHT_ORDER[1])
    joiner = _pick_model_file(model_dir, _WEIGHT_ORDER[2])
    num_threads = int(os.environ.get("SHERPA_NUM_THREADS", "2"))

    if joiner and encoder and decoder:
        # transducer 系列（如 streaming-zipformer-zh）
        _log(f"加载 transducer 模型（threads={num_threads}）: {model_dir}")
        return sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=tokens, encoder=encoder, decoder=decoder, joiner=joiner,
            num_threads=num_threads, provider="cpu",
        )
    if encoder and decoder:
        # paraformer 系列（默认：streaming-paraformer-bilingual-zh-en）
        _log(f"加载 paraformer 模型（threads={num_threads}）: {model_dir}")
        return sherpa_onnx.OnlineRecognizer.from_paraformer(
            tokens=tokens, encoder=encoder, decoder=decoder,
            num_threads=num_threads, provider="cpu",
        )
    raise FileNotFoundError(
        f"模型目录缺少权重文件（需要 encoder*.onnx + decoder*.onnx）：{model_dir}"
    )


def load_recognizer():
    """加载（或返回已加载的）识别器单例。"""
    global _recognizer
    if _recognizer is None:
        with _lock:
            if _recognizer is None:
                model_dir = _resolve_model_dir()
                _recognizer = _build_recognizer(model_dir)
    return _recognizer


# 兼容 engines 统一命名
get_recognizer = load_recognizer


def preload() -> None:
    """预加载模型（首次运行会联网下载）。"""
    load_recognizer()


def new_cache() -> dict:
    """新建一个识别会话的 cache（OnlineStream 只能在单个线程中使用，
    因此每个 WebSocket 会话各自创建，绝不能跨会话/跨线程复用）。"""
    return {"stream": None, "full": ""}


def _clean(text: str) -> str:
    """清理识别文本：去掉中英混排模型插入的空白（中文数字录入不需要空格）。"""
    return "".join((text or "").split())


def recognize_chunk(pcm_int16: bytes, cache: dict, is_final: bool) -> str:
    """流式识别一个 PCM chunk（Int16 16kHz mono，little-endian）。

    返回本会话累计的识别文本。is_final=True 时先 input_finished 再 flush 解码。
    """
    recognizer = load_recognizer()
    if len(pcm_int16) < 2:
        return cache.get("full", "")

    stream = cache.get("stream")
    if stream is None:
        stream = recognizer.create_stream()
        cache["stream"] = stream

    samples = np.frombuffer(pcm_int16, dtype=np.int16).astype(np.float32) / 32768.0
    stream.accept_waveform(SAMPLE_RATE, samples)
    if is_final:
        stream.input_finished()
    # 把内部已就绪的 chunk 全部解完，保证返回最新累计文本
    while recognizer.is_ready(stream):
        recognizer.decode_stream(stream)

    cache["full"] = _clean(recognizer.get_result(stream))
    return cache["full"]
