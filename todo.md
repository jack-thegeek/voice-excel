# 语音修改 Excel 成绩表 — 进度跟踪

## 目标
语音输入"序号 + 分数计算过程"，自动修改 `成绩表.xlsx` 中对应学生的分数。
示例：`2号，100-2-8等于几` → 100-2-8=90 → 修改 2号(曾昕奕) 第一单元分数为 90。

## 技术栈
- 包管理：uv
- 后端：FastAPI + uvicorn（ASGI）
- 前端：单页 HTML，AudioContext + WebSocket 流式推送 PCM 到后端
- 语音识别：多引擎可切换（`engines.py` 注册，前端下拉选择，localStorage 记忆）
  - sherpa-onnx `streaming-paraformer-bilingual-zh-en` int8（默认，轻量，内存 ~0.6GB，onnxruntime 免 torch）
  - FunASR `paraformer-zh-streaming`（按需加载，精度高，内存 ~3.1GB）
- Excel：openpyxl
- 自动打开浏览器：`webbrowser` + 后台线程

## Excel 结构（已确认）
- Sheet: `班级成绩登记表`
- 第1行：标题（合并 A1:K1）
- 第2行表头：A序号 / B姓名 / C第一单元 / D第二单元 / E第三单元 / F第四单元 / G第五单元 / H第六单元 / I期中考试 / J期末考试
- 第3-50行：学生数据，A列序号有跳号（无4、9），C列=第一单元分数
- 第51-53行：平均分/合格率/优秀率（公式，勿动）

## 任务清单

- [x] 1. 确认 Excel 结构，定位序号列(A)、姓名列(B)、目标分数列(C)
- [x] 2. 创建 `todo.md`
- [x] 3. 初始化 uv 项目（pyproject.toml + 依赖）
- [x] 4. 编写 `excel_editor.py`：读学生、按序号定位行、修改指定列、保存
- [x] 5. 编写 `parser.py`：解析语音文本 → (序号, 算式) → 计算分数
  - 支持"2号"/"二号"；支持"100-2-8"与"一百减二减八"；支持 加减乘除
  - 支持"等于几/等于多少/得多少"后缀
  - 支持小数"87.5"/"七十五点五"/"75点5"
- [x] 6. 编写 `main.py`：FastAPI 应用，提供 `/api/parse`、`/api/apply`、静态页
- [x] 7. 编写 `static/index.html`：语音按钮 + 文本输入回退 + 表格展示 + 确认修改
- [x] 8. 启动脚本：`run.sh` + uvicorn 启动 + 自动打开浏览器
- [x] 9. 测试：语音"2号 100-2-8等于几" → 90 → 写入 → 验证 Excel ✅
- [x] 10. 更新 todo.md 完成
- [x] 11. 新增「识别模式」下拉（单次识别 / 连续识别）：连续识别时一次语音录入结束后（无论写入成功或失败）自动重新聆听，无需重复点击 🎤
  - 选择状态用 localStorage 持久化；手动点击结束本次聆听时不自动重听
  - 说明：单次识别为默认，每次需手动点击 🎤
- [x] 12. 新增「语音引擎」下拉，支持 FunASR / sherpa-onnx 两个识别引擎自由切换
  - 新增 `engines.py` 引擎注册表 + `asr_sherpa.py`（sherpa-onnx 引擎），`asr.py` 重构为统一接口
  - WebSocket 首帧下发 `{"action":"start","engine":"..."}`；`/api/engines` 返回可用性，不可用引擎在下拉置灰
  - 模型查找/下载/解压与 FunASR 对称（env → 目录 → zip → 联网下载 int8 模型 ~237MB）
  - 默认引擎为 sherpa，启动只预加载它；FunASR 切过去才按需加载，可用 PRELOAD_ENGINES 调整
  - 已验证：两引擎 WebSocket 端到端识别均正常，FunASR 重构前后同音频输出完全一致

## 进度日志
- 2026-10-03 10:05 确认 Excel 结构，序号在 A 列（有跳号），目标分数列 C（第一单元）。
- 2026-10-03 10:08 完成全部模块编写。
- 2026-10-03 10:11 修复 parser 两处 bug：① 标点列表误含 ASCII "." 导致小数被拆；② 纯中文小数"七十五点五"未支持。
- 2026-10-03 10:12 端到端测试通过：/api/students、/api/parse、/api/apply 均正常；Excel 写入、.bak 备份、统计公式未动均验证 OK。
- 2026-10-04 新增「识别模式」下拉（static/index.html）：单次识别 / 连续识别，选择持久化到 localStorage；手动点击结束时不自动重听。
- 2026-10-04 默认识别模式改为连续识别；移除 🎤 图标。
- 2026-10-04 新增空格键快捷录音：页面焦点不在输入框/按钮/下拉等控件时，按空格开始或结束聆听。
- 2026-10-04 修复停止时提示残留：手动或关键词触发结束后，状态立即显示「正在识别最后内容…」，不再停留在「正在聆听，请说出…」。
- 2026-10-04 修复无内容时状态残留：结束识别但未识别到内容时，状态恢复为「未识别到内容，已就绪，可以开始录入」。
- 2026-10-04 新增「最近记录」卡片：保留上一条成功写入的结果（学生/列/计算过程/分数/等级/时间），连续识别自动重听时也能看到。
- 2026-10-04 成功录入详情统一改为在「最近记录」显示，样式与 div#status 完全一致（复用 buildStatus）；状态栏成功时恢复为就绪提示。
- 2026-10-06 新增「语音引擎」下拉（FunASR / sherpa-onnx）：
  asr.py 重构为统一引擎接口（available/is_loaded/preload/new_cache/recognize_chunk 返回累计全文），
  新增 asr_sherpa.py（sherpa-onnx + streaming-paraformer int8，支持 env/目录/zip/联网下载四种模型来源）
  与 engines.py 注册表；main.py 的 /ws/asr 改为按首帧 engine 路由，新增 GET /api/engines；
  前端下拉不可用引擎置灰、选择持久化；build.py/spec 同步支持打包 sherpa 模型与原生库。
  注意：FunASR 靠 len(cache)==0 判断首帧，会话 cache 必须包一层，不能混入自定义字段。
- 2026-10-06 默认引擎改为 sherpa-onnx（下拉排第一，启动只加载它，内存约 0.6GB）；
  FunASR 改为按需加载：用户切过去后下一次录音才加载（页面提示加载中）。
  同时给 get_engine 加「默认引擎不可用自动回退另一个引擎」；前端 localStorage key
  升为 voiceExcel.engine2（旧 key 里可能存着上一版默认值 funasr，会让新默认失效）。

## 用法
```bash
cd /home/jackson/workplace/voice-excel
./run.sh        # 启动服务 + 自动打开浏览器 (http://127.0.0.1:8899)
```
浏览器打开后：
1. 选班级、目标列（默认"第一单元"），默认引擎 sherpa-onnx，可在下拉切换 FunASR
2. 点 🎤 开始语音，说"2号，100-2-8等于几"
3. 识别结果显示在蓝色预览框，点 ✓ 确认写入 即修改 Excel
4. 也可在文本框手输回车（不语音时）

## 文件清单
- `pyproject.toml` / `uv.lock` — uv 依赖
- `main.py` — FastAPI 应用 + uvicorn 启动 + 自动开浏览器 + `/ws/asr` 多引擎流式识别端点
- `engines.py` — 语音引擎注册表（下拉顺序、可用性缓存、预加载顺序；第一个为默认引擎 sherpa）
- `asr_sherpa.py` — 语音引擎①（默认）：sherpa-onnx `streaming-paraformer-bilingual-zh-en` int8 封装
- `asr.py` — 语音引擎②：FunASR `paraformer-zh-streaming` 封装（单例模型 + 流式 cache，按需加载）
- `parser.py` — 语音文本解析（序号 + 算式 → 分数）
- `excel_editor.py` — openpyxl 读写，支持第一~第六单元/期中/期末列
- `static/index.html` — 单页前端，麦克风 PCM 采集 + 重采样 + WebSocket 推流
- `run.sh` — 启动脚本
- `成绩表.xlsx` / `成绩表.xlsx.bak` — 数据文件 + 备份

## FunASR 依赖（手动安装，未入 pyproject.toml）
项目 venv 已装（用 `uv pip install`，未写入 pyproject 以免 uv 解析老版 transformers）：
- torch 2.14.1+cpu / torchaudio 2.11.0+cpu
- funasr 1.4.16 / soundfile / modelscope（自动）
- transformers 5.x + tokenizers 0.23（避免 funasr 默认拉的 tokenizers 0.10.3 在 Python 3.14 上要 Rust 编译）

首次启动会后台下载 `paraformer-zh-streaming` 模型（~数百 MB）到 ModelScope 缓存
（只有切到 FunASR 引擎时才会触发）。

## sherpa-onnx 引擎（手动安装）
- `uv pip install sherpa-onnx`（onnxruntime 原生 wheel，无需编译，与 torch 共存无冲突）
- 模型：`sherpa_model/`（tokens.txt + encoder.int8.onnx + decoder.int8.onnx，约 237MB），
  首次用 sherpa 引擎时自动从 HuggingFace 下载，也可放 `sherpa_model.zip` 或用 `SHERPA_MODEL_DIR` 指定
- 环境变量：`ASR_ENGINE` 默认引擎（默认 `sherpa`）、`PRELOAD_ENGINES` 预加载哪些引擎、
  `SHERPA_MODEL_QUANT`（int8/fp32）、`SHERPA_NUM_THREADS`、`SHERPA_MODEL_REPO/HF_ENDPOINT`
