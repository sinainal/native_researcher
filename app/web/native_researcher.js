const state = {
  allArticles: [],
  articles: [],
  downloadabilityById: {},
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
  currentSessionId: localStorage.getItem("native_researcher_chat_session_id") || null,
  sidebarOpen: localStorage.getItem("native_researcher_sidebar_open") !== "false",
  chatHistoryExpanded: false,
  chatHistoryOpen: false,
};

const els = {
  healthStatus: document.getElementById("healthStatus"),
  articleCount: document.getElementById("articleCount"),
  selectedCount: document.getElementById("selectedCount"),
  query: document.getElementById("query"),
  yearStart: document.getElementById("yearStart"),
  yearEnd: document.getElementById("yearEnd"),
  maxResults: document.getElementById("maxResults"),
  searchBtn: document.getElementById("searchBtn"),
  chatSidebar: document.getElementById("chatSidebar"),
  sidebarToggleBtn: document.getElementById("sidebarToggleBtn"),
  chatHistoryList: document.getElementById("chatHistoryList"),
  newChatTriggers: document.querySelectorAll(".new-chat-trigger"),
  clearSelectionBtn: document.getElementById("clearSelectionBtn"),
  selectAllBtn: document.getElementById("selectAllBtn"),
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
const assistantSessionStorageKey = "native_researcher_chat_sessions";
const assistantCurrentSessionStorageKey = "native_researcher_chat_session_id";
const assistantSidebarStorageKey = "native_researcher_sidebar_open";
const stateModel = localStorage.getItem(assistantModelStorageKey) || "Gemini 3 Flash";
let assistantMessageUpdateFrame = null;
const assistantMessageUpdateQueue = new Set();
let resultsRenderScheduled = false;
let downloadabilityResolveRun = 0;

const downloadabilityLabels = {
  loading: "Checking",
  ready: "Ready",
  unavailable: "No PDF",
  downloaded: "Downloaded",
  failed: "Error",
};

const runtime = {
  apiKey: "",
  assistantModel: stateModel,
};

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

function persistAssistantSessions() {
  const nextSessions = state.assistantSessions
    .filter(sessionHasContent)
    .slice(0, 24)
    .map((item) => createAssistantSession(item));
  state.assistantSessions = nextSessions;
  localStorage.setItem(assistantSessionStorageKey, JSON.stringify(nextSessions));
  if (state.currentSessionId && nextSessions.some((item) => item.id === state.currentSessionId)) {
    localStorage.setItem(assistantCurrentSessionStorageKey, state.currentSessionId);
  } else {
    localStorage.removeItem(assistantCurrentSessionStorageKey);
  }
}

function loadStoredAssistantSessions() {
  let parsedSessions = [];
  try {
    const raw = localStorage.getItem(assistantSessionStorageKey);
    parsedSessions = raw ? JSON.parse(raw) : [];
  } catch (_error) {
    parsedSessions = [];
  }
  state.assistantSessions = Array.isArray(parsedSessions)
    ? parsedSessions.map((item) => createAssistantSession(item))
      .filter(sessionHasContent)
    : [];
  if (!state.assistantSessions.length) {
    state.currentSessionId = null;
    state.assistantThreadId = null;
    localStorage.removeItem("native_researcher_thread_id");
    localStorage.removeItem(assistantCurrentSessionStorageKey);
    return;
  }

  if (!state.currentSessionId || !state.assistantSessions.some((item) => item.id === state.currentSessionId)) {
    state.currentSessionId = state.assistantSessions[0]?.id || null;
  }
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
  localStorage.setItem("native_researcher_thread_id", session.threadId || "");
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
  localStorage.setItem("native_researcher_thread_id", state.assistantThreadId || "");
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
  localStorage.removeItem("native_researcher_thread_id");
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

function articleSourceLabel(article) {
  if (article.pmc_id) return "PMC";
  if (article.doi) return "DOI";
  if (article.pmid) return "PubMed";
  return "-";
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
  return ["ready", "downloaded"].includes(status);
}

function canAttemptDownload(info) {
  return isDownloadReadyStatus(info.status) || (info.status === "failed" && Number(info.candidateCount) > 0);
}

function getDownloadability(articleId) {
  return state.downloadabilityById[articleId] || {
    status: "loading",
    label: downloadabilityLabels.loading,
    detail: "Checking for downloadable PDF sources.",
    openUrl: null,
    candidateCount: 0,
  };
}

function downloadabilityDisplay(articleId) {
  const info = getDownloadability(articleId);
  if (info.status === "loading") {
    return { tone: "pending", text: downloadabilityLabels.loading };
  }
  if (info.status === "downloaded") {
    return { tone: "ready", text: downloadabilityLabels.downloaded };
  }
  if (isDownloadReadyStatus(info.status)) {
    return { tone: "ready", text: downloadabilityLabels.ready };
  }
  return { tone: "blocked", text: info.label || downloadabilityLabels.unavailable };
}

function downloadControlMarkup(article) {
  const info = getDownloadability(article.id);
  const display = downloadabilityDisplay(article.id);
  if (info.openUrl) {
    return `<a class="btn btn-primary btn-xs file-open-btn" href="${info.openUrl}" target="_blank" rel="noreferrer">PDF</a>`;
  }
  if (canAttemptDownload(info)) {
    return `<button type="button" class="btn btn-secondary btn-xs row-download-btn" data-id="${article.id}">Download</button>`;
  }
  return `<span class="native-download-state">${escapeHtml(display.text)}</span>`;
}

function renderDownloadabilityCell(article) {
  const info = getDownloadability(article.id);
  const display = downloadabilityDisplay(article.id);
  const tooltip = escapeHtml(info.detail || display.text);
  return `
    <div class="download-action-cell">
      <span class="availability-dot-shell ${display.tone}" title="${tooltip}">
        <span class="availability-dot"></span>
      </span>
      ${downloadControlMarkup(article)}
    </div>
  `;
}

function seedDownloadability(articles) {
  const source = Array.isArray(articles) ? articles : [];
  state.downloadabilityById = Object.fromEntries(
    source.map((article) => [
      article.id,
      {
        status: "loading",
        label: downloadabilityLabels.loading,
        detail: "Checking for downloadable PDF sources.",
        openUrl: null,
        candidateCount: 0,
      },
    ]),
  );
}

async function resolveArticleDownloadabilityInBackground(articles) {
  const source = Array.isArray(articles) ? articles : [];
  downloadabilityResolveRun += 1;
  const runId = downloadabilityResolveRun;
  if (!source.length) {
    state.downloadabilityById = {};
    scheduleResultsRender();
    return;
  }

  const queue = [...source];
  const concurrency = Math.min(4, queue.length);
  const worker = async () => {
    while (queue.length && downloadabilityResolveRun === runId) {
      const article = queue.shift();
      if (!article) break;
      try {
        const data = await fetchJson("/pdf/resolve", {
          method: "POST",
          body: JSON.stringify(articleReference(article)),
        });
        if (downloadabilityResolveRun !== runId) return;
        const candidates = Array.isArray(data.candidates) ? data.candidates : [];
        const primarySource = candidates[0]?.source || null;
        state.downloadabilityById[article.id] = candidates.length
          ? {
              status: "ready",
              label: downloadabilityLabels.ready,
              detail: primarySource
                ? `Downloadable PDF found via ${primarySource}.`
                : "Downloadable PDF source found.",
              openUrl: null,
              candidateCount: candidates.length,
            }
          : {
              status: "unavailable",
              label: downloadabilityLabels.unavailable,
              detail: "No downloadable PDF source was found.",
              openUrl: null,
              candidateCount: 0,
            };
      } catch (error) {
        if (downloadabilityResolveRun !== runId) return;
        state.downloadabilityById[article.id] = {
          status: "failed",
          label: downloadabilityLabels.failed,
          detail: error.message || "Could not check PDF availability.",
          openUrl: null,
          candidateCount: 0,
        };
      }
      scheduleResultsRender();
    }
  };

  await Promise.allSettled(Array.from({ length: concurrency }, () => worker()));
}

async function downloadSingleArticle(articleId) {
  const article = state.allArticles.find((item) => item.id === articleId) || state.articles.find((item) => item.id === articleId);
  if (!article) return;
  const current = getDownloadability(article.id);
  if (!canAttemptDownload(current)) return;

  state.downloadabilityById[article.id] = {
    ...current,
    status: "loading",
    label: downloadabilityLabels.loading,
    detail: "Downloading PDF.",
  };
  scheduleResultsRender();

  try {
    const data = await fetchJson("/pdf/download", {
      method: "POST",
      body: JSON.stringify({
        articles: [articleReference(article)],
        max_articles: 1,
        mode: "fast",
      }),
    });
    const result = data.results?.[0];
    if (result?.success) {
      state.downloadabilityById[article.id] = {
        status: "downloaded",
        label: downloadabilityLabels.downloaded,
        detail: result.file_path ? "PDF downloaded. Open it with the PDF button." : "PDF downloaded.",
        openUrl: result.file_path ? buildFileOpenUrl(result.file_path) : null,
        candidateCount: Math.max(1, current.candidateCount || result.candidate_count || 1),
      };
    } else {
      state.downloadabilityById[article.id] = {
        status: "failed",
        label: downloadabilityLabels.failed,
        detail: result?.error || "PDF download failed.",
        openUrl: null,
        candidateCount: current.candidateCount || 0,
      };
    }
  } catch (error) {
    state.downloadabilityById[article.id] = {
      status: "failed",
      label: downloadabilityLabels.failed,
      detail: error.message || "PDF download failed.",
      openUrl: null,
      candidateCount: current.candidateCount || 0,
    };
  }

  scheduleResultsRender();
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
  const downloadInfo = getDownloadability(article.id);
  const downloadDisplay = downloadabilityDisplay(article.id);
  return `
    <tr class="detail-row">
      <td colspan="10">
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
          <div class="inline-downloadability">
            <span class="availability-dot-shell ${downloadDisplay.tone}" title="${escapeHtml(downloadInfo.detail || downloadDisplay.text)}">
              <span class="availability-dot"></span>
            </span>
            <span class="detail-inline-text">${escapeHtml(downloadInfo.detail || downloadDisplay.text)}</span>
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
  ];
  els.metaStrip.innerHTML = chips
    .map(([label, value]) => `<span class="meta-chip">${label}: ${value}</span>`)
    .join("");
}

function updateCounters() {
  els.articleCount.textContent = String(state.articles.length);
  els.selectedCount.textContent = String(state.selectedIds.size);
  els.selectAllBtn.disabled = state.articles.length === 0;
  els.clearSelectionBtn.disabled = state.selectedIds.size === 0;
}

function applyArticleDataset(data) {
  state.lastPubmedResponse = data;
  state.lastSearchPayload = data.meta
    ? {
        query: data.meta.full_query || els.query.value.trim(),
        year_start: els.yearStart.value ? Number(els.yearStart.value) : null,
        year_end: els.yearEnd.value ? Number(els.yearEnd.value) : null,
        max_results: normalizedNumber(els.maxResults, 50),
      }
    : state.lastSearchPayload;
  state.allArticles = Array.isArray(data.articles) ? data.articles : [];
  state.articles = [...state.allArticles];
  seedDownloadability(state.allArticles);
  state.selectedIds = new Set();
  state.detailArticleId = null;
  renderMeta(data.meta || null);
  applyArticleSort();
  renderResults();
  void resolveArticleDownloadabilityInBackground(state.allArticles);
}

function renderResults() {
  updateCounters();
  updateSortButtons();

  if (!state.articles.length) {
    els.resultsBody.innerHTML = `
      <tr>
        <td colspan="10" class="empty-cell">
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
          <td><span class="native-source-chip">${escapeHtml(articleSourceLabel(article))}</span></td>
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
    max_results: normalizedNumber(els.maxResults, 50),
    use_cache: true,
  };
  if (!payload.query) {
    throw new Error("PubMed query cannot be empty.");
  }
  els.searchBtn.disabled = true;
  els.searchBtn.textContent = "Loading…";
  try {
    const response = await fetchJson("/pubmed/search", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    applyArticleDataset(response);
  } finally {
    els.searchBtn.disabled = false;
    els.searchBtn.textContent = "Search";
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
  if (action.status === "running") return "Searching PubMed";
  if (action.status === "error") return "PubMed search failed";
  return "Searched PubMed";
}

function assistantActionDetail(action) {
  const details = action.details || {};
  return details.query || "PubMed query";
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
          <span class="ai-action-row-kind">PubMed</span>
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
  if (!Array.isArray(actions) || !actions.length) return;
  actions.forEach((action) => {
    if (action.name !== "search_pubmed" || !action.details) return;
    const details = action.details;
    if (typeof details.query === "string") {
      els.query.value = details.query;
      autoResizeTextarea(els.query);
    }
    els.yearStart.value = details.year_start ? String(details.year_start) : "";
    els.yearEnd.value = details.year_end ? String(details.year_end) : "";
    els.maxResults.value = String(details.max_results || 50);
    applyArticleDataset({
      articles: Array.isArray(details.articles) ? details.articles : [],
      meta: details.meta || null,
    });
  });
}

async function sendAssistantMessage() {
  const message = els.assistantInput.value.trim();
  if (!message) return;
  if (!runtime.apiKey) {
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
  els.assistantInput.value = "";
  autoResizeTextarea(els.assistantInput);

  try {
    await streamJsonEvents(
      "/native-assistant/chat/stream",
      {
        method: "POST",
        signal: controller.signal,
        body: JSON.stringify({
          api_key: runtime.apiKey,
          message,
          model: runtime.assistantModel,
          thread_id: state.assistantThreadId,
          thinking_level: effectiveThinkingLevel(),
          articles: state.allArticles.map((article) => ({
            id: article.id,
            title: article.title,
            year: article.year,
            article_type: article.article_type,
            citation_count: article.citation_count,
            mesh_terms: article.mesh_terms || [],
            abstract: article.abstract || "",
            pmid: article.pmid,
            doi: article.doi,
            journal: article.journal,
          })),
          selected_ids: [...state.selectedIds],
        }),
      },
      (event) => {
        if (event.type === "start" && event.thread_id) {
          state.assistantThreadId = event.thread_id;
          localStorage.setItem("native_researcher_thread_id", event.thread_id);
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
          applyAssistantActions([event.action]);
          scheduleAssistantMessageUpdate(pendingMessage);
          syncCurrentSession();
          return;
        }
        if (event.type === "final") {
          pendingMessage.pending = false;
          pendingMessage.text = event.response?.answer || pendingMessage.text || "";
          pendingMessage.thinking = event.response?.thinking || pendingMessage.liveThinking || "";
          pendingMessage.meta = event.response?.used_article_ids?.length
            ? `Source IDs: ${event.response.used_article_ids.join(", ")}`
            : "";
          pendingMessage.actions = event.response?.executed_actions || pendingMessage.actions;
          scheduleAssistantMessageUpdate(pendingMessage);
          syncCurrentSession();
          return;
        }
        if (event.type === "error") {
          pendingMessage.pending = false;
          pendingMessage.text = `Assistant error: ${event.message || "Unknown error."}`;
          scheduleAssistantMessageUpdate(pendingMessage);
          syncCurrentSession();
        }
      },
    );
  } catch (error) {
    pendingMessage.pending = false;
    pendingMessage.text = `Assistant error: ${error.message || "Unknown error."}`;
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
    const payload = await fetchJson("/app/bootstrap");
    runtime.apiKey = payload.api_key || localStorage.getItem("researcher2_api_key") || "";
  } catch (_error) {
    runtime.apiKey = localStorage.getItem("researcher2_api_key") || "";
  }
}

function bindEvents() {
  els.searchBtn.addEventListener("click", async () => {
    try {
      await runSearch();
    } catch (error) {
      pushAssistantMessage({ role: "assistant", text: `Search error: ${error.message}` });
    }
  });

  els.query.addEventListener("input", () => autoResizeTextarea(els.query));
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

  els.sortButtons.forEach((button) => {
    button.addEventListener("click", () => toggleArticleSort(button.dataset.sortKey));
  });

  els.selectAllBtn.addEventListener("click", () => {
    state.selectedIds = new Set(state.articles.map((article) => article.id));
    renderResults();
  });

  els.clearSelectionBtn.addEventListener("click", () => {
    state.selectedIds.clear();
    renderResults();
  });

  els.sidebarToggleBtn?.addEventListener("click", () => {
    setSidebarOpen(!state.sidebarOpen);
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
  loadStoredAssistantSessions();
  updateAssistantModelUI();
  updateThinkingLabel();
  autoResizeTextarea(els.query);
  autoResizeTextarea(els.assistantInput);
  bindEvents();
  setSidebarOpen(state.sidebarOpen, { immediate: true });
  if (state.currentSessionId) {
    switchAssistantSession(state.currentSessionId);
  } else {
    state.assistantThreadId = null;
    state.assistantMessages = [];
    renderAssistantMessages();
    renderChatHistory();
  }
  setAssistantOpen(true);
  setChatHistoryOpen(false);
  await Promise.all([loadHealth(), loadBootstrap()]);
}

void init();
