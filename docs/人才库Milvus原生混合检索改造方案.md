# 人才库 Milvus 原生混合检索改造方案

> 文档状态：实施中（开发阶段单 Collection 方案）  
> 版本：v1.1  
> 更新日期：2026-07-13  
> 适用项目：`hr-backend`  
> 关联文档：[HR招聘智能对话助手需求与技术设计](HR招聘智能对话助手需求与技术设计.md)

## 1. 目标与范围

本改造面向候选人人才库检索，将当前仅支持稠密向量语义检索的能力，升级为由 **Milvus 单独完成** 的原生混合检索：

- 稠密向量检索负责语义匹配，例如“智能问答经验”召回做过 RAG、知识库问答的候选人。
- 原生 BM25 稀疏检索负责精确术语匹配，例如 `Python`、`FastAPI`、`Milvus`、职位名称和项目名。
- Milvus 在同一个 Collection 内通过 `hybrid_search` 融合两路结果。
- 可选 Reranker 对融合后的候选人进行二次排序。
- PostgreSQL 继续作为候选人业务事实源、数据权限复核和索引同步 Outbox 的存储，不参与关键词或语义召回。

本期重点是沉淀可复用的 Dense + Sparse + Fusion + Rerank RAG 骨架，而非单纯追求人才检索业务指标。

### 1.1 开发阶段约束

当前项目尚未上线生产环境，因此本期采用**单 Collection**设计，不引入生产迁移才需要的 v1/v2 双写、灰度比对和在线回滚机制。

最终只维护一个候选人检索 Collection：

```text
candidate_profiles
├─ dense_vector：语义检索
├─ sparse_vector：BM25 精确词检索
└─ 标量字段：权限和业务过滤
```

开发过程中已经创建的 `candidate_profiles_v1`、`candidate_profiles_v2` 仅作为本地实验产物；在统一初始化脚本完成后可以删除或忽略，不作为后续代码依赖。

### 1.2 非目标

本期不包含以下内容：

- 不接入 Elasticsearch、OpenSearch 或 PostgreSQL 全文检索作为额外召回源。
- 不改变候选人、职位、部门等业务表的权威归属。
- 不引入文档切片；当前仍保持“一名候选人一条可检索画像”。
- 不改变现有 HTTP 接口的入参与返回字段，避免前端和 HR Assistant Tool 同步大改。
- 不在第一版将 LLM 作为唯一 Reranker，先保留可关闭、可替换的重排接口。
- 不实现生产环境的双写、灰度、自动回滚和多版本 Collection 管理。

## 2. 当前实现与改造原因

### 2.1 当前代码路径

| 职责 | 当前实现 | 说明 |
| --- | --- | --- |
| Collection 初始化 | `scripts/init_milvus.py` | 已收敛为唯一的 `candidate_profiles`，包含稠密索引、BM25 Function 与稀疏索引。 |
| 画像与 Outbox | `services/candidate_search_profile_service.py`、`models/candidate_search.py` | PostgreSQL 保存脱敏画像快照和待同步事件。 |
| 索引同步 | `services/candidate_indexing_service.py` | 生成 Embedding 后写入 Milvus。 |
| 检索 | `services/talent_search_service.py` | 当前仅调用 `MilvusClient.search(... anns_field="dense_vector")`。 |
| 权限复核与详情补全 | `repository/candidate_repo.py` | 根据召回 ID 读取最新候选人资料并复核可见范围。 |

当前单路稠密检索的核心字段是：

```text
candidate_id + profile_text + dense_vector + 权限过滤字段
```

它能完成“语义相似”的召回，但对技能名、框架名、证书名、职位名等精确词的稳定命中不足。

### 2.2 为什么不使用 PostgreSQL / ES 作为混合召回源

本项目的混合检索统一使用 Milvus，原因如下：

1. 一个查询只需进入一个检索引擎，过滤条件、Top K、融合策略和检索日志边界更清晰。
2. Milvus 原生支持 BM25 稀疏检索、稠密检索及 `hybrid_search` 融合，不需要维护两套召回结果和分数归一化逻辑。
3. 该方案能练习完整的 Dense + Sparse + Fusion + Rerank RAG 架构，后续可复用于知识库、岗位库等场景。
4. PostgreSQL 仍执行其更适合的职责：事务、业务一致性、权限事实校验、画像快照和索引事件。

## 3. 目标架构

```text
候选人新增 / 更新
        │
        ▼
PostgreSQL 业务表 ──► 候选人脱敏画像 ──► candidate_index_outbox
                                             │
                                             ▼
                                  CandidateIndexingService
                                  ├─ 生成 dense_vector
                                  └─ Upsert profile_text + dense_vector
                                             │
                                             ▼
                         Milvus candidate_profiles
                         ├─ dense_vector：Embedding 语义检索
                         ├─ sparse_vector：Milvus BM25 自动生成
                         └─ 标量字段：权限及业务过滤

HR 查询 ──► TalentSearchService
              ├─ 根据模式执行 dense / sparse / hybrid
              ├─ 可选 Reranker
              └─ PostgreSQL 权限复核与详情补全
```

### 3.1 职责边界

| 层级 | 负责内容 | 不负责内容 |
| --- | --- | --- |
| `services/candidate_search_profile_service.py` | 构建脱敏、可检索的候选人画像文本和版本号 | 不生成向量，不直接查询 Milvus。 |
| `services/candidate_indexing_service.py` | 消费 Outbox、生成稠密向量、写入唯一的 `candidate_profiles` | 不决定候选人业务权限。 |
| `rag/retrievers/` | 构造 Milvus 检索请求、转换通用命中结果 | 不读取 SQLAlchemy 业务实体。 |
| `rag/rerankers/` | 对候选人画像和查询重排 | 不拥有业务数据，不直接修改候选人。 |
| `services/talent_search_service.py` | 编排检索、权限过滤、详情补全和响应组装 | 不实现具体向量数据库 API 细节。 |
| PostgreSQL Repository | 业务事实、可见范围复核和候选人详情加载 | 不作为混合检索召回源。 |

## 4. 单 Collection 设计

### 4.1 Collection 初始化策略

Milvus 的 BM25 Function、分析器和稀疏向量字段必须在 Collection 创建时定义，不能对旧的纯稠密 Collection 原地补齐。

由于当前仍是开发阶段，直接创建统一的 `candidate_profiles` 即可：

```text
旧实验 Collection：candidate_profiles_v1 / candidate_profiles_v2
最终开发 Collection：candidate_profiles
```

本地若存在旧实验数据，可在确认不需要保留后删除旧 Collection 并执行全量回灌；不需要双写或回滚逻辑。

### 4.2 Schema

| 字段 | 类型 | 用途 |
| --- | --- | --- |
| `candidate_id` | `VARCHAR`，主键 | 与 PostgreSQL 候选人 ID 对齐。 |
| `profile_text` | `VARCHAR`，开启 `enable_analyzer` | 脱敏画像原文，是 BM25 的输入。 |
| `dense_vector` | `FLOAT_VECTOR` | 由 Embedding 模型生成，用于语义检索。 |
| `sparse_vector` | `SPARSE_FLOAT_VECTOR` | 由 Milvus 的 BM25 Function 自动生成。 |
| `department_id` | `VARCHAR` | HR 部门范围过滤。 |
| `position_id` | `VARCHAR` | 职位过滤。 |
| `creator_id` | `VARCHAR` | 普通用户的数据范围过滤。 |
| `status` | `VARCHAR` | 候选人状态过滤。 |
| `profile_version` | `INT64` | 防止旧 Outbox 覆盖新画像。 |
| `embedding_model` | `VARCHAR` | 记录生成稠密向量的模型。 |
| `updated_at` | `INT64` | Milvus 侧排障和数据新鲜度判断。 |

### 4.3 中文分析器与画像格式

候选人资料主要为中文，应对 `profile_text` 启用 Milvus 中文 `jieba` 分词器，并保留英文、数字和常用技术符号的可检索性。

画像文本保持字段标签，示例：

```text
应聘职位：高级 Python 后端工程师
技能：Python、FastAPI、PostgreSQL、Redis、Milvus、RAG
工作经历：负责风控平台后端服务与异步任务调度。
项目经历：搭建企业知识库问答系统，完成向量检索和重排序。
教育经历：计算机科学与技术本科。
```

字段标签有两个作用：提升稠密语义表达的稳定性，也让 BM25 能准确命中“技能”“项目经历”等语义明确的词段。

### 4.4 索引与 Function

- `dense_vector`：使用余弦相似度与自动索引配置。
- `sparse_vector`：创建适用于 BM25 的稀疏向量索引。
- `profile_text -> sparse_vector`：通过 Milvus 内置 `BM25` Function 自动处理；应用层不自行计算 BM25 稀疏向量。
- 所有字段和 Function 在 `scripts/init_milvus.py` 中集中声明，避免运行时隐式建表。

## 5. 查询、模式与排序设计

### 5.1 三种检索模式

检索模式仅改变 Milvus 的召回方式，不改变权限过滤、PostgreSQL 二次复核和接口返回格式。

| 配置值 | Milvus 调用 | 使用场景 |
| --- | --- | --- |
| `dense` | `search(dense_vector)` | 验证纯语义召回，或查询表达较自然、词汇不固定的需求。 |
| `sparse` | `search(sparse_vector, BM25)` | 验证技术名、技能、职位名、证书等精确词召回。 |
| `hybrid` | `hybrid_search(dense + sparse + RRF)` | 默认目标模式，同时兼顾语义和精确词。 |

开发阶段通过环境变量切换模式：

```dotenv
# 可选值：dense、sparse、hybrid
TALENT_SEARCH_RETRIEVAL_MODE=hybrid
```

该配置只面向开发、测试和部署人员，不向普通前端用户开放。这样可以在同一套候选人数据上直接比较三种检索策略。

### 5.2 Hybrid 检索流程

以查询“找有 Python 后端和风控系统经验的候选人”为例：

1. `TalentSearchService` 校验 `query`、`top_k` 和当前用户身份。
2. 根据用户角色、部门、职位和状态生成同一份 Milvus 标量过滤表达式。
3. `dense` / `hybrid` 模式调用 Embedding 服务生成查询向量。
4. `dense` 模式查询 `dense_vector`。
5. `sparse` 模式将原始查询文本交给 `sparse_vector` 的 BM25 检索。
6. `hybrid` 模式创建两路检索请求并调用 `hybrid_search`，使用 RRF 融合。
7. 若启用 Reranker，使用 `query + profile_text` 对当前模式的候选集合重排。
8. 依据排序后的候选人 ID 从 PostgreSQL 获取最新资料并做最终可见性复核。
9. 返回维持当前接口兼容的候选人卡片、分数和画像摘要。

### 5.3 初始参数建议

| 参数 | 初始值 | 目的 |
| --- | --- | --- |
| `TALENT_SEARCH_DENSE_RECALL_K` | 30 | 给语义检索保留足够候选池。 |
| `TALENT_SEARCH_SPARSE_RECALL_K` | 30 | 给精确词匹配保留足够候选池。 |
| `TALENT_SEARCH_HYBRID_LIMIT` | 30 | RRF 融合后的候选池上限。 |
| `top_k` | 10 | 对外返回默认数量，继续沿用现有约束。 |
| `TALENT_SEARCH_RERANK_ENABLED` | `false` | 首版先验证融合检索链路，再增加模型依赖。 |

### 5.4 Reranker 的定位

Reranker 是排序阶段，不是新的数据源，也不影响“混合召回全部基于 Milvus”的原则。它可应用于 `dense`、`sparse`、`hybrid` 任一模式。

第一版定义稳定接口：

```python
class Reranker(Protocol):
    async def rerank(self, *, query: str, hits: list[RetrievalHit]) -> list[RetrievalHit]:
        """按照查询与候选人画像的相关性返回重新排序后的命中列表。"""
```

首版实现 `NoopReranker`，保证关闭重排时调用链稳定；启用时调用专用 Rerank 模型。

## 6. 文件级改造清单

| 阶段 | 文件 | 改造内容 | 状态 |
| --- | --- | --- | --- |
| 0 | `docs/人才库Milvus原生混合检索改造方案.md` | 维护方案与任务清单 | 已完成 |
| 1 | `settings/__init__.py`、`.env.example`、`rag/retrieval_types.py` | 通用检索配置与数据契约 | 已完成，待在阶段 2 收敛 Collection 命名 |
| 2 | `scripts/init_milvus.py` | 收敛为唯一 `candidate_profiles`，配置 Analyzer、BM25 Function、稀疏/稠密索引 | 已完成，待真实 Milvus 验证 |
| 3 | `services/candidate_indexing_service.py`、回灌脚本 | 唯一 Collection 的 Outbox 同步与历史候选人回灌 | 已完成，待真实 Milvus 验证 |
| 4 | `rag/retrievers/milvus_hybrid_retriever.py` | 封装 dense、sparse、hybrid 三种 Milvus 查询 | 已完成，待真实 Milvus 验证 |
| 5 | `services/talent_search_service.py` | 接入 Retriever、检索模式、权限复核和接口兼容 | 已完成，待真实 Milvus 验证 |
| 6 | `rag/rerankers/`、日志模块 | 可插拔 Reranker 与检索可观测性 | 已完成，待真实环境评测 |
| 7 | `tests/`、评测脚本与文档 | 自动化测试、人工评测集与运行说明 | 基础完成，待真实环境执行 |

## 7. 分步实施计划与验收条件

### 阶段 1：配置与通用数据契约（已完成）

**任务**

- [x] 增加稠密召回、稀疏召回、融合上限和 Rerank 开关配置。
- [x] 创建 `RetrievalHit`、`RetrievalRequest` 与 `RetrievalSource`。
- [x] 增加数据契约的基础单元测试。
- [x] 已移除版本化 Collection 配置，统一为 `MILVUS_CANDIDATE_COLLECTION=candidate_profiles`。

**验收**

- 设置缺失时可使用安全默认值启动。
- `RetrievalHit` 的单元测试覆盖序列化、去重和非法值。

### 阶段 2：统一创建候选人检索 Collection（已完成，待真实环境验证）

**任务**

- [x] 将 `scripts/init_milvus.py` 收敛为一个 `create_candidate_profile_collection()`。
- [x] 将唯一 Collection 名称统一为 `candidate_profiles`，移除 v1/v2 初始化函数和相关配置。
- [x] 为 `profile_text` 打开 Analyzer，配置中文 `jieba` 分词。
- [x] 增加 `sparse_vector` 和 `BM25` Function。
- [x] 创建稠密向量索引与 BM25 稀疏索引。
- [x] 新增 Collection Schema 的单元测试。
- [ ] 启动本地 Milvus 后，验证真实建表、Schema、Function 和索引。

**验收**

- 可通过 `python -m scripts.init_milvus` 重复执行，已有 `candidate_profiles` 不报错。
- `describe_collection` 能看到 `dense_vector`、`sparse_vector`、BM25 Function 和 Analyzer。
- 插入一条中文测试画像后，可使用原始文本完成 BM25 检索。

### 阶段 3：唯一索引同步与全量回灌（已完成，待真实环境验证）

**任务**

- [x] `CandidateIndexingService` 只向 `candidate_profiles` 写入 `profile_text` 和 `dense_vector`；不手工传入 `sparse_vector`。
- [x] 保留 `candidate_index_outbox` 的 `profile_version` 防止旧事件覆盖新画像。
- [x] 新建 `scripts/rebuild_candidate_milvus_index.py`，按稳定游标读取全部历史候选人；缺少画像时先生成脱敏画像。
- [x] 回灌脚本支持 `--dry-run`、`--batch-size`、`--changed-only` 与失败统计。
- [x] 删除 Outbox 事件时，只删除唯一的 `candidate_profiles` 中对应实体。

**验收**

- 更新候选人后，Outbox 能异步将最新画像写入唯一 Collection。
- 回灌脚本可重复执行，候选人 ID 不重复且版本正确。
- 画像中不出现手机号、邮箱、生日、原始简历路径等敏感字段。

### 阶段 4：Milvus 多模式 Retriever（已完成，待真实 Milvus 验证）

**任务**

- [x] 创建 `MilvusHybridRetriever`，接收 `RetrievalRequest` 并返回 `RetrievalHit`。
- [x] `dense` 模式使用 `dense_vector` 查询。
- [x] `sparse` 模式使用原始 query 和 `sparse_vector` 的 BM25 查询。
- [x] `hybrid` 模式使用 `AnnSearchRequest` 构造双路请求，并调用 `hybrid_search + RRFRanker`。
- [x] 三种模式使用相同的 Milvus 标量过滤表达式。
- [x] 对候选人 ID 去重，保持 Milvus 返回排序。

**验收**

- 给定“Python FastAPI 风控”，`sparse` 能稳定召回精确技术词命中。
- 给定“智能问答平台经验”，`dense` 能召回语义相近但关键词不同的资料。
- `hybrid` 同时包含两种信号的结果，且无权限候选人不会进入结果。

### 阶段 5：接入 TalentSearchService 与模式切换（已完成，待真实 Milvus 验证）

**任务**

- [x] 增加 `TALENT_SEARCH_RETRIEVAL_MODE=dense|sparse|hybrid` 配置，默认 `hybrid`。
- [x] `TalentSearchService` 改为依赖 `MilvusHybridRetriever`，根据模式选择检索路径。
- [x] 保留 `_build_milvus_filter` 作为检索前权限约束。
- [x] 保留 `CandidateRepo.list_visible_by_ids` 作为检索后权限复核和候选人详情补全。
- [x] 按 Retriever 返回的顺序组装 API 响应，避免 SQL 查询打乱排序。
- [x] 保持 `POST /talent-search/search` 与 HR Assistant Tool 契约兼容。

**验收**

- 修改 `.env` 的模式并重启服务后，可切换 dense、sparse、hybrid。
- PostgreSQL 不执行候选人全文 / 模糊检索，仅按 ID 批量加载和复核。
- 数据权限测试在超级管理员、HR、普通用户三类角色下均通过。

### 阶段 6：Reranker 与可观测性（已完成，待真实环境评测）

**任务**

- [x] 实现 `NoopReranker` 并作为默认实现。
- [x] 增加阿里云 DashScope 专用 Rerank 适配器，不改变 Retriever 接口；模型异常时自动降级到 Milvus 原始排序。
- [x] 在日志中记录检索模式、query 指纹、过滤字段摘要、召回/融合结果数、Rerank 耗时和最终 ID 列表。
- [x] 不记录完整简历、邮箱、手机号或模型密钥。
- [x] 为后续评测预留检索 trace ID。

**验收**

- 关闭 Rerank 时，结果直接来自当前检索模式。
- 打开 Rerank 时，最终结果数量、权限范围和接口契约不变。
- 单次检索可通过日志定位每个阶段的耗时与候选数量。

**专用 Rerank 配置**

```dotenv
TALENT_SEARCH_RERANK_ENABLED=true
TALENT_SEARCH_RERANK_PROVIDER=cohere_compatible
# Provider 表示 API 协议而非云厂商。默认协议兼容 qwen3-rerank、Cohere、Jina 等。
TALENT_SEARCH_RERANK_MODEL=qwen3-rerank
TALENT_SEARCH_RERANK_BASE_URL=https://dashscope.aliyuncs.com/compatible-api/v1/reranks
TALENT_SEARCH_RERANK_API_KEY=
```

`cohere_compatible` 使用顶层 `query/documents/results` 协议，是默认适配器；替换
云平台通常只需要修改 Base URL、Key 和模型名。目标服务确实要求阿里云原生
`input/parameters/output.results` 协议时，才设为 `dashscope_native`。例如使用已
开通的 `bge-reranker-v2-m3` 服务时，填写该服务的完整请求地址。`Qwen3-Reranker-
0.6B` 是开源模型检查点名称；阿里云托管 API 的模型标识为 `qwen3-rerank`，不应
将两者混用。

### 阶段 7：测试与评测（基础完成，待真实环境执行）

**任务**

- [x] 建立固定查询集，覆盖精确技能词、项目语义、权限过滤和空结果。
- [x] 对同一查询记录 dense、sparse、hybrid 的候选人 ID、排序和耗时，用于开发阶段比较。
- [x] 补齐 Schema、索引同步、Retriever、权限、Rerank 的自动化测试。
- [x] 更新运行说明与本方案状态。

**验收**

- 三种模式可在开发环境独立验证。
- 自动化测试覆盖索引创建、同步、召回、权限和错误处理。

### 7.1 本地评测运行说明

前提：本地 PostgreSQL、Milvus 和 Embedding 服务已可用；已执行 Collection 初始化和候选人全量回灌。使用不同角色的用户 ID 分别运行，可验证权限隔离。

```bash
# 先运行全部固定样本，结果仅打印到终端
uv run python -m scripts.evaluate_talent_search --user-id <用户ID>

# 仅运行一个样本，并将脱敏报告保存到本地文件
uv run python -m scripts.evaluate_talent_search \
  --user-id <用户ID> \
  --case-id acronym_rag \
  --output output/talent-search-evaluation.json
```

报告只包含样本 ID、模式、候选人 ID、分数、耗时和错误信息；不输出候选人姓名、完整画像或联系方式。

## 8. 测试任务清单

### 8.1 单元测试

- [x] `RetrievalHit` 去重和分数处理。
- [x] Collection Schema 中 Analyzer、BM25 Function 和双索引参数。
- [x] 稠密和稀疏 `AnnSearchRequest` 的字段、参数和过滤表达式一致性。
- [ ] RRF 融合结果的顺序转换。
- [x] `NoopReranker` 保持输入顺序。
- [ ] `TalentSearchService` 保持 Retriever 排序。
- [ ] `TalentSearchService` 对 PostgreSQL 返回的不可见候选人做剔除。
- [x] 画像文本的脱敏字段覆盖。

### 8.2 集成测试

- [ ] 创建 `candidate_profiles` 后检查 Schema、Function 和索引。
- [ ] 写入候选人画像后验证 dense、BM25 与 hybrid 三种查询。
- [ ] 中文“结巴分词”对技能、框架名和职位名的命中验证。
- [ ] Outbox 新增、更新、删除事件在唯一 Collection 的同步验证。
- [ ] 回灌脚本的幂等性验证。

### 8.3 人工验收查询集

| 查询 | 主要验证点 |
| --- | --- |
| `Python FastAPI Milvus` | `sparse` 模式下的精确技能词命中。 |
| `做过知识库问答或智能客服` | `dense` 模式下的语义召回。 |
| `有风控平台经验的后端工程师` | `hybrid` 模式的稠密和稀疏融合。 |
| `RAG` | 英文缩写、技术名分词与精确匹配。 |
| 指定职位和状态的查询 | Milvus 标量过滤。 |
| 不同 HR 用户相同查询 | 权限隔离与 SQL 二次复核。 |

## 9. 风险与处理策略

| 风险 | 影响 | 处理策略 |
| --- | --- | --- |
| BM25 Schema 不能原地添加 | 旧纯稠密 Collection 无法升级 | 开发环境直接创建统一的 `candidate_profiles` 并全量回灌。 |
| 中文专业术语分词不稳定 | 技术词召回下降 | 使用 `jieba`，后续维护领域词典并增加评测集。 |
| 稠密和稀疏分数不可直接比较 | 融合排序失真 | 首版采用 RRF，不自行线性拼接原始分数。 |
| Outbox 积压或失败 | Milvus 索引滞后 | 保留重试、失败记录和可重复回灌脚本。 |
| Reranker 增加耗时与成本 | 接口延迟变高 | 默认关闭，限制候选池和超时，降级到当前模式的原始结果。 |
| 敏感简历数据进入向量库 | 数据泄露风险 | 只从已脱敏 `profile_text` 建索引，测试中验证敏感字段缺失。 |

## 10. 完成定义

满足以下条件，视为本改造完成：

- 唯一的 `candidate_profiles` 已具备中文 Analyzer、BM25 稀疏向量和稠密向量。
- 候选人索引可通过 Outbox 增量同步和脚本全量回灌。
- 人才检索可以通过 `dense`、`sparse`、`hybrid` 三种模式运行，召回和融合均由 Milvus 完成。
- PostgreSQL 仅承担业务数据权威、权限复核和详情补全，不承担关键词召回。
- 接口、HR Assistant Tool 和权限行为与现有系统兼容。
- 有针对稠密、稀疏、融合、权限和 Rerank 的自动化测试及人工查询集。
