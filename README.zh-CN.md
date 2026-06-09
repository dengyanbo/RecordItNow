# RIN — Record It Now

> **Languages:** [English](README.md) · **中文** · **开发或贡献？** 见 [`docs/DEVELOPING.md`](docs/DEVELOPING.md)

[![tests](https://img.shields.io/badge/tests-470%20%2F%20470-brightgreen)](docs/DEVELOPING.md#testing)
[![python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)](#要求)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![platform](https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-0078D4)](#要求)
[![CI](https://github.com/dengyanbo/RecordItNow/actions/workflows/ci.yml/badge.svg)](https://github.com/dengyanbo/RecordItNow/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/dengyanbo/RecordItNow?display_name=tag)](https://github.com/dengyanbo/RecordItNow/releases)

一个 Windows 托盘应用：**按一个键截屏，然后让 LLM 把屏幕活动变成可搜索的内容**。

- **轻点**触发键 → 所有屏幕的全分辨率 PNG + 缩略图
- **长按** (> 500 ms) → MP4 + 音频录制，直到松手
- 空闲时间 / 非工作时间，RIN 自动 **OCR + Whisper + 视觉 LLM** 分析每次 capture，写入本地向量库
- **🔎 Search & Ask** 自然语言提问（比如 *"周二我看到的那个 error 是什么？"*），RAG agent 带 `cap-N` 引用回答
- 每日 / 每周生成 Markdown 报告，可导出 PDF / HTML / 写入 Obsidian vault
- **Skills** 插件按你的规则归类——默认识别 16 位 case ID 和 19 位 collab task ID，关闭后自动归档
- 100% 本地存储。云端 LLM 完全可选（默认 `copilot_cli` 不需要 API key）

---

## 安装

**一键安装** — 单个下载，不需要装 Python（~430 MB）：

1. 从 [GitHub Releases](https://github.com/dengyanbo/RecordItNow/releases) 下载 `RIN-vX.Y.Z-windows-installer.zip`
2. 右键 zip → **全部解压** （到任意目录）
3. 在解压出的目录里 **双击 `Install.bat`**

完事。安装器会：

- 把独立运行的 bundle 复制到 `%LOCALAPPDATA%\Programs\RIN\`
- 如果 `PATH` 里没 FFmpeg，自动用 winget 装一个
- 创建开始菜单快捷方式

**常用 flag** — 想用的话，在解压目录里开个 PowerShell 跑：

```powershell
.\install.ps1 -FromBundle .\bundle -Force -Autostart            # 同时设置开机自启
.\install.ps1 -FromBundle .\bundle -Force -InstallDir "D:\Apps\RIN"
.\install.ps1 -FromBundle .\bundle -Force -SkipDeps             # 跳过 FFmpeg 自动安装
```

想从源码构建或贡献代码？看 [`docs/DEVELOPING.md`](docs/DEVELOPING.md)。

装完之后：

- **启动**：开始菜单输 `RIN`，或直接跑 `%LOCALAPPDATA%\Programs\RIN\RIN.exe`
- **数据位置**：`%LOCALAPPDATA%\RIN\`（配置、截图、报告、向量库、日志）
- **退出**：托盘菜单 → *Quit*，或 **Ctrl+Alt+Shift+P** 暂停
- **进程单例**：第二次启动（双击图标、自启动重复触发）会自动检测到正在运行的实例并优雅退出，弹出小提示指向系统托盘；不会出现重复全局热键或并发数据库写入。

## 更新

1. 从 [Releases page](https://github.com/dengyanbo/RecordItNow/releases)
   下载最新的 `RIN-vX.Y.Z-windows-installer.zip`。
2. 从托盘退出 RIN（右键系统托盘图标 → Quit）。
3. 解压 zip，然后双击 `Install.bat`。

你的截图、录制、数据库、日志和已下载模型都在
`%LOCALAPPDATA%\RIN\`，**更新时会保留**。

---

## 截图

| Settings (浅色) | Reports (浅色) | Search & Ask (浅色) |
| :---: | :---: | :---: |
| ![](docs/screenshots/after/settings_light.png) | ![](docs/screenshots/after/reports_light.png) | ![](docs/screenshots/after/search_light.png) |
| **Settings (深色)** | **Reports (深色)** | **Search & Ask (深色)** |
| ![](docs/screenshots/after/settings_dark.png) | ![](docs/screenshots/after/reports_dark.png) | ![](docs/screenshots/after/search_dark.png) |

> 主题默认跟随 Windows；可在 Settings → Appearance 切换，
> 还有 4 种强调色 + 2 种密度可选。

---

## 快速上手

| 步 | 操作 | 发生什么 |
| --- | --- | --- |
| 1 | **Settings → Trigger → Learn new button**，按任意键（比如 F12） | 绑定保存到 `config.toml` |
| 2 | 在 Windows 任何地方按这个键 | 所有屏幕的 PNG + 240×135 缩略图保存 |
| 3 | 按住超过 500 ms | 开始录 MP4，托盘图标红点闪烁。松手停止。 |
| 4 | 托盘 → 🧠 *Analyze now* | OCR + LLM 总结每个未分析的 capture，toast 报告进度 |
| 5 | 托盘 → 🔎 *Search…* | 输入查询 → 语义搜索结果。提问 → agent 带 `cap-N` 引用回答 |
| 6 | 托盘 → 📄 *Reports…* → *Today* | 当天 Markdown 报告，工具栏可导出 PDF / HTML |
| 7 | Settings → **Skills** → 启用 *Support tickets* | 默认识别 16 位 case ID 和 19 位 collab task ID，看到 "Status: Closed" 就归档 |
| 8 | `Ctrl + Alt + Shift + P` | 紧急暂停快捷键（仅 RAM；持久暂停在 Settings → Privacy） |

---

## 功能

| 领域 | 能力 |
| --- | --- |
| **触发** | 绑定任意键盘 / 鼠标按钮 / HID / 蓝牙按钮，通过"按下你想要的"流程学习 |
| **捕获** | 多屏 PNG + 缩略图 JPG sidecar，分屏 MP4 视频，可选 DirectShow 音频混流，可选 5 秒语音备注 |
| **存储** | SQLite (WAL + 外键)、ChromaDB 向量、FTS5 报告搜索、按日期分文件夹、可配置保留期 |
| **LLM 后端** | GitHub Copilot CLI（默认，免 API key）· OpenAI · Azure OpenAI |
| **分析** | 每小时后台任务，仅在非工作时间或 idle 时跑；OCR + Whisper + 视觉 LLM。语言可配置。 |
| **Skills** | 可插拔归类。内置 `support_ticket` 默认识别 16 位 case ID + 19 位 collab task ID（关闭后自动归档）。自定义 skill 放在 `%LOCALAPPDATA%\RIN\skills\` 即可。 |
| **Topics & PoIs** | 将项目 / 客户 / 人物作为 PoI 跟踪；报告按 PoI 分组。 |
| **报告** | 每日 / 每周 Markdown 报告，全文检索（FTS5），可导出 PDF / HTML，可选 Obsidian vault 同步写入。 |
| **RAG 搜索** | 语义搜索 + RAG agent 带引用回答 |
| **隐私** | 应用黑名单（按前台窗口跳过捕获）、暂停 / 定时暂停、可选 AES-256 磁盘加密（Windows DPAPI） |
| **主题** | Fluent 2 风格 UI；浅色 / 深色 / 跟随 Windows；4 种强调色；2 种密度 |
| **日历集成（可选）** | Outlook (MS Graph) + Google Calendar — 日报中加入 `## Calendar` 段落 |
| **诊断** | 一键生成脱敏诊断 zip（配置 + 日志 + 环境，**不含**截图 / 不含密钥）用于支持场景 |

---

## 工作原理

```
┌─────────────────────────────────────────────────────────────────────────┐
│  系统托盘 (PySide6) — Capture · Record · Reports · Search · Settings    │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │
   ┌───────────────────────────┼───────────────────────────────┐
   ▼                           ▼                               ▼
 输入手势                   捕获服务                       调度器
 (tap / hold 状态机,       (mss + ffmpeg)                 (APScheduler:
  pynput + hidapi)              │                          每小时分析,
   │                            │                          每日报告,
   │                            │                          bucket 归档)
   └──────────────► SQLite + ChromaDB + 按日期分文件夹 ◄─────┘
                                │
                  ┌─────────────┼─────────────┐
                  ▼             ▼             ▼
             分析流水线       Skills        RAG agent
             OCR+Whisper    detect →      embed → retrieve
             视觉 LLM       bucket        → 带引用回答
                  │             │             │
                  └─────► Markdown 报告 + 归档 ◄─────┘
```

每个环节都可插拔：**LLM provider**、**Skills** 归类逻辑、
**报告输出**（Markdown / PDF / HTML / Obsidian）。

想看时序图 + 每个模块的设计原因？看
[`docs/architecture.md`](docs/architecture.md)。
遇到问题？看 [`docs/troubleshooting.md`](docs/troubleshooting.md)。

---

## 要求

- **Windows 10 (1809+) 或 Windows 11**
- ~2 GB 空闲磁盘（Python + FFmpeg + ML 模型缓存）
- 选其一作为 LLM：
  - **GitHub Copilot CLI**（默认，免 API key）— `winget install GitHub.cli` + `gh extension install github/gh-copilot`
  - **OpenAI** 或 **Azure OpenAI** API key（在 Settings 中配置）

---

## 项目状态

- 当前版本：**v0.9.1**（2026-06-09 发布）
- **470 / 470 pytest 通过** · ruff 清洁
- CI 在 Windows + Python 3.11 / 3.12 上绿
- 完整发布历史：[`docs/CHANGELOG.md`](docs/CHANGELOG.md)
- 想贡献或扩展？读 [`docs/DEVELOPING.md`](docs/DEVELOPING.md)
- 安全问题：[`.github/SECURITY.md`](.github/SECURITY.md)

## 许可证

MIT — 见 [`LICENSE`](LICENSE)。第三方许可见 [`NOTICE`](NOTICE)。
主要运行时依赖：

- **PySide6 / shiboken6** — LGPL-3.0 (动态链接)
- **Microsoft Fluent UI System Icons** — MIT (打包的 SVG)
- **ChromaDB, sentence-transformers, faster-whisper, RapidOCR** — Apache 2.0 / MIT
- **mss, pynput, hidapi, ffmpeg** — Apache 2.0 / LGPL (仅子进程调用)
