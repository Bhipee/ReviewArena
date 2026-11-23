# COMP6708 Assignment 3 — Mini Demo Proposal

## ReviewArena：基于“批评触发写法”检索的多智能体模拟审稿与 Rebuttal 系统

> 一句话：从约 10 万条 OpenReview 公开审稿意见中，抽取出“**论文里的哪种写法会引来哪种批评**”，以此为依据模拟多位审稿人与 Area Chair（AC），并把每条批评回到用户论文原文中核实。博士生在投稿前用它自查，在收到审稿意见后用它起草 rebuttal；导师用它快速把关。全程 training-free。

---

## 1. 问题与场景

| 角色 | 痛点 |
|---|---|
| 博士生（投稿前） | 不知道审稿人会从哪里下手；自己看自己的论文有盲区 |
| 博士生（收到审稿意见后） | rebuttal 时间短（约 1 周），要逐条回复、判断哪些要补实验 |
| 导师 | 同时带多个学生投稿，没时间逐篇模拟审稿、逐条改 rebuttal |
| 直接用 ChatGPT 审稿 | 意见泛泛（“建议增加实验”），**没有依据**、**不针对论文原文**，还会编造“缺少和 X 的比较”中的 X |

**关键观察（也是本项目的创新点）**：**相似论文 ≠ 相似问题。** 审稿批评往往是被论文中某种**具体写法**触发的（如“声称高效但只报 FLOPs”“3 个模块但没有逐模块消融”），与论文主题关系不大。因此检索单元应该是“**批评点 + 触发它的原文**”，而不是“整篇相似论文”。

---

## 2. 数据：OpenReview 审稿语料（大规模知识库）

| 内容 | 规模（估计） | 来源 |
|---|---|---|
| ICLR 2018–2025 投稿（含被拒论文）的元数据、审稿意见、作者回复、AC 元评审、最终决定 | 约 3.5 万篇论文、10 万+ 条审稿意见 | `openreview-py` API（公开数据） |
| NeurIPS 2021+ 公开审稿意见（可选补充） | 数万条 | 同上 |
| 论文 PDF（用于定位触发原文） | 只取子集，约 3,000–5,000 篇 | OpenReview PDF |

**时间划分（防止信息泄漏）**：知识库只用 **2018–2023**；**2025** 的论文作为测试集与演示样例。

### 2.1 离线处理流水线

```
OpenReview API ──► 原始 reviews / rebuttals / decisions (JSONL, Parquet)
        │
        ▼  ① 原子批评抽取（批量 LLM，可用本地 vLLM + Qwen 降成本）
  每条 review → 若干条原子批评:
  { critique_text, category, target_section, severity(1-3),
    quoted_span(审稿人引用的原文), resolved_after_rebuttal, paper_decision }
        │
        ▼  ② 触发原文定位
  用 quoted_span / 审稿人提到的章节、表格编号 → 在 PDF 中做模糊匹配 → trigger_text + 页码
        │
        ▼  ③ 批评类型归纳
  对 critique 嵌入后聚类 → LLM 命名 → 约 50–80 种批评类型（taxonomy）
        │
        ▼  ④ 建索引
  • 向量库 A：trigger_text 嵌入（主索引，“写法 → 批评”）
  • 向量库 B：critique_text 嵌入（用于去重、评测匹配）
  • 统计表（DuckDB）：P(批评类型 | 论文类型, claim 类型, 年份, 是否录用)
```

**成本控制**：全部 10 万条 review 只做①的低成本版本（批评类型 + 严重程度），用于统计先验；②的触发原文定位只在有 PDF 的子集上做。

---

## 3. 系统架构

```
┌───────────────────────────── Streamlit UI ─────────────────────────────┐
│ ①上传 PDF + 选目标会议   ②三位审稿人并排流式输出   ③证据面板（PDF 高亮） │
│ ④AC 元评审 + 录用概率    ⑤Rebuttal 工作台         ⑥批评类型统计看板      │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                       Orchestrator（LLM tool calling）
     ┌──────────────┬──────────────┼──────────────────┬──────────────────┐
     ▼              ▼              ▼                  ▼                  ▼
 Paper Parser   ReviewKB MCP    Scholar MCP       Skill Loader      Agents
 (section/claim  Server         Server            (按目标会议        Reviewer×3
  切分, 页码)    search_triggers (Semantic Scholar  加载 SKILL.md)    AC
                 critique_stats  / arXiv：查文献    iclr-reviewer    Verifier
                 similar_context 是否存在、新颖性)  neurips-reviewer  Rebuttal
                                                   area-chair
                                                   rebuttal-writer
```

### 3.1 审稿主流程（核心算法）

1. **解析与 claim 抽取**：将 PDF 切分为 section；用 LLM 抽取论文的**主张**（SOTA、高效、可泛化、理论保证……）和**设定**（数据集、baseline、模块数、评测方式）。
2. **触发检索**（解决“相似论文 ≠ 相似问题”）：
   - 每个片段 / 每条 claim → 在向量库 A 中检索相似的 trigger_text → 取回对应的历史批评；
   - 与统计先验融合打分：`score = α·sim(trigger) + β·P(类型 | claim, 论文类型) + γ·severity`；
   - 按批评类型去重，得到约 15–25 条**候选批评（假设）**。
3. **领域背景（相似论文的正确用法）**：相似论文只用来获取“该领域常用的数据集 / baseline”，并通过 Scholar MCP 查同期工作，用于判断“缺少哪些比较”和新颖性。
4. **核实（Verifier agent）**：逐条候选批评回到用户论文中查证（包括附录）：
   - 成立 → 保留，附**用户论文原文 + 页码**作为证据，同时附**历史依据**（某篇 ICLR 2022 论文因类似写法被这样批评）；
   - 已处理 → 丢弃，在 UI 中列为“已检查，不适用”（可展开查看原因）；
   - 涉及外部文献（“缺少和 X 的比较”）→ 调 Scholar MCP 确认 X 真实存在且时间早于投稿。
5. **多审稿人**：3 个 Reviewer agent 分到不同的已核实批评，并带有不同人设（理论严格型 / 实验挑剔型 / 写作与表达型），按目标会议的 skill 输出官方格式的审稿意见和评分。
6. **AC 元评审**：AC agent 汇总 3 份意见，写 meta-review；录用概率由“已核实批评的类型与严重程度”对照历史统计（DuckDB 中各类批评与录用率的关系）给出，**而不是让 LLM 直接拍一个数**。

### 3.2 Rebuttal 流程

1. 用户粘贴真实收到的审稿意见 → 拆成原子批评并分类；
2. 对每条批评，从知识库中检索**同类批评的历史 rebuttal**，并统计哪些回应方式之后被标记为“已解决”（`resolved_after_rebuttal`）；
3. `rebuttal-writer` skill 生成逐条回复草稿，分为三类：可以直接澄清 / 需要补实验 / 建议接受并修改；
4. 输出“**补实验清单**”（按优先级和预估工作量排序）和可直接粘贴的 Markdown 回复。

### 3.3 四种技术在系统中的位置

| 技术 | 用途 | 选择理由 |
|---|---|---|
| **RAG** | 触发写法检索 + 统计先验 + 历史 rebuttal 检索 | 审稿意见必须有依据；新增会议数据只需重新入库，无需训练 |
| **MCP** | 自建 `ReviewKB` server（审稿知识库）+ `Scholar` server（Semantic Scholar / arXiv） | 知识库以标准协议暴露，也能直接接入 Claude Desktop 等客户端；文献查询保证引用真实 |
| **Agent Skills** | `iclr-reviewer` / `neurips-reviewer` / `area-chair` / `rebuttal-writer` / `critique-verifier` | 各会议的审稿表格和评分标准不同，按需加载（渐进式披露），换会议只需新增一个 SKILL.md |
| **多智能体** | 3 位 Reviewer + AC + Verifier | 模拟真实审稿的多视角与汇总过程；Verifier 专门负责降低误报 |

---

## 4. 技术栈

| 模块 | 选型 |
|---|---|
| LLM | 支持 tool calling 的 API（Claude / GPT / Qwen / DeepSeek 均可）；离线批量抽取可用本地 vLLM + Qwen 以降低成本 |
| 数据采集 | `openreview-py`；存储为 Parquet，用 DuckDB 做统计分析 |
| PDF 解析 | PyMuPDF（保留页码与坐标，用于原文高亮）；可选 GROBID 做章节切分 |
| 嵌入与向量库 | `bge-m3` 或 API embedding；Chroma / Qdrant（本地） |
| 聚类 | UMAP + HDBSCAN，LLM 为每个簇命名 |
| MCP | Python `mcp` SDK（FastMCP） |
| 多智能体编排 | 自写 asyncio 并发调用 3 位 Reviewer（或使用 LangGraph） |
| UI | Streamlit（多列并排流式输出、`streamlit-pdf-viewer` 高亮、Plotly 图表） |

---

## 5. 五分钟现场演示脚本

| 时间 | 现场操作 | 观众应该看到 |
|---|---|---|
| 0:00–0:30 | 1 张幻灯片：痛点 +“相似论文 ≠ 相似问题” | 问题和核心想法 |
| 0:30–0:50 | 打开**批评类型看板** | 10 万条审稿意见归纳出的 Top 批评类型，以及它们和录用率的关系（展示大规模数据处理能力） |
| 0:50–2:20 | 上传一篇 ICLR 2025 论文（测试集，模型未见过其审稿意见），选“ICLR” | 3 位审稿人并排流式输出；点任意一条批评 → 左侧 PDF 高亮用户论文原文，右侧显示历史依据；“已检查，不适用”列表展示 Verifier 拦下的误报 |
| 2:20–2:50 | 一条“缺少和 X 的比较” | 界面日志显示 MCP 调用 `scholar.search(...)`，确认 X 真实存在 |
| 2:50–3:20 | AC 元评审 | 元评审 + 录用概率；旁边揭晓**这篇论文真实的分数和决定**作对比 |
| 3:20–4:20 | 切到 Rebuttal 工作台，粘贴该论文的一条真实审稿意见 | 逐条回复草稿 + 补实验清单，附“同类批评历史上哪种回应最有效” |
| 4:20–5:00 | 1 张幻灯片：评测结果 + 局限 | 见第 6 节 |

**保险措施**：演示论文的完整结果预先缓存（UI 有“回放”开关）；现场优先实时运行，若超过 60 秒或接口出错，立即切换到缓存结果；另备一段完整录屏。

---

## 6. 评测设计

**测试集**：ICLR 2025 中随机抽取 50 篇（录用、被拒各半），知识库只用 2018–2023 年的数据。

**对比方法**：

| 方法 | 说明 |
|---|---|
| A. 纯 LLM | 同一个 LLM 直接读论文写审稿意见 |
| B. 整篇相似论文 RAG | 检索主题最相似的 5 篇论文的审稿意见作为参考 |
| C. 触发检索（无核实） | 本方法去掉 Verifier |
| **D. ReviewArena** | 触发检索 + 统计先验 + 核实 |

**指标**：

| 指标 | 计算方式 |
|---|---|
| 真实问题召回率 | 测试论文的真实审稿意见同样拆成原子批评；生成的批评与真实批评用 LLM 判定是否匹配，计算召回率 |
| 精确率 / 误报率 | 生成的批评中有多少与真实批评匹配；另人工抽查 50 条，判断“即使真实审稿人没提，这条批评是否成立” |
| 分数相关性 | 模拟平均分与真实平均分的 Spearman 相关系数 |
| 录用预测 | 录用概率的 AUC |
| 引用真实性 | “缺少和 X 的比较”中 X 真实存在的比例（A 对比 D） |

**预期结论**：D > C > B ≈ A。B 与 A 接近即可说明“相似论文 ≠ 相似问题”；C 到 D 的提升说明 Verifier 能有效降低误报。

**LLM 判定的可信度**：抽 100 对由两名组员独立人工标注，报告 LLM 判定与人工判定的一致率（Cohen's κ）。

---

## 7. 四人分工

| 成员 | 角色 | 具体任务 | 交付物 |
|---|---|---|---|
| **A** | 数据工程 | OpenReview 抓取（2018–2025）；PDF 子集下载与解析；原子批评批量抽取；触发原文定位；聚类得到批评类型；DuckDB 统计表 | `data/`（Parquet）、`pipeline/`、批评类型表、看板所需统计数据 |
| **B** | 检索与核实 | 论文 section / claim 抽取；触发检索与打分融合；Verifier；`ReviewKB` MCP server；为评测提供方法 B / C / D 的统一接口 | `retrieval/`、`verifier.py`、`mcp_reviewkb_server.py` |
| **C** | 智能体与界面 | 3 位 Reviewer + AC + Rebuttal 智能体编排；5 个 SKILL.md；`Scholar` MCP server；Streamlit 界面（并排流式输出、PDF 高亮、看板、Rebuttal 工作台）；缓存回放 | `agents/`、`skills/`、`mcp_scholar_server.py`、`app.py`、`run.sh` |
| **D** | 评测、幻灯片与主讲 | 构建测试集；运行 A / B / C / D 四种方法；LLM 判定 + 人工标注一致率；出图；幻灯片（6–8 页）；演示台词与彩排；挑选演示用论文 | `eval/`、结果图表、`Assignment3-GroupX.pptx`、演示脚本 |

**现场分工**：D 主讲，C 操作界面，A / B 负责回答数据与算法方面的提问。

### 接口约定（第一天先定好，各人可并行开发）

```python
# A → B：知识库记录（Parquet / 向量库 metadata）
Critique = {id, paper_id, year, venue, category, target_section, severity,
            critique_text, trigger_text, trigger_page, resolved, decision}

# B → C
retrieve_candidates(paper: ParsedPaper, venue: str, k=20) -> list[Candidate]
verify(paper: ParsedPaper, cand: Candidate) -> {status: "valid"|"addressed"|"external",
                                                evidence: [{text, page}], reason}

# C → UI / D
run_review(pdf_path, venue, method="D") -> {reviews: [...], meta_review, accept_prob,
                                            rejected_candidates, tool_logs}
run_rebuttal(paper, review_text) -> {responses: [...], experiment_todo: [...]}
```

D 在评测中通过 `method` 参数切换 A / B / C / D，所以 B、C 实现时要保证四种方法共用同一套代码路径。

---

## 8. 时间表（11/23 – 11/25）

| 时间 | A | B | C | D |
|---|---|---|---|---|
| 11/23 下午 | 跑通 OpenReview 抓取，开始全量下载 | PDF 解析 + claim 抽取 | UI 骨架（假数据）+ Skill 文件 | 确定测试集，下载测试论文与真实审稿意见 |
| 11/23 晚 | 原子批评批量抽取（后台跑通宵） | 检索打分 + Verifier 原型 | Reviewer / AC 编排 + Scholar MCP | 写评测脚本与 LLM 判定提示词 |
| 11/24 上午 | 聚类得到批评类型 + DuckDB 统计 | ReviewKB MCP + 接入真实数据 | 接入 B 的接口，Rebuttal 工作台 | 幻灯片初稿；跑方法 A / B |
| 11/24 下午 | 看板数据；协助调试 | 调参（α, β, γ） | PDF 高亮、缓存回放、录屏 | 跑方法 C / D，人工标注，出图 |
| 11/24 晚 | **全员彩排 3 遍，严格计时 5 分钟；冻结代码** | | | |
| 11/25 | 现场演示 | | | |

**降级方案**（按优先级砍功能，保证核心可演示）：
1. 去掉 NeurIPS 数据，只用 ICLR；
2. 触发原文定位只做 1,000 篇论文；
3. Rebuttal 工作台只保留逐条回复，去掉补实验清单；
4. 评测缩小到 20 篇。

核心不可砍：触发检索 + Verifier + 3 位审稿人 + 与真实分数的对比，因为这是“相似论文 ≠ 相似问题”这一卖点的证据。

---

## 9. 风险与对策

| 风险 | 对策 |
|---|---|
| 10 万条意见批量抽取的 token 成本高 | 全量只做类型分类（短提示、便宜模型或本地 vLLM）；细粒度抽取只做 PDF 子集 |
| OpenReview API 限速 | 早启动、断点续传；先抓 ICLR 2020–2023 保证核心数据 |
| 审稿人引用的原文难以定位 | 以模糊匹配 + 章节 / 表格编号兜底；定位失败时退回用批评文本本身做检索 |
| LLM 可能在训练中见过测试论文的公开审稿意见 | 测试集用最新年份；幻灯片中如实说明这一局限；方法 A 也受同样影响，对比仍公平 |
| 现场运行慢（3 位审稿人 + 核实） | asyncio 并发；流式输出；缓存回放兜底 |
| 现场网络 / API 故障 | 缓存回放 + 录屏 |

---

## 10. 伦理与合规

- 数据来自 OpenReview **公开**的审稿意见，仅用于研究与教学。
- 定位为**作者自查和 rebuttal 辅助工具**。多数会议禁止审稿人把保密投稿上传给 LLM，因此**不应**用于替代真实审稿，界面中会给出提示。
- 录用概率仅供参考，并展示其依据（历史统计），避免学生过度依赖一个数字。

---

## 11. 预期影响

- **博士生**：投稿前发现可能被批评的写法与缺失实验；rebuttal 阶段把逐条整理的时间从几天缩短到几小时。
- **导师**：几分钟内获得带原文证据的审稿要点，集中精力判断真正关键的问题。
- **研究价值**：“批评类型 × 触发写法 × 录用率”的统计本身就是对 ML 顶会审稿规律的一份数据分析；“相似论文 ≠ 相似问题”的对比实验为审稿辅助类 RAG 系统提供了检索单元设计上的依据。
- **可扩展**：新增会议只需抓取数据并新增一个 SKILL.md；`ReviewKB` 以 MCP 形式提供，可被任何支持 MCP 的客户端调用。
