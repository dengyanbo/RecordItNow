# RIN — Record It Now（即刻记录）

> **语言：** [English](README.md) · **中文**

一款 Windows 后台应用，通过一个可自定义按钮，即可捕获、分析并搜索你的屏幕活动。

- **轻按**按钮 → 对所有显示器进行全分辨率 PNG 截图。
- **长按**（> 500 毫秒）→ 录制所有显示器的 MP4 视频（含系统声音和麦克风），松开停止。
- 在非工作时间，RIN 会用大模型分析这些捕获内容、生成摘要，并把摘要写入本地 RAG，
  之后你可以问类似 *"周二下午我看到的那个报错是什么？"* 的问题。
- 每天 / 每周自动生成 Markdown 总结报告。
- **100 % 本地存储**：SQLite 存元数据，ChromaDB 存向量，原始捕获存放在文件系统中。

> **项目状态：** v0.3.0 — Fluent 风格 UI 焕新。端到端流程实测验证：
> 捕获 → OCR → 视觉大模型 → SQLite + ChromaDB → 语义搜索 → 带引用的 RAG 问答。
> **172 个测试全部通过**，ruff 干净。已针对 Windows 常见运行期问题做加固
> （Ctrl+C 退出、cp1252 子进程解码、RDP 录制边缘情况、分析过程实时反馈）。

## v0.3.0 新增

- **Fluent 风格设计系统。** 所有色彩、字体、圆角、间距都集中在 `theme.py` —
  浅 / 深两套预设，四种重点色（blue / purple / teal / orange），两档密度
  （comfortable / compact）。全部通过 WCAG AA 对比度校验。
- **自动跟随 Windows 主题。** RIN 读取注册表里你设置的浅 / 深偏好并同步；
  也可以在 *设置 → 外观* 里手动覆盖。
- **设置对话框重新设计**：横向 Tab → **左侧导航栏** + 新增 *外观* 标签。
- **报告窗口**采用卡片式列表 + 主题化 Markdown 渲染。
- **搜索窗口**采用卡片化结果 + 聊天气泡式问答。
- **托盘图标**换成 Fluent 风格相机字形；录制时附带脉冲红点动画。
- 内置 **20 个 Fluent UI System Icons**（微软出品，MIT 协议）。
- **主题热切换**，无需重启。

## v0.2.0 新增

- **一键安装器。** 下载 release zip，右键 `install.ps1` → *用 PowerShell 运行*。
  脚本自动装好 Python、FFmpeg、Copilot CLI、所有 Python 依赖，无需手动配置。
- **可选 `-Prefetch` 参数** 在安装时预下载约 1 GB 的机器学习模型权重
  （sentence-transformers + RapidOCR + Whisper），首次 *Analyze now* 不需联网。
- **可选 `-Autostart` 参数** 把 RIN 注册为 Windows 开机自启项。
- **开始菜单快捷方式** 启动时不带黑色命令行窗口（`pythonw.exe -m rin`）。
- **`NOTICE` 文件** 列出全部第三方依赖及其 License。
- v0.1.1 的所有加固（Ctrl+C 退出、UTF-8 子进程安全、分析进度提示、Save
  崩溃修复、Reports/Search 真正可用）全部保留。

## 安装（普通用户）— 推荐

1. 从 [GitHub Releases](https://github.com/dengyanbo/RecordItNow/releases)
   下载最新的 `RIN-vX.Y.Z-windows.zip`
2. 右键 zip → *全部解压缩* → 选任意目录
3. 右键 `install.ps1` → *用 PowerShell 运行*
   （或者在该目录打开 PowerShell 跑 `.\install.ps1`）

```powershell
# 常用变体：
.\install.ps1                       # 默认安装
.\install.ps1 -Prefetch             # 同时预下载 ML 模型（约 1 GB）
.\install.ps1 -Autostart            # 同时注册开机自启
.\install.ps1 -InstallDir D:\Apps\RIN
.\install.ps1 -SkipDeps             # 跳过 Python/FFmpeg/Copilot CLI 安装
.\install.ps1 -Force                # 不询问直接覆盖
```

安装器把所有东西放到 `%LOCALAPPDATA%\Programs\RIN`（不需要管理员权限）。
装完直接在开始菜单搜 **RIN** 启动。

### 升级

在已有安装上重新跑 `install.ps1`，会询问是否覆盖（用 `-Force` 跳过询问）。
你在 `%LOCALAPPDATA%\RIN` 下的数据不会被动。

### 卸载

```powershell
# 1. 关闭开机自启（如果开过）
& "$env:LOCALAPPDATA\Programs\RIN\.venv\Scripts\python.exe" -c "from rin.utils.autostart import disable; disable()"

# 2. 删除程序文件
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\Programs\RIN"

# 3.（可选）清空你的截图/录像/数据库/模型缓存
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\RIN"

# 4.（可选）删开始菜单快捷方式
Remove-Item "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\RIN.lnk"
```

## 工作原理

```
┌────────────────────────────────────────────────────────────────────────┐
│  系统托盘（PySide6）                                                   │
│  截图 · 录制 · 报告 · 搜索 · 设置 · 暂停 · 退出                        │
└──────────────────────────────┬─────────────────────────────────────────┘
                               │
   ┌───────────────────────────┼───────────────────────────┐
   ▼                           ▼                           ▼
 输入手势                  捕获服务                    调度器
 （轻按 / 长按）           （mss + ffmpeg）            （分析 + 报告）
   │                           │                           │
   └──────────► SQLite + ChromaDB + 文件系统 ◄────────────┘
                               │
                  ┌────────────┴────────────┐
                  ▼                         ▼
                分析                       RAG 智能体
                （OCR + Whisper + LLM）    （嵌入 + 检索 + 对话）
```

## 功能特性

| 模块 | 能力 |
| --- | --- |
| **触发器** | 通过"学习下一次按键"流程，可绑定任意键盘按键、鼠标按钮或 HID / 蓝牙按钮 |
| **捕获** | 多显示器 PNG 截图（mss）以及按显示器拆分的 MP4 视频，包含系统音频与麦克风（ffmpeg + WASAPI 环回） |
| **存储** | SQLite（WAL + 外键）存元数据，ChromaDB 存向量，原始媒体按日期组织在文件树中，留存策略可配置 |
| **大模型适配** | GitHub Copilot CLI（默认，无需 API key）· OpenAI · Azure OpenAI — 可在设置中切换 |
| **分析** | 每小时后台任务，由工作时间或空闲检测双重门控；运行 RapidOCR + faster-whisper + 视觉大模型 |
| **报告** | 每天或每周的 Markdown 总结，包含 *亮点 / 应用 / 主题 / 待办事项* 各章节 |
| **RAG 搜索** | 跨所有捕获的语义搜索，附带引用的检索增强问答 |
| **隐私** | 一键紧急暂停快捷键（Ctrl+Alt+Shift+P）；除非主动选择云端大模型，否则不发起任何网络请求；所有数据存于 `%LOCALAPPDATA%\RIN\` |

## 环境要求

| 工具 | 版本 | 说明 |
| --- | --- | --- |
| Windows | 10 或 11 | 第 0 阶段跨平台，捕获 / 输入 / 紧急暂停为 Windows 专属 |
| Python | 3.11 或 3.12 | |
| FFmpeg | 最新版 | 视频录制（第 2 阶段）和关键帧抽取（第 6 阶段）必需。Windows：`winget install --id Gyan.FFmpeg -e`。安装完**重开一个 PowerShell** 让 PATH 生效。 |
| GitHub Copilot CLI | 最新版 | 默认大模型提供方。备选：OpenAI API key、Azure OpenAI |

## 开发（从源码运行）

如果你要贡献代码或从源码跑：

```powershell
# 1. 安装 uv（快速的 Python 包管理器）
winget install --id=astral-sh.uv -e

# 2. 创建虚拟环境并安装 RIN（含 dev extras）
uv venv
.\.venv\Scripts\Activate.ps1
uv pip install -e ".[all,dev]"

# 3. 启动托盘应用
python -m rin
```

按需精简安装：

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

```powershell
uv pip install -e ".[storage,capture,dev]"
```

## 运行时数据

```
%LOCALAPPDATA%\RIN\
├── config.toml      # 用户可改的设置
├── rin.db           # SQLite 元数据
├── chroma\          # ChromaDB 持久化目录
├── captures\        # 原始 PNG / MP4 / WAV 捕获
├── reports\         # 生成的 Markdown 报告
├── models\          # 缓存的 ONNX / Whisper / 嵌入模型
└── logs\
    └── rin.log      # 滚动 10 MB / 保留 14 天
```

设置环境变量 `RIN_DATA_DIR` 可覆盖根目录（测试时使用）。

## 运行测试

```powershell
pytest          # 完整测试套件（144 个测试）
ruff check src tests
python -m rin --smoke   # 启动并立即退出，用于冒烟检查
```

## 冒烟测试清单

安装完成后，按此手动流程验证全链路：

1. **启动。** 执行 `python -m rin --smoke`，应以 0 退出，`logs\rin.log` 中可见启动日志。
2. **托盘运行。** 执行 `python -m rin`，托盘出现 RIN 图标，右键弹出菜单。
   在终端按 **Ctrl+C** 验证可干净退出。
3. **学习触发器。** 设置 → 触发器 → *学习新按钮* → 按下任意按键，标签更新为对应键。
4. **截图。** 托盘 → *📸 立即截图*，PNG 出现在 `captures\YYYY\MM\DD\<时间戳>-shot\`。
5. **分析。** 托盘 → *🧠 立即分析*。Toast 按张弹出进度，托盘悬停提示显示
   `Analyzing K/N (cap-X)`，最后一个 Toast 显示 `Analysis complete — N/N captures analyzed`。
6. **搜索。** 托盘 → *搜索…*，输入关键词查看命中；输入问题，智能体应返回带 `cap-N` 引用的答案。
7. **生成报告。** 托盘 → *报告…* → *生成今日报告*，Markdown 保存到 `reports\daily-YYYYMMDD.md`。
8. **紧急暂停。** 按下 `Ctrl+Alt+Shift+P`，菜单中的 *暂停* 复选框切换，Toast 提示生效。
9. **录制（可选）。** 按住触发键超过 500 ms，开始录制，托盘图标右下角出现红点；松开 → MP4 保存。需 FFmpeg。
10. **开机自启。**
    ```powershell
    python -c "from rin.utils.autostart import enable, default_command; enable(default_command())"
    ```
    注销并重新登录，RIN 应自动启动。

## 打包独立可执行文件

```powershell
python scripts/package.py
```

输出：`dist\RIN\RIN.exe`。打包过程**不会**包含 FFmpeg 或机器学习模型，二者会在首次使用时再下载。

## 仓库结构

```
RecordItNow/
├── pyproject.toml
├── README.md            （英文 README）
├── README.zh-CN.md      （本文件，中文 README）
├── LICENSE
├── scripts/
│   ├── package.py       PyInstaller one-folder 打包
│   └── dev_run.ps1      开发启动脚本
├── src/rin/
│   ├── app.py           QApplication 装配
│   ├── config.py        Pydantic-settings + TOML
│   ├── paths.py         %LOCALAPPDATA%\RIN 路径帮助
│   ├── storage/         SQLAlchemy + ChromaDB
│   ├── capture/         mss + sounddevice + ffmpeg
│   ├── input/           pynput + hidapi + 手势状态机
│   ├── llm/             Copilot CLI / OpenAI / Azure 各 Provider
│   ├── analysis/        OCR + Whisper + 分析器 + 调度器
│   ├── reports/         每日 / 每周 Markdown 生成器
│   ├── rag/             sentence-transformers + RAG 智能体
│   ├── ui/              托盘 + 设置 / 报告 / 搜索 窗口
│   └── utils/           日志、开机自启、紧急暂停热键
└── tests/               20 个测试文件，共 144 个测试
```

## 打包发布（维护者）

```powershell
# 跑 pytest + ruff，生成 dist\RIN-vX.Y.Z-windows.zip
.\scripts\build_release.ps1

# 然后发布：
gh release create v0.2.0 dist\RIN-v0.2.0-windows.zip --title 'RIN v0.2.0' --notes-file CHANGELOG.md
```

旧的 `scripts\package.py`（PyInstaller one-folder 打包）作为未来 v0.3.0
"独立 .exe 发布"的起点保留，但 v0.2.0 流程不用它。

## 许可证

MIT —— 详见 [`LICENSE`](LICENSE)。
