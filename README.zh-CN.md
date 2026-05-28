# RIN — Record It Now（即刻记录）

> **语言：** [English](README.md) · **中文**

[![tests](https://img.shields.io/badge/tests-260%20%2F%20260-brightgreen)](#测试)
[![python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)](#环境要求)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![platform](https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-0078D4)](#环境要求)
[![release](https://img.shields.io/github/v/release/dengyanbo/RecordItNow?display_name=tag)](https://github.com/dengyanbo/RecordItNow/releases)

一个 Windows 托盘应用：**用一个按键捕获屏幕，再让大模型让它变得可检索**。

- **轻按**触发键 → 对所有显示器全分辨率 PNG 截图。
- **长按**（> 500 ms）→ 录制 MP4 视频 + 音频，松开停止。
- 在空闲或非工作时间，RIN 自动运行 **OCR + Whisper + 视觉大模型**，为每条
  捕获生成结构化摘要，并写入本地向量库。
- 打开 `RIN — Search & Ask`，用自然语言提问（"周二下午我看到的那个报错是什么？"）；
  一个 RAG 智能体会带 `cap-N` 引用回答。
- 自动生成每日 / 每周 Markdown 报告。
- 100 % 本地存储。除非你主动选了云端 LLM，否则不发任何网络请求（默认
  `copilot_cli` 不需要 API key）。

---

## 📑 目录

- [截图](#截图)
- [安装（普通用户）](#安装普通用户)
- [快速体验](#快速体验)
- [功能](#功能)
- [架构原理](#架构原理)
- 🤖 **[给 AI 智能体的导航](#-给-ai-智能体的导航)** — 仓库结构图、数据流、设计决策、常见任务
- [环境要求](#环境要求)
- [开发](#开发)
- [测试](#测试)
- [冒烟测试清单](#冒烟测试清单)
- [打包发布（维护者）](#打包发布维护者)
- [升级 / 卸载](#升级--卸载)
- [项目状态 & 变更日志](#项目状态--变更日志)
- [许可证](#许可证)

---

## 截图

| 设置（浅色） | 报告（浅色） | 搜索与问答（浅色） |
| :--- | :--- | :--- |
| ![](docs/screenshots/after/settings_light.png) | ![](docs/screenshots/after/reports_light.png) | ![](docs/screenshots/after/search_light.png) |
| **设置（深色）** | **报告（深色）** | **搜索与问答（深色）** |
| ![](docs/screenshots/after/settings_dark.png) | ![](docs/screenshots/after/reports_dark.png) | ![](docs/screenshots/after/search_dark.png) |

> 默认跟随 Windows 浅 / 深主题。可在 *设置 → 外观* 里手动覆盖，并选择四种重点色 + 两档密度。

---

## 安装（普通用户）

1. 从 [GitHub Releases](https://github.com/dengyanbo/RecordItNow/releases)
   下载最新的 `RIN-vX.Y.Z-windows.zip`。
2. 右键 → *全部解压缩*。
3. 右键 `install.ps1` → **用 PowerShell 运行**。

这个脚本会自动装好 Python 3.12、FFmpeg、GitHub Copilot CLI 以及全部 Python 依赖。

```powershell
.\install.ps1                       # 默认安装
.\install.ps1 -Prefetch             # 顺便预下载约 1 GB ML 模型
.\install.ps1 -Autostart            # 顺便注册开机自启
.\install.ps1 -InstallDir D:\Apps\RIN
.\install.ps1 -SkipDeps             # 跳过 Python/FFmpeg/Copilot 安装
.\install.ps1 -Force                # 直接覆盖已有安装
```

安装完成后：
- **启动：** 开始菜单搜 `RIN`，或 `pythonw.exe -m rin`。
- **数据目录：** `%LOCALAPPDATA%\RIN\`。
- **日志：** `%LOCALAPPDATA%\RIN\logs\rin.log`（10 MB 滚动）。
- **升级：** 重新跑 `install.ps1`。
- **干净退出：** 托盘菜单 → *Quit*，或在启动终端按 **Ctrl+C**。

---

## 快速体验

| 步骤 | 操作 | 发生了什么 |
| --- | --- | --- |
| 1 | **设置 → 触发器 → 学习新按钮**，按任意键（如 F12） | 绑定写入 `config.toml` |
| 2 | 在 Windows 任意位置按下该键 | PNG 写入 `captures\YYYY\MM\DD\<时间戳>-shot\` |
| 3 | 按住该键超过 500 ms | MP4 开始录制；托盘图标右下出现脉冲红点。松开停止。 |
| 4 | 托盘 → 🧠 *Analyze now* | RapidOCR + Copilot CLI 读取所有最近捕获；进度 Toast 报告状态。 |
| 5 | 托盘 → 🔎 *Search…* | 输入关键词 → 命中以卡片显示；提问 → 智能体附带 `cap-N` 引用回答。 |
| 6 | 托盘 → 📄 *Reports…* → *生成今日报告* | Markdown 报告保存到 `reports\daily-YYYYMMDD.md`，主题化 HTML 渲染。 |
| 7 | `Ctrl + Alt + Shift + P` | 紧急暂停切换：屏蔽所有触发键直到再次按下。 |

---

## 功能

| 模块 | 能力 |
| --- | --- |
| **触发器** | "学习下一次按键" 流程，可绑定任意键盘按键、鼠标按钮或 HID / 蓝牙按钮 |
| **捕获** | 多显示器 PNG 截图（mss）+ 按显示器拆分的 MP4 视频（ffmpeg `gdigrab`），可混入 DirectShow 音频 |
| **存储** | SQLite（WAL + 外键）存元数据，ChromaDB 存向量，原始媒体按日期组织在文件树中，留存策略可配置 |
| **大模型适配** | GitHub Copilot CLI（默认，无需 API key）· OpenAI · Azure OpenAI — 可在设置中切换 |
| **分析** | 每小时后台任务，由工作时间或空闲检测双重门控；运行 RapidOCR + faster-whisper + 视觉大模型 |
| **报告** | 每天或每周的 Markdown 总结，含 *亮点 / 应用 / 主题 / 待办事项* 章节 |
| **RAG 搜索** | 跨所有捕获的语义搜索，附带引用的检索增强问答 |
| **隐私** | 紧急暂停热键；除非主动选择云端大模型，否则不发任何网络请求；所有数据存于 `%LOCALAPPDATA%\RIN\` |
| **主题** | Fluent 2 校准 UI；浅色 / 深色 / 跟随 Windows；四种重点色；两档密度 |

---

## 架构原理

```
┌─────────────────────────────────────────────────────────────────────────┐
│  系统托盘（PySide6）                                                    │
│  截图 · 录制 · 报告 · 搜索 · 设置 · 暂停 · 退出                         │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │
   ┌───────────────────────────┼───────────────────────────────┐
   ▼                           ▼                               ▼
 输入手势                  捕获服务                        调度器
 （轻按 / 长按 FSM,        （mss + ffmpeg）                （APScheduler:
  pynput + hidapi）            │                            每小时分析,
   │                           │                            每日报告)
   └──────────► SQLite + ChromaDB + 日期化文件树 ◄────────────┘
                               │
                  ┌────────────┴────────────┐
                  ▼                         ▼
              分析流水线                  RAG 智能体
              OCR + Whisper +             sentence-transformers +
              视觉大模型                   检索 + 对话
                  │                         │
                  └──────► Markdown 报告生成器 ◄──┘
```

---

## 🤖 给 AI 智能体的导航

> 如果你是一个帮助维护 RIN 的大模型 / 编码 Agent，**这一节是你的入口**。
> 先看这一节，README 的其它部分主要面向终端用户。

### 仓库结构速览

| 路径 | 规模 | 干什么 |
| --- | --- | --- |
| `src/rin/app.py` | 小 | `QApplication` 引导 + SIGINT 处理 + 应用主题 |
| `src/rin/config.py` | 中 | `pydantic` schema，对应 `%LOCALAPPDATA%\RIN\config.toml`。所有用户可改的设置都在这。 |
| `src/rin/paths.py` | 小 | `%LOCALAPPDATA%\RIN\*` 目录助手。`RIN_DATA_DIR` 环境变量可覆盖根目录（测试用）。 |
| `src/rin/storage/` | 439 L | SQLAlchemy 模型 + Chroma 客户端 + 留存策略。**不要直接写裸 SQL**，新表用 `migrations.py`。 |
| `src/rin/capture/` | 710 L | `mss` 截图、`ffmpeg` 录制子进程、`sounddevice` 音频、`CaptureService` 编排器。 |
| `src/rin/input/` | 590 L | 纯 Python 手势状态机 + Qt 识别器 + pynput / hidapi 监听器 + learn-mode。 |
| `src/rin/llm/` | 482 L | `Provider` ABC + `copilot_cli` / `openai` / `azure` 三个 provider + `factory.make_provider(cfg)`。 |
| `src/rin/analysis/` | 727 L | OCR (rapidocr) + Whisper (faster-whisper) + 关键帧抽取 + summarizer + scheduler。 |
| `src/rin/rag/` | 273 L | sentence-transformers 嵌入器 + ChromaDB 索引 + 搜索 + 问答 agent。 |
| `src/rin/reports/` | 308 L | 每日 / 每周 Markdown 生成器 + APScheduler。 |
| `src/rin/ui/` | 2094 L | PySide6 托盘 + 设置 + 报告 + 搜索窗口。`theme.py` + `style.py` 拥有所有 QSS design tokens。 |
| `src/rin/utils/` | 188 L | 日志（loguru）、自启动（HKCU 注册表）、紧急暂停热键、Windows 助手。 |
| `tests/` | 40 个文件 | 195 个测试，全部通过。用 `pytest -q`。 |
| `scripts/` | 4 个文件 | `install.ps1`（用户安装器）、`build_release.ps1`（打包脚本）、`prefetch_models.py`、`dev_run.ps1`。 |

### 数据流：从轻按一下到可搜索的答案

```
1. 用户按下 F12
   ↓
2. pynput 监听线程发出 InputEvent
   ↓ (Qt.QueuedConnection)
3. InputManager → GestureStateMachine（纯 Python）
   ↓ shot_requested Qt 信号
4. TrayApp 提交 _on_shot_requested 到 QThreadPool
   ↓
5. CaptureService.take_screenshot()
   ↓
6. mss 抓取所有显示器 → PNG 写入 captures\YYYY\MM\DD\<时间戳>-shot\
   ↓
7. SQLAlchemy 写入 Capture 行（status="captured"）

   （之后，每小时一次，或用户点 "Analyze now"）

8. AnalysisScheduler._tick 非阻塞获取 Lock
   ↓
9. analyze_pending 遍历 status="captured" 的 Capture
   ↓
10. 每张：RapidOCR 抽文本 → Copilot CLI 视觉摘要
    ↓
11. build_summary 让 LLM 写一段最终段落
    ↓
12. SQLAlchemy 写入 Analysis + 把 status 翻成 "analyzed"
    ↓
13. sentence-transformers 嵌入器把向量写入 ChromaDB

   （之后，用户打开 Search & Ask）

14. 用户输入问题
    ↓
15. RAGAgent.ask 嵌入问题 → ChromaDB top-k 命中
    ↓
16. 构造 [SYSTEM]/[USER] prompt + 命中片段
    ↓
17. Copilot CLI 生成带 cap-N 引用的回答
    ↓
18. SearchWindow 渲染聊天气泡 + 引用条
```

### 设计决策日志（为什么是这样）

| 决定 | 原因 | 在哪验证 |
| --- | --- | --- |
| 用 **PySide6**，不用 PyQt6 / Tkinter / Tauri | LGPL 允许动态链接到 MIT 应用并二次分发；成熟；一个工具搞定托盘 + 窗口 | `pyproject.toml`, `NOTICE` |
| **不用 `PySide6-Fluent-Widgets`** | 它是 GPL-3.0，会把 RIN 拖进 GPL。我们在 `ui/style.py` 手写 Fluent 风格 QSS。 | `ui/style.py`、plan.md 决策表 |
| **打包 Fluent UI System Icons (MIT)** 作为 SVG 资源 | MIT 干净，随 wheel 发布，无运行时下载 | `NOTICE`, `src/rin/ui/assets/` |
| **GitHub Copilot CLI** 作为默认 LLM provider，不是 OpenAI | 普通用户不需要 API key；可视觉 (`--attachment`)；可在设置切换 | `src/rin/llm/copilot_cli.py` |
| **Claude Opus 4.7 1M-internal、high reasoning** 默认模型 | 质量最佳 + 1M 上下文应对长视频；用户可改 | `src/rin/config.py:LLMProviderConfig` |
| **ChromaDB**，不是 pinecone / qdrant / pgvector | 完全本地，零服务，嵌入式进程内 | `src/rin/storage/vector_store.py` |
| **sentence-transformers all-MiniLM-L6-v2** | 90 MB；CPU 快；对小语料够用 | `src/rin/rag/embedder.py` |
| **faster-whisper small** | int8 量化，CPU 实时级别转音频 | `src/rin/analysis/transcribe.py` |
| **RapidOCR ONNX**，不是 Tesseract / PaddleOCR | 自带 ONNX 模型，无需原生安装，MIT/Apache | `src/rin/analysis/ocr.py` |
| **SQLAlchemy 2.0 + 不用 Alembic** | 迁移很少且小；用 `PRAGMA user_version` 手动追踪 | `src/rin/storage/migrations.py` |
| **`ffmpeg` 子进程调用**，不用 `av` / `imageio-ffmpeg` | 长录制最稳的是 ffmpeg 自己的 gdigrab+dshow 通路；用 `q` 优雅停止 | `src/rin/capture/recorder.py` |
| **ffmpeg `stderr=DEVNULL`** | 不这么做的话长录制会撑满 64 KB Windows pipe 缓冲造成 ffmpeg 死锁。v0.3.1 review 修复。 | `src/rin/capture/recorder.py` |
| **子进程强制 `encoding="utf-8", errors="replace"`** | Windows 默认 cp1252，遇到中文 / emoji ffmpeg 输出会炸。v0.1.1 修复。 | `src/rin/llm/copilot_cli.py`, `src/rin/analysis/keyframes.py` |
| **APScheduler `BackgroundScheduler`**，外加 `threading.Lock` 保护 | 手动 "Analyze now" 会和每小时 tick 竞态；非阻塞锁直接跳过重复。v0.3.1 修复。 | `src/rin/analysis/scheduler.py` |
| **v0.3.x 不出 PyInstaller exe** | install.ps1 保持 zip < 200 KB；规避 Qt-in-onefile 的坑 | `scripts/install.ps1`、`scripts/package.py`（遗留） |
| **双语文档（英 / 中）** | 作者和大部分用户都是中英双语 | `README.md`, `README.zh-CN.md` |

### 常见 Agent 任务

每个任务都附最简范例文件的位置。

#### 加一个 LLM provider

1. 在 `src/rin/llm/` 下新建模块，继承 `rin.llm.base.Provider`（参考 `openai_provider.py`）。
2. 实现 `analyze_image`、`analyze_text`、`chat`、`capabilities`。
3. 在 `src/rin/llm/factory.py:make_provider` 里注册。
4. 在 `src/rin/config.py` 的 `LLMProviderConfig.name` 的 `Literal` 里加一个选项。
5. 在 `src/rin/ui/settings_dialog.py` 的 `LLM_NAMES` 里加。
6. 写单元测试，用一个 fake client（参考 `tests/test_llm_openai.py`）。

#### 加一个设置字段

1. 编辑 `src/rin/config.py` 里对应的 `BaseModel`（比如 `CaptureConfig`）。
   用 `pydantic.Field` 给默认值，老 `config.toml` 仍然能加载。
2. 在 `src/rin/ui/settings_dialog.py` 对应的 `_build_*_tab` 里加控件。
   标签用 `self._label(...)`，布局用 `self._form()`。
3. 在 `load_from_config` 和 `_on_save` 里串联加载 / 保存。
4. 扩展 `tests/test_ui_settings.py:test_dialog_save_round_trip` 覆盖新字段。

#### 加一个分析步骤

1. 在 `src/rin/analysis/` 下创建模块，导出一个纯函数。
2. 在 `src/rin/analysis/summarizer.py:analyze_capture`（截图路径）或
   `src/rin/analysis/video_analyzer.py:analyze_video`（视频路径）里串进编排。
3. 用已有的依赖注入入口写单元测试（`analyze_image_fn`、`extract_keyframes_fn`、`transcribe_fn`）。

#### 改主题 / 视觉

- 颜色在 `src/rin/ui/theme.py`。编辑 `LIGHT` / `DARK` 数据类或 `ACCENTS`。
  `tests/test_ui_theme.py` 套件会强制 WCAG AA 对比度。
- 尺寸 + 选择器在 `src/rin/ui/style.py:palette_to_qss`。`[role="..."]` 是 widget
  接入样式的方式（`widget.setProperty("primary", True)`）。

#### 发布新版本

```powershell
# 1. 改版本号：src/rin/__init__.py + pyproject.toml
# 2. 在 CHANGELOG.md 加一段
# 3. 验证
ruff check src tests scripts
pytest -q

# 4. 构建 zip
.\scripts\build_release.ps1

# 5. 打 tag + 发布
git add -A
git commit -m "vX.Y.Z — <一句话变更>"
git tag -a vX.Y.Z -m "RIN vX.Y.Z"
git push origin main vX.Y.Z
gh release create vX.Y.Z dist\RIN-vX.Y.Z-windows.zip --notes-file CHANGELOG.md
```

### 术语表

| 术语 | 含义 |
| --- | --- |
| **capture（捕获）** | `captures` 表里的一行 — 一次用户触发的事件（截图或录制）+ 它的文件 |
| **cap-N** | RAG 回答里引用的 capture ID（`cap-7` = `captures.id == 7`） |
| **analysis（分析）** | `analyses` 表里的一行，包含 capture 的 OCR + 大模型摘要 |
| **trigger（触发器）** | 用户绑定的输入 — 键盘 / 鼠标 / HID / 蓝牙按钮 |
| **gate（门控）** | 让每小时分析 tick 运行的条件：工作时间外 OR 空闲 |
| **provider** | 实现 `rin.llm.base.Provider` 的 LLM 后端。今天有三个：copilot_cli（默认）、openai、azure |
| **role** | widget 上的 Qt 属性，让它接入样式表规则。如：`primary`、`flat`、`muted`、`field-label`、`caption`、`nav`、`cards`、`empty-state-title` |

### Agent 应该尽量不动的文件

- `src/rin/ui/assets/*.svg` — Microsoft Fluent System Icons；替换必须来自上游 MIT 仓库
- `LICENSE` — MIT，不变
- `NOTICE` — 只有新增需要署名的依赖 / 资产时才更新
- `.gitignore` — 已排除 `.venv`、`dist`、`build`、`__pycache__`、SQLite 工作文件、`logs`

### 开任务前先读这些

| 想 … | 读 |
| --- | --- |
| 理解运行时入口 | `src/rin/app.py` 和 `src/rin/__main__.py` |
| 跟踪一次截图全流程 | 上面 **数据流** 图 + `src/rin/capture/screenshot.py` + `src/rin/analysis/summarizer.py` |
| 思考子进程生命周期 | `src/rin/capture/recorder.py` 和 `src/rin/llm/copilot_cli.py` |
| 思考线程 + Qt 信号 | `src/rin/input/manager.py` 和 `src/rin/ui/tray.py` |
| 看过往设计选择 | `CHANGELOG.md`（特别是 v0.3.1 的 review 笔记） |

---

## 环境要求

| 工具 | 版本 | 说明 |
| --- | --- | --- |
| Windows | 10 或 11 | 第 0 阶段跨平台，捕获 / 输入 / 紧急暂停为 Windows 专属 |
| Python | 3.11 / 3.12 / 3.13 | 安装器通过 winget 自动装 Python 3.12 |
| FFmpeg | 最新版 | 视频录制 + 关键帧抽取必需。`winget install Gyan.FFmpeg`。装完重开 PowerShell 让 PATH 生效。 |
| GitHub Copilot CLI | 最新版 | 默认 LLM 提供方。备选：OpenAI API key、Azure OpenAI。 |

---

## 开发

```powershell
# 1. 安装 uv（快速的 Python 包管理器）
winget install --id=astral-sh.uv -e

# 2. 创建虚拟环境并安装 RIN（含 dev extras）
uv venv
.\.venv\Scripts\Activate.ps1
uv pip install -e ".[all,dev]"

# 3. 启动托盘应用
python -m rin

# 冒烟 / lint / 测试
python -m rin --smoke
ruff check src tests scripts
pytest -q
```

可选 extras（`pyproject.toml` 里声明）：

| Extra | 用途 | 阶段 |
| --- | --- | --- |
| `storage` | SQLAlchemy + ChromaDB | 1 |
| `capture` | mss、sounddevice、pywin32 | 2 |
| `input` | keyboard、pynput、hidapi | 3 |
| `llm` | openai、keyring | 5 |
| `analysis` | APScheduler、rapidocr、faster-whisper | 6 |
| `reports` | Jinja2、markdown | 7 |
| `rag` | sentence-transformers | 8 |
| `dev` | pytest、ruff | 始终需要 |
| `all` | 除 `dev` 外全部 | 完整安装 |

---

## 测试

```powershell
pytest -q           # 全部 195 个测试，热缓存约 60-90 秒
ruff check src tests scripts
python -m rin --smoke
```

测试在 `tests/` 下，按子系统一文件（`test_capture_recorder.py`、`test_rag_agent.py` 等）。
重 I/O 都通过模块内已有的依赖注入入口 mock 掉。

---

## 冒烟测试清单

安装后按顺序走一遍：

1. **启动。** `python -m rin --smoke` → 退 0，`logs\rin.log` 有启动日志。
2. **托盘运行。** `python -m rin` → 托盘出现 RIN 图标。在终端按 **Ctrl+C** 验证可干净退出。
3. **学习触发器。** 设置 → 触发器 → *学习新按钮* → 按任意键。
4. **截图。** 托盘 → *📸 立即截图*，PNG 出现在 `captures\YYYY\MM\DD\<时间戳>-shot\`。
5. **分析。** 托盘 → *🧠 立即分析*。进度 Toast 弹出，最后一个 Toast `Analysis complete — N/N`。
6. **搜索。** 托盘 → *🔎 搜索…*，输入关键词；问问题，智能体返回带 `cap-N` 引用的答案。
7. **生成报告。** 托盘 → *📄 报告…* → *生成今日报告*。Markdown 保存到 `reports\daily-YYYYMMDD.md`。
8. **紧急暂停。** 按 `Ctrl + Alt + Shift + P`。复选框切换，Toast 提示。
9. **录制（可选）。** 按住触发键超过 500 ms，松开 → MP4 保存。需 FFmpeg。
10. **开机自启。**
    ```powershell
    python -c "from rin.utils.autostart import enable, default_command; enable(default_command())"
    ```
    注销重登。RIN 自动启动。停用用 `disable()`。

---

## 打包发布（维护者）

```powershell
.\scripts\build_release.ps1        # 产出 dist\RIN-vX.Y.Z-windows.zip
```

旧的 `scripts\package.py`（PyInstaller one-folder 打包）作为未来 v0.4.0+
独立 `.exe` 发布的起点保留，但 v0.3.x 流程不用它。

---

## 升级 / 卸载

### 升级

在已有安装上重跑 `install.ps1`，会询问是否覆盖（`-Force` 跳过询问）。
`%LOCALAPPDATA%\RIN` 下的数据会被保留。

### 卸载

```powershell
# 1. 关闭开机自启（如果开过）
& "$env:LOCALAPPDATA\Programs\RIN\.venv\Scripts\python.exe" -c "from rin.utils.autostart import disable; disable()"

# 2. 删除程序文件
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\Programs\RIN"

# 3.（可选）清空截图 / 录像 / 数据库 / 模型缓存
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\RIN"

# 4.（可选）删开始菜单快捷方式
Remove-Item "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\RIN.lnk"
```

---

## 项目状态 & 变更日志

- 当前版本：**v0.6.0**（2026-05-28 发布）
- 测试：**260 / 260 pytest 通过**，ruff 清洁
- 构建 / lint：在 Windows 10 / 11 + Python 3.11 / 3.12 上绿
- CI：每次 push 都跑 [`.github/workflows/ci.yml`](.github/workflows/ci.yml)
- 完整发布历史：[`CHANGELOG.md`](CHANGELOG.md)
- 想贡献？见 [`CONTRIBUTING.md`](CONTRIBUTING.md) 和 [`AGENTS.md`](AGENTS.md)。
  安全问题：[`SECURITY.md`](SECURITY.md)。

---

## 许可证

MIT — 见 [`LICENSE`](LICENSE)。

第三方署名见 [`NOTICE`](NOTICE)。主要运行时依赖及其 license：

- PySide6 / shiboken6 — LGPL-3.0（动态链接）
- ChromaDB · sentence-transformers · transformers · rapidocr-onnxruntime · openai — Apache-2.0
- SQLAlchemy · mss · faster-whisper · loguru · keyboard · keyring · Pillow · APScheduler — MIT 或 BSD
- Fluent UI System Icons (`src/rin/ui/assets/*.svg`) — Microsoft，MIT
- FFmpeg — LGPL / GPL，**不打包**；由 `install.ps1` 通过 winget 单独安装

除非你主动配置了需要联网的 LLM provider，否则 RIN 不发起任何云端请求。
默认 `copilot_cli` 走的是你已有的 GitHub Copilot CLI 鉴权。
