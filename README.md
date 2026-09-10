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

## 🔄 数据流全景（来源 → 存储 → 出口）

理解系统的核心是理解数据从哪里来、存在哪里、到哪里去。

### 全景图

```
                         ┌─────────────────────────────────────────┐
                         │              数据来源（输入）              │
                         ├─────────────────────────────────────────┤
                         │  CSV/Excel 模板  │  店长/店员对话  │  维修工指令  │
                         │  (data/templates/)│  (网页/企微)     │  (企微群)    │
                         │  ERP/POS API(可选)│  运营手动录入    │  定时任务     │
                         └─────────┬────────────────┬──────────────┘
                                   │                │
                                   ▼                ▼
                         ┌─────────────────────────────────────────┐
                         │              数据存储（持久化）            │
                         ├─────────────────────────────────────────┤
                         │  MySQL（7张表）      │  Redis（会话缓存） │
                         │  ├─ repair_orders    │  └─ 会话状态      │
                         │  ├─ chat_logs        │                   │
                         │  ├─ inventory        │  文件存储          │
                         │  ├─ promotions       │  ├─ data/raw_docs/│
                         │  ├─ stores           │  ├─ data/index.json│
                         │  ├─ devices          │  └─ deploy/.env   │
                         │  └─ staff            │     (配置/密钥)    │
                         └─────────┬────────────────┬──────────────┘
                                   │                │
                                   ▼                ▼
                         ┌─────────────────────────────────────────┐
                         │              数据出口（消费）              │
                         ├─────────────────────────────────────────┤
                         │  智能对话回答  │  网页前端展示  │  API 接口  │
                         │  (Agent+RAG)  │  (对话/报修/告警)│  (REST)   │
                         │                │                │           │
                         │  企微群推送    │  飞书告警推送  │  Prometheus│
                         │  (工单/派单)   │  (错误率/延迟) │  指标      │
                         └─────────────────────────────────────────┘
```

### 7 类业务数据的完整生命周期

| 数据类型 | 来源（输入） | 存储位置 | 出口（消费） | 更新方式 | 更新频率 |
|---|---|---|---|---|---|
| **报修工单** | 店长对话报修 / 网页表单 / API | MySQL `repair_orders` | 企微群推送 / 网页工单列表 / API | 系统自动流转（状态机） | 实时 |
| **物料库存** | CSV导入 / ERP同步 / 手动调整 / API | MySQL `inventory` | 对话查询回答 / API / 补货提醒 | 定时同步脚本 + CSV + API | 每10分钟（定时） |
| **促销政策** | CSV导入 / API手动录入 | MySQL `promotions` | 对话校验回答 / API / 前端展示 | CSV + API + 每天自动过期检查 | 活动上线时 |
| **门店信息** | CSV导入 / API手动录入 | MySQL `stores` | 对话门店校验 / API / 前端展示 | CSV + API | 开店/闭店时 |
| **设备信息** | CSV导入 / API手动录入 | MySQL `devices` | 报修设备校验 / API / 前端展示 | CSV + API | 采购/报废时 |
| **员工信息** | CSV导入 / API手动录入 | MySQL `staff` | API / 接单人识别（可选扩展） | CSV + API | 入职/离职时 |
| **知识库/SOP** | Markdown文档（`data/raw_docs/`） | `data/index.json`（向量索引） | RAG检索回答 / 对话上下文 | 改文档 → 重建索引 → 重启 | 政策变更时 |

### 3 类系统数据（自动管理，无需手动）

| 数据类型 | 来源 | 存储位置 | 出口 | 更新方式 |
|---|---|---|---|---|
| **对话日志** | 每次对话自动记录 | MySQL `chat_logs` | API查询 / 运营分析 | 系统自动 |
| **会话缓存** | 对话过程中自动生成 | Redis（连不上降级内存） | Agent状态机读取 | 系统自动（过期自动清理） |
| **配置/密钥** | 手动编辑 `.env` | `deploy/.env` | 所有模块启动时读取 | 改 `.env` → 重启服务 |

### 数据导入流程（从零到可用）

```
第1步：准备数据
    │
    ├─ 用 Excel 打开 data/templates/ 下的 CSV 模板
    ├─ 填写门店/设备/员工/促销/库存数据
    └─ 另存为 CSV（UTF-8 编码）
    │
第2步：批量导入
    │
    ├─ python scripts/import_stores.py data/templates/stores.csv
    ├─ python scripts/import_devices.py data/templates/devices.csv
    ├─ python scripts/import_staff.py data/templates/staff.csv
    ├─ python scripts/import_promotions.py data/templates/promotions.csv
    └─ python scripts/sync_inventory.py --import data/templates/inventory.csv
    │
第3步：知识库导入
    │
    ├─ 编辑 data/raw_docs/ 下的 Markdown 文档
    └─ python scripts/build_index.py（重建向量索引）
    │
第4步：启动服务
    │
    └─ uvicorn app.main:app --port 8000
    │
第5步：验证
    │
    ├─ curl http://127.0.0.1:8000/healthz
    ├─ curl http://127.0.0.1:8000/api/stores
    └─ 网页前端 http://127.0.0.1:8000 对话测试
```

### 数据消费方式（3 种出口）

| 出口方式 | 说明 | 示例 |
|---|---|---|
| **智能对话** | 店长/店员自然语言提问，Agent自动检索知识库+调用工具返回答案 | "可乐杯还有多少库存" → 查 inventory 表 → 返回库存数量 |
| **网页前端** | 三标签页（对话/报修/告警），可视化展示数据 | 报修工单列表、库存状态、告警指标 |
| **REST API** | 标准 HTTP 接口，可对接管理后台、移动端、第三方系统 | `GET /api/repairs`、`POST /api/inventory` |

### 外部推送（2 种主动出口）

| 推送方式 | 触发条件 | 推送内容 |
|---|---|---|
| **企业微信群** | 新报修工单 / 工单派单 | 工单详情、门店、设备、故障描述 |
| **飞书群** | 错误率≥5% / P95延迟≥3秒 | 告警详情、时间窗口、指标数值 |

---

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
├── scripts/
│   ├── gen_docs.py            # 生成样例运营文档
│   ├── build_index.py         # 构建向量索引
│   ├── init_db.py             # 初始化数据库
│   ├── init_master_data.py    # 初始化主数据（库存/促销/门店/设备/员工）
│   ├── simulate_client.py     # 命令行模拟对话
│   ├── sync_inventory.py      # 库存同步（模拟ERP/CSV导入/手动调整）
│   ├── import_stores.py       # 门店信息批量导入（Excel/CSV）
│   ├── import_devices.py      # 设备台账批量导入（Excel/CSV）
│   ├── import_staff.py        # 员工信息批量导入（Excel/CSV）
│   ├── import_promotions.py   # 促销政策批量导入（Excel/CSV）
│   └── check_promotions.py    # 促销活动自动过期检查
├── data/
│   ├── raw_docs/              # 原始运营文档（Markdown）
│   ├── templates/             # 数据导入模板（CSV，含示例数据）
│   │   ├── stores.csv         # 门店模板
│   │   ├── devices.csv        # 设备模板
│   │   ├── staff.csv          # 员工模板
│   │   ├── promotions.csv     # 促销模板
│   │   └── inventory.csv      # 库存模板
│   ├── index.json             # 向量索引（build_index.py 生成）
│   └── app.db                 # SQLite 数据库（MySQL 不可用时降级）
├── tests/                     # 单元测试（47 passed）
├── deploy/                    # Docker 部署配置
├── docs/design.md             # 架构设计文档
├── requirements.txt
├── .env.example
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

## 📊 数据导入（生产环境必备）

系统内置 5 张主数据表，支持 **Excel/CSV 批量导入** + **REST API 管理**，无需对接外部系统即可快速上线。

### 第一步：准备数据

`data/templates/` 目录提供了 5 个 CSV 模板（含示例数据），直接用 Excel 打开编辑即可：

| 模板文件 | 用途 | 必要列 |
|---|---|---|
| `stores.csv` | 门店信息 | store_id, name, address, phone, manager, status |
| `devices.csv` | 设备台账 | device_id, store_id, device_type, brand, model, status |
| `staff.csv` | 员工信息 | staff_id, name, role, phone, store_id, status |
| `promotions.csv` | 促销政策 | promo_code, name, rule, status, valid_from, valid_until |
| `inventory.csv` | 物料库存 | store_id, material, stock, unit, reorder_point |

> 所有导入脚本支持中英文列名自动识别，CSV 用 UTF-8 编码（Excel 另存为 CSV UTF-8）。

### 第二步：批量导入

```bash
# 导入门店信息
python scripts/import_stores.py data/templates/stores.csv

# 导入设备台账
python scripts/import_devices.py data/templates/devices.csv

# 导入员工信息
python scripts/import_staff.py data/templates/staff.csv

# 导入促销政策
python scripts/import_promotions.py data/templates/promotions.csv

# 导入物料库存
python scripts/sync_inventory.py --import data/templates/inventory.csv
```

### 第三步：验证导入结果

```bash
# 查看已导入的门店
python scripts/import_stores.py list

# 查看已导入的员工
python scripts/import_staff.py list

# 查看已导入的促销
python scripts/import_promotions.py list

# 查看已导入的设备
python scripts/import_devices.py list
```

### 库存实时同步

```bash
# 模拟 ERP 同步（随机波动，演示用）
python scripts/sync_inventory.py

# 只同步指定门店
python scripts/sync_inventory.py --store S001

# 手动设置某物料库存
python scripts/sync_inventory.py --set S001 可乐杯 500

# 库存增减（入库/出库）
python scripts/sync_inventory.py --delta S001 可乐杯 -100
```

生产环境将 `sync_inventory.py` 中的模拟逻辑替换为真实 ERP API 调用，配置为定时任务（每 10 分钟一次）即可实现实时库存同步。

### 促销自动过期

```bash
# 检查并自动标记过期活动（建议每天凌晨定时运行）
python scripts/check_promotions.py

# 预览模式（只检查不修改）
python scripts/check_promotions.py --dry-run
```

### 定时任务配置（Linux crontab）

```bash
# 编辑 crontab
crontab -e

# 粘贴以下内容：
*/10 * * * * cd /opt/project1_store_agent && python scripts/sync_inventory.py >> /var/log/sync_inventory.log 2>&1
0 2 * * * cd /opt/project1_store_agent && python scripts/check_promotions.py >> /var/log/check_promotions.log 2>&1
0 3 * * * cd /opt/project1_store_agent && python scripts/import_stores.py data/templates/stores.csv >> /var/log/import_stores.log 2>&1
```

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
- **单元测试**：47 passed（33 核心 + 14 主数据管理）
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

## 🗄️ 主数据管理

系统内置 5 张主数据表，支持动态管理和 ERP 同步：

| 数据表 | 用途 | 初始化脚本 |
|---|---|---|
| `inventory` | 门店物料库存（支持按门店分库存） | `scripts/init_master_data.py` |
| `promotions` | 促销政策（支持有效期/状态管理） | 同上 |
| `stores` | 门店主数据（地址/电话/店长/状态） | 同上 |
| `devices` | 设备清单（品牌/型号/保修/状态） | 同上 |
| `staff` | 员工信息（角色/电话/所属门店） | 同上 |

### 库存实时同步

```bash
# 初始化主数据（首次部署）
python scripts/init_master_data.py

# 模拟 ERP 同步（随机波动，演示用）
python scripts/sync_inventory.py

# 只同步指定门店
python scripts/sync_inventory.py --store S001

# 手动设置某物料库存
python scripts/sync_inventory.py --set S001 可乐杯 500

# 库存增减（入库/出库）
python scripts/sync_inventory.py --delta S001 可乐杯 -100
```

生产环境将 `sync_inventory.py` 中的模拟逻辑替换为真实 ERP API 调用，配置为定时任务（如每 5 分钟同步一次）即可实现实时库存同步。

### 管理接口（REST API）

所有主数据均提供 CRUD 接口，可对接管理后台：

```
GET    /api/inventory?store_id=S001    # 库存列表
GET    /api/inventory/S001/可乐杯        # 单物料查询
POST   /api/inventory                    # 新增/更新库存

GET    /api/promotions                   # 促销列表
GET    /api/promotions/P01               # 促销详情
POST   /api/promotions                   # 新增/更新促销

GET    /api/stores                       # 门店列表
POST   /api/stores                       # 新增/更新门店

GET    /api/devices?store_id=S001       # 设备清单
POST   /api/devices                      # 新增/更新设备

GET    /api/staff?role=维修工            # 员工列表
POST   /api/staff                        # 新增/更新员工
```

## 📄 License

MIT
