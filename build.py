"""一键打包脚本：voice-excel（主程序 onedir + 模型单独 zip）。

流程：
    1. (可选) 用 PyInstaller 打主程序 → dist/voice-excel/
    2. 把本地 FunASR 模型打成 funasr_model.zip → dist/funasr_model.zip
    3. 复制成绩表模板为默认数据文件 → dist/voice-excel/成绩表.xlsx
    4. 生成 使用说明.txt → dist/使用说明.txt

用法（在项目根目录、已用 uv 建好 .venv 的前提下）：
    .venv\\Scripts\\python.exe build.py                 # 完整打包
    .venv\\Scripts\\python.exe build.py --no-exe        # 只做模型 zip + 收尾（exe 已打好时）
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile

try:
    import modelscope
    from modelscope.hub.api import HubApi
except Exception:  # pragma: no cover
    HubApi = None

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist")
APP_DIR = os.path.join(DIST, "voice-excel")

# 在线模型名 → 本地缓存目录名（modelscope 的 file name 规则）
ONLINE_MODEL = "paraformer-zh-streaming"
MODEL_SCOPE_NAME = "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online"
MODEL_CACHE_DIRNAME = "iic--speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online"

# 模型必须包含的文件（zip 顶层直接放置这些文件名）
MODEL_FILES = (
    "configuration.json",
    "config.yaml",
    "model.pt",
    "tokens.json",
    "seg_dict",
    "am.mvn",
)


def local_model_dir() -> str | None:
    """定位本地已下载的模型目录（snapshots/master）。"""
    # 1. 环境变量指向的目录
    env = os.environ.get("FUNASR_MODEL_DIR")
    if env and os.path.isdir(os.path.join(env, "model.pt")):
        return env

    # 2. modelscope 默认缓存
    for msc in (
        os.path.join(os.path.expanduser("~"), ".cache", "modelscope"),
    ):
        base = os.path.join(msc, "models", MODEL_CACHE_DIRNAME)
        candidate = os.path.join(base, "snapshots", "master")
        if os.path.isfile(os.path.join(candidate, "model.pt")):
            return candidate

    # 3. modelscope API 解析（若 HubApi 可用且配置了缓存目录）
    if HubApi is not None:
        try:
            cache_root = modelscope.hub.constants.DEFAULT_MODELSCOPE_MODEL_CACHE_ROOT
            base = os.path.join(os.path.expanduser("~"), cache_root, MODEL_CACHE_DIRNAME)
            for snap in os.listdir(base) if os.path.isdir(base) else []:
                candidate = os.path.join(base, "snapshots", snap)
                if os.path.isfile(os.path.join(candidate, "model.pt")):
                    return candidate
        except Exception:
            pass
    return None


def build_exe() -> int:
    """运行 PyInstaller 打包主程序。"""
    python = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
    if not os.path.exists(python):
        python = sys.executable
    cmd = [python, "-m", "PyInstaller", "--clean", "--noconfirm", "voice-excel.spec"]
    print("[build] 运行:", " ".join(cmd))
    return subprocess.call(cmd, cwd=ROOT)


def make_model_zip(src_dir: str) -> str:
    """把模型必要文件打成单个 zip（顶层直接放文件）。"""
    os.makedirs(DIST, exist_ok=True)
    out = os.path.join(DIST, "funasr_model.zip")
    missing = [f for f in MODEL_FILES if not os.path.isfile(os.path.join(src_dir, f))]
    if missing:
        raise FileNotFoundError(f"模型目录缺少文件 {missing}: {src_dir}")

    print(f"[model]  源目录: {src_dir}")
    print(f"[model]  输出:   {out}")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        for f in MODEL_FILES:
            p = os.path.join(src_dir, f)
            zf.write(p, arcname=f)
            print(f"[model]    + {f}  ({os.path.getsize(p) / 1e6:.1f} MB)")
    size = os.path.getsize(out)
    print(f"[model]  完成: funasr_model.zip 共 {size / 1e6:.1f} MB")
    return out


def copy_template() -> None:
    """若无 成绩表.xlsx，则从模板复制一份到应用目录。"""
    os.makedirs(APP_DIR, exist_ok=True)
    template = os.path.join(ROOT, "成绩表_template.xlsx")
    target = os.path.join(APP_DIR, "成绩表.xlsx")
    if os.path.exists(template):
        if not os.path.exists(target):
            shutil.copy2(template, target)
            print(f"[data]   已复制模板 → {target}")
        else:
            print(f"[data]   已存在，跳过: {target}")
    else:
        print("[data]   警告: 未找到 成绩表_template.xlsx，请手动放入 成绩表.xlsx")


_USAGE = """voice-excel 语音修改 Excel 成绩表 —— 打包版使用说明
========================================================

【目录结构】
  voice-excel/
  ├── voice-excel.exe    主程序（双击运行）
  ├── _internal/         程序依赖（不要改动/删除）
  ├── 成绩表.xlsx         成绩数据（可自行替换，注意保留表头）
  └── debug.log          运行日志（首次运行后生成，便于排错）
  funasr_model.zip        语音识别模型（放在 voice-excel.exe 同目录或其父目录即可）

【运行方法】
  1. 确保 voice-excel.exe 与 funasr_model.zip（或解压后的 funasr_model/ 目录）
     放在同一个文件夹内（模型也可放在 exe 所在文件夹的上一级）。
  2. 双击 voice-excel.exe，稍等片刻会自动打开浏览器
     （默认 http://127.0.0.1:8899/）。
  3. 首次运行会从 funasr_model.zip 解压模型（约 848MB，约 5-10 秒），之后
     直接用已解压的 funasr_model/ 目录，不再重复解压。

【识别引擎】
  - 使用 FunASR 流式语音识别（paraformer-zh-streaming），纯 CPU 推理。
  - 如想跳过启动时的模型预加载：设置 SKIP_MODEL_PRELOAD=1

【模型查找顺序】
  ① 环境变量 FUNASR_MODEL_DIR 指向的目录
  ② exe 同目录 / 其父目录 下已解压的 funasr_model/ 目录
  ③ exe 同目录 / 其父目录 下的 funasr_model.zip（自动解压到 funasr_model/）
  ④ 若都找不到，则联网下载 paraformer-zh-streaming（约 849MB）
  也可手动解压 funasr_model.zip 成 funasr_model/ 目录，避免每次首启解压。

【数据文件】
  - 成绩表.xlsx 放在 exe 同目录，结构需与模板一致：
    Sheet 名「班级成绩登记表」；第 2 行表头（序号/姓名/第一单元~期末考试）；
    第 3 行起为学生数据；末行统计公式勿动。
  - 每次首次写入会自动备份一个 成绩表.xlsx.bak。

【运行要求】
  - 仅支持 Windows x64，无需安装 Python。
  - 运行内存约 3.1GB（PyTorch + 模型常驻），纯 CPU 识别。
  - 端口默认 8899，可用环境变量 PORT/HOST 修改。
"""


def write_usage() -> None:
    os.makedirs(DIST, exist_ok=True)
    p = os.path.join(DIST, "使用说明.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write(_USAGE)
    print(f"[doc]   已生成 {p}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-exe", action="store_true", help="跳过 PyInstaller（exe 已打好）")
    ap.add_argument("--no-model", action="store_true", help="跳过模型 zip 生成")
    args = ap.parse_args()

    if not args.no_exe:
        rc = build_exe()
        if rc != 0:
            print("[build] PyInstaller 打包失败，退出码", rc)
            return rc

    if not args.no_model:
        src = local_model_dir()
        if not src:
            print("[model] !!! 未找到本地模型，无法生成 funasr_model.zip。")
            print("[model]    请先运行一次程序联网下载，或设置 FUNASR_MODEL_DIR。")
        else:
            make_model_zip(src)

    copy_template()
    write_usage()

    print("\n[完成] 产物位于 dist/ 目录：")
    print("  - dist/voice-excel/          主程序（含 voice-excel.exe）")
    print("  - dist/funasr_model.zip      模型单文件（如有）")
    print("  - dist/使用说明.txt          说明")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
