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
  transferJobs: document.querySelector("#transferJobs"),
  transferError: document.querySelector("#transferError"),
  transferRefreshTime: document.querySelector("#transferRefreshTime"),
};

let currentJson = null;
const RESULT_PREVIEW_LIMIT = 20;
const TRANSFER_REFRESH_MS = 3000;
const TRANSFER_PAGE_SIZE = 500;
let transferLoading = false;

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

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const amount = bytes / 1024 ** index;
  return `${amount >= 100 || index === 0 ? amount.toFixed(0) : amount.toFixed(1)} ${units[index]}`;
}

function transferPhaseLabel(phase) {
  return {
    QUEUED: "等待搬运",
    TRANSFERRING: "正在搬运",
    INGESTING: "正在入库",
    INGESTED: "已入库",
    COMPLETED: "已完成",
    SKIPPED: "数据库已存在，已跳过",
    PARTIAL_FAILED: "部分失败",
    FAILED: "失败",
    CANCELLED: "已取消",
  }[phase] || phase || "未知状态";
}

function progressPercent(transferred, total, phase) {
  if (["INGESTED", "COMPLETED", "SKIPPED"].includes(phase)) return 100;
  const totalNumber = Number(total || 0);
  if (totalNumber <= 0) return 0;
  return Math.min(100, Math.max(0, (Number(transferred || 0) / totalNumber) * 100));
}

function makeProgressBar(percent) {
  const track = document.createElement("div");
  track.className = "progress-track";
  track.setAttribute("role", "progressbar");
  track.setAttribute("aria-valuemin", "0");
  track.setAttribute("aria-valuemax", "100");
  track.setAttribute("aria-valuenow", String(Math.round(percent)));
  const bar = document.createElement("div");
  bar.className = "progress-bar";
  bar.style.width = `${percent}%`;
  track.append(bar);
  return track;
}

function renderTransferJobs(jobs) {
  elements.transferJobs.replaceChildren();
  if (!jobs.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "暂无搬运任务";
    elements.transferJobs.append(empty);
    return;
  }

  for (const job of jobs) {
    const card = document.createElement("article");
    card.className = "transfer-card";

    const heading = document.createElement("div");
    heading.className = "transfer-card-heading";
    const title = document.createElement("div");
    const name = document.createElement("h3");
    name.textContent = `${job.source || "未知来源"} · ${job.server || "未知服务器"}`;
    const identifier = document.createElement("p");
    identifier.textContent = `任务 ${job.job_id}`;
    title.append(name, identifier);
    const state = document.createElement("span");
    state.className = `transfer-state state-${String(job.status || "unknown").toLowerCase()}`;
    state.textContent = transferPhaseLabel(job.phase || job.status);
    heading.append(title, state);
    card.append(heading);

    const progress = job.progress || {};
    const percent = Number(progress.percent || 0);
    const summary = document.createElement("div");
    summary.className = "transfer-progress-summary";
    const byteText = document.createElement("span");
    byteText.textContent = `${formatBytes(progress.transferred_bytes)} / ${formatBytes(progress.total_bytes)}`;
    const percentText = document.createElement("strong");
    percentText.textContent = `${percent.toFixed(1)}%`;
    summary.append(byteText, percentText);
    card.append(summary, makeProgressBar(percent));

    const counts = document.createElement("p");
    counts.className = "transfer-counts";
    counts.textContent = `共 ${progress.total_files || 0} 个；完成 ${progress.completed_files || 0}；跳过 ${progress.skipped_files || 0}；失败 ${progress.failed_files || 0}`;
    card.append(counts);

    const files = document.createElement("div");
    files.className = "transfer-files";
    for (const file of job.files || []) {
      const item = document.createElement("div");
      item.className = "transfer-file";
      const fileHeading = document.createElement("div");
      fileHeading.className = "transfer-file-heading";
      const path = document.createElement("span");
      path.className = "transfer-file-path";
      path.textContent = file.source_path;
      const phase = document.createElement("span");
      phase.textContent = transferPhaseLabel(file.phase || file.status);
      fileHeading.append(path, phase);
      const filePercent = progressPercent(
        file.transferred_bytes,
        file.size_bytes,
        file.phase || file.status,
      );
      const detail = document.createElement("p");
      detail.textContent = `${formatBytes(file.transferred_bytes)} / ${formatBytes(file.size_bytes)} · ${filePercent.toFixed(1)}%`;
      item.append(fileHeading, makeProgressBar(filePercent), detail);
      if (file.error_message) {
        const message = document.createElement("p");
        message.className = file.status === "SKIPPED" ? "skip-message" : "file-error";
        message.textContent = file.error_message;
        item.append(message);
      }
      files.append(item);
    }
    card.append(files);
    elements.transferJobs.append(card);
  }
}

async function loadTransferJobs() {
  if (transferLoading) return;
  transferLoading = true;
  elements.transferError.hidden = true;
  try {
    const jobs = [];
    let offset = 0;
    let hasMore = false;
    do {
      const payload = await fetchJson(
        `/api/v1/transfer-jobs?limit=${TRANSFER_PAGE_SIZE}&offset=${offset}`,
      );
      const page = Array.isArray(payload.jobs) ? payload.jobs : [];
      jobs.push(...page);
      hasMore = payload.has_more === true;
      offset += page.length;
    } while (hasMore);
    renderTransferJobs(jobs);
    elements.transferRefreshTime.textContent = `更新于 ${new Date().toLocaleTimeString()}`;
  } catch (error) {
    elements.transferError.hidden = false;
    elements.transferError.textContent = `搬运任务查询失败：${error.message}`;
  } finally {
    transferLoading = false;
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

Promise.all([loadHealth(), loadStats(), loadSources(), loadTransferJobs(), runQuery()]);
setInterval(loadTransferJobs, TRANSFER_REFRESH_MS);
