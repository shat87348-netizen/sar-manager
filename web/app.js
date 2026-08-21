const elements = {
  healthBadge: document.querySelector("#healthBadge"),
  summaryGrid: document.querySelector("#summaryGrid"),
  totalCount: document.querySelector("#totalCount"),
  readyCount: document.querySelector("#readyCount"),
  queryForm: document.querySelector("#queryForm"),
  sourceSelect: document.querySelector("#source"),
  queryButton: document.querySelector("#queryButton"),
  resetButton: document.querySelector("#resetButton"),
  copyButton: document.querySelector("#copyButton"),
  requestUrl: document.querySelector("#requestUrl"),
  errorMessage: document.querySelector("#errorMessage"),
  resultCount: document.querySelector("#resultCount"),
  results: document.querySelector("#results"),
  jsonOutput: document.querySelector("#jsonOutput"),
};

let currentJson = null;
const RESULT_PREVIEW_LIMIT = 20;

function setHealth(ok, text) {
  elements.healthBadge.className = `health-badge ${ok ? "ok" : "error"}`;
  elements.healthBadge.lastElementChild.textContent = text;
}

function setError(message = "") {
  elements.errorMessage.hidden = !message;
  elements.errorMessage.textContent = message;
}

function showJson(payload) {
  currentJson = payload;
  elements.jsonOutput.textContent = JSON.stringify(payload, null, 2);
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  let payload;
  try {
    payload = await response.json();
  } catch {
    payload = { detail: `接口返回了非 JSON 内容（HTTP ${response.status}）` };
  }
  if (!response.ok) {
    const detail = typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload);
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return payload;
}

async function loadHealth() {
  try {
    const payload = await fetchJson("/health");
    setHealth(payload.status === "ok", payload.status === "ok" ? "接口正常" : "状态异常");
  } catch (error) {
    setHealth(false, "连接失败");
    setError(`健康检查失败：${error.message}`);
  }
}

async function loadStats() {
  try {
    const payload = await fetchJson("/api/v1/stats");
    elements.totalCount.textContent = payload.total ?? 0;
    elements.readyCount.textContent = payload.by_status?.READY ?? 0;
    elements.summaryGrid.querySelectorAll("[data-source-card]").forEach((card) => card.remove());
    const sourceCounts = Object.entries(payload.by_source || {}).sort(([left], [right]) =>
      left.localeCompare(right),
    );
    for (const [source, count] of sourceCounts) {
      const card = document.createElement("article");
      card.className = "summary-card";
      card.dataset.sourceCard = source;
      const label = document.createElement("span");
      label.textContent = source;
      const value = document.createElement("strong");
      value.textContent = count;
      card.append(label, value);
      elements.summaryGrid.append(card);
    }
  } catch (error) {
    setError(`统计接口失败：${error.message}`);
  }
}

async function loadSources() {
  try {
    const payload = await fetchJson("/api/v1/sources");
    for (const source of payload.sources || []) {
      const option = document.createElement("option");
      option.value = source.code;
      option.textContent = `${source.code}（${source.count}）`;
      elements.sourceSelect.append(option);
    }
  } catch (error) {
    setError(`数据源接口失败：${error.message}`);
  }
}

function buildQueryUrl() {
  const formData = new FormData(elements.queryForm);
  const params = new URLSearchParams();
  for (const field of ["startTime", "endTime", "source", "name", "bbox"]) {
    const value = String(formData.get(field) || "").trim();
    if (value) params.set(field, value);
  }
  if (formData.get("includeNonReady")) params.set("includeNonReady", "true");
  params.set("limit", String(RESULT_PREVIEW_LIMIT));
  const query = params.toString();
  return `/api/v1/sar${query ? `?${query}` : ""}`;
}

function makeButton(text, clickHandler) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "button secondary small";
  button.textContent = text;
  button.addEventListener("click", clickHandler);
  return button;
}

function makeLink(text, href) {
  const link = document.createElement("a");
  link.className = "button secondary small";
  link.textContent = text;
  link.href = href;
  link.target = "_blank";
  link.rel = "noreferrer";
  return link;
}

async function loadDetail(id) {
  setError();
  try {
    const payload = await fetchJson(`/api/v1/sar/${encodeURIComponent(id)}`);
    showJson(payload);
    document.querySelector(".json-panel").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    setError(`详情接口失败：${error.message}`);
  }
}

function renderResults(features, hasMore = false) {
  elements.results.replaceChildren();
  elements.resultCount.textContent = hasMore
    ? `当前仅预览 ${features.length} 条；匹配结果更多，请缩小筛选条件。`
    : `本次查询返回 ${features.length} 条`;

  if (!features.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "没有符合条件的数据";
    elements.results.append(empty);
    return;
  }

  for (const feature of features) {
    const properties = feature.properties || {};
    const item = document.createElement("article");
    item.className = "result-item";

    const thumbnailAsset = properties.assets?.THUMBNAIL;
    const thumbnailIsTiff = thumbnailAsset?.mime_type === "image/tiff";
    if (properties.thumbnail_url && !thumbnailIsTiff) {
      const image = document.createElement("img");
      image.className = "thumbnail";
      image.src = properties.thumbnail_url;
      image.alt = `${properties.name || "SAR"} 缩略图`;
      image.loading = "lazy";
      item.append(image);
    } else {
      const placeholder = document.createElement("div");
      placeholder.className = "thumbnail thumbnail-placeholder";
      placeholder.textContent = thumbnailIsTiff ? "TIFF 兼作缩略图" : "无缩略图";
      item.append(placeholder);
    }

    const main = document.createElement("div");
    main.className = "result-main";
    const name = document.createElement("h3");
    name.className = "result-name";
    name.textContent = properties.name || properties.external_id || feature.id;
    const meta = document.createElement("div");
    meta.className = "result-meta";
    const source = document.createElement("span");
    source.textContent = properties.source || "未知来源";
    const time = document.createElement("span");
    time.textContent = properties.acquisition_time || "无采集时间";
    const status = document.createElement("span");
    status.className = "status-tag";
    status.textContent = properties.status || "UNKNOWN";
    meta.append(source, time, status);
    main.append(name, meta);
    item.append(main);

    const actions = document.createElement("div");
    actions.className = "result-actions";
    actions.append(makeButton("详情", () => loadDetail(feature.id)));
    if (properties.thumbnail_url) actions.append(makeLink("缩略图", properties.thumbnail_url));
    if (properties.tiff_url) actions.append(makeLink("TIFF", properties.tiff_url));
    if (properties.metadata_url) actions.append(makeLink("描述文件", properties.metadata_url));
    item.append(actions);
    elements.results.append(item);
  }
}

async function runQuery() {
  const url = buildQueryUrl();
  elements.queryButton.disabled = true;
  elements.queryButton.textContent = "查询中…";
  elements.requestUrl.textContent = `请求：${url}`;
  setError();
  try {
    const payload = await fetchJson(url);
    const features = Array.isArray(payload.features) ? payload.features : [];
    renderResults(features, payload.has_more === true);
    showJson(payload);
  } catch (error) {
    renderResults([]);
    setError(`查询失败：${error.message}`);
  } finally {
    elements.queryButton.disabled = false;
    elements.queryButton.textContent = "查询";
  }
}

elements.queryForm.addEventListener("submit", (event) => {
  event.preventDefault();
  runQuery();
});

elements.resetButton.addEventListener("click", () => {
  elements.queryForm.reset();
  runQuery();
});

elements.copyButton.addEventListener("click", async () => {
  if (!currentJson) return;
  try {
    await navigator.clipboard.writeText(JSON.stringify(currentJson, null, 2));
    const original = elements.copyButton.textContent;
    elements.copyButton.textContent = "已复制";
    setTimeout(() => {
      elements.copyButton.textContent = original;
    }, 1200);
  } catch {
    setError("浏览器未允许复制，请直接从响应区域选择文本。 ");
  }
});

Promise.all([loadHealth(), loadStats(), loadSources(), runQuery()]);
