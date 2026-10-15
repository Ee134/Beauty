/**
 * /cabinet 美妆柜：列表、筛选、手动添加、状态操作、导入入口。
 */

import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  createImport,
  createOwnedProduct,
  deleteOwnedProduct,
  listOwnedProducts,
  patchOwnedProduct,
} from "../api/endpoints";
import type { LifecycleStatus, OwnedProduct, OwnedProductListResponse } from "../api/types";
import { AsyncBlock, ActionFeedback, Badge, Notice, Panel, useToast } from "../components/ui";
import { formatDate, formatDateTime, toDateTimeLocal, fromDateTimeLocal } from "../lib/format";
import { lifecycleLabel, matchStatusLabel, usageLabel } from "../lib/labels";
import { useAction, useAsync } from "../state/useAsync";
import { useSession } from "../state/SessionContext";

type FilterKey = "all" | "active" | "paused" | "unopened" | "finished";

export function CabinetPage(): JSX.Element {
  const { me, refreshMe, refreshContext, lastLoadedAt } = useSession();
  const toast = useToast();
  const navigate = useNavigate();
  const [filter, setFilter] = useState<FilterKey>("all");
  // 表单默认可见（E2E 可直接输入）；cabinet-add-open 用于重新展开并聚焦。
  const [addOpen, setAddOpen] = useState(true);
  const list = useAsync<OwnedProductListResponse>(() => listOwnedProducts({ include_deleted: false }), {
    deps: [lastLoadedAt],
  });

  const refresh = () => {
    list.reload();
    void refreshMe();
    void refreshContext();
  };

  const products = list.data?.products ?? [];
  const visible = products.filter((product) => {
    switch (filter) {
      case "active":
        return product.usage_status === "active";
      case "paused":
        return product.usage_status !== "active";
      case "unopened":
        return product.lifecycle_status === "unopened";
      case "finished":
        return product.lifecycle_status === "finished" || product.lifecycle_status === "discarded";
      default:
        return true;
    }
  });

  return (
    <div className="stack">
      <Panel
        title="美妆柜"
        subtitle="多件同 SKU 各自独立记录；暂停不等于未开封"
        actions={
          <>
            <button type="button" data-testid="cabinet-add-open" onClick={() => setAddOpen(true)}>
              手动添加产品
            </button>
            <button type="button" onClick={refresh}>
              刷新
            </button>
          </>
        }
      >
        <div className="row tight">
          {(
            [
              ["all", `全部 ${products.length}`],
              ["active", "使用中"],
              ["paused", "已暂停/其他"],
              ["unopened", "未开封"],
              ["finished", "用完/丢弃"],
            ] as Array<[FilterKey, string]>
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              className={filter === key ? "primary" : ""}
              onClick={() => setFilter(key)}
            >
              {label}
            </button>
          ))}
        </div>
        {list.data && <Notice>{list.data.notice}</Notice>}
      </Panel>

      <ImportEntry onCreated={(batchId) => navigate(`/imports/${batchId}`)} />

      {/* 表单保持渲染（cabinet-add-open 只负责展开并聚焦），
          这样无论 E2E 是否先点击入口，cabinet-add-name/submit 都在 DOM 中。 */}
      <ManualAddForm
        open={addOpen}
        onOpen={() => {
          setAddOpen(true);
          window.setTimeout(() => {
            document.querySelector<HTMLInputElement>('[data-testid="cabinet-add-name"]')?.focus();
          }, 0);
        }}
        onCreated={(name) => {
          toast.show(`已加入美妆柜：${name}`);
          setAddOpen(false);
          refresh();
        }}
      />

      <Panel title="我的产品实例" subtitle={`共 ${visible.length} 件`}>
        <AsyncBlock
          loading={list.loading}
          error={list.error}
          data={list.data}
          onRetry={list.reload}
          loadingLabel="加载美妆柜…"
          isEmpty={() => visible.length === 0}
          empty={
            products.length === 0
              ? "美妆柜还是空的：可以手动添加，或上传演示订单截图导入。"
              : "当前筛选条件下没有产品。"
          }
        >
          {() => (
            <div className="grid" data-testid="cabinet-list">
              {visible.map((product) => (
                <ProductCard key={product.id} product={product} onChange={refresh} />
              ))}
            </div>
          )}
        </AsyncBlock>
      </Panel>

      {me && (
        <p className="small muted">
          数据为演示数据（provenance=demo_seed/import）；日期未知时保持「未知」，不会自动填成今天。
        </p>
      )}
    </div>
  );
}

function ImportEntry({ onCreated }: { onCreated: (batchId: string) => void }): JSX.Element {
  const [file, setFile] = useState<File | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const action = useAction<[File], Awaited<ReturnType<typeof createImport>>>((next) =>
    createImport(next),
  );

  const submit = async () => {
    if (!file) {
      return;
    }
    const result = await action.run(file);
    if (result) {
      onCreated(result.id);
    }
  };

  return (
    <Panel title="导入产品（截图/照片）" subtitle="POST /api/v1/imports，multipart 字段名 file">
      <div className="row">
        <input
          ref={inputRef}
          data-testid="import-file-input"
          type="file"
          accept="image/jpeg,image/png,image/webp"
          onChange={(event) => {
            setFile(event.target.files?.[0] ?? null);
            setNotice(null);
          }}
        />
        <button
          type="button"
          className="primary"
          data-testid="import-submit"
          disabled={!file || action.running}
          onClick={() => void submit()}
        >
          {action.running ? "上传中…" : "上传并识别"}
        </button>
      </div>
      <Notice tone="mock">
        mock 模式只识别内置演示截图样本（data/fixtures/imports/demo_order_screenshot_1.png、
        demo_order_screenshot_2.png），不代表真实 OCR 或视觉识别能力；其他图片不会编造识别结果。
      </Notice>
      {notice && <div className="state">{notice}</div>}
      <ActionFeedback error={action.error} />
    </Panel>
  );
}

function ManualAddForm({
  onCreated,
  open = true,
  onOpen,
}: {
  onCreated: (name: string) => void;
  /** 是否处于展开状态（收起时表单仍渲染，只是折叠显示）。 */
  open?: boolean;
  onOpen?: () => void;
}): JSX.Element {
  const [name, setName] = useState("");
  const [size, setSize] = useState("");
  const [lifecycle, setLifecycle] = useState<LifecycleStatus>("unopened");
  const [purchaseDate, setPurchaseDate] = useState("");
  const [openedDate, setOpenedDate] = useState("");
  const [paoMonths, setPaoMonths] = useState("");
  const action = useAction(() =>
    createOwnedProduct({
      custom_name: name,
      match_status: "custom",
      size: size || null,
      lifecycle_status: lifecycle,
      usage_status: "active",
      purchase_date: fromDateTimeLocal(purchaseDate),
      opened_date: fromDateTimeLocal(openedDate),
      pao_months: paoMonths ? Number(paoMonths) : null,
    }),
  );

  const submit = async () => {
    const result = await action.run();
    if (result) {
      onCreated(result.custom_name);
      setName("");
      setSize("");
      setPaoMonths("");
      setPurchaseDate("");
      setOpenedDate("");
      action.reset();
    }
  };

  return (
    <Panel title="手动添加" subtitle="POST /api/v1/owned-products（不猜测任何日期）">
      <div className="row" style={open ? undefined : { display: "none" }}>
        <div className="field">
          <label htmlFor="manual-name">产品名称 *</label>
          <input
            id="manual-name"
            data-testid="cabinet-add-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="例如：我的某瓶精华"
          />
        </div>
        <div className="field">
          <label htmlFor="manual-size">规格</label>
          <input id="manual-size" value={size} onChange={(event) => setSize(event.target.value)} placeholder="30ml" />
        </div>
        <div className="field">
          <label htmlFor="manual-lifecycle">开封状态</label>
          <select
            id="manual-lifecycle"
            value={lifecycle}
            onChange={(event) => setLifecycle(event.target.value as LifecycleStatus)}
          >
            <option value="unopened">未开封</option>
            <option value="opened">已开封</option>
            <option value="unknown">未知</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="manual-purchase">购买日期</label>
          <input
            id="manual-purchase"
            type="datetime-local"
            value={purchaseDate}
            onChange={(event) => setPurchaseDate(event.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="manual-opened">开封日期</label>
          <input
            id="manual-opened"
            type="datetime-local"
            value={openedDate}
            onChange={(event) => setOpenedDate(event.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="manual-pao">开封后可用月数（PAO）</label>
          <input
            id="manual-pao"
            type="number"
            min={1}
            max={120}
            value={paoMonths}
            onChange={(event) => setPaoMonths(event.target.value)}
            placeholder="仅包装标注时填写"
          />
        </div>
        <button
          type="button"
          className="primary"
          data-testid="cabinet-add-submit"
          disabled={action.running || name.trim().length === 0}
          onClick={() => void submit()}
        >
          {action.running ? "添加中…" : "加入美妆柜"}
        </button>
      </div>
      {!open && onOpen && (
        <div className="row tight">
          <button type="button" data-testid="cabinet-add-expand" onClick={onOpen}>
            展开表单
          </button>
        </div>
      )}
      <Notice>
        到期日只在「包装/用户确认日期」或「开封日期 + 包装 PAO 同时确认」时计算；否则显示未知。
      </Notice>
      <ActionFeedback error={action.error} />
    </Panel>
  );
}

function ProductCard({ product, onChange }: { product: OwnedProduct; onChange: () => void }): JSX.Element {
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(product.custom_name);
  const [size, setSize] = useState(product.size ?? "");
  const [openedDate, setOpenedDate] = useState(toDateTimeLocal(product.opened_date));
  const [paoMonths, setPaoMonths] = useState(product.pao_months ? String(product.pao_months) : "");

  const patch = useAction((body: Parameters<typeof patchOwnedProduct>[1]) =>
    patchOwnedProduct(product.id, body),
  );
  const remove = useAction(() => deleteOwnedProduct(product.id));

  const apply = async (body: Parameters<typeof patchOwnedProduct>[1]) => {
    const result = await patch.run(body);
    if (result) {
      toast.show("已更新（服务端返回新版本号）。");
      setEditing(false);
      onChange();
    }
  };

  return (
    <div className="panel tight stack" data-testid="cabinet-item" data-owned-id={product.id}>
      <div className="row tight" style={{ justifyContent: "space-between" }}>
        <Link to={`/products/${product.id}`} style={{ fontWeight: 600 }}>
          {product.custom_name}
        </Link>
        <Badge tone={product.match_status === "matched" ? "ok" : "warn"}>
          {matchStatusLabel(product.match_status)}
        </Badge>
      </div>
      <div className="row tight">
        <Badge>{lifecycleLabel(product.lifecycle_status)}</Badge>
        <Badge tone={product.usage_status === "active" ? "ok" : "warn"}>
          {usageLabel(product.usage_status)}
        </Badge>
        {product.review_flag && <Badge tone="warn">需关注（此前有负面反馈记录）</Badge>}
        <Badge tone={product.ingredient_source_status === "available" ? "ok" : "warn"}>
          成分资料：{product.ingredient_source_status}
        </Badge>
      </div>
      <dl className="kv">
        <div style={{ display: "contents" }}>
          <dt>规格</dt>
          <dd>{product.size ?? "未填写"}</dd>
        </div>
        <div style={{ display: "contents" }}>
          <dt>购买日期</dt>
          <dd>{formatDate(product.purchase_date)}</dd>
        </div>
        <div style={{ display: "contents" }}>
          <dt>开封日期</dt>
          <dd>{formatDate(product.opened_date)}</dd>
        </div>
        <div style={{ display: "contents" }}>
          <dt>到期</dt>
          <dd>
            {formatDate(product.effective_expiry)}
            {product.expiry_unknown_reason ? `（${product.expiry_unknown_reason}）` : ""}
          </dd>
        </div>
        <div style={{ display: "contents" }}>
          <dt>版本号</dt>
          <dd className="mono">v{product.version}</dd>
        </div>
        <div style={{ display: "contents" }}>
          <dt>更新时间</dt>
          <dd>{formatDateTime(product.updated_at)}</dd>
        </div>
      </dl>
      {product.key_actives.length > 0 && (
        <div className="small muted">关键成分：{product.key_actives.join("、")}</div>
      )}

      <div className="row tight">
        {product.usage_status === "active" ? (
          <button
            type="button"
            disabled={patch.running}
            onClick={() => void apply({ usage_status: "paused", expected_version: product.version })}
          >
            暂停使用
          </button>
        ) : (
          <button
            type="button"
            disabled={patch.running}
            onClick={() => void apply({ usage_status: "active", expected_version: product.version })}
          >
            恢复使用
          </button>
        )}
        {product.lifecycle_status !== "finished" && (
          <button
            type="button"
            disabled={patch.running}
            onClick={() => void apply({ lifecycle_status: "finished", expected_version: product.version })}
          >
            标记用完
          </button>
        )}
        <button type="button" onClick={() => setEditing((value) => !value)}>
          {editing ? "取消编辑" : "编辑"}
        </button>
        <button
          type="button"
          className="danger"
          disabled={remove.running}
          onClick={() => {
            void (async () => {
              const result = await remove.run();
              if (result) {
                toast.show(result.notice);
                onChange();
              }
            })();
          }}
        >
          删除（软删除）
        </button>
      </div>

      {editing && (
        <div className="stack">
          <div className="row">
            <div className="field">
              <label htmlFor={`name-${product.id}`}>名称</label>
              <input id={`name-${product.id}`} value={name} onChange={(event) => setName(event.target.value)} />
            </div>
            <div className="field">
              <label htmlFor={`size-${product.id}`}>规格</label>
              <input id={`size-${product.id}`} value={size} onChange={(event) => setSize(event.target.value)} />
            </div>
            <div className="field">
              <label htmlFor={`opened-${product.id}`}>开封日期</label>
              <input
                id={`opened-${product.id}`}
                type="datetime-local"
                value={openedDate}
                onChange={(event) => setOpenedDate(event.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor={`pao-${product.id}`}>PAO 月数</label>
              <input
                id={`pao-${product.id}`}
                type="number"
                min={1}
                max={120}
                value={paoMonths}
                onChange={(event) => setPaoMonths(event.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor={`lifecycle-${product.id}`}>开封状态</label>
              <select
                id={`lifecycle-${product.id}`}
                value={product.lifecycle_status}
                onChange={(event) =>
                  void apply({ lifecycle_status: event.target.value, expected_version: product.version })
                }
              >
                <option value="unopened">未开封</option>
                <option value="opened">已开封</option>
                <option value="finished">已用完</option>
                <option value="discarded">已丢弃</option>
                <option value="unknown">未知</option>
              </select>
            </div>
          </div>
          <div className="row tight">
            <button
              type="button"
              className="primary"
              disabled={patch.running}
              onClick={() =>
                void apply({
                  custom_name: name,
                  size: size || null,
                  opened_date: fromDateTimeLocal(openedDate),
                  pao_months: paoMonths ? Number(paoMonths) : null,
                  expected_version: product.version,
                })
              }
            >
              保存
            </button>
            <span className="small muted">保存时携带 expected_version={product.version}，冲突会返回 409。</span>
          </div>
        </div>
      )}

      <ActionFeedback error={patch.error} />
      <ActionFeedback error={remove.error} />
      {product.expiry_unknown_reason && (
        <Notice>到期未知说明：{product.expiry_unknown_reason}</Notice>
      )}
    </div>
  );
}
