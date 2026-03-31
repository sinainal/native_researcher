const state = {
  allArticles: [],
  articles: [],
  projectId: null,
  projectPath: null,
  projectName: "Project",
  projectRenaming: false,
  projectRenameSaving: false,
  projectDownloads: [],
  downloadabilityCache: {},
  downloadabilityById: {},
  downloadabilityRunId: 0,
  queryHistory: [],
  activeQueryId: null,
  queryDetailId: null,
  citationRunId: 0,
  citationsLoading: false,
  selectedIds: new Set(),
  sortKey: null,
  sortDirection: "asc",
  lastSearchPayload: null,
  lastPubmedResponse: null,
  detailArticleId: null,
  assistantThreadId: null,
  assistantMessages: [],
  assistantOpen: true,
  thinkingLevel: localStorage.getItem("native_researcher_thinking_level") || "off",
  assistantStreamAbort: null,
  assistantSessions: [],
  currentSessionId: null,
  sidebarOpen: localStorage.getItem("native_researcher_sidebar_open") !== "false",
  chatHistoryExpanded: false,
  chatHistoryOpen: false,
};

const els = {
  healthStatus: document.getElementById("healthStatus"),
  projectNameDisplay: document.getElementById("projectNameDisplay"),
  projectNameInput: document.getElementById("projectNameInput"),
  articleCount: document.getElementById("articleCount"),
  selectedCount: document.getElementById("selectedCount"),
  query: document.getElementById("query"),
  yearStart: document.getElementById("yearStart"),
  yearEnd: document.getElementById("yearEnd"),
  maxResults: document.getElementById("maxResults"),
  searchBtn: document.getElementById("searchBtn"),
  chatSidebar: document.getElementById("chatSidebar"),
  sidebarToggleBtn: document.getElementById("sidebarToggleBtn"),
  sidebarQueriesBtn: document.getElementById("sidebarQueriesBtn"),
  sidebarDownloadsBtn: document.getElementById("sidebarDownloadsBtn"),
  sidebarSettingsBtn: document.getElementById("sidebarSettingsBtn"),
  sidebarPanelKicker: document.getElementById("sidebarPanelKicker"),
  sidebarPanelTitle: document.getElementById("sidebarPanelTitle"),
  sidebarQueriesPanel: document.getElementById("sidebarQueriesPanel"),
  sidebarDownloadsPanel: document.getElementById("sidebarDownloadsPanel"),
  sidebarSettingsPanel: document.getElementById("sidebarSettingsPanel"),
  chatHistoryList: document.getElementById("chatHistoryList"),
  newChatTriggers: document.querySelectorAll(".new-chat-trigger"),
  workspaceQueryCount: document.getElementById("workspaceQueryCount"),
  workspaceQueryList: document.getElementById("workspaceQueryList"),
  workspaceQueryDetail: document.getElementById("workspaceQueryDetail"),
  sidebarQuickQuery: document.getElementById("sidebarQuickQuery"),
  sidebarQuickMaxResults: document.getElementById("sidebarQuickMaxResults"),
  sidebarQuickSearchBtn: document.getElementById("sidebarQuickSearchBtn"),
  sidebarQuickStatus: document.getElementById("sidebarQuickStatus"),
  workspaceDownloadCount: document.getElementById("workspaceDownloadCount"),
  workspaceDownloadList: document.getElementById("workspaceDownloadList"),
  clearSelectionBtn: document.getElementById("clearSelectionBtn"),
  selectAllBtn: document.getElementById("selectAllBtn"),
  quickDownloadSelectedBtn: document.getElementById("quickDownloadSelectedBtn"),
  metaStrip: document.getElementById("metaStrip"),
  resultsBody: document.getElementById("resultsBody"),
  sortButtons: document.querySelectorAll(".table-sort-btn"),
  assistantPanel: document.getElementById("assistantPanel"),
  assistantHeaderTitle: document.getElementById("assistantHeaderTitle"),
  assistantHistoryToggleBtn: document.getElementById("assistantHistoryToggleBtn"),
  assistantHistoryPanel: document.getElementById("assistantHistoryPanel"),
  assistantThreadShell: document.getElementById("assistantThreadShell"),
  assistantMessages: document.getElementById("assistantMessages"),
  assistantInput: document.getElementById("assistantInput"),
  apiKeysBtn: document.getElementById("apiKeysBtn"),
  apiKeysOverlay: document.getElementById("apiKeysOverlay"),
  apiKeysPopup: document.getElementById("apiKeysPopup"),
  apiKeysForm: document.getElementById("apiKeysForm"),
  apiKeysClose: document.getElementById("apiKeysClose"),
  apiKeysCancel: document.getElementById("apiKeysCancel"),
  assistantApiKeyInput: document.getElementById("assistantApiKeyInput"),
  ncbiApiKeyInput: document.getElementById("ncbiApiKeyInput"),
  unpaywallEmailInput: document.getElementById("unpaywallEmailInput"),
  workspaceSettingsState: document.getElementById("workspaceSettingsState"),
  pubmedOaOnlyToggle: document.getElementById("pubmedOaOnlyToggle"),
  pubmedOaOnlyStatus: document.getElementById("pubmedOaOnlyStatus"),
  sidebarOpenApiKeysBtn: document.getElementById("sidebarOpenApiKeysBtn"),
  assistantSendBtn: document.getElementById("assistantSendBtn"),
  assistantModelBtn: document.getElementById("assistantModelBtn"),
  assistantModelLabel: document.getElementById("assistantModelLabel"),
  assistantModelMenu: document.getElementById("assistantModelMenu"),
  assistantModelWrap: document.getElementById("assistantModelWrap"),
  assistantModelItems: document.querySelectorAll(".assistant-model-item"),
  thinkToggleBtn: document.getElementById("thinkToggleBtn"),
  thinkLabel: document.getElementById("thinkLabel"),
  thinkMenu: document.getElementById("thinkMenu"),
  thinkToggleWrap: document.getElementById("thinkToggleWrap"),
  detailPopupOverlay: document.getElementById("detailPopupOverlay"),
  detailPopup: document.getElementById("detailPopup"),
  detailPopupEyebrow: document.getElementById("detailPopupEyebrow"),
  detailPopupTitle: document.getElementById("detailPopupTitle"),
  detailPopupMeta: document.getElementById("detailPopupMeta"),
  detailPopupBody: document.getElementById("detailPopupBody"),
  detailPopupClose: document.getElementById("detailPopupClose"),
};

const assistantModelLabelMap = {
  "Gemini 3.1 Pro": "Gemini 3.1 Pro",
  "Gemini 3 Flash": "Gemini 3 Flash",
  "Gemini 3.1 Flash Lite": "Gemini 3.1 Flash Lite",
  "Gemini 2.5 Pro": "Gemini 2.5 Pro",
  "Gemini 2.5 Flash": "Gemini 2.5 Flash",
  "Gemini 2.5 Flash Lite": "Gemini 2.5 Flash Lite",
};

const assistantModelThinkingSupport = {
  "Gemini 3.1 Pro": true,
  "Gemini 3 Flash": true,
  "Gemini 3.1 Flash Lite": true,
  "Gemini 2.5 Pro": true,
  "Gemini 2.5 Flash": true,
  "Gemini 2.5 Flash Lite": false,
};

const assistantModelStorageKey = "native_researcher_model";
const assistantSidebarStorageKey = "native_researcher_sidebar_open";
const activeProjectStorageKey = "native_researcher_active_project";
const sidebarPanelStorageKey = "native_researcher_sidebar_panel";
const pubmedOaOnlyStorageKey = "native_researcher_pubmed_oa_only";
const stateModel = localStorage.getItem(assistantModelStorageKey) || "Gemini 3 Flash";
let assistantMessageUpdateFrame = null;
const assistantMessageUpdateQueue = new Set();
let resultsRenderScheduled = false;
let appErrorLoggingBound = false;

const downloadabilityLabels = {
  loading: "Downloading",
  high: "Ready",
  medium: "Ready",
  low: "Ready",
  blocked: "Unavailable",
  unavailable: "Unavailable",
  downloaded: "Downloaded",
  failed: "Error",
};

const runtime = {
  apiKey: "",
  ncbiApiKey: "",
  unpaywallEmail: "",
  pubmedOaOnly: localStorage.getItem(pubmedOaOnlyStorageKey) !== "false",
  assistantModel: stateModel,
};

state.sidebarPanel = localStorage.getItem(sidebarPanelStorageKey) || "queries";

function generateSessionId() {
  return `chat_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

function generateAssistantMessageId() {
  return `msg_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function fetchJson(url, options = {}) {
  return fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  }).then(async (response) => {
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = payload.detail || `HTTP ${response.status}`;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return payload;
  });
}

function chunkArray(items, size) {
  const normalizedSize = Math.max(1, Number(size) || 1);
  const chunks = [];
  for (let index = 0; index < items.length; index += normalizedSize) {
    chunks.push(items.slice(index, index + normalizedSize));
  }
  return chunks;
}

function trackAppEvent(level, event, message, context = {}) {
  const payload = {
    level,
    event,
    message: String(message || "").slice(0, 240),
    context,
  };
  fetch("/app/events", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    keepalive: true,
  }).catch(() => {});
}

function bindAppErrorLogging() {
  if (appErrorLoggingBound || typeof window === "undefined") return;
  appErrorLoggingBound = true;
  window.addEventListener("error", (event) => {
    trackAppEvent("error", "window_error", event.message || "Unhandled window error.", {
      filename: event.filename || "",
      lineno: event.lineno || 0,
      colno: event.colno || 0,
    });
  });
  window.addEventListener("unhandledrejection", (event) => {
    const reason = event.reason;
    const message = typeof reason === "string"
      ? reason
      : reason?.message || "Unhandled promise rejection.";
    trackAppEvent("error", "unhandled_rejection", message, {
      project_id: state.projectId || "",
    });
  });
}

function clearLegacyAssistantStorage() {
  localStorage.removeItem("native_researcher_chat_sessions");
  localStorage.removeItem("native_researcher_chat_session_id");
  localStorage.removeItem("native_researcher_thread_id");
}

function currentProjectParam() {
  return new URLSearchParams(window.location.search).get("project")?.trim() || "";
}

function projectOpenUrl(projectId) {
  return `/native_researcher?project=${encodeURIComponent(projectId)}`;
}

function projectDownloadDir() {
  return state.projectPath ? `${state.projectPath}/pdfs` : null;
}

function formatFileSize(sizeBytes) {
  const size = Number(sizeBytes || 0);
  if (!Number.isFinite(size) || size <= 0) return "0 KB";
  if (size >= 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(size / 1024))} KB`;
}

function formatRelativeTime(value) {
  if (!value) return "new";
  const target = new Date(value);
  if (Number.isNaN(target.getTime())) return "new";
  const diffMs = Date.now() - target.getTime();
  const diffMinutes = Math.max(1, Math.round(diffMs / 60000));
  if (diffMinutes < 60) return `${diffMinutes}m`;
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h`;
  const diffDays = Math.round(diffHours / 24);
  if (diffDays < 30) return `${diffDays}d`;
  const diffMonths = Math.round(diffDays / 30);
  return `${diffMonths}mo`;
}

function formatElapsedClock(startedAt) {
  if (!startedAt) return "00:00";
  const totalSeconds = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

async function runConcurrentQueue(items, concurrency, handler) {
  const source = Array.isArray(items) ? items : [];
  if (!source.length) return;
  let cursor = 0;

  async function worker() {
    while (cursor < source.length) {
      const index = cursor;
      cursor += 1;
      const item = source[index];
      if (item === undefined) return;
      await handler(item, index);
    }
  }

  await Promise.all(
    Array.from({ length: Math.min(Math.max(1, concurrency), source.length) }, () => worker()),
  );
}

function renderProjectDownloads() {
  if (!els.workspaceDownloadList || !els.workspaceDownloadCount) return;
  const items = Array.isArray(state.projectDownloads) ? state.projectDownloads : [];
  els.workspaceDownloadCount.textContent = String(items.length);
  if (!items.length) {
    els.workspaceDownloadList.innerHTML = `
      <div class="native-workspace-library-empty">
        <div class="native-workspace-library-empty-title">No papers yet</div>
        <div class="native-workspace-library-empty-copy">Downloaded files for this project will appear here.</div>
      </div>
    `;
    return;
  }
  els.workspaceDownloadList.innerHTML = items
    .map((item) => `
      <a class="native-workspace-download-item" href="${buildFileOpenUrl(item.path)}" target="_blank" rel="noreferrer">
        <span class="native-workspace-download-name">${escapeHtml(item.name)}</span>
        <span class="native-workspace-download-meta">${escapeHtml(formatFileSize(item.size_bytes))} · ${escapeHtml(formatRelativeTime(item.modified_at))}</span>
      </a>
    `)
    .join("");
}

function sidebarPanelMeta(panel) {
  if (panel === "downloads") {
    return { kicker: "Library", title: "Downloads" };
  }
  if (panel === "settings") {
    return { kicker: "Controls", title: "Settings" };
  }
  return { kicker: "History", title: "Queries" };
}

function setSidebarPanel(panel) {
  state.sidebarPanel = panel === "downloads" || panel === "settings" ? panel : "queries";
  localStorage.setItem(sidebarPanelStorageKey, state.sidebarPanel);
  els.sidebarQueriesBtn?.classList.toggle("is-active", state.sidebarPanel === "queries");
  els.sidebarDownloadsBtn?.classList.toggle("is-active", state.sidebarPanel === "downloads");
  els.sidebarSettingsBtn?.classList.toggle("is-active", state.sidebarPanel === "settings");
  if (els.sidebarQueriesPanel) els.sidebarQueriesPanel.hidden = state.sidebarPanel !== "queries";
  if (els.sidebarDownloadsPanel) els.sidebarDownloadsPanel.hidden = state.sidebarPanel !== "downloads";
  if (els.sidebarSettingsPanel) els.sidebarSettingsPanel.hidden = state.sidebarPanel !== "settings";
  const meta = sidebarPanelMeta(state.sidebarPanel);
  if (els.sidebarPanelKicker) els.sidebarPanelKicker.textContent = meta.kicker;
  if (els.sidebarPanelTitle) els.sidebarPanelTitle.textContent = meta.title;
  scheduleProjectStateSave();
}

function queryTitleFromPayload(payload) {
  const raw = payload?.query?.trim() || "Untitled query";
  return raw.length > 42 ? `${raw.slice(0, 42).trim()}…` : raw;
}

function currentQueryRecord() {
  return state.queryHistory.find((item) => item.id === state.activeQueryId) || null;
}

function renderQueryDetail() {
  if (!els.workspaceQueryDetail) return;
  const record = state.queryHistory.find((item) => item.id === state.queryDetailId) || currentQueryRecord();
  if (!record) {
    els.workspaceQueryDetail.innerHTML = `
      <div class="native-workspace-library-empty">
        <div class="native-workspace-library-empty-title">Query details</div>
        <div class="native-workspace-library-empty-copy">Select a saved query to inspect the exact request and result metadata.</div>
      </div>
    `;
    return;
  }
  const meta = record.meta || {};
  const filters = [
    record.search_payload?.year_start ? `from ${record.search_payload.year_start}` : "",
    record.search_payload?.year_end ? `to ${record.search_payload.year_end}` : "",
    record.search_payload?.article_type ? record.search_payload.article_type : "",
  ].filter(Boolean).join(" · ");
  els.workspaceQueryDetail.innerHTML = `
    <div class="native-query-detail-header">
      <div class="native-query-detail-kicker">Query Details</div>
      <div class="native-query-detail-title">${escapeHtml(record.title || "Saved query")}</div>
      <div class="native-query-detail-meta">${escapeHtml(formatSessionTime(record.updated_at))}</div>
    </div>
    <div class="native-query-detail-grid">
      <div class="native-query-detail-item">
        <div class="native-query-detail-label">Query</div>
        <div class="native-query-detail-value">${escapeHtml(record.search_payload?.query || "-")}</div>
      </div>
      <div class="native-query-detail-item">
        <div class="native-query-detail-label">Resolved query</div>
        <div class="native-query-detail-value">${escapeHtml(meta.full_query || "-")}</div>
      </div>
      <div class="native-query-detail-item">
        <div class="native-query-detail-label">Results</div>
        <div class="native-query-detail-value">${escapeHtml(String(meta.total_results_found ?? 0))} total · ${escapeHtml(String(meta.fetched_results ?? record.articles?.length ?? 0))} fetched</div>
      </div>
      <div class="native-query-detail-item">
        <div class="native-query-detail-label">Requests</div>
        <div class="native-query-detail-value">${escapeHtml(String(meta.request_count ?? 0))} requests · ${escapeHtml(String(meta.elapsed_ms ?? 0))} ms</div>
      </div>
      <div class="native-query-detail-item">
        <div class="native-query-detail-label">Filters</div>
        <div class="native-query-detail-value">${escapeHtml(filters || "None")}</div>
      </div>
      <div class="native-query-detail-item">
        <div class="native-query-detail-label">Cached</div>
        <div class="native-query-detail-value">${meta.cache_hit ? "Yes" : "No"}</div>
      </div>
    </div>
  `;
}

function renderQueryHistory() {
  if (!els.workspaceQueryList || !els.workspaceQueryCount) return;
  els.workspaceQueryCount.textContent = String(state.queryHistory.length);
  if (!state.queryHistory.length) {
    els.workspaceQueryList.innerHTML = `
      <div class="native-workspace-library-empty">
        <div class="native-workspace-library-empty-title">No queries yet</div>
        <div class="native-workspace-library-empty-copy">Search history for this project will appear here.</div>
      </div>
    `;
    renderQueryDetail();
    return;
  }
  els.workspaceQueryList.innerHTML = state.queryHistory
    .map((item) => `
      <button
        type="button"
        class="native-query-history-item ${item.id === state.activeQueryId ? "is-active" : ""}"
        data-query-id="${item.id}"
      >
        <span class="native-query-history-title">${escapeHtml(item.title || "Saved query")}</span>
        <span class="native-query-history-meta">${escapeHtml(formatSessionAgeCompact(item.updated_at))} · ${escapeHtml(String(item.meta?.fetched_results ?? item.articles?.length ?? 0))} items</span>
      </button>
    `)
    .join("");
  els.workspaceQueryList.querySelectorAll("[data-query-id]").forEach((node) => {
    node.addEventListener("click", () => {
      restoreQueryRecord(node.dataset.queryId);
    });
  });
  renderQueryDetail();
}

function syncSidebarQuickControls() {
  if (els.sidebarQuickQuery) {
    const nextQuery = els.query?.value?.trim() || "";
    if (!els.sidebarQuickQuery.value.trim() || nextQuery) {
      els.sidebarQuickQuery.value = nextQuery;
    }
    autoResizeTextarea(els.sidebarQuickQuery);
  }
  if (els.sidebarQuickMaxResults && els.maxResults) {
    const nextMax = normalizedNumber(els.maxResults, 20);
    els.sidebarQuickMaxResults.value = String(nextMax);
  }
  if (els.sidebarQuickStatus) {
    els.sidebarQuickStatus.textContent = "Uses the same OA-aware PubMed search and downloader.";
  }
}

function createQueryRecordFromDataset(response) {
  const payload = cloneJson(state.lastSearchPayload || {});
  const timestamp = new Date().toISOString();
  return {
    id: `qry_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`,
    title: queryTitleFromPayload(payload),
    created_at: timestamp,
    updated_at: timestamp,
    search_payload: payload,
    meta: cloneJson(response.meta || null),
    articles: cloneJson(response.articles || []),
  };
}

function upsertActiveQueryRecord() {
  if (!state.lastSearchPayload?.query || !state.lastPubmedResponse?.articles?.length) return;
  const existingIndex = state.activeQueryId
    ? state.queryHistory.findIndex((item) => item.id === state.activeQueryId)
    : -1;
  const record = existingIndex >= 0
    ? {
      ...cloneJson(state.queryHistory[existingIndex]),
      title: queryTitleFromPayload(state.lastSearchPayload),
      updated_at: new Date().toISOString(),
      search_payload: cloneJson(state.lastSearchPayload),
      meta: cloneJson(state.lastPubmedResponse.meta || null),
      articles: cloneJson(state.lastPubmedResponse.articles || []),
    }
    : createQueryRecordFromDataset(state.lastPubmedResponse);
  state.activeQueryId = record.id;
  state.queryDetailId = record.id;
  if (existingIndex >= 0) {
    state.queryHistory.splice(existingIndex, 1);
  }
  state.queryHistory.unshift(record);
  state.queryHistory = state.queryHistory.slice(0, 30);
  renderQueryHistory();
}

function projectStatePayload() {
  upsertActiveQueryRecord();
  persistAssistantSessions({ scheduleSave: false });
  return {
    active_query_id: state.activeQueryId,
    selected_ids: [...state.selectedIds],
    detail_article_id: state.detailArticleId,
    sidebar_panel: state.sidebarPanel,
    query_detail_id: state.queryDetailId || state.activeQueryId,
    downloadability_cache: cloneJson(state.downloadabilityCache),
    query_history: cloneJson(state.queryHistory),
    current_session_id: state.currentSessionId,
    assistant_sessions: cloneJson(state.assistantSessions),
  };
}

let projectStateSaveTimer = null;

function scheduleProjectStateSave() {
  if (!state.projectId) return;
  if (projectStateSaveTimer) clearTimeout(projectStateSaveTimer);
  projectStateSaveTimer = setTimeout(() => {
    projectStateSaveTimer = null;
    void saveProjectState();
  }, 220);
}

async function saveProjectState() {
  if (!state.projectId) return;
  try {
    await fetchJson(`/app/projects/${encodeURIComponent(state.projectId)}/state`, {
      method: "PUT",
      body: JSON.stringify(projectStatePayload()),
    });
  } catch (error) {
    trackAppEvent("error", "project_state_save_failed", error.message || "Project state could not be saved.", {
      project_id: state.projectId || "",
    });
  }
}

function restoreQueryRecord(queryId) {
  const record = state.queryHistory.find((item) => item.id === queryId);
  if (!record) return;
  state.activeQueryId = record.id;
  state.queryDetailId = record.id;
  state.lastSearchPayload = cloneJson(record.search_payload || null);
  applyArticleDataset(
    {
      meta: cloneJson(record.meta || null),
      articles: cloneJson(record.articles || []),
    },
    { persist: false }
  );
  if (record.search_payload) {
    els.query.value = record.search_payload.query || "";
    els.yearStart.value = record.search_payload.year_start ? String(record.search_payload.year_start) : "";
    els.yearEnd.value = record.search_payload.year_end ? String(record.search_payload.year_end) : "";
    els.maxResults.value = String(record.search_payload.max_results || 50);
    autoResizeTextarea(els.query);
  }
  syncSidebarQuickControls();
  renderQueryHistory();
  scheduleProjectStateSave();
}

async function loadProjectState() {
  if (!state.projectId) return;
  try {
    const payload = await fetchJson(`/app/projects/${encodeURIComponent(state.projectId)}/state`);
    const restoredSelectedIds = new Set(Array.isArray(payload.selected_ids) ? payload.selected_ids : []);
    const restoredDetailArticleId = Number.isInteger(payload.detail_article_id) ? payload.detail_article_id : null;
    state.queryHistory = Array.isArray(payload.query_history) ? payload.query_history : [];
    state.activeQueryId = payload.active_query_id || state.queryHistory[0]?.id || null;
    state.queryDetailId = payload.query_detail_id || state.activeQueryId;
    state.downloadabilityCache = sanitizePersistedDownloadabilityCache(payload.downloadability_cache);
    state.selectedIds = new Set();
    state.detailArticleId = null;
    applyAssistantProjectState(payload);
    setSidebarPanel(payload.sidebar_panel || state.sidebarPanel);
    renderQueryHistory();
    if (state.activeQueryId) {
      restoreQueryRecord(state.activeQueryId);
      state.selectedIds = restoredSelectedIds;
      state.detailArticleId = restoredDetailArticleId;
      renderResults();
    } else {
      state.lastSearchPayload = null;
      state.lastPubmedResponse = null;
      applyArticleDataset({ meta: null, articles: [] }, { persist: false });
      if (els.query) {
        els.query.value = "";
        autoResizeTextarea(els.query);
      }
      renderResults();
    }
  } catch (error) {
    state.queryHistory = [];
    state.activeQueryId = null;
    state.queryDetailId = null;
    state.downloadabilityCache = {};
    state.selectedIds = new Set();
    state.detailArticleId = null;
    state.lastSearchPayload = null;
    state.lastPubmedResponse = null;
    applyArticleDataset({ meta: null, articles: [] }, { persist: false });
    resetAssistantProjectState();
    renderAssistantMessages();
    renderChatHistory();
    renderQueryHistory();
    trackAppEvent("error", "project_state_load_failed", error.message || "Project state could not be loaded.", {
      project_id: state.projectId || "",
    });
  }
}

async function loadProjectDownloads() {
  if (!state.projectId) {
    state.projectDownloads = [];
    renderProjectDownloads();
    return;
  }
  try {
    const payload = await fetchJson(`/app/projects/${encodeURIComponent(state.projectId)}/downloads`);
    state.projectDownloads = Array.isArray(payload.items) ? payload.items : [];
    renderProjectDownloads();
  } catch (error) {
    state.projectDownloads = [];
    renderProjectDownloads();
    trackAppEvent("error", "project_download_list_failed", error.message || "Project downloads could not be loaded.", {
      project_id: state.projectId || "",
    });
  }
}

async function touchProjectActivity() {
  if (!state.projectId) return;
  try {
    await fetchJson(`/app/projects/${encodeURIComponent(state.projectId)}/touch`, {
      method: "POST",
    });
  } catch (_error) {
    return;
  }
}

function updateProjectUI() {
  const projectName = state.projectName || "Project";
  if (els.projectNameDisplay) {
    els.projectNameDisplay.textContent = projectName;
    els.projectNameDisplay.title = `${projectName} · Double-click to rename`;
  }
  if (els.projectNameInput && !state.projectRenaming) {
    els.projectNameInput.value = projectName;
  }
  document.title = `${projectName} — Native Researcher`;
}

function renderSettingsPanel() {
  const enabled = Boolean(runtime.pubmedOaOnly);
  if (els.workspaceSettingsState) {
    els.workspaceSettingsState.textContent = enabled ? "On" : "Off";
  }
  if (els.pubmedOaOnlyToggle) {
    els.pubmedOaOnlyToggle.checked = enabled;
  }
  if (els.pubmedOaOnlyStatus) {
    els.pubmedOaOnlyStatus.textContent = enabled
      ? "OA filter is active. Every PubMed search adds free full text[sb]."
      : "OA filter is off. PubMed queries run exactly as written.";
  }
}

function setApiKeysDialogOpen(next) {
  const open = Boolean(next);
  els.apiKeysPopup?.classList.toggle("is-open", open);
  els.apiKeysOverlay?.classList.toggle("is-open", open);
  if (els.apiKeysPopup) els.apiKeysPopup.hidden = !open;
  if (els.apiKeysOverlay) els.apiKeysOverlay.hidden = !open;
}

function applyApiKeyValues(payload = {}) {
  runtime.apiKey = payload.assistant_api_key || localStorage.getItem("researcher2_api_key") || "";
  runtime.ncbiApiKey = payload.ncbi_api_key || "";
  runtime.unpaywallEmail = payload.unpaywall_email || "";
  runtime.pubmedOaOnly = payload.pubmed_oa_only !== undefined
    ? Boolean(payload.pubmed_oa_only)
    : localStorage.getItem(pubmedOaOnlyStorageKey) !== "false";
  localStorage.setItem("researcher2_api_key", runtime.apiKey);
  localStorage.setItem(pubmedOaOnlyStorageKey, runtime.pubmedOaOnly ? "true" : "false");
  if (els.assistantApiKeyInput) els.assistantApiKeyInput.value = runtime.apiKey;
  if (els.ncbiApiKeyInput) els.ncbiApiKeyInput.value = runtime.ncbiApiKey;
  if (els.unpaywallEmailInput) els.unpaywallEmailInput.value = runtime.unpaywallEmail;
  renderSettingsPanel();
}

async function loadApiKeys() {
  const payload = await fetchJson("/app/api-keys");
  applyApiKeyValues(payload);
}

async function saveApiKeys(overrides = {}, options = {}) {
  const { closeDialog = true } = options;
  const payload = await fetchJson("/app/api-keys", {
    method: "PUT",
    body: JSON.stringify({
      assistant_api_key: runtime.apiKey,
      ncbi_api_key: runtime.ncbiApiKey,
      unpaywall_email: runtime.unpaywallEmail,
      pubmed_oa_only: runtime.pubmedOaOnly,
      ...overrides,
    }),
  });
  applyApiKeyValues(payload);
  trackAppEvent("info", "api_keys_saved_ui", "API keys updated from the native UI.", {
    has_ncbi_api_key: Boolean(runtime.ncbiApiKey),
    has_unpaywall_email: Boolean(runtime.unpaywallEmail),
    pubmed_oa_only: Boolean(runtime.pubmedOaOnly),
  });
  if (closeDialog) {
    setApiKeysDialogOpen(false);
  }
}

function applyActiveProject(project) {
  if (!project?.id) return;
  const projectChanged = Boolean(state.projectId && state.projectId !== project.id);
  if (projectChanged) {
    if (state.assistantStreamAbort) {
      state.assistantStreamAbort.abort();
      state.assistantStreamAbort = null;
    }
    state.downloadabilityCache = {};
    state.downloadabilityById = {};
    resetAssistantProjectState();
    renderAssistantMessages();
    renderChatHistory();
  }
  state.projectId = project.id;
  state.projectPath = project.project_path || null;
  state.projectName = project.name || "Project";
  localStorage.setItem(activeProjectStorageKey, state.projectId);
  updateProjectUI();
  void loadProjectDownloads();
  void loadProjectState();
  if (currentProjectParam() !== state.projectId) {
    window.history.replaceState({}, "", projectOpenUrl(state.projectId));
  }
}

async function createDefaultProject() {
  return fetchJson("/app/projects", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

async function loadProject(projectId) {
  return fetchJson(`/app/projects/${encodeURIComponent(projectId)}`);
}

async function ensureActiveProject() {
  const candidates = [currentProjectParam(), localStorage.getItem(activeProjectStorageKey) || ""].filter(Boolean);
  for (const candidate of candidates) {
    try {
      const project = await loadProject(candidate);
      applyActiveProject(project);
      return;
    } catch (_error) {
      if (candidate === localStorage.getItem(activeProjectStorageKey)) {
        localStorage.removeItem(activeProjectStorageKey);
      }
    }
  }

  const project = await createDefaultProject();
  applyActiveProject(project);
}

function setProjectRenaming(next) {
  state.projectRenaming = Boolean(next);
  if (!els.projectNameDisplay || !els.projectNameInput) return;
  els.projectNameDisplay.hidden = state.projectRenaming;
  els.projectNameInput.hidden = !state.projectRenaming;
  if (!state.projectRenaming) {
    els.projectNameInput.value = state.projectName || "Project";
  }
}

function startProjectRename() {
  if (!state.projectId || state.projectRenameSaving || !els.projectNameInput) return;
  setProjectRenaming(true);
  els.projectNameInput.focus();
  els.projectNameInput.select();
}

function cancelProjectRename() {
  if (state.projectRenameSaving) return;
  setProjectRenaming(false);
}

async function saveProjectRename() {
  if (!state.projectId || !state.projectRenaming || state.projectRenameSaving || !els.projectNameInput) return;
  const nextName = els.projectNameInput.value.trim();
  if (!nextName || nextName === state.projectName) {
    cancelProjectRename();
    return;
  }

  state.projectRenameSaving = true;
  els.projectNameInput.disabled = true;
  try {
    const project = await fetchJson(`/app/projects/${encodeURIComponent(state.projectId)}`, {
      method: "PATCH",
      body: JSON.stringify({ name: nextName }),
    });
    applyActiveProject(project);
    trackAppEvent("info", "project_renamed_ui", project.name || nextName, {
      project_id: project.id || state.projectId,
    });
  } catch (error) {
    console.error("Project rename failed.", error);
    trackAppEvent("error", "project_rename_failed", error.message || "Project rename failed.", {
      project_id: state.projectId,
      attempted_name: nextName,
    });
  } finally {
    state.projectRenameSaving = false;
    els.projectNameInput.disabled = false;
    setProjectRenaming(false);
  }
}

function scheduleResultsRender() {
  if (resultsRenderScheduled) return;
  resultsRenderScheduled = true;
  const flush = () => {
    resultsRenderScheduled = false;
    renderResults();
  };
  if (typeof window !== "undefined" && typeof window.requestAnimationFrame === "function") {
    window.requestAnimationFrame(flush);
  } else {
    setTimeout(flush, 0);
  }
}

function createLinkedAbortController(externalSignal) {
  const controller = new AbortController();
  if (!externalSignal) return controller;
  if (externalSignal.aborted) {
    controller.abort(externalSignal.reason);
    return controller;
  }
  externalSignal.addEventListener("abort", () => controller.abort(externalSignal.reason), { once: true });
  return controller;
}

async function streamJsonEvents(url, options = {}, onEvent) {
  const {
    headers: optionHeaders = {},
    signal: externalSignal,
    idleTimeoutMs: idleTimeoutOption,
    responseTimeoutMs: responseTimeoutOption,
    ...fetchOptions
  } = options;
  const idleTimeoutMs = Number.isFinite(idleTimeoutOption) ? idleTimeoutOption : 45000;
  const responseTimeoutMs = Number.isFinite(responseTimeoutOption) ? responseTimeoutOption : 20000;
  const requestController = createLinkedAbortController(externalSignal);

  let responseTimeoutId = setTimeout(() => {
    if (!requestController.signal.aborted) {
      requestController.abort(new Error("Model stream timed out."));
    }
  }, responseTimeoutMs);

  let response;
  try {
    response = await fetch(url, {
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        ...optionHeaders,
      },
      ...fetchOptions,
      signal: requestController.signal,
    });
  } catch (error) {
    clearTimeout(responseTimeoutId);
    if (requestController.signal.aborted && !externalSignal?.aborted) {
      throw new Error("Model stream timed out.");
    }
    throw error;
  }
  clearTimeout(responseTimeoutId);

  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail = payload.detail || `HTTP ${response.status}`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  if (!response.body) {
    throw new Error("Live response stream was not available.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    let timeoutId = null;
    const nextChunk = Promise.race([
      reader.read(),
      new Promise((_, reject) => {
        timeoutId = setTimeout(() => reject(new Error("Model stream timed out.")), idleTimeoutMs);
      }),
    ]);
    const { done, value } = await nextChunk.finally(() => {
      if (timeoutId) clearTimeout(timeoutId);
    });
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const rawEvent = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const dataLines = rawEvent
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart());
      if (dataLines.length) {
        onEvent(JSON.parse(dataLines.join("\n")));
      }
      boundary = buffer.indexOf("\n\n");
    }

    if (done) {
      const trailingDataLines = buffer
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart());
      if (trailingDataLines.length) {
        onEvent(JSON.parse(trailingDataLines.join("\n")));
      }
      break;
    }
  }
}

function autoResizeTextarea(node) {
  if (!node) return;
  node.style.height = "0px";
  node.style.height = `${node.scrollHeight}px`;
}

function normalizedNumber(node, fallback) {
  const value = Number(node.value);
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

function helperArticlePayload() {
  return state.allArticles.map((article) => ({
    id: article.id,
    title: article.title,
    year: article.year || null,
    article_type: articleTypeLabel(article) !== "-" ? articleTypeLabel(article) : null,
    citation_count: Number.isInteger(article.citation_count) ? article.citation_count : null,
    mesh_terms: article.mesh_terms || [],
    abstract: article.abstract || "",
    pmid: article.pmid || null,
    doi: article.doi || null,
    journal: article.journal || null,
  }));
}

function parseOptionalNumber(value) {
  const parsed = Number.parseInt(String(value ?? "").trim(), 10);
  return Number.isFinite(parsed) ? parsed : null;
}

function cloneJson(value) {
  return JSON.parse(JSON.stringify(value));
}

function sanitizeAssistantAction(action) {
  if (!action) return null;
  const details = action.details || {};
  return {
    type: action.type,
    name: action.name,
    title: action.title,
    status: action.status,
    call_id: action.call_id,
    details: {
      query: details.query || "",
      year_start: details.year_start ?? null,
      year_end: details.year_end ?? null,
      max_results: details.max_results ?? null,
      article_type: details.article_type ?? null,
      min_cite: details.min_cite ?? null,
      count: Array.isArray(details.articles) ? details.articles.length : details.count ?? null,
    },
  };
}

function sanitizeAssistantMessage(message) {
  return {
    id: message.id || generateAssistantMessageId(),
    role: message.role,
    text: message.text || "",
    pending: false,
    thinking: message.thinking || message.liveThinking || "",
    thinkingEnabled: Boolean(message.thinkingEnabled),
    meta: message.meta || "",
    actions: Array.isArray(message.actions)
      ? message.actions.map(sanitizeAssistantAction).filter(Boolean)
      : [],
  };
}

function sessionTitleFromMessages(messages) {
  const firstUser = messages.find((item) => item.role === "user" && item.text?.trim());
  const source = firstUser?.text?.trim() || "New chat";
  return source.length > 42 ? `${source.slice(0, 42).trim()}…` : source;
}

function sessionPreviewFromMessages(messages) {
  const latest = [...messages].reverse().find((item) => item.text?.trim());
  const source = latest?.text?.trim() || "No messages yet";
  return source.length > 72 ? `${source.slice(0, 72).trim()}…` : source;
}

function sessionHasContent(session) {
  if (!Array.isArray(session?.messages)) return false;
  return session.messages.some((item) => Boolean(
    item?.text?.trim()
    || item?.thinking?.trim()
    || item?.liveThinking?.trim()
    || item?.meta?.trim()
    || item?.actions?.length
  ));
}

function createAssistantSession(seed = {}) {
  const messages = Array.isArray(seed.messages) ? seed.messages.map((item) => cloneJson(item)) : [];
  return {
    id: seed.id || generateSessionId(),
    threadId: seed.threadId || null,
    title: seed.title || sessionTitleFromMessages(messages),
    preview: seed.preview || sessionPreviewFromMessages(messages),
    updatedAt: seed.updatedAt || new Date().toISOString(),
    messages,
  };
}

function resetAssistantProjectState() {
  state.assistantSessions = [];
  state.currentSessionId = null;
  state.assistantThreadId = null;
  state.assistantMessages = [];
  state.chatHistoryExpanded = false;
  state.chatHistoryOpen = false;
}

function persistAssistantSessions({ scheduleSave = true } = {}) {
  const nextSessions = state.assistantSessions
    .filter(sessionHasContent)
    .slice(0, 24)
    .map((item) => createAssistantSession(item));
  state.assistantSessions = nextSessions;
  if (!state.currentSessionId || !nextSessions.some((item) => item.id === state.currentSessionId)) {
    state.currentSessionId = nextSessions[0]?.id || null;
  }
  if (scheduleSave) scheduleProjectStateSave();
}

function applyAssistantProjectState(payload = {}) {
  const parsedSessions = Array.isArray(payload.assistant_sessions)
    ? payload.assistant_sessions.map((item) => createAssistantSession(item)).filter(sessionHasContent)
    : [];
  state.assistantSessions = parsedSessions;
  state.currentSessionId = payload.current_session_id || null;
  if (!state.currentSessionId || !state.assistantSessions.some((item) => item.id === state.currentSessionId)) {
    state.currentSessionId = state.assistantSessions[0]?.id || null;
  }
  state.chatHistoryExpanded = false;
  state.assistantThreadId = currentAssistantSession()?.threadId || null;
  state.assistantMessages = Array.isArray(currentAssistantSession()?.messages)
    ? currentAssistantSession().messages.map((item) => cloneJson(item))
    : [];
  setChatHistoryOpen(false);
  renderAssistantMessages();
  renderChatHistory();
}

function syncCurrentSession({ persist = true } = {}) {
  if (!state.currentSessionId) return;
  const index = state.assistantSessions.findIndex((item) => item.id === state.currentSessionId);
  if (index === -1) return;
  const session = state.assistantSessions[index];
  session.threadId = state.assistantThreadId;
  session.messages = state.assistantMessages.map(sanitizeAssistantMessage);
  session.title = sessionTitleFromMessages(session.messages);
  session.preview = sessionPreviewFromMessages(session.messages);
  session.updatedAt = new Date().toISOString();
  state.assistantSessions.splice(index, 1);
  state.assistantSessions.unshift(session);
  state.currentSessionId = session.id;
  renderChatHistory();
  if (persist) persistAssistantSessions();
}

function switchAssistantSession(sessionId) {
  if (!sessionId) return;
  if (state.currentSessionId && state.currentSessionId !== sessionId) syncCurrentSession();
  const index = state.assistantSessions.findIndex((item) => item.id === sessionId);
  if (index === -1) return;
  const [session] = state.assistantSessions.splice(index, 1);
  state.assistantSessions.unshift(session);
  state.currentSessionId = session.id;
  state.assistantThreadId = session.threadId || null;
  state.assistantMessages = Array.isArray(session.messages) ? session.messages.map((item) => cloneJson(item)) : [];
  renderAssistantMessages();
  renderChatHistory();
  persistAssistantSessions();
}

function createNewAssistantChat() {
  state.assistantStreamAbort?.abort();
  state.assistantStreamAbort = null;
  if (state.currentSessionId) syncCurrentSession();
  state.currentSessionId = null;
  state.assistantThreadId = null;
  state.assistantMessages = [];
  setChatHistoryOpen(false);
  renderAssistantMessages();
  renderChatHistory();
  persistAssistantSessions();
  requestAnimationFrame(() => {
    els.assistantInput?.focus();
  });
}

function formatSessionTime(isoStamp) {
  if (!isoStamp) return "";
  const value = new Date(isoStamp);
  if (Number.isNaN(value.getTime())) return "";
  return new Intl.DateTimeFormat("en-US", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(value);
}

function formatSessionAgeCompact(isoStamp) {
  if (!isoStamp) return "";
  const value = new Date(isoStamp);
  if (Number.isNaN(value.getTime())) return "";
  const diffMs = Math.max(0, Date.now() - value.getTime());
  const diffMinutes = Math.floor(diffMs / 60000);
  if (diffMinutes < 1) return "now";
  if (diffMinutes < 60) return `${diffMinutes}m`;
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 7) return `${diffDays}d`;
  return new Intl.DateTimeFormat("en-US", {
    day: "2-digit",
    month: "short",
  }).format(value);
}

function currentAssistantSession() {
  return state.assistantSessions.find((item) => item.id === state.currentSessionId) || null;
}

function renderAssistantHeader() {
  if (els.assistantHeaderTitle) {
    els.assistantHeaderTitle.textContent = state.chatHistoryOpen
      ? "Chats"
      : (currentAssistantSession()?.title || "New chat");
  }
  if (els.assistantHistoryToggleBtn) {
    const label = state.chatHistoryOpen ? "Back to chat" : "Open chat history";
    els.assistantHistoryToggleBtn.setAttribute("aria-label", label);
    els.assistantHistoryToggleBtn.setAttribute("title", label);
  }
}

function setChatHistoryOpen(next) {
  state.chatHistoryOpen = Boolean(next);
  els.assistantPanel?.classList.toggle("is-history-open", state.chatHistoryOpen);
  if (els.assistantHistoryPanel) {
    els.assistantHistoryPanel.hidden = !state.chatHistoryOpen;
  }
  renderAssistantHeader();
}

function renderChatHistory() {
  if (!els.chatHistoryList) return;
  if (!state.assistantSessions.length) {
    els.chatHistoryList.innerHTML = '<div class="native-chat-empty">No chats yet.</div>';
    renderAssistantHeader();
    return;
  }
  const visibleSessions = state.chatHistoryExpanded ? state.assistantSessions : state.assistantSessions.slice(0, 4);
  els.chatHistoryList.innerHTML = [
    ...visibleSessions.map((session) => {
      const title = session.title || "New chat";
      const preview = session.preview || "No messages yet";
      const updatedAt = formatSessionTime(session.updatedAt);
      const summary = [title, preview, updatedAt].filter(Boolean).join(" • ");
      const age = formatSessionAgeCompact(session.updatedAt);
      return `
        <button
          type="button"
          class="native-chat-history-item ${session.id === state.currentSessionId ? "is-active" : ""}"
          data-session-id="${session.id}"
          title="${escapeHtml(summary)}"
          aria-label="${escapeHtml(summary)}"
        >
          <span class="native-chat-history-title">${escapeHtml(title)}</span>
          <span class="native-chat-history-time">${escapeHtml(age)}</span>
        </button>
      `;
    }),
    state.assistantSessions.length > 4
      ? `
        <button
          type="button"
          class="native-chat-history-more"
          data-history-toggle="true"
        >
          ${state.chatHistoryExpanded ? "Show less" : `View all (${state.assistantSessions.length})`}
        </button>
      `
      : "",
  ].join("");

  els.chatHistoryList.querySelectorAll("[data-session-id]").forEach((node) => {
    node.addEventListener("click", () => {
      switchAssistantSession(node.dataset.sessionId);
      setChatHistoryOpen(false);
    });
  });
  els.chatHistoryList.querySelector("[data-history-toggle]")?.addEventListener("click", () => {
    state.chatHistoryExpanded = !state.chatHistoryExpanded;
    renderChatHistory();
  });
  renderAssistantHeader();
}

function setSidebarOpen(next, { immediate = false } = {}) {
  void immediate;
  state.sidebarOpen = Boolean(next);
  els.chatSidebar?.classList.toggle("is-open", state.sidebarOpen);
  els.chatSidebar?.classList.toggle("is-collapsed", !state.sidebarOpen);
  localStorage.setItem(assistantSidebarStorageKey, state.sidebarOpen ? "true" : "false");
}

function articleTypeLabel(article) {
  return article.article_type || article.article_types?.[0] || "-";
}

function citationLabel(article) {
  if (Number.isInteger(article.citation_count)) return String(article.citation_count);
  if (state.citationsLoading && (article.pmid || article.doi)) return "…";
  return "-";
}

function articleLinks(article) {
  return {
    doi: article.doi ? `https://doi.org/${encodeURIComponent(article.doi)}` : null,
    pmc: article.pmc_id ? `https://pmc.ncbi.nlm.nih.gov/articles/${article.pmc_id}/` : null,
    pubmed: article.pmid ? `https://pubmed.ncbi.nlm.nih.gov/${article.pmid}/` : null,
  };
}

function bestArticleLink(article) {
  const links = articleLinks(article);
  return links.pmc || links.doi || links.pubmed || null;
}

function articleReference(article) {
  return {
    title: article.title || null,
    year: article.year || null,
    doi: article.doi || null,
    pmc_id: article.pmc_id || null,
    pmid: article.pmid || null,
  };
}

function buildFileOpenUrl(filePath) {
  return `/pdf/file?path=${encodeURIComponent(filePath)}`;
}

function isDownloadReadyStatus(status) {
  return ["high", "medium", "low", "downloaded"].includes(status);
}

function getDownloadability(articleId) {
  return state.downloadabilityById[articleId] || {
    status: "unavailable",
    label: downloadabilityLabels.unavailable,
    detail: "No article identifiers available.",
    openUrl: null,
  };
}

function setArticleDownloadability(articleId, next) {
  const current = getDownloadability(articleId);
  state.downloadabilityById[articleId] = {
    ...current,
    ...next,
  };
}

function persistableDownloadabilityInfo(info) {
  if (!info || !info.status) return null;
  if (info.status !== "downloaded") return null;
  return {
    status: info.status,
    label: info.label || "",
    detail: info.detail || "",
    openUrl: info.openUrl || null,
  };
}

function sanitizePersistedDownloadabilityCache(cache) {
  const source = cache && typeof cache === "object" ? cache : {};
  return Object.fromEntries(
    Object.entries(source).filter(([, info]) => info?.status === "downloaded"),
  );
}

function rememberArticleDownloadability(article, info) {
  const cacheKey = articleIdentityKey(article);
  const stableInfo = persistableDownloadabilityInfo(info);
  if (!cacheKey) return;
  const previous = state.downloadabilityCache[cacheKey] || null;
  if (!stableInfo) {
    if (previous) {
      delete state.downloadabilityCache[cacheKey];
      scheduleProjectStateSave();
    }
    return;
  }
  if (
    previous
    && previous.status === stableInfo.status
    && previous.label === stableInfo.label
    && previous.detail === stableInfo.detail
    && previous.openUrl === stableInfo.openUrl
  ) {
    return;
  }
  state.downloadabilityCache[cacheKey] = stableInfo;
  scheduleProjectStateSave();
}

function downloadabilityDisplay(articleId) {
  const info = getDownloadability(articleId);
  if (info.status === "loading") {
    return { tone: "pending", text: info.label || downloadabilityLabels.loading };
  }
  if (info.status === "downloaded") {
    return { tone: "ready", text: downloadabilityLabels.downloaded };
  }
  if (isDownloadReadyStatus(info.status)) {
    return { tone: "ready", text: downloadabilityLabels.high };
  }
  return { tone: "blocked", text: info.label || downloadabilityLabels.unavailable };
}

function downloadControlMarkup(article) {
  const info = getDownloadability(article.id);
  const display = downloadabilityDisplay(article.id);
  const canOpen = Boolean(info.openUrl);
  const disabled = display.tone !== "ready" ? "disabled" : "";
  const buttonClass = display.tone === "ready"
    ? "btn btn-primary btn-xs row-download-btn"
    : "btn btn-secondary btn-xs row-download-btn";
  const buttonLabel = display.tone === "pending"
    ? (info.label || downloadabilityLabels.loading)
    : display.tone === "blocked"
      ? downloadabilityLabels.unavailable
      : "Download";
  return canOpen
    ? `<a class="btn btn-primary btn-xs file-open-btn" href="${info.openUrl}" target="_blank" rel="noreferrer">Open</a>`
    : `<button type="button" class="${buttonClass}" data-id="${article.id}" ${disabled}>${escapeHtml(buttonLabel)}</button>`;
}

function renderDownloadabilityCell(article) {
  return `<div class="download-action-cell">${downloadControlMarkup(article)}</div>`;
}

function seedDownloadability(articles) {
  const source = Array.isArray(articles) ? articles : [];
  state.downloadabilityById = Object.fromEntries(
    source.map((article) => {
      const cached = state.downloadabilityCache[articleIdentityKey(article)] || null;
      if (cached) {
        return [article.id, { ...cached }];
      }
      return [
        article.id,
        article.pmc_id || article.doi || article.pmid
          ? {
            status: "high",
            label: downloadabilityLabels.high,
            detail: "Ready to download.",
            openUrl: null,
          }
          : {
            status: "unavailable",
            label: downloadabilityLabels.unavailable,
            detail: "No PMID, DOI, or PMCID signal.",
            openUrl: null,
          },
      ];
    }),
  );
}

async function requestArticleDownload(article, options = {}) {
  const { timeoutMs = null, signal = null } = options;
  const controller = createLinkedAbortController(signal);
  const timeoutId = Number.isFinite(timeoutMs) && timeoutMs > 0
    ? setTimeout(() => {
      if (!controller.signal.aborted) {
        controller.abort(new Error("Single article download timed out."));
      }
    }, timeoutMs)
    : null;
  let data;
  try {
    data = await fetchJson("/pdf/download", {
      method: "POST",
      body: JSON.stringify({
        articles: [articleReference(article)],
        download_dir: projectDownloadDir(),
        max_articles: 1,
      }),
      signal: controller.signal,
    });
  } catch (error) {
    if (timeoutId) clearTimeout(timeoutId);
    if (controller.signal.aborted && !signal?.aborted) {
      throw new Error("Single article download timed out.");
    }
    throw error;
  }
  if (timeoutId) clearTimeout(timeoutId);
  return data.results?.[0] || null;
}

async function requestBatchDownload(articles, options = {}) {
  const { timeoutMs = null, signal = null } = options;
  const batch = Array.isArray(articles) ? articles.filter(Boolean) : [];
  if (!batch.length) {
    return {
      total: 0,
      success_count: 0,
      failed_count: 0,
      results: [],
    };
  }
  const controller = createLinkedAbortController(signal);
  const timeoutId = Number.isFinite(timeoutMs) && timeoutMs > 0
    ? setTimeout(() => {
      if (!controller.signal.aborted) {
        controller.abort(new Error("Batch download timed out."));
      }
    }, timeoutMs)
    : null;
  try {
    return await fetchJson("/pdf/download", {
      method: "POST",
      body: JSON.stringify({
        articles: batch.map(articleReference),
        download_dir: projectDownloadDir(),
        max_articles: batch.length,
      }),
      signal: controller.signal,
    });
  } catch (error) {
    if (timeoutId) clearTimeout(timeoutId);
    if (controller.signal.aborted && !signal?.aborted) {
      throw new Error("Batch download timed out.");
    }
    throw error;
  } finally {
    if (timeoutId) clearTimeout(timeoutId);
  }
}

function applyDownloadResultState(article, result) {
  if (!article) return;
  if (result?.success) {
    const next = {
      status: "downloaded",
      label: downloadabilityLabels.downloaded,
      detail: result.file_path ? "Downloaded file is ready to open." : "Downloaded file is ready.",
      openUrl: result.file_path ? buildFileOpenUrl(result.file_path) : null,
    };
    setArticleDownloadability(article.id, next);
    rememberArticleDownloadability(article, next);
    return true;
  }
  const next = {
    status: "failed",
    label: downloadabilityLabels.failed,
    detail: result?.error || "Download failed.",
    openUrl: null,
  };
  setArticleDownloadability(article.id, next);
  return false;
}

async function downloadSingleArticle(articleId) {
  const article = state.articles.find((item) => item.id === articleId);
  if (!article) return;
  const current = getDownloadability(article.id);
  if (!isDownloadReadyStatus(current.status) && current.status !== "downloaded") return;

  state.downloadabilityById[article.id] = {
    status: "loading",
    label: "Downloading",
    detail: "Saving file.",
    openUrl: current.openUrl || null,
  };
  scheduleResultsRender();

  try {
    const result = await requestArticleDownload(article);
    if (applyDownloadResultState(article, result)) {
      trackAppEvent("info", "pdf_downloaded", article.title || "File downloaded.", {
        article_id: article.id,
        pmid: article.pmid || "",
        project_id: state.projectId || "",
      });
      await Promise.allSettled([loadProjectDownloads(), touchProjectActivity()]);
    } else {
      trackAppEvent("error", "pdf_download_failed", result?.error || "Download failed.", {
        pmid: article.pmid || "",
        article_id: article.id,
      });
    }
  } catch (error) {
    trackAppEvent("error", "pdf_download_failed", error.message || "Download failed.", {
      pmid: article.pmid || "",
      article_id: article.id,
    });
    applyDownloadResultState(article, { success: false, error: error.message || "Download failed." });
  }

  scheduleResultsRender();
}

function selectedArticles() {
  return state.articles.filter((article) => state.selectedIds.has(article.id));
}

function activeArticles() {
  return selectedArticles().length ? selectedArticles() : state.articles;
}

function articleIdentityKey(article) {
  return article?.pmid || article?.doi || article?.pmc_id || article?.title || "";
}

function applyBatchDownloadResults(chosen, results) {
  const chosenByKey = new Map(chosen.map((article) => [articleIdentityKey(article), article]));
  const seenKeys = new Set();
  const successes = [];
  const failures = [];
  (Array.isArray(results) ? results : []).forEach((result) => {
    const key = articleIdentityKey(result.article);
    const article = chosenByKey.get(key);
    if (!article) return;
    seenKeys.add(key);
    if (applyDownloadResultState(article, result)) {
      successes.push({ article, result });
    } else {
      failures.push({ article, result });
    }
  });
  chosen.forEach((article) => {
    const key = articleIdentityKey(article);
    if (seenKeys.has(key)) return;
    const result = { success: false, error: "Download result was not returned." };
    applyDownloadResultState(article, result);
    failures.push({ article, result });
  });
  scheduleResultsRender();
  return { successes, failures };
}

async function downloadSelectedArticles() {
  const chosen = activeArticles().filter((article) => {
    const current = getDownloadability(article.id);
    return isDownloadReadyStatus(current.status) || current.status === "downloaded";
  });
  if (!chosen.length) return;
  const concurrency = 1;
  const singleTimeoutMs = 65000;
  const originalBatchLabel = els.quickDownloadSelectedBtn?.textContent || "Download Selected";
  if (els.quickDownloadSelectedBtn) {
    els.quickDownloadSelectedBtn.disabled = true;
    els.quickDownloadSelectedBtn.textContent = "Downloading…";
  }
  chosen.forEach((article) => {
    const current = getDownloadability(article.id);
    setArticleDownloadability(article.id, {
      status: "loading",
      label: "Downloading",
      detail: "Fast batch in progress.",
      openUrl: current.openUrl || null,
    });
  });
  scheduleResultsRender();

  try {
    const successes = [];
    const failures = [];
    let cursor = 0;
    let completed = 0;

    const refreshDownloads = async () => {
      await Promise.allSettled([loadProjectDownloads(), touchProjectActivity()]);
    };

    const updateButtonLabel = () => {
      if (els.quickDownloadSelectedBtn) {
        els.quickDownloadSelectedBtn.textContent = `Downloading ${completed} / ${chosen.length}`;
      }
    };

    const processArticle = async (article, index) => {
      try {
        const result = await requestArticleDownload(article, { timeoutMs: singleTimeoutMs });
        if (applyDownloadResultState(article, result)) {
          successes.push({ article, result });
          trackAppEvent("info", "pdf_downloaded", article.title || "File downloaded.", {
            article_id: article.id,
            pmid: article.pmid || "",
            project_id: state.projectId || "",
          });
        } else {
          failures.push({ article, result });
          trackAppEvent("error", "pdf_download_failed", result?.error || "Download failed.", {
            article_id: article.id,
            pmid: article.pmid || "",
            project_id: state.projectId || "",
          });
        }
      } catch (singleError) {
        const result = { success: false, error: singleError.message || "Download failed." };
        applyDownloadResultState(article, result);
        failures.push({ article, result });
        trackAppEvent("error", "pdf_download_failed", result.error, {
          article_id: article.id,
          pmid: article.pmid || "",
          project_id: state.projectId || "",
        });
      }
      completed += 1;
      updateButtonLabel();
      scheduleResultsRender();
      if (completed === chosen.length || completed % concurrency === 0 || index < concurrency) {
        await refreshDownloads();
      }
    };

    const worker = async () => {
      while (true) {
        const nextIndex = cursor;
        cursor += 1;
        if (nextIndex >= chosen.length) return;
        await processArticle(chosen[nextIndex], nextIndex);
      }
    };

    updateButtonLabel();
    await Promise.all(Array.from({ length: concurrency }, () => worker()));
    await refreshDownloads();
  } catch (error) {
    chosen.forEach((article) => {
      applyDownloadResultState(article, { success: false, error: error.message || "Download failed." });
    });
    trackAppEvent("error", "pdf_batch_download_failed", error.message || "Batch download failed.", {
      project_id: state.projectId || "",
      selected_count: chosen.length,
    });
    scheduleResultsRender();
  } finally {
    if (els.quickDownloadSelectedBtn) {
      els.quickDownloadSelectedBtn.disabled = false;
      els.quickDownloadSelectedBtn.textContent = originalBatchLabel;
    }
  }
}

function compactList(items, limit = 8) {
  if (!items?.length) return "-";
  const visible = items.slice(0, limit);
  const suffix = items.length > limit ? ` +${items.length - limit}` : "";
  return `${visible.join(", ")}${suffix}`;
}

function detailMetaMarkup(article) {
  const lines = [];
  if (article.year) lines.push(`Year ${article.year}`);
  if (article.pmid) lines.push(`PMID ${article.pmid}`);
  if (article.doi) lines.push(`DOI ${article.doi}`);
  if (article.pmc_id) lines.push(`PMC ${article.pmc_id}`);
  return lines.map((item) => `<span class="detail-meta-chip">${item}</span>`).join("");
}

function detailMetaText(article) {
  const lines = [];
  if (article.title) lines.push(article.title);
  if (article.year) lines.push(`Year ${article.year}`);
  if (article.pmid) lines.push(`PMID ${article.pmid}`);
  if (article.doi) lines.push(`DOI ${article.doi}`);
  return lines.join(" • ");
}

function detailPopupPayload(article, field) {
  switch (field) {
    case "abstract":
      return {
        eyebrow: "Article Summary",
        title: article.title || "Abstract",
        meta: detailMetaText(article),
        body: article.abstract?.trim() || "Abstract not available.",
      };
    case "journal":
      return {
        eyebrow: "Article Detail",
        title: "Journal & Publication",
        meta: article.title || "",
        body: [article.journal || "-", article.publication_date || "-"].join("\n"),
      };
    case "authors":
      return {
        eyebrow: "Article Detail",
        title: "Authors",
        meta: article.title || "",
        body: article.authors?.length ? article.authors.join("\n") : "Author information not available.",
      };
    case "mesh":
      return {
        eyebrow: "Article Detail",
        title: "MeSH",
        meta: article.title || "",
        body: article.mesh_terms?.length ? article.mesh_terms.join(", ") : "MeSH terms not available.",
      };
    case "keywords":
      return {
        eyebrow: "Article Detail",
        title: "Keywords",
        meta: article.title || "",
        body: article.keywords?.length ? article.keywords.join(", ") : "Keywords not available.",
      };
    case "article_types":
      return {
        eyebrow: "Article Detail",
        title: "Article Types",
        meta: article.title || "",
        body: article.article_types?.length ? article.article_types.join(", ") : "Article type information not available.",
      };
    case "related_articles":
      return {
        eyebrow: "Article Detail",
        title: "Related Articles",
        meta: article.title || "",
        body: article.related_articles?.length ? article.related_articles.join("\n") : "No related articles found.",
      };
    default:
      return {
        eyebrow: "Article Detail",
        title: article.title || "Detail",
        meta: detailMetaText(article),
        body: "-",
      };
  }
}

function setDetailPopupOpen(next) {
  els.detailPopup.hidden = !next;
  els.detailPopupOverlay.hidden = !next;
  els.detailPopup.classList.toggle("is-open", next);
  els.detailPopupOverlay.classList.toggle("is-open", next);
}

function closeDetailPopup() {
  setDetailPopupOpen(false);
}

function openDetailPopup(articleId, field) {
  const article = state.allArticles.find((item) => item.id === articleId) || state.articles.find((item) => item.id === articleId);
  if (!article) return;
  const payload = detailPopupPayload(article, field);
  els.detailPopupEyebrow.textContent = payload.eyebrow || "";
  els.detailPopupTitle.textContent = payload.title || "";
  els.detailPopupMeta.textContent = payload.meta || "";
  els.detailPopupBody.textContent = payload.body || "";
  setDetailPopupOpen(true);
}

function detailBlockMarkup(article, field, label, text, subtext = "") {
  return `
    <button
      type="button"
      class="detail-block detail-popup-trigger"
      data-article-id="${article.id}"
      data-popup-field="${field}"
    >
      <div class="detail-label">${label}</div>
      <div class="detail-text">${text}</div>
      ${subtext ? `<div class="detail-subtext">${subtext}</div>` : ""}
    </button>
  `;
}

function detailRowMarkup(article) {
  const link = bestArticleLink(article);
  return `
    <tr class="detail-row">
      <td colspan="9">
        <div class="inline-detail">
          <div class="inline-detail-top">
            <div>
              <div class="detail-kicker">Article Summary</div>
              <div class="detail-meta">${detailMetaMarkup(article)}</div>
            </div>
            <div class="detail-actions">
              ${link ? `<a class="detail-link" href="${link}" target="_blank" rel="noreferrer">Link</a>` : ""}
              ${downloadControlMarkup(article)}
            </div>
          </div>
          <button
            type="button"
            class="inline-abstract-card detail-popup-trigger"
            data-article-id="${article.id}"
            data-popup-field="abstract"
          >
            <div class="detail-label">Abstract</div>
            <div class="inline-abstract">${escapeHtml(article.abstract?.trim() || "Abstract not available.")}</div>
          </button>
          <div class="detail-grid">
            ${detailBlockMarkup(article, "journal", "Journal & Publication", article.journal || "-", article.publication_date || "-")}
            ${detailBlockMarkup(article, "authors", "Authors", compactList(article.authors, 10))}
            ${detailBlockMarkup(article, "mesh", "MeSH", compactList(article.mesh_terms, 12))}
            ${detailBlockMarkup(article, "keywords", "Keywords", compactList(article.keywords, 12))}
            ${detailBlockMarkup(article, "article_types", "Article Types", compactList(article.article_types, 8))}
            ${detailBlockMarkup(article, "related_articles", "Related Articles", compactList(article.related_articles, 8))}
          </div>
        </div>
      </td>
    </tr>
  `;
}

function defaultSortDirection(key) {
  return {
    id: "asc",
    pmid: "asc",
    year: "desc",
    article_type: "asc",
    citation_count: "desc",
  }[key] || "asc";
}

function articleSortValue(article, sortKey) {
  switch (sortKey) {
    case "id":
      return article.id;
    case "pmid":
      return parseOptionalNumber(article.pmid);
    case "year":
      return parseOptionalNumber(article.year);
    case "article_type":
      return articleTypeLabel(article);
    case "citation_count":
      return Number.isInteger(article.citation_count) ? article.citation_count : null;
    default:
      return null;
  }
}

function applyArticleSort() {
  if (!state.sortKey) return;
  const direction = state.sortDirection === "desc" ? -1 : 1;
  state.articles = [...state.articles].sort((left, right) => {
    const leftValue = articleSortValue(left, state.sortKey);
    const rightValue = articleSortValue(right, state.sortKey);
    if (leftValue === null && rightValue === null) return left.id - right.id;
    if (leftValue === null) return 1;
    if (rightValue === null) return -1;
    if (typeof leftValue === "number" && typeof rightValue === "number") {
      const numeric = (leftValue - rightValue) * direction;
      return numeric || (left.id - right.id);
    }
    const textCompare = String(leftValue).localeCompare(String(rightValue), "en", {
      numeric: true,
      sensitivity: "base",
    });
    return textCompare * direction || (left.id - right.id);
  });
}

function updateSortButtons() {
  els.sortButtons.forEach((button) => {
    const isActive = button.dataset.sortKey === state.sortKey;
    button.classList.toggle("is-active", isActive);
    button.dataset.direction = isActive ? state.sortDirection : "none";
    button.setAttribute("aria-pressed", isActive ? "true" : "false");
    button.closest("th")?.setAttribute(
      "aria-sort",
      isActive ? (state.sortDirection === "asc" ? "ascending" : "descending") : "none",
    );
  });
}

function toggleArticleSort(sortKey) {
  if (!sortKey) return;
  if (state.sortKey === sortKey) {
    state.sortDirection = state.sortDirection === "asc" ? "desc" : "asc";
  } else {
    state.sortKey = sortKey;
    state.sortDirection = defaultSortDirection(sortKey);
  }
  applyArticleSort();
  renderResults();
}

function renderMeta(meta) {
  if (!meta) {
    els.metaStrip.innerHTML = "";
    return;
  }
  const chips = [
    ["Total results", meta.total_results_found],
    ["Fetched", meta.fetched_results],
    ["Batch", meta.batch_size_used],
    ["Requests", meta.request_count],
    ["Duration", `${meta.elapsed_ms} ms`],
    ["Cache", meta.cache_hit ? "hit" : "miss"],
    ["OA", meta.oa_only ? "on" : "off"],
  ];
  els.metaStrip.innerHTML = chips
    .map(([label, value]) => `<span class="meta-chip">${label}: ${value}</span>`)
    .join("");
}

function updateCounters() {
  const hasSelection = state.selectedIds.size > 0;
  els.articleCount.textContent = String(state.articles.length);
  els.selectedCount.textContent = String(state.selectedIds.size);
  els.selectAllBtn.disabled = state.articles.length === 0;
  els.clearSelectionBtn.disabled = !hasSelection;
  if (els.quickDownloadSelectedBtn) {
    els.quickDownloadSelectedBtn.disabled = !hasSelection;
    els.quickDownloadSelectedBtn.classList.toggle("is-active", hasSelection);
  }
}

async function enrichCitationsInBackground() {
  if (!state.allArticles.length) return;
  const runId = Date.now();
  state.citationRunId = runId;
  state.citationsLoading = true;
  const queue = [...state.allArticles];
  const chunkSize = 10;
  const workerCount = 4;
  let cursor = 0;

  async function worker() {
    while (cursor < queue.length) {
      if (state.citationRunId !== runId) return;
      const start = cursor;
      cursor += chunkSize;
      const chunk = queue.slice(start, start + chunkSize);
      if (!chunk.length) return;
      try {
        const data = await fetchJson("/pubmed/citations", {
          method: "POST",
          body: JSON.stringify({
            articles: chunk.map(articleReference),
          }),
        });
        if (state.citationRunId !== runId) return;
        const byKey = new Map(
          (data.items || []).map((item) => [item.pmid || item.doi, item.citation_count]),
        );
        state.allArticles = state.allArticles.map((article) => {
          const key = article.pmid || article.doi;
          if (!key || !byKey.has(key)) return article;
          return {
            ...article,
            citation_count: byKey.get(key),
          };
        });
        state.articles = [...state.allArticles];
        if (state.lastPubmedResponse) {
          state.lastPubmedResponse = {
            ...state.lastPubmedResponse,
            articles: cloneJson(state.allArticles),
          };
        }
        applyArticleSort();
        renderResults();
        upsertActiveQueryRecord();
        scheduleProjectStateSave();
      } catch (error) {
        trackAppEvent("error", "pubmed_citation_enrich_failed", error.message || "Citation enrichment failed.", {
          project_id: state.projectId || "",
          chunk_start: start,
          chunk_size: chunk.length,
        });
      }
    }
  }

  try {
    await Promise.all(
      Array.from({ length: Math.min(workerCount, Math.ceil(queue.length / chunkSize)) }, () => worker()),
    );
  } finally {
    if (state.citationRunId === runId) {
      state.citationsLoading = false;
      renderResults();
    }
  }
}

function applyArticleDataset(data, options = {}) {
  const { persist = true } = options;
  state.lastPubmedResponse = data;
  state.allArticles = Array.isArray(data.articles) ? data.articles : [];
  state.articles = [...state.allArticles];
  state.downloadabilityRunId += 1;
  seedDownloadability(state.allArticles);
  state.selectedIds.clear();
  state.detailArticleId = null;
  closeDetailPopup();
  renderMeta(data.meta || null);
  applyArticleSort();
  renderResults();
  if (persist) {
    upsertActiveQueryRecord();
    scheduleProjectStateSave();
  }
}

function renderResults() {
  updateCounters();
  updateSortButtons();

  if (!state.articles.length) {
    els.resultsBody.innerHTML = `
      <tr>
        <td colspan="9" class="empty-cell">
          <div class="native-empty-state">
            <div class="native-empty-state-title">No search yet</div>
            <div class="native-empty-state-copy">Start with a topic in Searcher AI.</div>
          </div>
        </td>
      </tr>
    `;
    return;
  }

  els.resultsBody.innerHTML = state.articles
    .map((article) => {
      const link = bestArticleLink(article);
      const detailRow = state.detailArticleId === article.id ? detailRowMarkup(article) : "";
      return `
        <tr class="article-row ${state.detailArticleId === article.id ? "is-active" : ""}" data-row-id="${article.id}">
          <td><input type="checkbox" class="row-check" data-id="${article.id}" ${state.selectedIds.has(article.id) ? "checked" : ""}></td>
          <td>${article.id}</td>
          <td>${escapeHtml(article.pmid || "-")}</td>
          <td class="year-cell">${escapeHtml(article.year || "-")}</td>
          <td class="type-cell">${escapeHtml(articleTypeLabel(article))}</td>
          <td class="count-cell">${escapeHtml(citationLabel(article))}</td>
          <td class="title-cell">${escapeHtml(article.title || "-")}</td>
          <td>${link ? `<a class="table-link" href="${link}" target="_blank" rel="noreferrer">Link</a>` : "-"}</td>
          <td>${renderDownloadabilityCell(article)}</td>
        </tr>
        ${detailRow}
      `;
    })
    .join("");

  document.querySelectorAll(".row-check").forEach((node) => {
    node.addEventListener("change", () => {
      const id = Number(node.dataset.id);
      if (node.checked) state.selectedIds.add(id);
      else state.selectedIds.delete(id);
      updateCounters();
      scheduleProjectStateSave();
    });
  });

  document.querySelectorAll(".article-row").forEach((node) => {
    node.addEventListener("click", (event) => {
      if (
        event.target.closest(".row-check")
        || event.target.closest(".table-link")
        || event.target.closest(".row-download-btn")
        || event.target.closest(".file-open-btn")
      ) return;
      const clickedId = Number(node.dataset.rowId);
      state.detailArticleId = state.detailArticleId === clickedId ? null : clickedId;
      renderResults();
      scheduleProjectStateSave();
    });
  });

  document.querySelectorAll(".row-download-btn").forEach((node) => {
    node.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      await downloadSingleArticle(Number(node.dataset.id));
    });
  });

  document.querySelectorAll(".detail-popup-trigger").forEach((node) => {
    node.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      openDetailPopup(Number(node.dataset.articleId), node.dataset.popupField);
    });
  });
}

async function runSearch() {
  const payload = {
    query: els.query.value.trim(),
    year_start: els.yearStart.value ? Number(els.yearStart.value) : null,
    year_end: els.yearEnd.value ? Number(els.yearEnd.value) : null,
    max_results: normalizedNumber(els.maxResults, 20),
    batch_size: null,
    min_cite: null,
    article_type: null,
    use_cache: true,
  };
  if (!payload.query) {
    throw new Error("PubMed query cannot be empty.");
  }
  els.searchBtn.disabled = true;
  state.lastSearchPayload = payload;
  trackAppEvent("info", "pubmed_search_started", payload.query, {
    project_id: state.projectId || "",
    max_results: payload.max_results,
    pubmed_oa_only: Boolean(runtime.pubmedOaOnly),
  });
  try {
    const response = await fetchJson("/pubmed/search", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.citationsLoading = response.articles?.length > 0;
    applyArticleDataset(response);
    syncSidebarQuickControls();
    trackAppEvent("info", "pubmed_search_completed", `${response.meta?.fetched_results || 0} articles`, {
      project_id: state.projectId || "",
      fetched_results: response.meta?.fetched_results || 0,
      elapsed_ms: response.meta?.elapsed_ms || 0,
      pubmed_oa_only: Boolean(response.meta?.oa_only),
    });
    void enrichCitationsInBackground();
  } catch (error) {
    state.lastPubmedResponse = null;
    state.allArticles = [];
    state.articles = [];
    state.citationsLoading = false;
    state.selectedIds.clear();
    state.detailArticleId = null;
    state.downloadabilityById = {};
    renderMeta(null);
    renderResults();
    throw error;
  } finally {
    els.searchBtn.disabled = false;
  }
}

async function runSidebarQuickSearch() {
  const query = els.sidebarQuickQuery?.value?.trim() || "";
  if (!query) {
    throw new Error("Sidebar query cannot be empty.");
  }
  const maxResults = normalizedNumber(els.sidebarQuickMaxResults, 5);
  if (els.sidebarQuickSearchBtn) els.sidebarQuickSearchBtn.disabled = true;
  if (els.sidebarQuickStatus) els.sidebarQuickStatus.textContent = "Running PubMed search…";
  els.query.value = query;
  els.maxResults.value = String(maxResults);
  autoResizeTextarea(els.query);
  autoResizeTextarea(els.sidebarQuickQuery);
  try {
    await runSearch();
    if (els.sidebarQuickStatus) {
      els.sidebarQuickStatus.textContent = `${state.articles.length} articles loaded.`;
    }
  } catch (error) {
    if (els.sidebarQuickStatus) {
      els.sidebarQuickStatus.textContent = error.message || "Sidebar search failed.";
    }
    throw error;
  } finally {
    if (els.sidebarQuickSearchBtn) els.sidebarQuickSearchBtn.disabled = false;
  }
}

function setAssistantOpen(next) {
  state.assistantOpen = next;
  els.assistantPanel.hidden = !next;
  els.assistantPanel.classList.toggle("is-open", next);
  if (next) {
    requestAnimationFrame(() => {
      els.assistantInput?.focus();
    });
  }
}

function updateAssistantModelUI() {
  els.assistantModelLabel.textContent = assistantModelLabelMap[runtime.assistantModel] || runtime.assistantModel;
  els.assistantModelItems.forEach((item) => {
    item.classList.toggle("is-selected", item.dataset.model === runtime.assistantModel);
  });
  updateThinkingControlsUI();
}

function currentModelSupportsThinking() {
  return Boolean(assistantModelThinkingSupport[runtime.assistantModel]);
}

function effectiveThinkingLevel() {
  return currentModelSupportsThinking() ? state.thinkingLevel : "off";
}

function updateThinkingControlsUI() {
  const supportsThinking = currentModelSupportsThinking();
  const divider = els.thinkToggleWrap?.previousElementSibling;
  if (els.thinkToggleWrap) {
    els.thinkToggleWrap.hidden = !supportsThinking;
  }
  if (divider?.classList.contains("assistant-toolbar-divider")) {
    divider.hidden = !supportsThinking;
  }
  if (!supportsThinking) {
    els.thinkMenu.hidden = true;
    els.thinkToggleBtn.setAttribute("aria-expanded", "false");
  }
}

function updateThinkingLabel() {
  const labels = {
    off: "Think: Off",
    low: "Think: Low",
    max: "Think: Max",
  };
  els.thinkLabel.textContent = labels[effectiveThinkingLevel()] || labels.off;
  document.querySelectorAll(".think-menu-item").forEach((item) => {
    item.classList.toggle("is-selected", item.dataset.level === state.thinkingLevel);
  });
}

function assistantActionLabel(action) {
  const details = action.details || {};
  const running = {
    search_pubmed: "Searching PubMed",
    get_article_details: "Reading article details",
    list_catalog_articles: "Scanning catalog",
  };
  const success = {
    search_pubmed: details.retry_used ? "Broadened PubMed search" : "Searched PubMed",
    get_article_details: "Read article details",
    list_catalog_articles: "Scanned catalog",
  };
  const error = {
    search_pubmed: "PubMed search failed",
    get_article_details: "Article detail read failed",
    list_catalog_articles: "Catalog scan failed",
  };
  if (action.status === "running") return running[action.name] || "Running tool";
  if (action.status === "error") return error[action.name] || "Tool failed";
  return success[action.name] || "Tool completed";
}

function assistantActionDetail(action) {
  const details = action.details || {};
  if (action.name === "search_pubmed") {
    if (details.retry_used && details.retry_query) return details.retry_query;
    return details.query || "Building PubMed query";
  }
  if (action.name === "get_article_details") {
    const ids = details.requested_ids || details.returned_ids || details.ids || [];
    return ids.length ? `ID ${ids.join(", ")}` : "Opening article details";
  }
  if (action.name === "list_catalog_articles") {
    return details.query || "Scanning loaded catalog";
  }
  return action.name || "Tool";
}

function assistantActionKindLabel(action) {
  const map = {
    search_pubmed: "PubMed",
    get_article_details: "Evidence",
    list_catalog_articles: "Catalog",
  };
  return map[action.name] || "Tool";
}

function upsertAssistantAction(actions, action, callId) {
  const next = Array.isArray(actions) ? [...actions] : [];
  const resolvedId = callId || action.call_id || `action_${next.length + 1}`;
  const index = next.findIndex((item) => item.call_id === resolvedId);
  const merged = {
    ...(index >= 0 ? next[index] : {}),
    ...action,
    call_id: resolvedId,
  };
  if (index >= 0) next[index] = merged;
  else next.push(merged);
  return next;
}

function assistantMessageMarkup(item) {
  if (!item.id) item.id = generateAssistantMessageId();
  const roleName = item.role === "user" ? "You" : "Searcher AI";
  return `
    <div class="assistant-message ${item.role}" data-message-id="${item.id}">
      <div class="assistant-message-role">${escapeHtml(roleName)}</div>
      <div class="assistant-message-thinking-slot">${assistantThinkingMarkup(item)}</div>
      <div class="assistant-message-actions-slot">${assistantActionsMarkup(item)}</div>
      <div class="assistant-message-content-slot">${assistantContentMarkup(item)}</div>
      <div class="assistant-message-meta-slot">${assistantMetaMarkup(item)}</div>
    </div>
  `;
}

function assistantThinkingMarkup(item) {
  if (item.role === "user" || !item.pending) return "";
  const label = item.thinkingEnabled ? "Thinking" : "";
  return `
    <div class="ai-thinking-live-panel is-pending">
      <div class="ai-thinking-live-head">
        <span class="ai-thinking-wave" aria-hidden="true">
          <span></span><span></span><span></span>
        </span>
        ${label ? `<span class="ai-thinking-live-label">${label}</span>` : ""}
      </div>
    </div>
  `;
}

function assistantActionsMarkup(item) {
  return item.role !== "user" && item.actions?.length
    ? `<div class="ai-action-list">${item.actions.map((act) => `
        <div class="ai-action-row ${act.status || "success"}">
          <span class="ai-action-row-status ${act.status || "success"}">${act.status === "error" ? "!" : act.status === "success" ? "✓" : ""}</span>
          <span class="ai-action-row-kind">${escapeHtml(assistantActionKindLabel(act))}</span>
          <span class="ai-action-row-text">${escapeHtml(assistantActionLabel(act))}</span>
          <span class="ai-action-row-sep">·</span>
          <span class="ai-action-row-detail" title="${escapeHtml(assistantActionDetail(act))}">${escapeHtml(assistantActionDetail(act))}</span>
        </div>`).join("")}</div>`
    : "";
}

function assistantContentMarkup(item) {
  return item.text
    ? `<div class="assistant-message-text ${item.pending ? "is-streaming" : ""}">${escapeHtml(item.text)}${item.pending ? '<span class="assistant-stream-caret"></span>' : ""}</div>`
    : "";
}

function assistantMetaMarkup(item) {
  return item.meta ? `<div class="assistant-message-meta">${escapeHtml(item.meta)}</div>` : "";
}

function assistantShouldStickToBottom() {
  if (!els.assistantMessages) return false;
  const threshold = 56;
  return els.assistantMessages.scrollHeight - els.assistantMessages.scrollTop - els.assistantMessages.clientHeight <= threshold;
}

function updateAssistantMessageNode(message) {
  if (!message?.id || !els.assistantMessages) return;
  const node = els.assistantMessages.querySelector(`[data-message-id="${message.id}"]`);
  if (!node) {
    renderAssistantMessages();
    return;
  }
  node.querySelector(".assistant-message-thinking-slot").innerHTML = assistantThinkingMarkup(message);
  node.querySelector(".assistant-message-actions-slot").innerHTML = assistantActionsMarkup(message);
  node.querySelector(".assistant-message-content-slot").innerHTML = assistantContentMarkup(message);
  node.querySelector(".assistant-message-meta-slot").innerHTML = assistantMetaMarkup(message);
}

function scheduleAssistantMessageUpdate(message) {
  if (!message) return;
  if (!message.id) message.id = generateAssistantMessageId();
  assistantMessageUpdateQueue.add(message);
  if (assistantMessageUpdateFrame !== null) return;
  assistantMessageUpdateFrame = requestAnimationFrame(() => {
    assistantMessageUpdateFrame = null;
    const shouldStick = assistantShouldStickToBottom();
    assistantMessageUpdateQueue.forEach((item) => updateAssistantMessageNode(item));
    assistantMessageUpdateQueue.clear();
    if (shouldStick && els.assistantMessages) {
      els.assistantMessages.scrollTop = els.assistantMessages.scrollHeight;
    }
  });
}

function assistantEmptyStateMarkup() {
  return `
    <div class="native-assistant-empty">
      <div class="native-assistant-empty-icon" aria-hidden="true">
        <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
          <path d="M9.5 4.5c1.7-1.3 3.8-1.3 5.5 0 .9.7 1.5 1.8 1.7 3 .9.1 1.7.5 2.3 1.1a4 4 0 0 1 0 5.6 4 4 0 0 1-2.4 1.1 4.7 4.7 0 0 1-9.1.7A3.6 3.6 0 0 1 5 15.2a3.7 3.7 0 0 1-.7-5.1 3.6 3.6 0 0 1 2.8-1.5c.2-1.7 1-3 2.4-4.1Z" />
          <path d="M10 11h4" />
          <path d="M12 9v4" />
        </svg>
      </div>
      <div class="native-assistant-empty-title">Ready</div>
      <div class="native-assistant-empty-copy">Start a new chat or open a recent one from history.</div>
    </div>
  `;
}

function renderAssistantMessages() {
  if (assistantMessageUpdateFrame !== null) {
    cancelAnimationFrame(assistantMessageUpdateFrame);
    assistantMessageUpdateFrame = null;
  }
  assistantMessageUpdateQueue.clear();
  const hasMessages = state.assistantMessages.length > 0;
  els.assistantMessages.innerHTML = hasMessages
    ? state.assistantMessages.map(assistantMessageMarkup).join("")
    : assistantEmptyStateMarkup();
  els.assistantMessages.scrollTop = hasMessages ? els.assistantMessages.scrollHeight : 0;
  els.assistantPanel.classList.toggle("is-pristine", !hasMessages);
  renderAssistantHeader();
}

function pushAssistantMessage(message) {
  const nextMessage = {
    ...message,
    id: message.id || generateAssistantMessageId(),
  };
  state.assistantMessages.push(nextMessage);
  renderAssistantMessages();
  syncCurrentSession();
  return nextMessage;
}

function applyAssistantActions(actions) {
  let applied = false;
  if (!Array.isArray(actions) || !actions.length) return false;
  actions.forEach((action) => {
    if (action.name !== "search_pubmed" || action.status === "error" || !action.details) return;
    const details = action.details;
    const articles = Array.isArray(details.articles) ? details.articles : [];
    const meta = details.meta || null;
    if (typeof details.query === "string") {
      els.query.value = details.query;
      autoResizeTextarea(els.query);
    }
    els.yearStart.value = details.year_start ? String(details.year_start) : "";
    els.yearEnd.value = details.year_end ? String(details.year_end) : "";
    els.maxResults.value = String(details.max_results || articles.length || 10);
    state.lastSearchPayload = {
      query: details.query || "",
      year_start: details.year_start || null,
      year_end: details.year_end || null,
      max_results: details.max_results || articles.length || 10,
      batch_size: null,
      min_cite: Number.isInteger(details.min_cite) ? details.min_cite : null,
      article_type: typeof details.article_type === "string" ? details.article_type : null,
      use_cache: true,
    };
    state.citationsLoading = articles.length > 0;
    applyArticleDataset({ articles, meta });
    applied = true;
    if (articles.length) {
      void enrichCitationsInBackground();
    }
  });
  return applied;
}

async function sendAssistantMessage() {
  const message = els.assistantInput.value.trim();
  if (!message) return;
  if (!runtime.apiKey) {
    trackAppEvent("error", "assistant_missing_api_key", "Assistant API key not found.", {
      project_id: state.projectId || "",
    });
    pushAssistantMessage({
      role: "assistant",
      text: "Assistant error: API key not found.",
    });
    return;
  }

  if (state.chatHistoryOpen) {
    setChatHistoryOpen(false);
  }

  if (!state.currentSessionId) {
    const session = createAssistantSession({ messages: [] });
    state.assistantSessions.unshift(session);
    state.currentSessionId = session.id;
  }

  if (state.assistantStreamAbort) state.assistantStreamAbort.abort();
  const controller = new AbortController();
  state.assistantStreamAbort = controller;

  pushAssistantMessage({ role: "user", text: message });
  const pendingMessage = pushAssistantMessage({
    role: "assistant",
    text: "",
    pending: true,
    actions: [],
    liveThinking: "",
    thinkingEnabled: effectiveThinkingLevel() !== "off",
  });
  let searchAppliedDuringStream = false;
  els.assistantInput.value = "";
  autoResizeTextarea(els.assistantInput);

  try {
    await streamJsonEvents(
      "/assistant/chat/stream",
      {
        method: "POST",
        signal: controller.signal,
        idleTimeoutMs: 45000,
        responseTimeoutMs: 20000,
        body: JSON.stringify({
          api_key: runtime.apiKey,
          message,
          model: runtime.assistantModel,
          mode: "fast",
          thread_id: state.assistantThreadId,
          thinking_level: effectiveThinkingLevel(),
          articles: helperArticlePayload(),
          selected_ids: [...state.selectedIds],
        }),
      },
      (event) => {
        if (event.type === "start" && event.thread_id) {
          state.assistantThreadId = event.thread_id;
          syncCurrentSession();
          return;
        }
        if (event.type === "status") {
          pendingMessage.liveThinking = event.text || pendingMessage.liveThinking;
          scheduleAssistantMessageUpdate(pendingMessage);
          return;
        }
        if (event.type === "thinking_delta") {
          pendingMessage.liveThinking = `${pendingMessage.liveThinking || ""}${event.text || ""}`;
          scheduleAssistantMessageUpdate(pendingMessage);
          return;
        }
        if (event.type === "answer_delta") {
          pendingMessage.text = `${pendingMessage.text || ""}${event.text || ""}`;
          scheduleAssistantMessageUpdate(pendingMessage);
          return;
        }
        if (event.type === "tool_call") {
          pendingMessage.actions = upsertAssistantAction(
            pendingMessage.actions,
            event.action || {},
            event.call_id,
          );
          scheduleAssistantMessageUpdate(pendingMessage);
          return;
        }
        if (event.type === "tool_result") {
          pendingMessage.actions = upsertAssistantAction(
            pendingMessage.actions,
            event.action || {},
            event.call_id,
          );
          if (applyAssistantActions([event.action || {}])) {
            searchAppliedDuringStream = true;
          }
          scheduleAssistantMessageUpdate(pendingMessage);
          syncCurrentSession();
          return;
        }
        if (event.type === "final") {
          pendingMessage.pending = false;
          pendingMessage.text = event.response?.answer || pendingMessage.text || "";
          pendingMessage.thinking = event.response?.thinking || pendingMessage.liveThinking || "";
          pendingMessage.meta = event.response?.used_article_ids?.length
            ? `Article IDs: ${event.response.used_article_ids.join(", ")}`
            : "";
          pendingMessage.actions = event.response?.executed_actions || pendingMessage.actions;
          if (!searchAppliedDuringStream) {
            applyAssistantActions(event.response?.executed_actions || []);
          }
          scheduleAssistantMessageUpdate(pendingMessage);
          syncCurrentSession();
          return;
        }
        if (event.type === "error") {
          pendingMessage.pending = false;
          pendingMessage.text = `Assistant error: ${event.message || "Unknown error."}`;
          trackAppEvent("error", "assistant_stream_failed", event.message || "Unknown assistant error.", {
            project_id: state.projectId || "",
            model: runtime.assistantModel,
          });
          scheduleAssistantMessageUpdate(pendingMessage);
          syncCurrentSession();
        }
      },
    );
  } catch (error) {
    pendingMessage.pending = false;
    pendingMessage.text = `Assistant error: ${error.message || "Unknown error."}`;
    trackAppEvent("error", "assistant_stream_failed", error.message || "Unknown assistant error.", {
      project_id: state.projectId || "",
      model: runtime.assistantModel,
    });
    scheduleAssistantMessageUpdate(pendingMessage);
    syncCurrentSession();
  } finally {
    if (state.assistantStreamAbort === controller) {
      state.assistantStreamAbort = null;
    }
    syncCurrentSession();
  }
}

async function loadHealth() {
  try {
    const health = await fetchJson("/health");
    els.healthStatus.textContent = health.status === "ok" ? "Ready" : "Issue";
  } catch (_error) {
    els.healthStatus.textContent = "Connection Error";
  }
}

async function loadBootstrap() {
  try {
    await loadApiKeys();
  } catch (_error) {
    applyApiKeyValues({
      assistant_api_key: localStorage.getItem("researcher2_api_key") || "",
    });
  }
}

function bindEvents() {
  els.searchBtn.addEventListener("click", async () => {
    try {
      await runSearch();
    } catch (error) {
      trackAppEvent("error", "pubmed_search_failed", error.message || "PubMed search failed.", {
        project_id: state.projectId || "",
      });
      pushAssistantMessage({ role: "assistant", text: `Search error: ${error.message}` });
    }
  });

  els.query.addEventListener("input", () => autoResizeTextarea(els.query));
  els.sidebarQuickQuery?.addEventListener("input", () => autoResizeTextarea(els.sidebarQuickQuery));
  els.sidebarQuickSearchBtn?.addEventListener("click", async () => {
    try {
      await runSidebarQuickSearch();
    } catch (error) {
      trackAppEvent("error", "sidebar_pubmed_search_failed", error.message || "Sidebar PubMed search failed.", {
        project_id: state.projectId || "",
      });
      pushAssistantMessage({ role: "assistant", text: `Sidebar search error: ${error.message}` });
    }
  });
  els.assistantInput.addEventListener("input", () => autoResizeTextarea(els.assistantInput));
  els.assistantInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendAssistantMessage();
    }
  });
  els.assistantSendBtn.addEventListener("click", () => {
    void sendAssistantMessage();
  });

  els.projectNameDisplay?.addEventListener("dblclick", () => {
    startProjectRename();
  });
  els.projectNameInput?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      void saveProjectRename();
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      cancelProjectRename();
    }
  });
  els.projectNameInput?.addEventListener("blur", () => {
    void saveProjectRename();
  });

  els.sortButtons.forEach((button) => {
    button.addEventListener("click", () => toggleArticleSort(button.dataset.sortKey));
  });

  els.selectAllBtn.addEventListener("click", () => {
    state.selectedIds = new Set(state.articles.map((article) => article.id));
    renderResults();
    scheduleProjectStateSave();
  });

  els.clearSelectionBtn.addEventListener("click", () => {
    state.selectedIds.clear();
    renderResults();
    scheduleProjectStateSave();
  });

  els.quickDownloadSelectedBtn?.addEventListener("click", () => {
    void downloadSelectedArticles();
  });
  els.apiKeysBtn?.addEventListener("click", () => {
    setApiKeysDialogOpen(true);
  });
  els.apiKeysOverlay?.addEventListener("click", () => {
    setApiKeysDialogOpen(false);
  });
  els.apiKeysClose?.addEventListener("click", () => {
    setApiKeysDialogOpen(false);
  });
  els.apiKeysCancel?.addEventListener("click", () => {
    setApiKeysDialogOpen(false);
  });
  els.apiKeysForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    await saveApiKeys({
      assistant_api_key: els.assistantApiKeyInput?.value || "",
      ncbi_api_key: els.ncbiApiKeyInput?.value || "",
      unpaywall_email: els.unpaywallEmailInput?.value || "",
    });
  });
  els.pubmedOaOnlyToggle?.addEventListener("change", async () => {
    const nextValue = Boolean(els.pubmedOaOnlyToggle?.checked);
    if (els.pubmedOaOnlyToggle) els.pubmedOaOnlyToggle.disabled = true;
    try {
      await saveApiKeys({ pubmed_oa_only: nextValue }, { closeDialog: false });
      trackAppEvent("info", "pubmed_oa_setting_updated", "PubMed OA search setting updated.", {
        pubmed_oa_only: nextValue,
      });
    } catch (error) {
      renderSettingsPanel();
      trackAppEvent("error", "pubmed_oa_setting_failed", error.message || "PubMed OA setting could not be saved.", {
        pubmed_oa_only: nextValue,
      });
    } finally {
      if (els.pubmedOaOnlyToggle) els.pubmedOaOnlyToggle.disabled = false;
    }
  });
  els.sidebarToggleBtn?.addEventListener("click", () => {
    setSidebarOpen(!state.sidebarOpen);
  });
  els.sidebarQueriesBtn?.addEventListener("click", () => {
    setSidebarPanel("queries");
  });
  els.sidebarDownloadsBtn?.addEventListener("click", () => {
    setSidebarPanel("downloads");
  });
  els.sidebarSettingsBtn?.addEventListener("click", () => {
    setSidebarPanel("settings");
  });
  els.sidebarOpenApiKeysBtn?.addEventListener("click", () => {
    setApiKeysDialogOpen(true);
  });
  els.assistantHistoryToggleBtn?.addEventListener("click", () => {
    setChatHistoryOpen(!state.chatHistoryOpen);
  });
  els.newChatTriggers.forEach((node) => {
    node.addEventListener("click", () => createNewAssistantChat());
  });

  els.assistantModelBtn.addEventListener("click", () => {
    const next = els.assistantModelMenu.hidden;
    els.assistantModelMenu.hidden = !next;
    els.assistantModelBtn.setAttribute("aria-expanded", next ? "true" : "false");
    els.thinkMenu.hidden = true;
    els.thinkToggleBtn.setAttribute("aria-expanded", "false");
  });
  els.assistantModelItems.forEach((item) => {
    item.addEventListener("click", () => {
      runtime.assistantModel = item.dataset.model;
      localStorage.setItem(assistantModelStorageKey, runtime.assistantModel);
      updateAssistantModelUI();
      updateThinkingLabel();
      els.assistantModelMenu.hidden = true;
      els.assistantModelBtn.setAttribute("aria-expanded", "false");
    });
  });

  els.thinkToggleBtn.addEventListener("click", () => {
    const next = els.thinkMenu.hidden;
    els.thinkMenu.hidden = !next;
    els.thinkToggleBtn.setAttribute("aria-expanded", next ? "true" : "false");
    els.assistantModelMenu.hidden = true;
    els.assistantModelBtn.setAttribute("aria-expanded", "false");
  });
  document.querySelectorAll(".think-menu-item").forEach((item) => {
    item.addEventListener("click", () => {
      state.thinkingLevel = item.dataset.level;
      localStorage.setItem("native_researcher_thinking_level", state.thinkingLevel);
      updateThinkingLabel();
      els.thinkMenu.hidden = true;
      els.thinkToggleBtn.setAttribute("aria-expanded", "false");
    });
  });

  document.addEventListener("click", (event) => {
    if (!event.target.closest("#assistantModelWrap")) {
      els.assistantModelMenu.hidden = true;
      els.assistantModelBtn.setAttribute("aria-expanded", "false");
    }
    if (!event.target.closest("#thinkToggleWrap")) {
      els.thinkMenu.hidden = true;
      els.thinkToggleBtn.setAttribute("aria-expanded", "false");
    }
  });

  els.detailPopupOverlay.addEventListener("click", closeDetailPopup);
  els.detailPopupClose.addEventListener("click", closeDetailPopup);
}

async function init() {
  bindAppErrorLogging();
  clearLegacyAssistantStorage();
  resetAssistantProjectState();
  updateProjectUI();
  renderProjectDownloads();
  renderQueryHistory();
  updateAssistantModelUI();
  updateThinkingLabel();
  setApiKeysDialogOpen(false);
  autoResizeTextarea(els.query);
  autoResizeTextarea(els.sidebarQuickQuery);
  autoResizeTextarea(els.assistantInput);
  syncSidebarQuickControls();
  bindEvents();
  setSidebarOpen(state.sidebarOpen, { immediate: true });
  setSidebarPanel(state.sidebarPanel);
  renderAssistantMessages();
  renderChatHistory();
  setAssistantOpen(true);
  setChatHistoryOpen(false);
  await Promise.all([loadHealth(), loadBootstrap(), ensureActiveProject()]);
}

void init();
