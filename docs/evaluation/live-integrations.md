# 真实外部接入：实测记录

本文件只记录**实际执行过**的检查与原始输出。未执行的项在文末「未实测」中列出，不做任何推断。

环境：macOS（arm64），Python 3.12，执行时间见下方时间戳（UTC）。

---

## 1. 真实天气 API（WEATHER_MODE=live，Open-Meteo）

命令：

```bash
./.venv/bin/python scripts/smoke_live_weather.py CN-GZ CN-BJ
```

结果：**成功**（exit code 0）。端点 `https://api.open-meteo.com/v1/forecast`，无需密钥。

```text
WEATHER_MODE=live endpoint=https://api.open-meteo.com/v1/forecast
--- CN-GZ 广州 (provider=open-meteo mode=live)
    quality=ok missing=[]
    current: {"temperature_c": 26.8, "relative_humidity": 71, "wind_speed_ms": 2.8, "precipitation_mm": 0.0, "uv_index": 5.75, "condition": "0"}
    issued_at: 2026-10-15T13:03:59+00:00 valid_to: 2026-10-15T14:03:59+00:00
    forecast 2026-10-15 {"temperature_max_c": 31.9, "temperature_min_c": 24.2, "relative_humidity": 67, "uv_index_max": 5.75, "precipitation_mm": 0.9, "condition": "51"}
    forecast 2026-10-16 {"temperature_max_c": 32.9, "temperature_min_c": 23.1, "relative_humidity": 68, "uv_index_max": 7.2, "precipitation_mm": 0.0, "condition": "3"}
    forecast 2026-10-17 {"temperature_max_c": 33.8, "temperature_min_c": 24.5, "relative_humidity": 66, "uv_index_max": 7.15, "precipitation_mm": 0.1, "condition": "51"}
    persisted snapshot: 99c50527-… freshness: ok
--- CN-BJ 北京 (provider=open-meteo mode=live)
    quality=ok missing=[]
    current: {"temperature_c": 19.7, "relative_humidity": 50, "wind_speed_ms": 1.63, "precipitation_mm": 0.0, "uv_index": 4.4, "condition": "2"}
    issued_at: 2026-10-15T13:04:03+00:00 valid_to: 2026-10-15T14:04:03+00:00
    forecast 2026-10-15 {"temperature_max_c": 26.6, "temperature_min_c": 11.6, "relative_humidity": 51, "uv_index_max": 4.4, "precipitation_mm": 0.0, "condition": "2"}
    forecast 2026-10-16 {"temperature_max_c": 18.1, "temperature_min_c": 13.2, "relative_humidity": 41, "uv_index_max": 3.8, "precipitation_mm": 5.1, "condition": "80"}
    forecast 2026-10-17 {"temperature_max_c": 16.9, "temperature_min_c": 12.5, "relative_humidity": 86, "uv_index_max": 0.15, "precipitation_mm": 42.6, "condition": "81"}
    persisted snapshot: c377d502-… freshness: ok
```

观察与限制：

- 单位已在请求中固定为 `wind_speed_unit=ms`，与快照 `units` 声明一致。
- `uv_index` 由 `hourly.uv_index` 取「不晚于当前时刻」的最近值得到；若提供方不返回该字段，
  实现会写入 `null` 并把字段记入 `missing_fields`，**不会**用 0 代替。
- 真实模式下 `is_demo=false`、`mode=live`；快照只有在 `issued_at` 超过
  `WEATHER_MAX_AGE_MINUTES`（默认 60）时才标记 `stale`（按提供方数据时间判断，不只看 `fetched_at`）。
- 该端点为固定配置项 `WEATHER_API_BASE`，模型无法构造任意抓取 URL（防 SSRF）。
- 未做：长期配额/限流压测、供应商 SLA 核对、多供应商故障切换。

## 2. 知识来源抓取（已用于种子数据）

`data/sources/real_sources.json` 中的 URL 与引文为 2026-10-15 实际抓取结果：

- PubChem 化合物 HTML 页面在抓取时被 reCAPTCHA 拦截（HTTP 200 但内容为校验页），
  因此改用 NCBI 官方机器可读端点 `https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/{cid}/JSON`
  获取同一记录（CID 936 Nicotinamide / CID 338 Salicylic Acid / CID 445354 Retinol）。
- `cosing.ec.europa.eu` 在本环境 DNS 不可解析，**未使用 CosIng 数据**。
- `laroche-posay.us/.co.uk/.ca/.fr` 返回 403，改用官方德国站，区域记为 `EU`。
- 审核人字段为 `demo_seed`：**这不是品牌或医学审核**，真实上线必须替换为合格审核人签署。

## 3. 未实测（需要凭据或外部协调）

| 项目 | 原因 | 接入条件 |
|---|---|---|
| 真实模型调用（`MODEL_MODE=live`） | 无 `API_KEY`/`API_BASE`/`MODEL_NAME` | 提供 OpenAI 兼容端点与密钥；测试用 stub 已覆盖编排与校验路径（AC14/AC15） |
| 真实 Web Push 发送 | 无 VAPID 密钥与受支持设备 | 生成 VAPID 密钥对并在 Chromium/Firefox 上实测订阅与送达 |
| 原生推送（APNs/FCM） | P1，未实现 | 原生客户端 + 推送凭据 |
| 真实电商/CRM 订单接口 | 无合法接口与凭据 | 合同、OAuth 凭据、数据最小化评估 |
| 品牌侧外发 | 不存在通道 | 数据共享协议、用户同意、品牌运营审核流程 |
| 生产级真实认证 | 演示模式 | OIDC/密码体系与风控 |
| PostgreSQL 运行验证 | 本地只跑 SQLite | 提供实例并重跑 `alembic upgrade head` 与测试套件 |

## 4. Playwright 浏览器安装记录

`npx playwright install chromium` 首次尝试失败：

```text
Error: EPERM: operation not permitted, mkdir '/Users/ee/Library/Caches/ms-playwright'
```

原因：沙箱不允许写入用户级缓存目录。做法：把浏览器下载到仓库内
`PLAYWRIGHT_BROWSERS_PATH=<repo>/.playwright-browsers`，并在 `scripts/run_e2e_tests.sh`
中导出该变量。

实际执行（复现命令）：

```bash
# 终端 1
./scripts/run_e2e_server.sh          # 专用 e2e.db + alembic upgrade + seed + uvicorn :8000
# 终端 2
./scripts/run_e2e_tests.sh
```

结果：**7 passed（10.0 s，chromium）**。

| 流程 | 覆盖内容 |
|---|---|
| flow1 | 上传演示截图 → 修正候选名称/数量 → 确认入柜 → 对话生成计划草稿 → 点「接受」→ `/routine` 显示生效版本 |
| flow2 | 对话报告刺痛 → 只生成复核询问（版本不变）→ 选择暂停 → v+1 草稿 → 接受 → 历史保留 → 预算 300→500 修正 → 刷新后保持 |
| flow3 | 交接预览（草稿，不产生工单）→ 确认提交（`已提交到本地演示工作台`）→ 切换到 staff 身份打开工单详情 → 更新为 resolved → 切回消费者查询进度 → 展开时间线 |
| flow4 | 生成图鉴 → 每张卡片显示 data_status 与免责声明 → 关联措辞（含「不代表因果关系」、不含「过敏」）→ 未展示的延伸列出 `无已审核来源` → 选择成分并提交补充陈述 |
| flow5 | 组合提示 → 选择「间隔」→ 生成草稿 → 接受 → 删除一条反馈 → 重新生成图鉴 → 刷新后仍反映删除 |
| flow6 | 手动选城市 → 创建行程（类型=行程 + 目的地）→ 授权旅行提醒并打开免打扰窗口 → 调度 tick → inbox 出现卡片 → 采纳只记录意向 → 撤销授权后不再发送 |
| flow7 | 环境数据缺失时如实展示（缺失字段区域可见） |

未做的 E2E 检查：iOS Safari 安装、真实 Web Push 通知展示与点击深链接、离线行为、多浏览器（只跑 chromium）。
