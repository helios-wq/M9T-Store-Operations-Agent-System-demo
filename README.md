# 连锁门店运营智能助手 Agent 系统

某连锁餐饮品牌全国 200+ 直营门店。店长/店员通过网页前端或企业微信向助手提问：查运营 SOP、报修设备、核对促销规则、查物料库存。助手基于 **自研 Agent 状态机（4节点条件路由）+ RAG + Function Calling** 实现端到端自助闭环。

## 🌐 在线演示

- **前端页面**：http://47.98.122.252
- **API 文档**：http://47.98.122.252/docs
- **健康检查**：http://47.98.122.252/healthz

> 演示服务器为 2核2G 轻量部署（MySQL + Redis + 内存向量库），LLM 在线模式已启用。

## ✨ 核心功能

| 功能 | 说明 |
|---|---|
| 💬 智能对话 | 自然语言提问，自动识别意图（报修/库存/促销/知识问答/转人工） |
| 🔧 报修工单 | 对话式报修，自动建单，状态机流转（已受理→已派单→维修中→已解决→已关闭） |
| 📦 库存查询 | 实时查询门店物料库存，低于补货线自动提醒 |
| 🎁 促销校验 | 核对促销活动规则、有效期、适用范围 |
| 📚 知识检索 | RAG 检索门店运营 SOP，支持口语化提问（同义词扩展 + 多路检索 + 重排） |
| 🔔 监控告警 | 错误率/P95 延迟超阈值自动飞书告警，Prometheus 指标暴露 |
| 📱 网页前端 | 三标签页（对话/报修/告警），响应式设计，手机浏览器直接用 |
| 🏢 企业微信 | 群机器人主动推送 + 回调被动回复，维修工群内指令推进工单状态 |

## 🏗️ 技术架构

```
前端（HTML/CSS/JS）
    ↓ Nginx 反代（80端口）
FastAPI（REST + SSE 流式）
    ↓
自研 Agent 状态机（4节点条件路由）
    ├─ 意图识别节点
    ├─ 知识检索节点（RAG: 向量+关键词 RRF 融合 + 重排）
    ├─ 工具执行节点（报修/库存/促销 Function Calling）
    └─ 结果输出节点
    双模式：LangGraph 在线执行 / 自研手动执行器（离线降级 + SSE 流式）
    ↓
存储层：MySQL（工单/日志持久化）+ Redis（会话缓存）+ 向量库（Milvus/内存降级）
    ↓
外部：DeepSeek LLM + 硅基流动 Embedding + 飞书/企微 Webhook
```

## 📁 项目结构

```
project1_store_agent/
├── app/
│   ├── main.py              # FastAPI 入口（REST + SSE）
│   ├── config.py            # 配置中心（.env 读取）
│   ├── db.py                # MySQL/SQLite 持久化 + 工单状态机
│   ├── schemas.py           # Pydantic 请求/响应模型
│   ├── session.py           # Redis/内存会话管理
│   ├── wecom.py             # 企业微信接入（回调 + 机器人推送）
│   ├── monitor.py           # 监控告警 + Prometheus 指标
│   ├── llm/client.py        # LLM 客户端（在线/离线双模式）
│   ├── agent/
│   │   ├── graph.py         # Agent 状态机编排（LangGraph/手动执行器双模式）
│   │   ├── nodes.py         # 意图识别/检索/工具/输出 4 节点
│   │   ├── state.py         # Agent 状态定义
│   │   └── tools.py         # 报修/库存/促销 3 个工具
│   ├── rag/
│   │   ├── chunker.py       # 结构化分块
│   │   ├── embedder.py      # 向量化（API/离线哈希）
│   │   ├── vector_store.py  # Milvus/内存向量库
│   │   ├── query_rewriter.py # 查询重写/同义词扩展
│   │   ├── reranker.py      # 重排器
│   │   └── retriever.py     # 多路检索 RRF 融合
│   └── eval/                # 评测集 + 评测脚本
├── data/
│   ├── gen_docs.py          # 生成 300+ 份样例门店文档
│   ├── raw_docs/            # 原始运营文档
│   └── index.json           # 向量索引（354 条 Chunk）
├── deploy/
│   ├── Dockerfile           # 应用镜像
│   ├── docker-compose.yml   # 完整版（Milvus + MySQL + Redis + Nginx）
│   ├── docker-compose.lite.yml # 轻量版（MySQL + Redis + 内存向量库，2核2G可用）
│   ├── nginx.conf           # Nginx 反代配置（SSE 支持）
│   └── html/                # 前端静态页面
├── scripts/
│   ├── build_index.py       # 构建向量索引
│   ├── init_db.py           # 初始化数据库
│   └── simulate_client.py   # 命令行对话模拟
├── tests/                    # 单元测试（33 passed）
├── docs/design.md            # 架构设计文档
├── requirements.txt
├── .env.example              # 环境变量模板（Key 已脱敏）
├── .gitignore
├── pytest.ini
└── README.md
```

## 🚀 快速开始（离线模式，无需任何 Key）

```bash
# 1. 克隆项目
git clone <your-repo-url>
cd project1_store_agent

# 2. 创建虚拟环境并安装依赖
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac
pip install -r requirements.txt

# 3. 生成样例文档并构建索引
python scripts/gen_docs.py
python scripts/build_index.py

# 4. 跑单元测试
pytest tests -q

# 5. 命令行模拟对话
python scripts/simulate_client.py

# 6. 启动 HTTP 服务
uvicorn app.main:app --reload --port 8000
```

访问 http://localhost:8000 查看前端页面，http://localhost:8000/docs 查看 API 文档。

## 🔧 配置说明

复制 `.env.example` 为 `.env`，填写真实配置：

| 配置项 | 说明 | 可选 |
|---|---|---|
| `LLM_API_KEY` | DeepSeek API Key | 不填则离线规则模式 |
| `EMBED_API_KEY` | 硅基流动 Embedding Key | 不填则离线哈希向量 |
| `MYSQL_*` | MySQL 连接配置 | 连不上自动降级 SQLite |
| `REDIS_*` | Redis 连接配置 | 连不上自动降级内存会话 |
| `MILVUS_*` | Milvus 向量库配置 | 连不上自动降级内存向量库 |
| `FEISHU_WEBHOOK` | 飞书群机器人 Webhook | 不填则跳过告警推送 |
| `WECOM_WEBHOOK` | 企业微信群机器人 Webhook | 不填则跳过工单推送 |

## 🐳 Docker 部署

### 轻量版（推荐，2核2G 服务器可用）

```bash
cd deploy
cp ../.env.example .env  # 填写真实配置
docker compose -f docker-compose.lite.yml up -d --build
```

启动 4 个容器：MySQL + Redis + App + Nginx，向量库自动降级内存模式。

### 完整版（含 Milvus 向量库）

```bash
cd deploy
cp ../.env.example .env
docker compose up -d --build
```

启动 7 个容器：etcd + MinIO + Milvus + MySQL + Redis + App + Nginx。

## 📊 性能指标

- **召回率@3**：98.75%（120 条评测集，离线哈希向量模式）
- **意图准确率**：100%
- **任务完成率**：100%
- **幻觉率**：0%
- **单元测试**：33 passed
- **工单状态机**：5 状态流转，不可跳级/回退，关闭需店长确认

## 📝 工单闭环流程

```
店长报修（对话/表单）
    ↓
工单创建（已受理）→ 企微维修群推送
    ↓
维修工派单（已派单）→ 企微群推送（含故障描述）
    ↓
维修工接单（维修中）
    ↓
维修完成（已解决）
    ↓
店长确认（已关闭）
```

维修工可在企微群内回复「RX单号 已派单/维修中/已解决」自动推进状态，或在网页前端操作。

## 📄 License

MIT
