# voice-excel 语音修改 Excel 成绩表

用语音说"2号，100-2-8等于几"，自动算出 90 并写入对应学生分数列。

## 工作流

浏览器麦克风 → 后端语音引擎流式识别（FunASR / sherpa-onnx 可选）→ 文本解析（序号 + 算式）→ openpyxl 写入 Excel

## 技术栈

- **包管理**：uv
- **后端**：FastAPI + uvicorn（ASGI）
- **语音识别**：两个引擎可切换，由 `engines.py` 统一注册，前端「语音引擎」下拉选择
  - `sherpa-onnx`（默认）：同名模型转换的 ONNX int8 版（`streaming-paraformer-bilingual-zh-en`），
    基于 onnxruntime，无需 torch，内存约 0.6GB、启动即就绪
  - `FunASR`：`paraformer-zh-streaming`，精度高，运行内存约 3.1GB，按需切换时才会加载
- **Excel**：openpyxl
- **前端**：单页 HTML，AudioContext + WebSocket 流式推送 PCM

## 目录结构

```
voice-excel/
├── main.py              # FastAPI 应用 + /ws/asr 流式识别端点（多引擎）
├── asr.py               # 语音引擎 ①：FunASR 流式封装（paraformer-zh-streaming）
├── asr_sherpa.py        # 语音引擎 ②：sherpa-onnx 流式封装（streaming-paraformer int8）
├── engines.py           # 引擎注册表（新引擎在这里登记即可出现在前端下拉里）
├── parser.py            # 语音文本解析（序号 + 算式 → 分数）
├── excel_editor.py      # openpyxl 读写
├── static/index.html    # 单页前端
├── run.sh               # 启动脚本
├── 成绩表_template.xlsx # 空模板（匿名化）
└── pyproject.toml
```

## 安装

需要 Python ≥ 3.10（已在 3.14 测试通过）。

```bash
# 1. 用 uv 创建虚拟环境
uv venv

# 2. 安装项目依赖
uv pip install fastapi "uvicorn[standard]" openpyxl

# 3a. 安装 FunASR 引擎（CPU 版 torch + funasr）
#    注意：funasr 默认拉老版 transformers → tokenizers 0.10.3 在 Python 3.14 上要 Rust 编译。
#    先装新版 transformers 带预编译 wheel，再装 funasr：
uv pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
uv pip install "transformers>=4.40" "tokenizers>=0.19"
uv pip install funasr soundfile --upgrade-package transformers --upgrade-package tokenizers

# 3b. 安装 sherpa-onnx 引擎（可选，纯 onnxruntime，装不上也能跑，只是引擎下拉里置灰）
uv pip install sherpa-onnx
```

## 准备数据

复制模板为真实数据文件（不入库）：

```bash
cp 成绩表_template.xlsx 成绩表.xlsx
# 用 Excel/WPS 打开 成绩表.xlsx，填入学生姓名和分数
```

Excel 结构：
- Sheet 名：`班级成绩登记表`
- 第 1 行：标题（合并 A1:K1）
- 第 2 行表头：A序号 / B姓名 / C第一单元 / D第二单元 / E第三单元 / F第四单元 / G第五单元 / H第六单元 / I期中考试 / J期末考试
- 第 3-50 行：学生数据（A 列序号可跳号）
- 第 51-53 行：平均分 / 合格率 / 优秀率（公式，勿动）

## 运行

```bash
./run.sh
# 或
.venv/bin/python main.py
```

启动后自动打开浏览器 http://127.0.0.1:8899/

首次启动会在后台下载默认引擎（sherpa-onnx）的模型：约 237MB 到项目目录
`sherpa_model/`，之后从本地秒级加载。FunASR 模型（约 849MB，下载到
`~/.cache/modelscope/`）只有切到该引擎时才会触发下载/加载。

## 语音引擎选择

前端「录入设置」里多了一个 **语音引擎** 下拉（选择会记住）：

| 引擎 | 模型 | 体积 | 内存 | 特点 |
| --- | --- | --- | --- | --- |
| `sherpa-onnx`（默认） | streaming-paraformer-bilingual-zh-en (int8) | 237MB | ~0.6GB | 轻量、延迟低 |
| `FunASR` | paraformer-zh-streaming | 849MB | ~3.1GB | 精度高 |

- 未安装依赖的引擎在下拉里显示「（不可用）」并给出原因，不会影响另一个引擎。
- 启动只预加载默认引擎（sherpa，约 0.6GB）；FunASR 要等用户切到它、下一次录音时
  才由 WebSocket 按需加载（页面会显示"正在加载…约 10-30 秒"）。
- 引擎 id 不传（老客户端）时用默认引擎；默认引擎不可用（如没有 sherpa 模型又无法联网下载）
  会自动回退到另一个可用引擎。
- 相关环境变量：

| 变量 | 说明 |
| --- | --- |
| `ASR_ENGINE` | 默认引擎（`funasr` / `sherpa`，默认 `sherpa`） |
| `PRELOAD_ENGINES` | 启动时预加载哪些引擎：`all` / `funasr,sherpa` / `none` |
| `SKIP_MODEL_PRELOAD` | `=1` 时完全跳过启动预加载 |
| `SHERPA_MODEL_QUANT` | sherpa 权重档位：`int8`（默认）/ `fp32`（更准但 825MB） |
| `SHERPA_MODEL_DIR` | 指定 sherpa 模型目录（含 `tokens.txt` + `encoder*.onnx` + `decoder*.onnx`） |
| `SHERPA_MODEL_REPO` |  sherpa 模型下载源（HuggingFace repo，默认 `csukuangfj/sherpa-onnx-streaming-paraformer-bilingual-zh-en`） |
| `FUNASR_MODEL_DIR` | 指定 FunASR 模型目录 |

sherpa-onnx 模型查找顺序：环境变量 `SHERPA_MODEL_DIR` → exe/项目目录下的 `sherpa_model/` →
`sherpa_model.zip`（自动解压）→ 联网下载。

## 使用

1. 顶部选目标列（默认"第一单元"）
2. 点 🎤 开始语音 → Chrome 提示麦克风权限，允许
3. 说"2号，100-2-8等于几"
4. 增量出字，遇到"等于几/等于多少"自动结束并写入 Excel
5. 也可在文本框手输回车（不语音时）

支持：
- 序号"2号"/"二号"
- 算式"100-2-8"与"一百减二减八"，加减乘除
- 小数"87.5"/"七十五点五"/"75点5"
- 后缀"等于几/等于多少/得多少"

## 资源占用参考

- FunASR：模型 849 MB（磁盘），运行内存约 3.1 GB（PyTorch 常驻），切到该引擎才会加载
- sherpa-onnx：模型 237 MB（int8，磁盘），运行内存约 0.6 GB，启动即预加载
- 推理均为 CPU，RTF 0.1-0.5，无需 GPU

## 打包（可选）

把主程序打成 onedir 文件夹、模型打成独立 zip：

```bash
# 首次需安装打包工具
uv pip install pyinstaller pyinstaller-hooks-contrib

# 一键打包（跑 PyInstaller + 生成两个模型 zip + 复制模板 + 写说明）
.venv/Scripts/python.exe build.py
```

产物在 `dist/`：

- `dist/voice-excel/` —— 主程序（`voice-excel.exe` + `_internal/` 依赖）
- `dist/funasr_model.zip` —— FunASR 语音模型（放在 exe 同目录或其父目录即自动解压加载）
- `dist/sherpa_model.zip` —— sherpa-onnx 语音模型（同上）
- `dist/使用说明.txt`

模型查找顺序：环境变量 `FUNASR_MODEL_DIR` / `SHERPA_MODEL_DIR` → exe 同目录或父目录的
`funasr_model/` / `sherpa_model/` → 同名 `.zip`（自动解压）→ 联网下载。打包后无需安装 Python。

## 许可

MIT
