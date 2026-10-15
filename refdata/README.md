# 真实来源的原始抓取证据（探针输出）

这些文件是 2026-10-15 用 web_fetch 实际抓取到的原始响应，用来支撑
`data/sources/real_sources.json` 中的 URL、引文与 `retrieved_at`。**应用运行时不读取本目录**，
它们只是可审计的来源证据。

| 文件 | 来源 | 说明 |
|---|---|---|
| `pubchem_936.json` / `pubchem_338.json` / `pubchem_445354.json` | NCBI PubChem PUG-View 机器可读端点 | 烟酰胺 / 水杨酸 / 视黄醇的原始记录（化合物 HTML 页面被 reCAPTCHA 拦截，因此使用官方 JSON 端点） |
| `pubchem_445154.json` | 同上 | 误认为是视黄醇的 CID（实为白藜芦醇），保留用于说明纠错过程，**未被使用** |
| `prod_cerave_sa.html`、`prod_ord_niacinamide.html`、`prod_lrp_uvmune_de.html` | 品牌官网 | 3 个真实 SKU 的成分表与使用说明页面快照 |
| `prod_*.html`（其余） | 品牌官网 | 抓取过程中的中间页面（如 403 拦截页），用于说明哪些地址不可用 |
| `result.json` | 抓取脚本输出 | 汇总后的结构化结果，逐条带 verbatim 引用与 locator |

注意事项：

- 这些是**第三方页面快照**，仅作本地来源核验使用，不应再分发或用于训练。
  品牌 HTML 已在 `.gitignore` 中排除，仓库只保留 PubChem 的公开 JSON 与 `result.json`。
- 审核人字段为 `demo_seed`：**不是品牌官方审核，也不是医学审核**。
- `cosing.ec.europa.eu` 在本环境 DNS 不可解析，因此**没有使用任何 CosIng 数据**。
