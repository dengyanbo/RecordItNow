# 关注点（PoI）

> 让被动记录变成按主题组织的报告。

## 什么是 PoI？

PoI 是你希望 RIN **按它来归组 captures** 的对象。它可以是项目、客户、论文、团队、代号，也可以是你频繁协作的人。

当 RIN 分析新的 capture 时，会同时查看 OCR 文本、音频转写、以及摘要。如果命中了某个 PoI，这条 capture 就会被挂到该
PoI 的 bucket 下。这样一来，报告不再只是按时间堆在一起，而是可以先按主题分段。

你可以把 PoI 理解成 RIN 里的个人归档轴线：

- 「把这周和 Project Atlas 有关的内容放一起」
- 「日报按客户整理，而不是按时间流水账」
- 「发布周只看我关心的几个工作流」

PoI 更适合 **有名字的主题**。如果你的工作核心是工单号、事故号、Case ID 这类稳定标识，内置的 `support_ticket`
skill 依然更合适。两者也可以同时启用。

## 建立 PoI 的三种方式

不想手改 TOML 也没关系。RIN 给了三条常用路径：

1. **向导** —— 完成 RIN 初始设置后，PoI 向导会自动出现一次。它会带你声明几个关注点、跑一次 discovery、
   再确认哪些内容应该长期跟踪。

2. **Settings → Topics & PoIs** —— 这是日常主入口。你可以随时新增、编辑、暂停、归档、接受建议、拒绝噪音，
   然后保存。

3. **CLI：按你自己的节奏运行 discovery** —— `python -m rin poi-discover --days 14` 会从最近 N 天
   captures 中挖候选 PoI。你可以在 Settings 里点 **Discover now…**，也可以自己手动跑命令，甚至用 Task
   Scheduler 定时。注意：RIN **不会** 自动帮你周期性发现。

核心原则只有一句：**discovery 只负责建议，最终由你决定。** 在你接受之前，候选项不会变成真正启用的 PoI。

## 快速上手

最简单的方式是先手动加一个 PoI，然后立刻看日报是否按它分组。

1. 打开 **Settings → Topics & PoIs**。
2. 点击 **Add manually**。
3. 输入一个短而稳定的名字。比如 `Project Atlas`、`Northwind`、`Fulfillment rewrite`。
4. 如果名字不够直观，再补一条 description。这既方便你自己回看，也能让可选的 LLM judge 更好理解上下文。
5. 填一到多个 **keywords**。先从你屏幕上最常见、最容易命中的词开始。
6. 如果同一个主题有多个叫法，给它补上 **aliases**。比如 `Atlas rollout`、`fulfillment rewrite`。
7. 只有在主题本身带稳定 ID 时，才建议写 **regex**。比如 `JIRA-\d+`、`GH-\d+`、`INC\d{7}`。
8. 决定要不要启用 **LLM judge**。如果这个主题本身就很好匹配，先关着更省钱。
9. 点击 **Save**。
10. 触发一次明确提到该 PoI 的 capture。
11. 不想等调度器的话，立刻运行 **Analyze now**。
12. 打开 **Reports**，生成今天的日报。
13. 确认里面出现了 `## <PoI 名称>` 段落。

> [截图占位：Settings → Topics & PoIs 标签页]
>
> [截图占位：Add manually 表单]
>
> [截图占位：按 PoI 分组的日报]

一开始先记住三条经验：

- `name` 最好就是你愿意拿来当报告小节标题的名字。
- 稳定 ID 放 `regex`，人能读懂的名字放 `name`。
- 先收窄再放宽。宽泛的 PoI 比狭窄的 PoI 更难清理。

如果你完全没把握，先建 2 到 3 个 PoI 就够了。这样 reports 更好读，候选建议也更容易判断。

## 四种匹配策略

每个 PoI 都可以混合使用 keywords、regex、aliases 和可选的 LLM
judge。大多数人从 keywords + aliases 开始；有稳定 ID 时再加
regex；只有主题本身很模糊时才需要打开 judge。

### 1）Keywords

Keywords 是大小写不敏感的子串匹配，便宜、快速、完全本地。适合
名字本身就很明确的主题，比如 `atlas` 或 `fulfillment rewrite`。
像 `api`、`meeting` 这种过泛的词，最好配合 aliases 或 judge 一起用。

### 2）Regex

Regex 适合稳定标识，比如 `JIRA-\d+`、`GH-\d+`、`INC\d{7}`、
`CASE\d{6,8}`。当上下文说法会变，但编号本身不变时，regex 往往是
最强信号。

### 3）Aliases

Aliases 是同一个 PoI 的其他叫法，例如缩写、代号、改名前后的名称，
或客户简称。`Project Atlas` 既可以保留正式名字，也能顺便匹配
`atlas rollout`、`fulfillment rewrite` 这类说法。

### 4）LLM judge（可选）

当 `llm_judge = true` 时，RIN 会让已配置的 provider 判断某条
capture 是否真的和该 PoI 有关。它适合处理语义型、模糊型场景。
Keywords、regex、aliases 都不额外花钱；judge 可能会消耗 tokens，
而 `llm_judge_max_chars` 会限制送出的文本量。

### 实际匹配顺序

可以把 `topic` skill 理解成：先 regex，再 keywords / aliases，最后才
是可选的 judge。这样大部分情况都能保持低成本、可预测。

## Discovery（候选发现）

Discovery 会把最近一段时间的历史内容转成 **候选 PoI**，但不会自动
启用任何主题；它只负责把值得你审查的建议提出来。

你可以从下面几处触发它：

- **Settings → Topics & PoIs → Discover now…**
- PoI 向导
- `python -m rin poi-discover --days N`

Discovery 主要挖四类信号：

- **Regex 挖掘** — 在多条 capture 里重复出现的机器型 ID
- **Domain 挖掘** — OCR URL 里反复出现的 hostname
- **Phrase 挖掘** — 类似 `Project Atlas` 这样的重复 Title Case 短语
- **LLM batch** (`--use-llm`) — 对抽样摘要做一次模型抽取，补足本地
  规则难以发现的命名实体或工作流

CLI 默认是 dry-run，会直接打印建议。加上 `--persist` 后，建议会写入
`poi_candidates`，供你稍后在 UI 里审核。候选状态有 `pending`、
`accepted`、`rejected`、`merged`；在你接受之前，它始终只是建议。

## 归档生命周期

PoI 只要还不断被新 capture 命中，就会保持活跃。通常有三种方式让它结束。

### 1）按天数自动归档

`archive_after_days` 的意思是：如果连续 N 天都没有新的 capture 提到它，就把它视为已完成，可以归档。

这对短期项目、客户升级、实验性工作流特别实用。

### 2）命中关闭短语

`closed_phrases` 允许你定义明确终点。一旦 capture 里出现这些短语，PoI 就可以立即关闭。

例如：

- `project closed`
- `shipped to prod`
- `migration complete`

如果你的工作本来就有固定收尾语，这一招会很准。

### 3）在 UI 里手动处理

有时你比文本更早知道这件事已经结束。这时可以直接在 **Settings → Topics & PoIs** 里手动归档或暂停。

实践上可以这样理解：

- 还可能恢复，就先暂停
- 确认结束了，再归档

## 报告

`reports.layout` 决定日报和周报怎么排。目前有三种模式：

- `chronological`
- `per_poi`
- `auto`

默认值是 `auto`，通常也是最推荐的选择。

行为很简单：

- 只要报告周期里命中过任意 PoI，就按 PoI 分组
- 如果一个 PoI 都没命中，就退回原来的时间顺序布局

简化示例：

```md
# Daily report — 2026-06-02

## Project Atlas
- Reviewed rollout checklist (`cap-41`)
- Fixed migration script (`cap-44`)

## Northwind
- Triage call notes (`cap-47`)
- Drafted follow-up email (`cap-49`)

## Everything else
- General admin and unrelated captures
```

这种布局特别适合你一天同时推进多个主题的时候。导出时也更像真正的状态汇报。

## TOML 参考

喜欢直接改 `config.toml` 的用户，可以参考下面的声明式配置。`topic` skill 不需要你写 Python。

```toml
[skills]
enabled = ["topic", "support_ticket"]
poi_wizard_seen = true

[skills.topic]
llm_judge_max_chars = 1200

[[skills.topic.topics]]
name = "Project Atlas"
description = "Internal rewrite of the fulfillment pipeline"
keywords = ["atlas", "fulfillment rewrite"]
regex = []
aliases = ["atlas rollout"]
llm_judge = true
archive_after_days = 21
closed_phrases = ["project closed", "shipped to prod"]
```

几个字段说明：

- `enabled` 控制 `topic` skill 是否启用
- `poi_wizard_seen = true` 表示一次性向导已经展示过
- `keywords`、`regex`、`aliases` 都是可选列表
- `llm_judge` 是按单个 topic 开关的
- `archive_after_days` 和 `closed_phrases` 共同决定何时关闭 bucket

如果你手动编辑 TOML，建议每个 PoI 用一个独立的 `[[skills.topic.topics]]` 表。这样 diff 更清晰，
后续合并也更容易。

## CLI

```bash
python -m rin poi-discover --days 14            # dry-run, regex/domain/phrase only
python -m rin poi-discover --days 30 --use-llm  # also use LLM batch (1 LLM call)
python -m rin poi-discover --days 30 --persist  # save results to poi_candidates table
```

实用提示：

- `--days` 用来控制回看窗口大小
- `--use-llm` 是可选且会产生 token 成本
- `--persist` 会把建议保存到 Settings 里可审核的候选表
- 需要的话可以把 `--use-llm` 和 `--persist` 一起用

## 常见问题

### 之后还能改 PoI 吗？

可以。打开 **Settings → Topics & PoIs**，选中对应主题后，名字、描述、keywords、aliases、
regex、归档规则都能继续改。PoI 本来就应该随着工作变化而迭代。

### 不开 LLM 能用吗？

完全可以。Keywords、regex、aliases、按 PoI 分组的报告、以及本地 discovery 都不依赖云端 LLM。
真正可选的只有：

- 单个 topic 的 `llm_judge`
- `poi-discover --use-llm`
- 以及你自己选用的摘要生成 provider

如果你想先走最省成本的路径，就从纯本地匹配开始。

### 隐私会受影响吗？

PoI 不会改变 RIN 的基本隐私模型。Captures、config、reports、SQLite 数据库默认都还是本地。只有你显式开启的
LLM judge 或 LLM discovery batch 才会把文本发给已配置 provider。如果这两个都关着，PoI 匹配就是本地完成。

### `topic` 和 `support_ticket` 可以一起用吗？

可以，而且很常见。`support_ticket` 负责刚性的 ticket ID，`topic` 负责更宽泛的项目、客户、人员、计划。同一条
capture 可以同时归到两个体系里。

### 怎么导出按 PoI 整理后的内容？

直接走正常的报告流程即可。生成日报或周报后，在 Reports 窗口里导出 Markdown、PDF、或 HTML。如果你配置了 Obsidian
vault，分组后的报告也会写进去。

## 另请参阅

- [docs/skills.md](skills.md) — 技能框架的底层说明（偏进阶）。
- [DEVELOPING.md](../DEVELOPING.md) — 面向开发者的文档。
- [CHANGELOG.md](../CHANGELOG.md) — 发布记录。
