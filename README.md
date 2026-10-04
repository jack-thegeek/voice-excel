# voice-excel 语音修改 Excel 成绩表

用语音说"2号，100-2-8等于几"，自动算出 90 并写入对应学生分数列。

## 工作流

浏览器麦克风 → 后端 FunASR 流式识别 → 文本解析（序号 + 算式）→ openpyxl 写入 Excel

## 技术栈

- **包管理**：uv
- **后端**：FastAPI + uvicorn（ASGI）
- **语音识别**：Windows 默认使用 `Windows.Media.SpeechRecognition` 连续识别；不可用时自动回退到 FunASR `paraformer-zh-streaming`
- **Excel**：openpyxl
- **前端**：单页 HTML，AudioContext + WebSocket 流式推送 PCM

## 目录结构

```
voice-excel/
├── main.py              # FastAPI 应用 + /ws/asr 流式识别端点
├── asr.py               # FunASR 流式封装（paraformer-zh-streaming）
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

# 3. 安装 FunASR（CPU 版 torch + funasr）
#    注意：funasr 默认拉老版 transformers → tokenizers 0.10.3 在 Python 3.14 上要 Rust 编译。
#    先装新版 transformers 带预编译 wheel，再装 funasr：
uv pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
uv pip install "transformers>=4.40" "tokenizers>=0.19"
uv pip install funasr soundfile --upgrade-package transformers --upgrade-package tokenizers
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

首次启动会后台下载 FunASR 模型（约 849 MB）到 `~/.cache/modelscope/`，之后从缓存加载约 2 秒。

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

- 模型文件：849 MB（磁盘）
- 运行内存：约 3.1 GB（PyTorch + 模型常驻）
- 推理：CPU，RTF 0.1-0.5，无需 GPU

## 打包（可选）

把主程序打成 onedir 文件夹、模型打成独立 zip：

```bash
# 首次需安装打包工具
uv pip install pyinstaller pyinstaller-hooks-contrib

# 一键打包（跑 PyInstaller + 生成模型 zip + 复制模板 + 写说明）
.venv/Scripts/python.exe build.py
```

产物在 `dist/`：

- `dist/voice-excel/` —— 主程序（`voice-excel.exe` + `_internal/` 依赖）
- `dist/funasr_model.zip` —— 语音模型（单文件，放在 exe 同目录或其父目录即自动解压加载）
- `dist/使用说明.txt`

模型查找顺序：环境变量 `FUNASR_MODEL_DIR` → exe 同目录或父目录的 `funasr_model/` →
exe 同目录或父目录的 `funasr_model.zip` → 联网下载。打包后无需安装 Python。

## 许可

MIT
