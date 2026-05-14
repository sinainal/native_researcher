const state = {
  allArticles: [],
  articles: [],
  datasetRevision: 0,
  projectStateLoadToken: 0,
  projectId: null,
  projectPath: null,
  projectName: "Project",
  projectRenaming: false,
  projectRenameSaving: false,
  projectDownloadGroups: [],
  projectDownloads: [],
  downloadabilityCache: {},
  downloadabilityById: {},
  downloadabilityRunId: 0,
  queryHistory: [],
  researchRuns: [],
  activeQueryId: null,
  queryDetailId: null,
  citationRunId: 0,
  citationsLoading: false,
  selectedIds: new Set(),
  tableFilters: {
    years: [],
    articleTypes: [],
    citationBuckets: [],
    journalQuartiles: [],
    meshTerms: [],
    keywords: [],
  },
  sortKey: null,
  sortDirection: "asc",
  lastSearchPayload: null,
  lastPubmedResponse: null,
  articleDatasetMode: "query",
  detailArticleId: null,
  documentViewer: null,
  documentViewerMode: "table",
  documentViewerContentMode: "structured",
  documentViewerArtifactPaths: {},
  documentViewerRenderToken: 0,
  assistantThreadId: null,
  assistantMessages: [],
  assistantMode: localStorage.getItem("native_researcher_assistant_mode") || "fast",
  assistantOpen: true,
  thinkingLevel: localStorage.getItem("native_researcher_thinking_level") || "off",
  assistantStreamAbort: null,
  assistantSessions: [],
  currentSessionId: null,
  ollamaBaseUrl: "http://localhost:11434",
  ollamaModel: "",
  ollamaThinkingLevel: "off",
  ollamaModels: [],
  ollamaConnected: false,
  ollamaVersion: "",
  ollamaError: "",
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
  searchResource: document.getElementById("searchResource"),
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
  sidebarQuickYearStart: document.getElementById("sidebarQuickYearStart"),
  sidebarQuickYearEnd: document.getElementById("sidebarQuickYearEnd"),
  sidebarQuickSearchResource: document.getElementById("sidebarQuickSearchResource"),
  sidebarQuickSearchBtn: document.getElementById("sidebarQuickSearchBtn"),
  sidebarQuickStatus: document.getElementById("sidebarQuickStatus"),
  workspaceDownloadCount: document.getElementById("workspaceDownloadCount"),
  workspaceDownloadList: document.getElementById("workspaceDownloadList"),
  clearSelectionBtn: document.getElementById("clearSelectionBtn"),
  selectAllBtn: document.getElementById("selectAllBtn"),
  quickDownloadSelectedBtn: document.getElementById("quickDownloadSelectedBtn"),
  tableFilterBtn: document.getElementById("tableFilterBtn"),
  tableFilterOverlay: document.getElementById("tableFilterOverlay"),
  tableFilterPopup: document.getElementById("tableFilterPopup"),
  tableFilterClose: document.getElementById("tableFilterClose"),
  tableFilterBody: document.getElementById("tableFilterBody"),
  tableFilterMeta: document.getElementById("tableFilterMeta"),
  tableFilterClear: document.getElementById("tableFilterClear"),
  tableFilterApply: document.getElementById("tableFilterApply"),
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
  assistantDraftBtn: document.getElementById("assistantDraftBtn"),
  assistantModeMenu: document.getElementById("assistantModeMenu"),
  assistantNormalModeBtn: document.getElementById("assistantNormalModeBtn"),
  assistantResearchModeBtn: document.getElementById("assistantResearchModeBtn"),
  apiKeysBtn: document.getElementById("apiKeysBtn"),
  apiKeysOverlay: document.getElementById("apiKeysOverlay"),
  apiKeysPopup: document.getElementById("apiKeysPopup"),
  apiKeysForm: document.getElementById("apiKeysForm"),
  apiKeysClose: document.getElementById("apiKeysClose"),
  apiKeysCancel: document.getElementById("apiKeysCancel"),
  assistantApiKeyInput: document.getElementById("assistantApiKeyInput"),
  settingsAssistantApiKeyInput: document.getElementById("settingsAssistantApiKeyInput"),
  settingsAssistantApiKeySaveBtn: document.getElementById("settingsAssistantApiKeySaveBtn"),
  settingsAssistantApiKeyStatus: document.getElementById("settingsAssistantApiKeyStatus"),
  ncbiApiKeyInput: document.getElementById("ncbiApiKeyInput"),
  openalexApiKeyInput: document.getElementById("openalexApiKeyInput"),
  coreApiKeyInput: document.getElementById("coreApiKeyInput"),
  unpaywallEmailInput: document.getElementById("unpaywallEmailInput"),
  workspaceSettingsState: document.getElementById("workspaceSettingsState"),
  pubmedOaOnlyToggle: document.getElementById("pubmedOaOnlyToggle"),
  pubmedOaOnlyStatus: document.getElementById("pubmedOaOnlyStatus"),
  aiPrimarySearchResourceInput: document.getElementById("aiPrimarySearchResourceInput"),
  aiPrimarySearchResourceStatus: document.getElementById("aiPrimarySearchResourceStatus"),
  pdfDownloaderModeInput: document.getElementById("pdfDownloaderModeInput"),
  pdfDownloaderModeStatus: document.getElementById("pdfDownloaderModeStatus"),
  pdfUnpaywallFallbackToggle: document.getElementById("pdfUnpaywallFallbackToggle"),
  pdfUnpaywallFallbackStatus: document.getElementById("pdfUnpaywallFallbackStatus"),
  pdfCoreFallbackToggle: document.getElementById("pdfCoreFallbackToggle"),
  pdfCoreFallbackStatus: document.getElementById("pdfCoreFallbackStatus"),
  pdfArxivFallbackToggle: document.getElementById("pdfArxivFallbackToggle"),
  pdfArxivFallbackStatus: document.getElementById("pdfArxivFallbackStatus"),
  sidebarOpenModelSettingsBtn: document.getElementById("sidebarOpenModelSettingsBtn"),
  ollamaBaseUrlInput: document.getElementById("ollamaBaseUrlInput"),
  ollamaConnectBtn: document.getElementById("ollamaConnectBtn"),
  ollamaSaveBtn: document.getElementById("ollamaSaveBtn"),
  assistantOllamaThinkingWrap: document.getElementById("assistantOllamaThinkingWrap"),
  assistantOllamaThinkingBtn: document.getElementById("assistantOllamaThinkingBtn"),
  assistantOllamaThinkingLabel: document.getElementById("assistantOllamaThinkingLabel"),
  assistantOllamaThinkingMenu: document.getElementById("assistantOllamaThinkingMenu"),
  ollamaStatus: document.getElementById("ollamaStatus"),
  llamacppBaseUrlInput: document.getElementById("llamacppBaseUrlInput"),
  llamacppModelInput: document.getElementById("llamacppModelInput"),
  llamacppProfileInput: document.getElementById("llamacppProfileInput"),
  llamacppContextInput: document.getElementById("llamacppContextInput"),
  llamacppBatchInput: document.getElementById("llamacppBatchInput"),
  llamacppUbatchInput: document.getElementById("llamacppUbatchInput"),
  llamacppCpuMoeInput: document.getElementById("llamacppCpuMoeInput"),
  llamacppCacheKInput: document.getElementById("llamacppCacheKInput"),
  llamacppCacheVInput: document.getElementById("llamacppCacheVInput"),
  llamacppCacheRamInput: document.getElementById("llamacppCacheRamInput"),
  llamacppReasoningInput: document.getElementById("llamacppReasoningInput"),
  llamacppReasoningBudgetInput: document.getElementById("llamacppReasoningBudgetInput"),
  llamacppFitTargetInput: document.getElementById("llamacppFitTargetInput"),
  llamacppExecutableInput: document.getElementById("llamacppExecutableInput"),
  llamacppModelPathInput: document.getElementById("llamacppModelPathInput"),
  llamacppLibraryPathInput: document.getElementById("llamacppLibraryPathInput"),
  llamacppServerArgsInput: document.getElementById("llamacppServerArgsInput"),
  llamacppConnectBtn: document.getElementById("llamacppConnectBtn"),
  llamacppStartBtn: document.getElementById("llamacppStartBtn"),
  llamacppSaveBtn: document.getElementById("llamacppSaveBtn"),
  llamacppStatus: document.getElementById("llamacppStatus"),
  availableModelsList: document.getElementById("availableModelsList"),
  availableModelsStatus: document.getElementById("availableModelsStatus"),
  modelSettingsOverlay: document.getElementById("modelSettingsOverlay"),
  modelSettingsPopup: document.getElementById("modelSettingsPopup"),
  modelSettingsClose: document.getElementById("modelSettingsClose"),
  modelSettingsSummary: document.getElementById("modelSettingsSummary"),
  downloadWorkerCountInput: document.getElementById("downloadWorkerCountInput"),
  downloadWorkerCountStatus: document.getElementById("downloadWorkerCountStatus"),
  sidebarOpenApiKeysBtn: document.getElementById("sidebarOpenApiKeysBtn"),
  assistantSendBtn: document.getElementById("assistantSendBtn"),
  assistantModelBtn: document.getElementById("assistantModelBtn"),
  assistantModelLabel: document.getElementById("assistantModelLabel"),
  assistantModelMenu: document.getElementById("assistantModelMenu"),
  assistantModelWrap: document.getElementById("assistantModelWrap"),
  assistantModelLoadingPopup: document.getElementById("assistantModelLoadingPopup"),
  assistantModelLoadingSize: document.getElementById("assistantModelLoadingSize"),
  assistantModelLoadingTitle: document.getElementById("assistantModelLoadingTitle"),
  assistantModelLoadingMeta: document.getElementById("assistantModelLoadingMeta"),
  assistantModelLoadingBarFill: document.getElementById("assistantModelLoadingBarFill"),
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
  resultsCard: document.getElementById("resultsCard"),
  documentViewerCard: document.getElementById("documentViewerCard"),
  documentViewerBackBtn: document.getElementById("documentViewerBackBtn"),
  documentViewerPdfBtn: document.getElementById("documentViewerPdfBtn"),
  documentViewerXmlBtn: document.getElementById("documentViewerXmlBtn"),
  documentViewerReloadBtn: document.getElementById("documentViewerReloadBtn"),
  documentViewerRawBtn: document.getElementById("documentViewerRawBtn"),
  documentViewerEyebrow: document.getElementById("documentViewerEyebrow"),
  documentViewerTitle: document.getElementById("documentViewerTitle"),
  documentViewerMeta: document.getElementById("documentViewerMeta"),
  documentViewerBody: document.getElementById("documentViewerBody"),
};

const assistantModelLabelMap = {
  "Gemini 3.1 Pro": "Gemini 3.1 Pro",
  "Gemini 3 Flash": "Gemini 3 Flash",
  "Gemini 3.1 Flash Lite": "Gemini 3.1 Flash Lite",
  "Gemini 2.5 Pro": "Gemini 2.5 Pro",
  "Gemini 2.5 Flash": "Gemini 2.5 Flash",
  "Gemini 2.5 Flash Lite": "Gemini 2.5 Flash Lite",
};
const assistantBaseModels = [
  "Gemini 3.1 Pro",
  "Gemini 3 Flash",
  "Gemini 3.1 Flash Lite",
  "Gemini 2.5 Pro",
  "Gemini 2.5 Flash",
  "Gemini 2.5 Flash Lite",
];
const assistantModelDefaultVisibility = {
  "Gemini 3 Flash": true,
  "Gemini 3.1 Flash Lite": true,
};

const assistantModelThinkingSupport = {
  "Gemini 3.1 Pro": true,
  "Gemini 3 Flash": true,
  "Gemini 3.1 Flash Lite": true,
  "Gemini 2.5 Pro": true,
  "Gemini 2.5 Flash": true,
  "Gemini 2.5 Flash Lite": false,
};

const researchPlanDatabaseOptions = ["PubMed", "PMC", "Europe PMC", "OpenAlex", "CORE", "arXiv"];

const assistantModelStorageKey = "native_researcher_model";
const assistantModelVisibilityStorageKey = "native_researcher_model_visibility";
const assistantSidebarStorageKey = "native_researcher_sidebar_open";
const activeProjectStorageKey = "native_researcher_active_project";
const sidebarPanelStorageKey = "native_researcher_sidebar_panel";
const pubmedOaOnlyStorageKey = "native_researcher_pubmed_oa_only";
const downloadWorkersStorageKey = "native_researcher_download_workers";
const searchResourceStorageKey = "native_researcher_search_resource";
const stateModel = localStorage.getItem(assistantModelStorageKey) || "Gemini 3 Flash";
let assistantMessageUpdateFrame = null;
const assistantMessageUpdateQueue = new Set();
let resultsRenderScheduled = false;
let appErrorLoggingBound = false;
let pdfJsLoadPromise = null;
let pdfJsViewerLoadPromise = null;

const pdfJsScriptUrl = "https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.min.js";
const pdfJsWorkerUrl = "https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.worker.min.js";
const pdfJsViewerScriptUrl = "https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/web/pdf_viewer.js";

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
  openalexApiKey: "",
  coreApiKey: "",
  unpaywallEmail: "",
  pubmedOaOnly: localStorage.getItem(pubmedOaOnlyStorageKey) !== "false",
  pdfUnpaywallFallbackEnabled: true,
  pdfCoreFallbackEnabled: false,
  pdfArxivFallbackEnabled: false,
  ollamaBaseUrl: "http://localhost:11434",
  ollamaModel: "",
  ollamaModels: [],
  ollamaConnected: false,
  ollamaVersion: "",
  ollamaError: "",
  ollamaWarmupError: "",
  ollamaWarmupPending: false,
  ollamaWarmupModel: "",
  llamacppBaseUrl: "http://localhost:8098",
  llamacppModel: "qwen3.6-35b-a3b-q4_K_M",
  llamacppExecutable: "",
  llamacppModelPath: "",
  llamacppLibraryPath: "",
  llamacppServerArgs: "",
  llamacppModels: [],
  llamacppConnected: false,
  llamacppStarted: false,
  llamacppError: "",
  llamacppWarmupError: "",
  downloadWorkers: clampDownloadWorkers(localStorage.getItem(downloadWorkersStorageKey)),
  searchResource: normalizeSearchResource(localStorage.getItem(searchResourceStorageKey), "pubmed"),
  aiPrimarySearchResource: "pubmed",
  pdfDownloaderMode: "pdf_xml",
  assistantModel: stateModel,
  assistantModelVisibility: loadAssistantModelVisibility(),
  assistantModelLoading: false,
  assistantModelLoadingTarget: "",
  assistantModelLoadingStartedAt: 0,
};

function clampDownloadWorkers(value) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  if (!Number.isFinite(parsed)) return 4;
  return Math.min(8, Math.max(1, parsed));
}

function normalizeSearchResource(value, fallback = "pubmed") {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (["openalex", "pubmed", "europe_pmc", "pmc", "core", "arxiv"].includes(normalized)) {
    return normalized;
  }
  return fallback;
}

function searchResourceLabel(value) {
  if (String(value ?? "").trim().toLowerCase() === "research_plan") return "Research Plan";
  const normalized = normalizeSearchResource(value, "pubmed");
  if (normalized === "openalex") return "OpenAlex";
  if (normalized === "pubmed") return "PubMed";
  if (normalized === "europe_pmc") return "Europe PMC";
  if (normalized === "pmc") return "PMC";
  if (normalized === "core") return "CORE";
  if (normalized === "arxiv") return "arXiv";
  return "PubMed";
}

function normalizePdfDownloaderMode(value, fallback = "pdf_xml") {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (["pdf_xml", "best", "xml", "pdf", "legacy", "hybrid", "article_downloader", "final_method", "perfect"].includes(normalized)) {
    if (["best", "legacy", "hybrid", "article_downloader", "final_method", "perfect"].includes(normalized)) {
      return "pdf_xml";
    }
    return normalized;
  }
  return fallback;
}

function normalizeOllamaBaseUrl(value, fallback = "http://localhost:11434") {
  let normalized = String(value ?? "").trim() || fallback.trim();
  if (!normalized.includes("://")) {
    normalized = `http://${normalized}`;
  }
  return normalized.replace(/\/+$/, "");
}

function normalizeLlamaCppBaseUrl(value, fallback = "http://localhost:8098") {
  let normalized = String(value ?? "").trim() || fallback.trim();
  if (!normalized.includes("://")) {
    normalized = `http://${normalized}`;
  }
  return normalized.replace(/\/+$/, "");
}

function normalizeOllamaThinkingLevel(value, fallback = "off") {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (["off", "on"].includes(normalized)) return normalized;
  if (["low", "medium", "high", "max", "minimal", "true", "yes", "1"].includes(normalized)) return "on";
  return fallback;
}

function collectOllamaConnectCandidates() {
  const candidates = [];
  const seen = new Set();
  const rawCandidates = [
    els.ollamaBaseUrlInput?.value,
    runtime.ollamaBaseUrl,
    "http://localhost:11434",
    "http://127.0.0.1:11434",
    "http://[::1]:11434",
    "http://host.docker.internal:11434",
  ];

  for (const candidate of rawCandidates) {
    const raw = String(candidate ?? "").trim();
    if (!raw) continue;
    const normalized = normalizeOllamaBaseUrl(raw, raw);
    if (!normalized || seen.has(normalized)) continue;
    seen.add(normalized);
    candidates.push(normalized);
  }

  return candidates;
}

function ollamaThinkingLevelLabel(value) {
  const normalized = normalizeOllamaThinkingLevel(value, "off");
  const labels = {
    off: "Off",
    on: "On",
  };
  return labels[normalized] || labels.off;
}

const llamaCppProfiles = {
  "qwen36-safe": {
    context: "32768",
    batch: "1024",
    ubatch: "256",
    cpuMoe: "15",
    cacheK: "turbo4",
    cacheV: "turbo3",
    cacheRam: "0",
    reasoning: "auto",
    reasoningBudget: "2048",
    fitTarget: "1024",
  },
  "qwen36-fast": {
    context: "32768",
    batch: "1024",
    ubatch: "128",
    cpuMoe: "14",
    cacheK: "turbo4",
    cacheV: "turbo3",
    cacheRam: "0",
    reasoning: "auto",
    reasoningBudget: "1024",
    fitTarget: "1024",
  },
  balanced: {
    context: "16384",
    batch: "1024",
    ubatch: "256",
    cpuMoe: "16",
    cacheK: "q8_0",
    cacheV: "q8_0",
    cacheRam: "2048",
    reasoning: "auto",
    reasoningBudget: "1024",
    fitTarget: "1024",
  },
};

function llamaCppProfileArgs(profile) {
  return [
    "-c", profile.context,
    "-b", profile.batch,
    "-ub", profile.ubatch,
    "-np", "1",
    "-ngl", "all",
    "--n-cpu-moe", profile.cpuMoe,
    "--flash-attn", "on",
    "-ctk", profile.cacheK,
    "-ctv", profile.cacheV,
    "--threads", "10",
    "--threads-batch", "16",
    "--direct-io",
    "--no-warmup",
    "--no-webui",
    "-fitt", profile.fitTarget,
    "--cache-ram", profile.cacheRam,
    "--reasoning", profile.reasoning,
    "--reasoning-budget", profile.reasoningBudget,
  ].join(" ");
}

function parseLlamaCppArgs(args) {
  const valueAfter = (flag, fallback) => {
    const parts = String(args || "").match(/"[^"]*"|'[^']*'|\S+/g) || [];
    const index = parts.indexOf(flag);
    return index >= 0 && parts[index + 1] ? parts[index + 1].replace(/^['"]|['"]$/g, "") : fallback;
  };
  const parsed = {
    context: valueAfter("-c", valueAfter("--ctx-size", "32768")),
    batch: valueAfter("-b", "1024"),
    ubatch: valueAfter("-ub", "256"),
    cpuMoe: valueAfter("--n-cpu-moe", "15"),
    cacheK: valueAfter("-ctk", valueAfter("--cache-type-k", "turbo4")),
    cacheV: valueAfter("-ctv", valueAfter("--cache-type-v", "turbo3")),
    cacheRam: valueAfter("--cache-ram", valueAfter("-cram", "0")),
    reasoning: valueAfter("--reasoning", valueAfter("-rea", "auto")),
    reasoningBudget: valueAfter("--reasoning-budget", "-1"),
    fitTarget: valueAfter("-fitt", valueAfter("--fit-target", "1024")),
  };
  const matched = Object.entries(llamaCppProfiles).find(([, profile]) => (
    profile.context === parsed.context
    && profile.batch === parsed.batch
    && profile.ubatch === parsed.ubatch
    && profile.cpuMoe === parsed.cpuMoe
    && profile.cacheK === parsed.cacheK
    && profile.cacheV === parsed.cacheV
    && profile.cacheRam === parsed.cacheRam
    && profile.reasoning === parsed.reasoning
    && profile.reasoningBudget === parsed.reasoningBudget
    && profile.fitTarget === parsed.fitTarget
  ));
  return { ...parsed, profile: matched?.[0] || "custom" };
}

function buildLlamaCppArgsFromControls() {
  const profile = {
    context: String(els.llamacppContextInput?.value || "32768"),
    batch: String(els.llamacppBatchInput?.value || "1024"),
    ubatch: String(els.llamacppUbatchInput?.value || "256"),
    cpuMoe: String(els.llamacppCpuMoeInput?.value || "15"),
    cacheK: String(els.llamacppCacheKInput?.value || "turbo4"),
    cacheV: String(els.llamacppCacheVInput?.value || "turbo3"),
    cacheRam: String(els.llamacppCacheRamInput?.value || "0"),
    reasoning: String(els.llamacppReasoningInput?.value || "auto"),
    reasoningBudget: String(els.llamacppReasoningBudgetInput?.value || "-1"),
    fitTarget: String(els.llamacppFitTargetInput?.value || "1024"),
  };
  return llamaCppProfileArgs(profile);
}

function loadAssistantModelVisibility() {
  const defaults = assistantBaseModels.reduce((acc, model) => {
    acc[model] = Boolean(assistantModelDefaultVisibility[model]);
    return acc;
  }, {});
  const raw = localStorage.getItem(assistantModelVisibilityStorageKey);
  if (!raw) return defaults;
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return defaults;
    for (const [model, enabled] of Object.entries(parsed)) {
      defaults[model] = Boolean(enabled);
    }
    return defaults;
  } catch (_error) {
    return defaults;
  }
}

function persistAssistantModelVisibility() {
  localStorage.setItem(assistantModelVisibilityStorageKey, JSON.stringify(runtime.assistantModelVisibility || {}));
}

function assistantModelDisplayLabel(model) {
  const normalized = String(model || "").trim();
  if (!normalized) return "";
  if (isOllamaAssistantModel(normalized)) {
    return `Ollama · ${normalized.slice("ollama:".length).trim()}`;
  }
  if (isLlamaCppAssistantModel(normalized)) {
    return `llama.cpp · ${normalized.slice("llamacpp:".length).trim()}`;
  }
  return assistantModelLabelMap[normalized] || normalized;
}

function assistantModelProviderLabel(model) {
  if (isOllamaAssistantModel(model) || isLlamaCppAssistantModel(model)) return "Local";
  return "Gemini";
}

function assistantModelDefaultValue() {
  return "Gemini 3 Flash";
}

function isAssistantModelVisible(model) {
  const normalized = String(model || "").trim();
  if (!normalized) return false;
  return Boolean(runtime.assistantModelVisibility?.[normalized]);
}

function setAssistantModelVisibility(model, visible) {
  const normalized = String(model || "").trim();
  if (!normalized) return;
  runtime.assistantModelVisibility = {
    ...(runtime.assistantModelVisibility || {}),
    [normalized]: Boolean(visible),
  };
  persistAssistantModelVisibility();
}

function ensureAssistantModelVisible(model) {
  const normalized = String(model || "").trim();
  if (!normalized) return;
  if (!isAssistantModelVisible(normalized)) {
    setAssistantModelVisibility(normalized, true);
  }
}

function assistantGeminiModelItems() {
  return assistantBaseModels.map((model) => ({
    value: model,
    label: assistantModelLabelMap[model] || model,
    provider: "gemini",
    providerLabel: "Gemini",
    available: true,
    visible: isAssistantModelVisible(model),
    defaultVisible: Boolean(assistantModelDefaultVisibility[model]),
  }));
}

function assistantLocalModelItems() {
  const models = Array.isArray(runtime.ollamaModels) ? runtime.ollamaModels : [];
  const names = new Set();
  for (const model of models) {
    const name = String(model?.name || "").trim();
    if (name) names.add(name);
  }
  const selectedLocal = String(runtime.ollamaModel || "").trim();
  if (selectedLocal) names.add(selectedLocal);
  return [...names]
    .sort((left, right) => left.localeCompare(right))
    .map((name) => {
      const value = `ollama:${name}`;
      return {
        value,
        label: `Ollama · ${name}`,
        provider: "local",
        providerLabel: "Local",
        available: runtime.ollamaConnected || name === selectedLocal,
        visible: isAssistantModelVisible(value),
        modelName: name,
      };
    });
}

function assistantLlamaCppModelItems() {
  const names = new Set();
  const configured = String(runtime.llamacppModel || "local").trim();
  if (configured) names.add(configured);
  for (const model of Array.isArray(runtime.llamacppModels) ? runtime.llamacppModels : []) {
    const name = String(model?.id || "").trim();
    if (name) names.add(name);
  }
  return [...names]
    .sort((left, right) => left.localeCompare(right))
    .map((name) => {
      const value = `llamacpp:${name}`;
      return {
        value,
        label: `llama.cpp · ${name}`,
        provider: "local",
        providerLabel: "Local",
        available: runtime.llamacppConnected || name === configured,
        visible: isAssistantModelVisible(value),
        modelName: name,
      };
    });
}

function assistantModelCatalog() {
  return [...assistantGeminiModelItems(), ...assistantLocalModelItems(), ...assistantLlamaCppModelItems()];
}

function renderAvailableModelsMarkup() {
  const geminiItems = assistantGeminiModelItems();
  const localItems = assistantLocalModelItems();
  const llamacppItems = assistantLlamaCppModelItems();
  const renderItem = (item) => {
    const active = normalizeAssistantModel(runtime.assistantModel) === item.value;
    const disabled = item.available ? "" : " disabled";
    const checked = item.visible ? " checked" : "";
    return `
      <label class="native-model-option${item.available ? "" : " is-disabled"}${active ? " is-active" : ""}">
        <input type="checkbox" data-model="${escapeHtml(item.value)}"${checked}${disabled}>
        <span class="native-model-option-copy">
          <span class="native-model-option-title">${escapeHtml(item.label)}</span>
          <span class="native-model-option-meta">${escapeHtml(item.providerLabel)}${item.available ? "" : " · unavailable"}${item.defaultVisible ? " · default" : ""}</span>
        </span>
        <span class="native-model-option-badge">${escapeHtml(item.providerLabel)}</span>
      </label>`;
  };
  return `
    <div class="native-model-group">
      <div class="native-model-group-title">Gemini API</div>
      <div class="native-model-list-inner">
        ${geminiItems.map(renderItem).join("")}
      </div>
    </div>
    <div class="native-model-group">
      <div class="native-model-group-title">Ollama</div>
      ${
        localItems.length
          ? `<div class="native-model-list-inner">
              ${localItems.map(renderItem).join("")}
            </div>`
          : '<div class="native-model-empty">No local models detected yet. Connect Ollama to populate this list.</div>'
      }
    </div>
    <div class="native-model-group">
      <div class="native-model-group-title">llama.cpp</div>
      ${
        llamacppItems.length
          ? `<div class="native-model-list-inner">
              ${llamacppItems.map(renderItem).join("")}
            </div>`
          : '<div class="native-model-empty">No llama.cpp model configured yet.</div>'
      }
    </div>`;
}

function assistantModelOptions() {
  const activeModel = normalizeAssistantModel(runtime.assistantModel);
  const items = assistantModelCatalog();
  const visibleItems = items.filter((item) => item.visible || item.value === activeModel);
  if (!visibleItems.some((item) => item.value === activeModel)) {
    visibleItems.unshift({
      value: activeModel,
      label: assistantModelDisplayLabel(activeModel),
      provider: (isOllamaAssistantModel(activeModel) || isLlamaCppAssistantModel(activeModel)) ? "local" : "gemini",
      providerLabel: assistantModelProviderLabel(activeModel),
      available: true,
      visible: true,
      defaultVisible: false,
    });
  }
  return visibleItems;
}

function pdfDownloaderModeLabel(value) {
  const normalized = normalizePdfDownloaderMode(value, "pdf_xml");
  if (normalized === "pdf_xml") return "PDF + XML";
  if (normalized === "xml") return "XML Only";
  if (normalized === "pdf") return "PDF Only";
  return "PDF + XML";
}

function ollamaModelLabel(model) {
  if (!model?.name) return "";
  const sizeValue = Number(model.size || 0);
  const sizeLabel = Number.isFinite(sizeValue) && sizeValue > 0
    ? ` (${(sizeValue / (1024 * 1024 * 1024)).toFixed(1)} GB)`
    : "";
  return `${model.name}${sizeLabel}`;
}

function ollamaModelSizeLabel(modelName) {
  const normalized = String(modelName || "").trim();
  if (!normalized) return "";
  const match = Array.isArray(runtime.ollamaModels)
    ? runtime.ollamaModels.find((item) => String(item?.name || "").trim() === normalized)
    : null;
  const sizeValue = Number(match?.size || 0);
  if (!Number.isFinite(sizeValue) || sizeValue <= 0) return "";
  return `${Math.round(sizeValue / (1024 * 1024)).toLocaleString()} MB`;
}

function currentOllamaAssistantModel() {
  return runtime.ollamaModel ? `ollama:${runtime.ollamaModel}` : "";
}

function currentLlamaCppAssistantModel() {
  return runtime.llamacppModel ? `llamacpp:${runtime.llamacppModel}` : "";
}

function isOllamaAssistantModel(model) {
  return String(model || "").startsWith("ollama:");
}

function isLlamaCppAssistantModel(model) {
  return String(model || "").startsWith("llamacpp:");
}

function isLocalAssistantModel(model) {
  return isOllamaAssistantModel(model) || isLlamaCppAssistantModel(model);
}

function normalizeAssistantModel(model) {
  const requested = String(model || "").trim();
  if (isOllamaAssistantModel(requested)) {
    const ollamaChoice = requested.slice("ollama:".length).trim();
    return ollamaChoice ? `ollama:${ollamaChoice}` : assistantModelDefaultValue();
  }
  if (isLlamaCppAssistantModel(requested)) {
    const llamaChoice = requested.slice("llamacpp:".length).trim();
    return llamaChoice ? `llamacpp:${llamaChoice}` : assistantModelDefaultValue();
  }
  return assistantBaseModels.includes(requested) ? requested : assistantModelDefaultValue();
}

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

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function nextAnimationFrame() {
  return new Promise((resolve) => {
    if (typeof window !== "undefined" && typeof window.requestAnimationFrame === "function") {
      window.requestAnimationFrame(() => resolve());
      return;
    }
    resolve();
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

const assistantSendIconMarkup = `
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"
    stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path d="M12 19V7" />
    <path d="m7 11 5-5 5 5" />
  </svg>
`;

const assistantStopIconMarkup = `
  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
    <rect x="7" y="7" width="10" height="10" rx="2" />
  </svg>
`;

function setAssistantSendButtonStreaming(isStreaming) {
  if (!els.assistantSendBtn) return;
  const streaming = Boolean(isStreaming);
  els.assistantSendBtn.classList.toggle("is-stop", streaming);
  els.assistantSendBtn.innerHTML = streaming ? assistantStopIconMarkup : assistantSendIconMarkup;
  els.assistantSendBtn.setAttribute("aria-label", streaming ? "Stop response" : "Send");
  els.assistantSendBtn.title = streaming ? "Stop response" : "Send";
  els.assistantSendBtn.disabled = Boolean(runtime.assistantModelLoading) && !streaming;
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
  const groups = Array.isArray(state.projectDownloadGroups) ? state.projectDownloadGroups : [];
  const items = Array.isArray(state.projectDownloads) ? state.projectDownloads : [];
  const totalCount = items.length || groups.reduce((sum, group) => sum + (Array.isArray(group?.items) ? group.items.length : 0), 0);
  els.workspaceDownloadCount.textContent = String(totalCount);
  if (!groups.length && !items.length) {
    els.workspaceDownloadList.innerHTML = `
      <div class="native-workspace-library-empty">
        <div class="native-workspace-library-empty-title">No papers yet</div>
        <div class="native-workspace-library-empty-copy">Downloaded files for this project will appear here.</div>
      </div>
    `;
    return;
  }
  const renderDownloadItem = (item) => {
    const title = item?.name || item?.title || "Document";
    const meta = [
      formatFileSize(item?.size_bytes || 0),
      formatRelativeTime(item?.modified_at || ""),
    ].filter(Boolean);
    return `
      <button type="button" class="native-workspace-download-item native-workspace-download-item-child" data-file-path="${escapeHtml(item.path)}" data-file-title="${escapeHtml(title)}" data-artifact-paths="${escapeHtml(JSON.stringify(item.artifact_paths || {}))}">
        <span class="native-workspace-download-item-title">${escapeHtml(title)}</span>
        <span class="native-workspace-download-item-meta">${escapeHtml(meta.join(" · "))}</span>
      </button>
    `;
  };
  const renderGroup = (group) => {
    const itemsInGroup = Array.isArray(group?.items) ? group.items : [];
    const queryLabel = group?.title || "Query";
    const metaParts = [
      group?.query ? group.query : "",
      `${itemsInGroup.length} papers`,
      formatFileSize(group?.size_bytes || 0),
    ];
    const groupBadges = [];
    const artifactTypes = Array.isArray(group?.artifact_types) ? group.artifact_types : [];
    if (artifactTypes.includes("pdf") && artifactTypes.includes("xml")) {
      groupBadges.push('<span class="native-workspace-download-badge native-workspace-download-badge-dual">PDF + XML</span>');
    } else {
      artifactTypes.forEach((type) => {
        groupBadges.push(`<span class="native-workspace-download-badge">${escapeHtml(type.toUpperCase())}</span>`);
      });
    }
    return `
      <details class="native-workspace-download-group">
        <summary class="native-workspace-download-group-summary">
          <span class="native-workspace-download-group-summary-main">
            <span class="native-workspace-download-group-toggle" aria-hidden="true"></span>
            <span class="native-workspace-download-group-title">${escapeHtml(queryLabel)}</span>
            <span class="native-workspace-download-group-count">${escapeHtml(String(itemsInGroup.length))}</span>
            <span class="native-workspace-download-badges native-workspace-download-group-badges">
              ${groupBadges.join("")}
            </span>
          </span>
          <span class="native-workspace-download-group-meta">${escapeHtml(metaParts.filter(Boolean).join(" · "))}</span>
        </summary>
        <div class="native-workspace-download-group-body">
          ${itemsInGroup.map((item) => renderDownloadItem(item)).join("")}
        </div>
      </details>
    `;
  };
  if (groups.length) {
    els.workspaceDownloadList.innerHTML = groups.map((group) => renderGroup(group)).join("");
    return;
  }
  els.workspaceDownloadList.innerHTML = `
    <details class="native-workspace-download-group">
      <summary class="native-workspace-download-group-summary">
        <span class="native-workspace-download-group-summary-main">
          <span class="native-workspace-download-group-toggle" aria-hidden="true"></span>
          <span class="native-workspace-download-group-title">Downloads</span>
          <span class="native-workspace-download-group-count">${escapeHtml(String(items.length))}</span>
        </span>
        <span class="native-workspace-download-group-meta">${escapeHtml(formatFileSize(items.reduce((sum, item) => sum + (item.size_bytes || 0), 0)))} · ${escapeHtml(formatRelativeTime(items[0]?.modified_at || ""))}</span>
      </summary>
      <div class="native-workspace-download-group-body">
        ${items.map((item) => renderDownloadItem(item)).join("")}
      </div>
    </details>
  `;
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

function selectedQueryRecords() {
  const selectedIds = state.selectedQueryIds instanceof Set ? state.selectedQueryIds : new Set();
  if (!selectedIds.size) return [];
  return state.queryHistory.filter((item) => selectedIds.has(item.id));
}

function selectedQueryDataset() {
  const records = selectedQueryRecords();
  if (!records.length) return null;
  const articles = [];
  const seen = new Set();
  for (const record of records) {
    for (const article of Array.isArray(record.articles) ? record.articles : []) {
      const identity = articleIdentityKey(article);
      if (!identity || seen.has(identity)) continue;
      seen.add(identity);
      articles.push(cloneJson(article));
    }
  }
  return {
    meta: {
      ...(cloneJson(records[0]?.meta || {}) || {}),
      full_query: "Selected query set",
      total_results_found: records.reduce((sum, record) => sum + Number(record.meta?.total_results_found ?? record.articles?.length ?? 0), 0),
      fetched_results: records.reduce((sum, record) => sum + Number(record.meta?.fetched_results ?? record.articles?.length ?? 0), 0),
      request_count: records.reduce((sum, record) => sum + Number(record.meta?.request_count ?? 0), 0),
      elapsed_ms: records.reduce((sum, record) => sum + Number(record.meta?.elapsed_ms ?? 0), 0),
      primary_source: records[0]?.meta?.primary_source || runtime.searchResource || "pubmed",
      sources_used: Array.from(new Set(
        records.flatMap((record) => Array.isArray(record.meta?.sources_used) ? record.meta.sources_used : [])
      )),
      cache_hit: false,
      selected_query_count: records.length,
      selected_article_count: articles.length,
    },
    articles,
  };
}

function applySelectedQuerySelection() {
  const dataset = selectedQueryDataset();
  if (!dataset) {
    if (state.activeQueryId) {
      restoreQueryRecord(state.activeQueryId);
      return;
    }
    if (state.queryHistory.length) {
      restoreQueryRecord(state.queryHistory[0].id);
      return;
    }
    applyArticleDataset({ meta: null, articles: [] }, { persist: false });
    renderQueryDetail();
    return;
  }
  applyArticleDataset(dataset, { persist: false, mode: "selected_queries" });
}

function syncSelectedQuerySelection() {
  if (!(state.selectedQueryIds instanceof Set)) {
    state.selectedQueryIds = new Set();
  }
  const validIds = new Set(state.queryHistory.map((item) => item.id));
  for (const id of [...state.selectedQueryIds]) {
    if (!validIds.has(id)) {
      state.selectedQueryIds.delete(id);
    }
  }
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
  const requestedSource = searchResourceLabel(record.search_payload?.preferred_source || "pubmed");
  const actualSource = searchResourceLabel(meta.primary_source || record.search_payload?.preferred_source || "pubmed");
  const sourcesUsed = Array.isArray(meta.sources_used) && meta.sources_used.length
    ? meta.sources_used.map((item) => searchResourceLabel(item)).join(", ")
    : actualSource;
  const downloadGroup = Array.isArray(state.projectDownloadGroups)
    ? state.projectDownloadGroups.find((group) => group?.key === record.id)
    : null;
  const sharedCount = Number.isInteger(downloadGroup?.shared_item_count) ? downloadGroup.shared_item_count : 0;
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
        <div class="native-query-detail-label">Shared articles</div>
        <div class="native-query-detail-value">${escapeHtml(String(sharedCount))} shared across other query groups</div>
      </div>
      <div class="native-query-detail-item">
        <div class="native-query-detail-label">Requests</div>
        <div class="native-query-detail-value">${escapeHtml(String(meta.request_count ?? 0))} requests · ${escapeHtml(String(meta.elapsed_ms ?? 0))} ms</div>
      </div>
      <div class="native-query-detail-item">
        <div class="native-query-detail-label">Source</div>
        <div class="native-query-detail-value">${escapeHtml(requestedSource)} requested · ${escapeHtml(actualSource)} used</div>
      </div>
      <div class="native-query-detail-item">
        <div class="native-query-detail-label">Database</div>
        <div class="native-query-detail-value">${escapeHtml(sourcesUsed)}</div>
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
  syncSelectedQuerySelection();
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
  const selectedCount = state.selectedQueryIds instanceof Set ? state.selectedQueryIds.size : 0;
  const allChecked = selectedCount > 0 && selectedCount === state.queryHistory.length;
  const someChecked = selectedCount > 0 && selectedCount < state.queryHistory.length;
  els.workspaceQueryList.innerHTML = `
    <button type="button" class="native-query-history-select-all ${allChecked ? "is-active" : ""}" data-select-all-queries="1">
      <span class="native-query-history-select-all-box ${allChecked ? "is-checked" : someChecked ? "is-indeterminate" : ""}" aria-hidden="true"></span>
      <span class="native-query-history-select-all-label">All queries</span>
      <span class="native-query-history-meta">${escapeHtml(String(state.queryHistory.length))} saved</span>
    </button>
    ${state.queryHistory
    .map((item) => `
      <button
        type="button"
        class="native-query-history-item ${item.id === state.activeQueryId ? "is-active" : ""}"
        data-query-id="${item.id}"
      >
        <span class="native-query-history-row">
          <span class="native-query-history-check ${state.selectedQueryIds instanceof Set && state.selectedQueryIds.has(item.id) ? "is-checked" : ""}" aria-hidden="true"></span>
          <span class="native-query-history-text">
            <span class="native-query-history-title">${escapeHtml(item.title || "Saved query")}</span>
            <span class="native-query-history-meta">${escapeHtml(formatSessionAgeCompact(item.updated_at))} · ${escapeHtml(String(item.meta?.fetched_results ?? item.articles?.length ?? 0))} items</span>
          </span>
        </span>
      </button>
    `)
    .join("")}
  `;
  els.workspaceQueryList.querySelectorAll("[data-query-id]").forEach((node) => {
    node.addEventListener("click", () => {
      restoreQueryRecord(node.dataset.queryId);
    });
  });
  els.workspaceQueryList.querySelectorAll("[data-query-id] .native-query-history-check").forEach((node) => {
    node.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const queryButton = node.closest("[data-query-id]");
      const queryId = queryButton?.dataset.queryId;
      if (!queryId) return;
      if (!(state.selectedQueryIds instanceof Set)) {
        state.selectedQueryIds = new Set();
      }
      if (state.selectedQueryIds.has(queryId)) {
        state.selectedQueryIds.delete(queryId);
      } else {
        state.selectedQueryIds.add(queryId);
      }
      if (state.selectedQueryIds.size === 0) {
        if (state.activeQueryId) {
          restoreQueryRecord(state.activeQueryId);
        } else if (state.queryHistory.length) {
          restoreQueryRecord(state.queryHistory[0].id);
        }
      } else {
        applySelectedQuerySelection();
        renderQueryHistory();
        scheduleProjectStateSave();
      }
    });
  });
  const selectAllButton = els.workspaceQueryList.querySelector("[data-select-all-queries]");
  if (selectAllButton) {
    selectAllButton.addEventListener("click", () => {
      if (!(state.selectedQueryIds instanceof Set)) {
        state.selectedQueryIds = new Set();
      }
      if (state.selectedQueryIds.size === state.queryHistory.length && state.queryHistory.length > 0) {
        state.selectedQueryIds.clear();
        if (state.activeQueryId) {
          restoreQueryRecord(state.activeQueryId);
        } else if (state.queryHistory.length) {
          restoreQueryRecord(state.queryHistory[0].id);
        }
      } else {
        state.selectedQueryIds = new Set(state.queryHistory.map((item) => item.id));
        applySelectedQuerySelection();
        renderQueryHistory();
        scheduleProjectStateSave();
      }
    });
  }
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
  if (els.sidebarQuickYearStart && els.yearStart) {
    els.sidebarQuickYearStart.value = els.yearStart.value || "";
  }
  if (els.sidebarQuickYearEnd && els.yearEnd) {
    els.sidebarQuickYearEnd.value = els.yearEnd.value || "";
  }
  if (els.searchResource && els.sidebarQuickSearchResource) {
    const nextResource = normalizeSearchResource(els.searchResource.value || runtime.searchResource, "pubmed");
    els.searchResource.value = nextResource;
    els.sidebarQuickSearchResource.value = nextResource;
  }
  if (els.sidebarQuickStatus) {
    els.sidebarQuickStatus.textContent = `Uses the same search stack. Primary source: ${searchResourceLabel(runtime.searchResource)}.`;
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

function upsertResearchExecutionCandidateQuery(response, plan, options = {}) {
  const articles = Array.isArray(options.articles) && options.articles.length
    ? options.articles
    : Array.isArray(response?.candidate_articles) && response.candidate_articles.length
      ? response.candidate_articles
      : [];
  const runTrace = response?.run_trace || {};
  const queryTitle = plan?.topic || plan?.objective || runTrace.topic || "Research plan execution";
  const queryId = options.id || (runTrace.id ? `research_${runTrace.id}` : `research_agent_${Date.now().toString(36)}`);
  if (!articles.length || !queryId) return "";
  const timestamp = new Date().toISOString();
  state.queryHistory = state.queryHistory.filter((item) => item.id !== queryId);
  state.queryHistory.unshift({
    id: queryId,
    title: options.title || `${queryTitle} · Agent Query`,
    created_at: timestamp,
    updated_at: timestamp,
    search_payload: {
      query: queryTitle,
      year_start: null,
      year_end: null,
      max_results: Math.max(1, Math.min(5000, articles.length)),
      batch_size: null,
      min_cite: null,
      article_type: null,
      use_cache: true,
      preferred_source: "pubmed",
    },
    meta: {
      ...(cloneJson(options.meta || response.meta || {})),
      fetched_results: articles.length,
      batch_size_used: articles.length,
      primary_source: "research_plan_candidates",
    },
    articles: cloneJson(articles),
  });
  state.queryHistory = state.queryHistory.slice(0, 30);
  return queryId;
}

function upsertActiveQueryRecord() {
  if (state.articleDatasetMode !== "query") return;
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
    selected_query_ids: [...(state.selectedQueryIds instanceof Set ? state.selectedQueryIds : new Set())],
    selected_ids: [...state.selectedIds],
    detail_article_id: state.detailArticleId,
    sidebar_panel: state.sidebarPanel,
    query_detail_id: state.queryDetailId || state.activeQueryId,
    downloadability_cache: cloneJson(state.downloadabilityCache),
    query_history: cloneJson(state.queryHistory),
    research_runs: cloneJson(state.researchRuns),
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
  if (!(state.selectedQueryIds instanceof Set) || state.selectedQueryIds.size === 0) {
    applyArticleDataset(
      {
        meta: cloneJson(record.meta || null),
        articles: cloneJson(record.articles || []),
      },
      { persist: false }
    );
  }
  if (record.search_payload) {
    els.query.value = record.search_payload.query || "";
    els.yearStart.value = record.search_payload.year_start ? String(record.search_payload.year_start) : "";
    els.yearEnd.value = record.search_payload.year_end ? String(record.search_payload.year_end) : "";
    els.maxResults.value = String(record.search_payload.max_results || 50);
    runtime.searchResource = normalizeSearchResource(record.search_payload.preferred_source, runtime.searchResource || "pubmed");
    localStorage.setItem(searchResourceStorageKey, runtime.searchResource);
    if (els.searchResource) els.searchResource.value = runtime.searchResource;
    autoResizeTextarea(els.query);
  }
  if (state.selectedQueryIds instanceof Set && state.selectedQueryIds.size > 0) {
    applySelectedQuerySelection();
  }
  syncSidebarQuickControls();
  renderQueryHistory();
  scheduleProjectStateSave();
}

async function loadProjectState() {
  if (!state.projectId) return;
  const projectId = state.projectId;
  const loadToken = ++state.projectStateLoadToken;
  const datasetRevision = state.datasetRevision;
  try {
    const payload = await fetchJson(`/app/projects/${encodeURIComponent(state.projectId)}/state`);
    if (
      projectId !== state.projectId
      || loadToken !== state.projectStateLoadToken
      || datasetRevision !== state.datasetRevision
    ) {
      return;
    }
    const restoredSelectedIds = new Set(Array.isArray(payload.selected_ids) ? payload.selected_ids : []);
    const restoredDetailArticleId = Number.isInteger(payload.detail_article_id) ? payload.detail_article_id : null;
    state.queryHistory = Array.isArray(payload.query_history) ? payload.query_history : [];
    state.researchRuns = Array.isArray(payload.research_runs) ? payload.research_runs : [];
    state.activeQueryId = payload.active_query_id || state.queryHistory[0]?.id || null;
    state.queryDetailId = payload.query_detail_id || state.activeQueryId;
    state.selectedQueryIds = new Set(Array.isArray(payload.selected_query_ids) ? payload.selected_query_ids : []);
    state.downloadabilityCache = sanitizePersistedDownloadabilityCache(payload.downloadability_cache);
    state.selectedIds = new Set();
    state.detailArticleId = null;
    applyAssistantProjectState(payload);
    setSidebarPanel(payload.sidebar_panel || state.sidebarPanel);
    renderQueryHistory();
    if (state.selectedQueryIds instanceof Set && state.selectedQueryIds.size > 0 && !state.activeQueryId) {
      applySelectedQuerySelection();
    }
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
    if (
      projectId !== state.projectId
      || loadToken !== state.projectStateLoadToken
      || datasetRevision !== state.datasetRevision
    ) {
      return;
    }
    state.queryHistory = [];
    state.researchRuns = [];
    state.activeQueryId = null;
    state.queryDetailId = null;
    state.selectedQueryIds = new Set();
    state.downloadabilityCache = {};
    state.selectedIds = new Set();
    state.detailArticleId = null;
    state.selectedQueryIds = new Set();
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
    state.projectDownloadGroups = [];
    state.projectDownloads = [];
    renderProjectDownloads();
    renderQueryDetail();
    return;
  }
  try {
    const payload = await fetchJson(`/app/projects/${encodeURIComponent(state.projectId)}/downloads`);
    state.projectDownloadGroups = Array.isArray(payload.groups) ? payload.groups : [];
    state.projectDownloads = Array.isArray(payload.items) ? payload.items : [];
    renderProjectDownloads();
    renderQueryDetail();
  } catch (error) {
    state.projectDownloadGroups = [];
    state.projectDownloads = [];
    renderProjectDownloads();
    renderQueryDetail();
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
    const fallbackCount = [
      runtime.pdfUnpaywallFallbackEnabled,
      runtime.pdfCoreFallbackEnabled,
      runtime.pdfArxivFallbackEnabled,
    ].filter(Boolean).length;
    els.workspaceSettingsState.textContent = `${enabled ? "OA" : "Custom"} · ${searchResourceLabel(runtime.aiPrimarySearchResource)} · ${pdfDownloaderModeLabel(runtime.pdfDownloaderMode)} · ${fallbackCount} fallback${fallbackCount === 1 ? "" : "s"} · x${runtime.downloadWorkers}`;
  }
  if (els.pubmedOaOnlyToggle) {
    els.pubmedOaOnlyToggle.checked = enabled;
  }
  if (els.pubmedOaOnlyStatus) {
    els.pubmedOaOnlyStatus.textContent = enabled
      ? "OA filter is active. Every PubMed search adds free full text[sb]."
      : "OA filter is off. PubMed queries run exactly as written.";
  }
  if (els.downloadWorkerCountInput) {
    els.downloadWorkerCountInput.value = String(runtime.downloadWorkers);
  }
  if (els.downloadWorkerCountStatus) {
    els.downloadWorkerCountStatus.textContent = `Batch downloads use ${runtime.downloadWorkers} parallel worker${runtime.downloadWorkers === 1 ? "" : "s"}.`;
  }
  if (els.aiPrimarySearchResourceInput) {
    els.aiPrimarySearchResourceInput.value = normalizeSearchResource(runtime.aiPrimarySearchResource, "pubmed");
  }
  if (els.aiPrimarySearchResourceStatus) {
    const label = searchResourceLabel(runtime.aiPrimarySearchResource);
    els.aiPrimarySearchResourceStatus.textContent = `Searcher AI uses ${label} for search tool calls.`;
  }
  if (els.pdfDownloaderModeInput) {
    els.pdfDownloaderModeInput.value = normalizePdfDownloaderMode(runtime.pdfDownloaderMode, "pdf_xml");
  }
  if (els.pdfDownloaderModeStatus) {
    const mode = normalizePdfDownloaderMode(runtime.pdfDownloaderMode, "pdf_xml");
    if (mode === "pdf_xml") {
      els.pdfDownloaderModeStatus.textContent = "PDF + XML mode saves the XML first and the PDF when available.";
    } else if (mode === "xml") {
      els.pdfDownloaderModeStatus.textContent = "XML mode uses PMC, Europe PMC, NCBI eFetch and Crossref XML sources.";
    } else if (mode === "pdf") {
      els.pdfDownloaderModeStatus.textContent = "PDF mode uses PMC, Europe PMC, Crossref, DOI landing and linkout sources.";
    } else {
      els.pdfDownloaderModeStatus.textContent = "PDF + XML mode saves the XML first and the PDF when available.";
    }
  }
  if (els.pdfUnpaywallFallbackToggle) {
    els.pdfUnpaywallFallbackToggle.checked = Boolean(runtime.pdfUnpaywallFallbackEnabled);
  }
  if (els.pdfUnpaywallFallbackStatus) {
    els.pdfUnpaywallFallbackStatus.textContent = runtime.pdfUnpaywallFallbackEnabled
      ? "Unpaywall fallback is enabled and runs only when an email is configured."
      : "Unpaywall fallback is disabled.";
  }
  if (els.pdfCoreFallbackToggle) {
    els.pdfCoreFallbackToggle.checked = Boolean(runtime.pdfCoreFallbackEnabled);
  }
  if (els.pdfCoreFallbackStatus) {
    els.pdfCoreFallbackStatus.textContent = runtime.pdfCoreFallbackEnabled
      ? "CORE fallback is enabled. It accepts only strict DOI/title matches."
      : "CORE fallback is disabled, preserving the fastest default download path.";
  }
  if (els.pdfArxivFallbackToggle) {
    els.pdfArxivFallbackToggle.checked = Boolean(runtime.pdfArxivFallbackEnabled);
  }
  if (els.pdfArxivFallbackStatus) {
    els.pdfArxivFallbackStatus.textContent = runtime.pdfArxivFallbackEnabled
      ? "arXiv fallback is enabled for exact DOI or very high confidence title matches."
      : "arXiv fallback is disabled.";
  }
  if (els.settingsAssistantApiKeyInput) {
    els.settingsAssistantApiKeyInput.value = runtime.apiKey || "";
  }
  if (els.settingsAssistantApiKeyStatus) {
    els.settingsAssistantApiKeyStatus.textContent = runtime.apiKey
      ? "Gemini cloud models will use the saved API key."
      : "Add a Gemini API key to unlock the cloud models.";
  }
  if (els.modelSettingsSummary) {
    const selectedModel = normalizeAssistantModel(runtime.assistantModel);
    const visibleGemini = assistantGeminiModelItems().filter((item) => item.visible).length;
    const visibleLocal = assistantModelCatalog().filter((item) => item.provider === "local" && item.visible).length;
    const localState = [
      runtime.ollamaConnected ? `${runtime.ollamaModels.length} Ollama` : "Ollama off",
      runtime.llamacppConnected ? "llama.cpp on" : "llama.cpp off",
    ].join(" · ");
    els.modelSettingsSummary.textContent = `${assistantModelDisplayLabel(selectedModel) || selectedModel} selected · ${visibleGemini} Gemini visible · ${visibleLocal} local visible · ${localState}.`;
  }
  if (els.ollamaBaseUrlInput) {
    els.ollamaBaseUrlInput.value = runtime.ollamaBaseUrl || "http://localhost:11434";
  }
  if (els.ollamaStatus) {
    const parts = [];
    if (runtime.ollamaConnected) {
      parts.push(`Ollama is reachable${runtime.ollamaVersion ? ` (v${runtime.ollamaVersion})` : ""}.`);
      parts.push(`${Array.isArray(runtime.ollamaModels) ? runtime.ollamaModels.length : 0} model${(runtime.ollamaModels?.length || 0) === 1 ? "" : "s"} detected.`);
      if (runtime.ollamaModel) {
        parts.push(`Selected model: ${runtime.ollamaModel}.`);
      }
      if (runtime.ollamaWarmupPending) {
        parts.push(`Loading ${runtime.ollamaWarmupModel || runtime.ollamaModel || "model"}...`);
      }
    } else {
      parts.push(`Ollama is not reachable at ${runtime.ollamaBaseUrl || "http://localhost:11434"}.`);
    }
    if (runtime.ollamaError) {
      parts.push(runtime.ollamaError);
    }
    if (runtime.ollamaWarmupError) {
      parts.push(`Warmup failed: ${runtime.ollamaWarmupError}`);
    }
    els.ollamaStatus.textContent = parts.join(" ");
  }
  if (els.llamacppBaseUrlInput) els.llamacppBaseUrlInput.value = runtime.llamacppBaseUrl || "http://localhost:8098";
  if (els.llamacppModelInput) els.llamacppModelInput.value = runtime.llamacppModel || "local";
  if (els.llamacppExecutableInput) els.llamacppExecutableInput.value = runtime.llamacppExecutable || "";
  if (els.llamacppModelPathInput) els.llamacppModelPathInput.value = runtime.llamacppModelPath || "";
  if (els.llamacppLibraryPathInput) els.llamacppLibraryPathInput.value = runtime.llamacppLibraryPath || "";
  if (els.llamacppServerArgsInput) els.llamacppServerArgsInput.value = runtime.llamacppServerArgs || "";
  const llamaArgs = parseLlamaCppArgs(runtime.llamacppServerArgs || "");
  if (els.llamacppProfileInput) els.llamacppProfileInput.value = llamaArgs.profile;
  if (els.llamacppContextInput) els.llamacppContextInput.value = llamaArgs.context;
  if (els.llamacppBatchInput) els.llamacppBatchInput.value = llamaArgs.batch;
  if (els.llamacppUbatchInput) els.llamacppUbatchInput.value = llamaArgs.ubatch;
  if (els.llamacppCpuMoeInput) els.llamacppCpuMoeInput.value = llamaArgs.cpuMoe;
  if (els.llamacppCacheKInput) els.llamacppCacheKInput.value = llamaArgs.cacheK;
  if (els.llamacppCacheVInput) els.llamacppCacheVInput.value = llamaArgs.cacheV;
  if (els.llamacppCacheRamInput) els.llamacppCacheRamInput.value = llamaArgs.cacheRam;
  if (els.llamacppReasoningInput) els.llamacppReasoningInput.value = llamaArgs.reasoning;
  if (els.llamacppReasoningBudgetInput) els.llamacppReasoningBudgetInput.value = llamaArgs.reasoningBudget;
  if (els.llamacppFitTargetInput) els.llamacppFitTargetInput.value = llamaArgs.fitTarget;
  if (els.llamacppStatus) {
    const parts = [];
    if (runtime.llamacppConnected) {
      parts.push(`llama.cpp is reachable at ${runtime.llamacppBaseUrl}.`);
      if (runtime.llamacppStarted) parts.push("Started by Native Researcher.");
      if (runtime.llamacppModel) parts.push(`Selected model: ${runtime.llamacppModel}.`);
    } else {
      parts.push(`llama.cpp is not reachable at ${runtime.llamacppBaseUrl || "http://localhost:8098"}.`);
    }
    if (runtime.llamacppError) parts.push(runtime.llamacppError);
    if (runtime.llamacppWarmupError) parts.push(`Warmup failed: ${runtime.llamacppWarmupError}`);
    els.llamacppStatus.textContent = parts.join(" ");
  }
  if (els.availableModelsStatus) {
    if (runtime.ollamaConnected || runtime.llamacppConnected) {
      const localCount = assistantLocalModelItems().length + assistantLlamaCppModelItems().length;
      els.availableModelsStatus.textContent = `${localCount} local model${localCount === 1 ? "" : "s"} configured. Toggle any Gemini preset, Ollama model, or llama.cpp model to show it in the assistant selector.`;
    } else {
      els.availableModelsStatus.textContent = "Only the Gemini presets are currently available. Connect Ollama or llama.cpp to use local models.";
    }
  }
  if (els.availableModelsList) {
    els.availableModelsList.innerHTML = renderAvailableModelsMarkup();
  }
  if (els.searchResource) {
    els.searchResource.value = normalizeSearchResource(runtime.searchResource, "pubmed");
  }
  if (els.sidebarQuickSearchResource) {
    els.sidebarQuickSearchResource.value = normalizeSearchResource(runtime.searchResource, "pubmed");
  }
}

function setApiKeysDialogOpen(next) {
  const open = Boolean(next);
  els.apiKeysPopup?.classList.toggle("is-open", open);
  els.apiKeysOverlay?.classList.toggle("is-open", open);
  if (els.apiKeysPopup) els.apiKeysPopup.hidden = !open;
  if (els.apiKeysOverlay) els.apiKeysOverlay.hidden = !open;
  if (els.apiKeysPopup) els.apiKeysPopup.setAttribute("aria-hidden", open ? "false" : "true");
}

function setModelSettingsDialogOpen(next) {
  const open = Boolean(next);
  els.modelSettingsPopup?.classList.toggle("is-open", open);
  els.modelSettingsOverlay?.classList.toggle("is-open", open);
  if (els.modelSettingsPopup) els.modelSettingsPopup.hidden = !open;
  if (els.modelSettingsOverlay) els.modelSettingsOverlay.hidden = !open;
  if (els.modelSettingsPopup) els.modelSettingsPopup.setAttribute("aria-hidden", open ? "false" : "true");
  if (open) {
    requestAnimationFrame(() => {
      els.settingsAssistantApiKeyInput?.focus();
    });
  } else {
    requestAnimationFrame(() => {
      els.sidebarOpenModelSettingsBtn?.focus();
    });
  }
}

function setAssistantModelLoading(next, target = "") {
  runtime.assistantModelLoading = Boolean(next);
  runtime.assistantModelLoadingTarget = next ? String(target || "").trim() : "";
  runtime.assistantModelLoadingStartedAt = next ? Date.now() : 0;
  updateAssistantModelLoadingPopup();
}

function updateAssistantModelLoadingPopup() {
  const popup = els.assistantModelLoadingPopup;
  if (!popup) return;
  const target = normalizeAssistantModel(runtime.assistantModelLoadingTarget || runtime.assistantModel);
  const isLlamaTarget = isLlamaCppAssistantModel(target);
  const localModel = isOllamaAssistantModel(target)
    ? target.slice("ollama:".length).trim()
    : (isLlamaTarget ? target.slice("llamacpp:".length).trim() : "");
  const loading = Boolean(runtime.assistantModelLoading) && Boolean(localModel);
  popup.hidden = !loading;
  popup.classList.toggle("is-open", loading);
  if (!loading) {
    if (els.assistantModelLoadingSize) els.assistantModelLoadingSize.textContent = "";
    if (els.assistantModelLoadingTitle) els.assistantModelLoadingTitle.textContent = "";
    if (els.assistantModelLoadingMeta) els.assistantModelLoadingMeta.textContent = "";
    if (els.assistantModelLoadingBarFill) els.assistantModelLoadingBarFill.style.width = "0%";
    if (els.assistantInput) els.assistantInput.disabled = false;
    setAssistantSendButtonStreaming(Boolean(state.assistantStreamAbort));
    return;
  }
  const sizeLabel = isLlamaTarget ? "Local server" : (ollamaModelSizeLabel(localModel) || "Loading...");
  const displayLabel = assistantModelDisplayLabel(target) || localModel;
  if (els.assistantModelLoadingSize) els.assistantModelLoadingSize.textContent = sizeLabel;
  if (els.assistantModelLoadingTitle) els.assistantModelLoadingTitle.textContent = `Loading ${displayLabel}...`;
  if (els.assistantModelLoadingMeta) {
    if (isLlamaTarget) {
      els.assistantModelLoadingMeta.textContent = runtime.llamacppWarmupError
        ? `Warmup error: ${runtime.llamacppWarmupError}`
        : "Waiting for llama.cpp to produce the first response.";
    } else {
      const warmupTarget = String(runtime.ollamaWarmupModel || runtime.ollamaModel || "").trim();
      const warmupMatchesTarget = !warmupTarget || warmupTarget === localModel;
      const warmupLabel = runtime.ollamaWarmupPending && warmupMatchesTarget
        ? "Starting Ollama and warming the model."
        : "Preparing the model for chat.";
      els.assistantModelLoadingMeta.textContent = runtime.ollamaWarmupError
        ? `Warmup error: ${runtime.ollamaWarmupError}`
        : warmupLabel;
    }
  }
  if (els.assistantModelLoadingBarFill) {
    els.assistantModelLoadingBarFill.style.width = "100%";
  }
  if (els.assistantInput) els.assistantInput.disabled = true;
  if (els.assistantSendBtn) els.assistantSendBtn.disabled = true;
}

function applyApiKeyValues(payload = {}) {
  runtime.apiKey = payload.assistant_api_key || localStorage.getItem("researcher2_api_key") || "";
  runtime.ncbiApiKey = payload.ncbi_api_key || "";
  runtime.openalexApiKey = payload.openalex_api_key || "";
  runtime.coreApiKey = payload.core_api_key || "";
  runtime.unpaywallEmail = payload.unpaywall_email || "";
  runtime.pubmedOaOnly = payload.pubmed_oa_only !== undefined
    ? Boolean(payload.pubmed_oa_only)
    : localStorage.getItem(pubmedOaOnlyStorageKey) !== "false";
  runtime.aiPrimarySearchResource = normalizeSearchResource(
    payload.ai_primary_search_resource,
    runtime.aiPrimarySearchResource || "pubmed",
  );
  runtime.pdfDownloaderMode = normalizePdfDownloaderMode(
    payload.pdf_downloader_mode,
    runtime.pdfDownloaderMode || "pdf_xml",
  );
  runtime.pdfUnpaywallFallbackEnabled = payload.pdf_unpaywall_fallback_enabled !== undefined
    ? Boolean(payload.pdf_unpaywall_fallback_enabled)
    : true;
  runtime.pdfCoreFallbackEnabled = Boolean(payload.pdf_core_fallback_enabled);
  runtime.pdfArxivFallbackEnabled = Boolean(payload.pdf_arxiv_fallback_enabled);
  localStorage.setItem("researcher2_api_key", runtime.apiKey);
  localStorage.setItem(pubmedOaOnlyStorageKey, runtime.pubmedOaOnly ? "true" : "false");
  if (els.assistantApiKeyInput) els.assistantApiKeyInput.value = runtime.apiKey;
  if (els.settingsAssistantApiKeyInput) els.settingsAssistantApiKeyInput.value = runtime.apiKey;
  if (els.ncbiApiKeyInput) els.ncbiApiKeyInput.value = runtime.ncbiApiKey;
  if (els.openalexApiKeyInput) els.openalexApiKeyInput.value = runtime.openalexApiKey;
  if (els.coreApiKeyInput) els.coreApiKeyInput.value = runtime.coreApiKey;
  if (els.unpaywallEmailInput) els.unpaywallEmailInput.value = runtime.unpaywallEmail;
  renderSettingsPanel();
}

function applyOllamaValues(payload = {}) {
  const previousOllamaModel = currentOllamaAssistantModel();
  runtime.ollamaBaseUrl = normalizeOllamaBaseUrl(
    payload.ollama_base_url,
    runtime.ollamaBaseUrl || "http://localhost:11434",
  );
  runtime.ollamaModel = String(payload.ollama_model || "").trim();
  runtime.ollamaThinkingLevel = normalizeOllamaThinkingLevel(
    payload.ollama_thinking_level,
    runtime.ollamaThinkingLevel || "off",
  );
  runtime.ollamaConnected = Boolean(payload.connected);
  runtime.ollamaVersion = String(payload.version || "").trim();
  runtime.ollamaModels = Array.isArray(payload.models) ? payload.models : [];
  runtime.ollamaError = String(payload.error || "").trim();
  runtime.ollamaWarmupError = String(payload.warmup_error || "").trim();
  runtime.ollamaWarmupPending = Boolean(payload.warming_up);
  runtime.ollamaWarmupModel = String(payload.warming_model || "").trim();
  if (runtime.ollamaModel && !runtime.ollamaModels.some((model) => model.name === runtime.ollamaModel)) {
    runtime.ollamaModels = [...runtime.ollamaModels];
  }
  if (runtime.assistantModelLoading && isOllamaAssistantModel(runtime.assistantModelLoadingTarget)) {
    runtime.assistantModel = normalizeAssistantModel(runtime.assistantModelLoadingTarget);
  } else if (isOllamaAssistantModel(runtime.assistantModel)) {
    const nextOllamaModel = currentOllamaAssistantModel();
    runtime.assistantModel = nextOllamaModel || "Gemini 3 Flash";
  } else if (runtime.assistantModel === previousOllamaModel) {
    runtime.assistantModel = currentOllamaAssistantModel() || "Gemini 3 Flash";
  }
  if (currentOllamaAssistantModel()) {
    ensureAssistantModelVisible(currentOllamaAssistantModel());
  }
  updateAssistantModelUI();
  updateThinkingLabel();
  updateAssistantModelLoadingPopup();
  renderSettingsPanel();
}

function applyLlamaCppValues(payload = {}) {
  const previousModel = currentLlamaCppAssistantModel();
  runtime.llamacppBaseUrl = normalizeLlamaCppBaseUrl(
    payload.llamacpp_base_url,
    runtime.llamacppBaseUrl || "http://localhost:8098",
  );
  runtime.llamacppModel = String(payload.llamacpp_model || runtime.llamacppModel || "local").trim();
  runtime.llamacppExecutable = String(payload.llamacpp_executable || "").trim();
  runtime.llamacppModelPath = String(payload.llamacpp_model_path || "").trim();
  runtime.llamacppLibraryPath = String(payload.llamacpp_library_path || "").trim();
  runtime.llamacppServerArgs = String(payload.llamacpp_server_args || "").trim();
  runtime.llamacppConnected = Boolean(payload.connected);
  runtime.llamacppStarted = Boolean(payload.started);
  runtime.llamacppModels = Array.isArray(payload.models) ? payload.models : [];
  runtime.llamacppError = String(payload.error || "").trim();
  runtime.llamacppWarmupError = String(payload.warmup_error || "").trim();
  if (isLlamaCppAssistantModel(runtime.assistantModel)) {
    runtime.assistantModel = currentLlamaCppAssistantModel() || "Gemini 3 Flash";
  } else if (runtime.assistantModel === previousModel) {
    runtime.assistantModel = currentLlamaCppAssistantModel() || "Gemini 3 Flash";
  }
  if (currentLlamaCppAssistantModel()) {
    ensureAssistantModelVisible(currentLlamaCppAssistantModel());
  }
  updateAssistantModelUI();
  renderSettingsPanel();
}

async function monitorOllamaWarmup(targetModel, timeoutMs = 600000) {
  const normalizedTarget = normalizeAssistantModel(targetModel);
  const startedAt = Date.now();
  while (runtime.assistantModelLoading && normalizeAssistantModel(runtime.assistantModelLoadingTarget) === normalizedTarget) {
    await loadOllamaSettings().catch(() => {});
    const warmupModel = String(runtime.ollamaWarmupModel || runtime.ollamaModel || "").trim();
    const waitingForTarget = !warmupModel || warmupModel === normalizedTarget.slice("ollama:".length).trim();
    if (!runtime.ollamaWarmupPending && waitingForTarget) {
      break;
    }
    if (Date.now() - startedAt >= timeoutMs) {
      runtime.ollamaWarmupError = `Ollama warmup timed out for ${assistantModelDisplayLabel(normalizedTarget) || normalizedTarget}.`;
      break;
    }
    await delay(1500);
  }
  const minVisibleMs = 6000;
  const visibleFor = Date.now() - Number(runtime.assistantModelLoadingStartedAt || startedAt);
  if (runtime.assistantModelLoading && visibleFor < minVisibleMs) {
    await delay(minVisibleMs - visibleFor);
  }
  if (runtime.assistantModelLoading && normalizeAssistantModel(runtime.assistantModelLoadingTarget) === normalizedTarget) {
    setAssistantModelLoading(false);
    updateAssistantModelUI();
    updateThinkingLabel();
    renderSettingsPanel();
  }
  if (runtime.ollamaWarmupError) {
    trackAppEvent("error", "assistant_model_select_failed", runtime.ollamaWarmupError, {
      assistant_model: normalizedTarget,
    });
  }
}

async function loadApiKeys() {
  const payload = await fetchJson("/app/api-keys");
  applyApiKeyValues(payload);
}

async function loadOllamaSettings() {
  const payload = await fetchJson("/app/ollama");
  applyOllamaValues(payload);
}

async function loadLlamaCppSettings() {
  const payload = await fetchJson("/app/llamacpp");
  applyLlamaCppValues(payload);
}

async function saveApiKeys(overrides = {}, options = {}) {
  const { closeDialog = true } = options;
  const payload = await fetchJson("/app/api-keys", {
    method: "PUT",
    body: JSON.stringify({
      assistant_api_key: runtime.apiKey,
      ncbi_api_key: runtime.ncbiApiKey,
      openalex_api_key: runtime.openalexApiKey,
      core_api_key: runtime.coreApiKey,
      unpaywall_email: runtime.unpaywallEmail,
      pubmed_oa_only: runtime.pubmedOaOnly,
      ai_primary_search_resource: normalizeSearchResource(runtime.aiPrimarySearchResource, "pubmed"),
      pdf_downloader_mode: normalizePdfDownloaderMode(runtime.pdfDownloaderMode, "pdf_xml"),
      pdf_unpaywall_fallback_enabled: Boolean(runtime.pdfUnpaywallFallbackEnabled),
      pdf_core_fallback_enabled: Boolean(runtime.pdfCoreFallbackEnabled),
      pdf_arxiv_fallback_enabled: Boolean(runtime.pdfArxivFallbackEnabled),
      ...overrides,
    }),
  });
  applyApiKeyValues(payload);
  trackAppEvent("info", "api_keys_saved_ui", "API keys updated from the native UI.", {
    has_ncbi_api_key: Boolean(runtime.ncbiApiKey),
    has_openalex_api_key: Boolean(runtime.openalexApiKey),
    has_core_api_key: Boolean(runtime.coreApiKey),
    has_unpaywall_email: Boolean(runtime.unpaywallEmail),
    pubmed_oa_only: Boolean(runtime.pubmedOaOnly),
    ai_primary_search_resource: normalizeSearchResource(runtime.aiPrimarySearchResource, "pubmed"),
    pdf_downloader_mode: normalizePdfDownloaderMode(runtime.pdfDownloaderMode, "pdf_xml"),
    pdf_unpaywall_fallback_enabled: Boolean(runtime.pdfUnpaywallFallbackEnabled),
    pdf_core_fallback_enabled: Boolean(runtime.pdfCoreFallbackEnabled),
    pdf_arxiv_fallback_enabled: Boolean(runtime.pdfArxivFallbackEnabled),
  });
  if (closeDialog) {
    setApiKeysDialogOpen(false);
  }
}

async function submitOllamaSettings(overrides = {}) {
  const payload = await fetchJson("/app/ollama", {
    method: "PUT",
    body: JSON.stringify({
      ollama_base_url: runtime.ollamaBaseUrl,
      ollama_model: runtime.ollamaModel,
      ollama_thinking_level: normalizeOllamaThinkingLevel(runtime.ollamaThinkingLevel, "off"),
      ...overrides,
    }),
  });
  return payload;
}

async function submitLlamaCppSettings(overrides = {}) {
  const payload = await fetchJson("/app/llamacpp", {
    method: "PUT",
    body: JSON.stringify({
      llamacpp_base_url: runtime.llamacppBaseUrl,
      llamacpp_model: runtime.llamacppModel,
      llamacpp_executable: runtime.llamacppExecutable,
      llamacpp_model_path: runtime.llamacppModelPath,
      llamacpp_library_path: runtime.llamacppLibraryPath,
      llamacpp_server_args: runtime.llamacppServerArgs,
      ...overrides,
    }),
  });
  return payload;
}

async function saveLlamaCppSettings(overrides = {}) {
  const payload = await submitLlamaCppSettings({
    start: false,
    warmup: false,
    ...overrides,
  });
  applyLlamaCppValues(payload);
  trackAppEvent("info", "llamacpp_settings_saved_ui", "llama.cpp settings updated from the native UI.", {
    llamacpp_base_url: payload.llamacpp_base_url || runtime.llamacppBaseUrl,
    llamacpp_model: payload.llamacpp_model || runtime.llamacppModel,
    connected: Boolean(payload.connected),
  });
  return payload;
}

async function saveOllamaSettings(overrides = {}) {
  const payload = await submitOllamaSettings({
    warmup: false,
    ...overrides,
  });
  applyOllamaValues(payload);
  trackAppEvent("info", "ollama_settings_saved_ui", "Ollama settings updated from the native UI.", {
    ollama_base_url: payload.ollama_base_url || runtime.ollamaBaseUrl,
    ollama_model: payload.ollama_model || runtime.ollamaModel,
    connected: Boolean(payload.connected),
  });
  return payload;
}

async function connectOllamaSettings() {
  const candidates = collectOllamaConnectCandidates();
  const originalBaseUrl = String(els.ollamaBaseUrlInput?.value || runtime.ollamaBaseUrl || "").trim();
  let lastError = "";
  if (els.ollamaConnectBtn) els.ollamaConnectBtn.disabled = true;
  try {
    for (const baseUrl of candidates) {
      runtime.ollamaBaseUrl = baseUrl;
      try {
        const payload = await submitOllamaSettings({
          ollama_base_url: baseUrl,
          ollama_thinking_level: normalizeOllamaThinkingLevel(runtime.ollamaThinkingLevel, "off"),
          warmup: true,
        });
        applyOllamaValues(payload);
        if (!payload.connected) {
          lastError = payload.error || `Ollama is not reachable at ${baseUrl}.`;
          continue;
        }
        runtime.ollamaBaseUrl = payload.ollama_base_url || baseUrl;
        if (els.ollamaBaseUrlInput) els.ollamaBaseUrlInput.value = runtime.ollamaBaseUrl;
        trackAppEvent("info", "ollama_connected_ui", "Ollama connection requested from the native UI.", {
          ollama_base_url: payload.ollama_base_url || baseUrl,
          ollama_model: runtime.ollamaModel,
          connected: Boolean(payload.connected),
          warming_up: Boolean(payload.warming_up),
          candidates_tried: candidates,
        });
        return payload;
      } catch (error) {
        lastError = error.message || `Ollama connection failed at ${baseUrl}.`;
      }
    }
    runtime.ollamaBaseUrl = normalizeOllamaBaseUrl(originalBaseUrl || runtime.ollamaBaseUrl || "http://localhost:11434");
    if (els.ollamaBaseUrlInput) els.ollamaBaseUrlInput.value = runtime.ollamaBaseUrl;
    throw new Error(lastError || "Ollama could not be connected.");
  } catch (error) {
    renderSettingsPanel();
    trackAppEvent("error", "ollama_connect_failed", error.message || "Ollama connection failed.", {
      ollama_base_url: runtime.ollamaBaseUrl,
      ollama_model: runtime.ollamaModel,
      candidates_tried: candidates,
    });
    throw error;
  } finally {
    if (els.ollamaConnectBtn) els.ollamaConnectBtn.disabled = false;
  }
}

async function selectAssistantModel(requestedModel) {
  const normalized = normalizeAssistantModel(requestedModel);
  if (!normalized) return;
  if (runtime.assistantModelLoading) return;
  if (isOllamaAssistantModel(normalized)) {
    const localModel = normalized.slice("ollama:".length).trim();
    if (!localModel) {
      return;
    }
    runtime.ollamaWarmupError = "";
    runtime.ollamaWarmupPending = true;
    runtime.ollamaWarmupModel = localModel;
    setAssistantModelLoading(true, normalized);
    runtime.assistantModel = normalized;
    ensureAssistantModelVisible(runtime.assistantModel);
    localStorage.setItem(assistantModelStorageKey, runtime.assistantModel);
    updateAssistantModelUI();
    updateThinkingLabel();
    renderSettingsPanel();
    await nextAnimationFrame();
    try {
      const payload = await saveOllamaSettings({
        ollama_model: localModel,
        warmup: true,
      });
      if (!payload.connected) {
        throw new Error(payload.error || "Ollama is not reachable.");
      }
      if (payload.warmup_error && !payload.warming_up) {
        throw new Error(payload.warmup_error);
      }
      runtime.assistantModel = `ollama:${localModel}`;
      ensureAssistantModelVisible(runtime.assistantModel);
      localStorage.setItem(assistantModelStorageKey, runtime.assistantModel);
      trackAppEvent("info", "assistant_model_selected_ui", "Local model selected from the assistant panel.", {
        assistant_model: runtime.assistantModel,
        provider: "ollama",
      });
      void monitorOllamaWarmup(normalized);
    } catch (error) {
      runtime.ollamaWarmupPending = false;
      setAssistantModelLoading(false);
      trackAppEvent("error", "assistant_model_select_failed", error.message || "Local model could not be loaded.", {
        assistant_model: normalized,
      });
    }
    updateAssistantModelUI();
    updateThinkingLabel();
    renderSettingsPanel();
    return;
  }
  if (isLlamaCppAssistantModel(normalized)) {
    const localModel = normalized.slice("llamacpp:".length).trim();
    if (!localModel) return;
    runtime.llamacppWarmupError = "";
    runtime.llamacppModel = localModel;
    setAssistantModelLoading(true, normalized);
    runtime.assistantModel = normalized;
    ensureAssistantModelVisible(runtime.assistantModel);
    localStorage.setItem(assistantModelStorageKey, runtime.assistantModel);
    updateAssistantModelUI();
    renderSettingsPanel();
    await nextAnimationFrame();
    try {
      const payload = await saveLlamaCppSettings({
        llamacpp_model: localModel,
        warmup: true,
      });
      if (!payload.connected) {
        throw new Error(payload.error || "llama.cpp is not reachable.");
      }
      if (payload.warmup_error) {
        throw new Error(payload.warmup_error);
      }
      runtime.assistantModel = `llamacpp:${localModel}`;
      ensureAssistantModelVisible(runtime.assistantModel);
      localStorage.setItem(assistantModelStorageKey, runtime.assistantModel);
      trackAppEvent("info", "assistant_model_selected_ui", "llama.cpp model selected from the assistant panel.", {
        assistant_model: runtime.assistantModel,
        provider: "llamacpp",
      });
    } catch (error) {
      runtime.llamacppWarmupError = error.message || "llama.cpp model could not be loaded.";
      trackAppEvent("error", "assistant_model_select_failed", runtime.llamacppWarmupError, {
        assistant_model: normalized,
      });
    } finally {
      setAssistantModelLoading(false);
    }
    updateAssistantModelUI();
    updateThinkingLabel();
    renderSettingsPanel();
    return;
  }
  runtime.assistantModel = normalized;
  ensureAssistantModelVisible(runtime.assistantModel);
  localStorage.setItem(assistantModelStorageKey, runtime.assistantModel);
  trackAppEvent("info", "assistant_model_selected_ui", "Assistant model selected from the panel.", {
    assistant_model: runtime.assistantModel,
    provider: "gemini",
  });
  updateAssistantModelUI();
  updateThinkingLabel();
  renderSettingsPanel();
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
  if (action.name === "create_research_plan") {
    return {
      type: action.type,
      name: action.name,
      title: action.title,
      status: action.status,
      call_id: action.call_id,
      details: cloneJson(details),
    };
  }
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

function persistAssistantSessions({ scheduleSave = true, preserveCurrentSelection = true } = {}) {
  const nextSessions = state.assistantSessions
    .filter(sessionHasContent)
    .slice(0, 24)
    .map((item) => createAssistantSession(item));
  state.assistantSessions = nextSessions;
  if (state.currentSessionId && !nextSessions.some((item) => item.id === state.currentSessionId)) {
    state.currentSessionId = nextSessions[0]?.id || null;
  } else if (!state.currentSessionId && preserveCurrentSelection) {
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
  persistAssistantSessions({ preserveCurrentSelection: false });
  requestAnimationFrame(() => {
    els.assistantInput?.focus();
  });
}

function setAssistantModeMenuOpen(next) {
  if (!els.assistantModeMenu || !els.assistantDraftBtn) return;
  const isOpen = Boolean(next);
  els.assistantModeMenu.hidden = !isOpen;
  els.assistantDraftBtn.setAttribute("aria-expanded", isOpen ? "true" : "false");
}

function setAssistantMode(mode) {
  const normalized = mode === "research_agent" ? "research_agent" : "fast";
  state.assistantMode = normalized;
  localStorage.setItem("native_researcher_assistant_mode", normalized);
  if (els.assistantInput) {
    els.assistantInput.placeholder = normalized === "research_agent"
      ? "Describe the research topic for the Researcher Agent..."
      : "Ask Searcher AI...";
  }
  renderAssistantHeader();
}

function startResearchAgentMode() {
  setAssistantModeMenuOpen(false);
  setAssistantMode("research_agent");
  createNewAssistantChat();
  pushAssistantMessage({
    role: "assistant",
    text: "Research Agent Mode is ready. Send a research topic and I will create the first structured plan with the planning tool.",
    meta: "Planning only. No search or screening will run yet.",
  });
}

function startNormalMode() {
  setAssistantModeMenuOpen(false);
  setAssistantMode("fast");
  els.assistantInput?.focus();
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
    const fallbackTitle = state.assistantMode === "research_agent" ? "Research Agent" : "New chat";
    els.assistantHeaderTitle.textContent = state.chatHistoryOpen
      ? "Chats"
      : (currentAssistantSession()?.title || fallbackTitle);
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

function currentSearchSource() {
  return normalizeSearchResource(
    state.lastPubmedResponse?.meta?.primary_source
      || state.lastSearchPayload?.preferred_source
      || runtime.searchResource,
    "pubmed",
  );
}

function currentSearchSourceLabel() {
  return searchResourceLabel(currentSearchSource());
}

function currentSearchSourcesUsed() {
  const used = state.lastPubmedResponse?.meta?.sources_used;
  if (Array.isArray(used) && used.length) {
    return used.map((item) => searchResourceLabel(item)).join(", ");
  }
  return currentSearchSourceLabel();
}

function detailFieldPresentation(field) {
  const source = currentSearchSource();
  if (source === "openalex") {
    switch (field) {
      case "mesh":
        return {
          label: "Primary Topic",
          title: "Primary Topic",
          empty: "Primary topic not available.",
        };
      case "keywords":
        return {
          label: "Topics",
          title: "Topics",
          empty: "Topics not available.",
        };
      case "related_articles":
        return {
          label: "Related Works",
          title: "Related Works",
          empty: "Related works not available.",
        };
      default:
        break;
    }
  }
  if (source === "arxiv") {
    switch (field) {
      case "mesh":
        return {
          label: "Primary Category",
          title: "Primary Category",
          empty: "Primary category not available.",
        };
      case "keywords":
        return {
          label: "Categories",
          title: "Categories",
          empty: "Categories not available.",
        };
      default:
        break;
    }
  }
  switch (field) {
    case "mesh":
      return {
        label: "MeSH",
        title: "MeSH",
        empty: "MeSH terms not available.",
      };
    case "keywords":
      return {
        label: "Keywords",
        title: "Keywords",
        empty: "Keywords not available.",
      };
    case "related_articles":
      return {
        label: "Related Articles",
        title: "Related Articles",
        empty: "No related articles found.",
      };
    default:
      return {
        label: field,
        title: field,
        empty: "Not available.",
      };
  }
}

function articleTitleMeta(article) {
  const bits = [article.journal || "", article.publication_date || ""].filter(Boolean);
  const branch = articleResearchBranchLabel(article);
  const score = articleResearchScore(article);
  if (branch) bits.push(`Branch ${branch}`);
  if (score !== null) bits.push(`Score ${formatResearchScore(score)}`);
  const sourceId = sourceRecordLabel(article);
  if (sourceId) bits.push(sourceId);
  if (article.doi) bits.push(`DOI ${article.doi}`);
  return bits.slice(0, 4).join(" · ");
}

function articleResearchMeta(article) {
  return article?.research_meta && typeof article.research_meta === "object" ? article.research_meta : {};
}

function articleResearchScore(article) {
  const value = Number(articleResearchMeta(article).score);
  return Number.isFinite(value) ? value : null;
}

function formatResearchScore(score) {
  if (!Number.isFinite(Number(score))) return "-";
  return Number(score).toFixed(2);
}

function articleResearchBranchLabel(article) {
  const meta = articleResearchMeta(article);
  const selected = String(meta.selected_branch_label || "").trim();
  if (selected) return selected;
  const branches = Array.isArray(meta.branches) ? meta.branches : [];
  return branches.map((item) => item?.label || item?.id || "").filter(Boolean).join(", ");
}

function articleResearchSourcesLabel(article) {
  const meta = articleResearchMeta(article);
  const sources = Array.isArray(meta.sources) ? meta.sources : [];
  if (sources.length) return sources.map((item) => searchResourceLabel(item)).join(", ");
  return currentSearchSourcesUsed();
}

function articleResearchSourceDetails(article) {
  const meta = articleResearchMeta(article);
  const matches = Array.isArray(meta.source_matches) && meta.source_matches.length
    ? meta.source_matches
    : Array.isArray(meta.matches) ? meta.matches : [];
  if (!matches.length) return `Sources: ${articleResearchSourcesLabel(article) || "-"}`;
  return matches.map((match, index) => [
    `Match ${index + 1}`,
    `Source: ${searchResourceLabel(match.source || match.database || "")}`,
    `Branch: ${match.branch_label || match.branch_id || "-"}`,
    `Raw query: ${match.raw_query || "-"}`,
    `Extracted query: ${match.extracted_query || match.query || "-"}`,
  ].join("\n")).join("\n\n");
}

function sourceRecordLabel(article) {
  const recordId = article?.source_record_id || "";
  if (!recordId) return "";
  const source = String(article?.source_name || "").toLowerCase();
  if (source === "arxiv") return `arXiv ${recordId}`;
  if (source === "core") return `CORE ${recordId}`;
  if (source === "openalex") return `OpenAlex ${recordId}`;
  return recordId;
}

function tableIdentifier(article) {
  if (article?.pmid) return article.pmid;
  if (article?.pmc_id) return article.pmc_id;
  const sourceId = sourceRecordLabel(article);
  if (sourceId) return sourceId;
  if (article?.doi) return article.doi;
  return "-";
}

function journalQuartileLabel(article) {
  return article.journal_quartile || "-";
}

function journalQuartileSubtext(article) {
  const bits = [];
  if (typeof article.journal_sjr === "number") bits.push(`SJR ${article.journal_sjr.toFixed(3)}`);
  if (Number.isInteger(article.journal_metric_year)) bits.push(String(article.journal_metric_year));
  return bits.join(" · ");
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
  if (["core", "arxiv"].includes(String(article?.source_name || "").toLowerCase())) {
    return article.landing_page_url || links.doi || links.pubmed || links.pmc || null;
  }
  return links.pmc || links.doi || links.pubmed || article.landing_page_url || null;
}

function articleReference(article) {
  return {
    source_name: article.source_name || null,
    source_record_id: article.source_record_id || null,
    title: article.title || null,
    year: article.year || null,
    journal: article.journal || null,
    doi: article.doi || null,
    pmc_id: article.pmc_id || null,
    pmid: article.pmid || null,
    oa_pdf_url: article.oa_pdf_url || null,
    landing_page_url: article.landing_page_url || null,
  };
}

function buildFileOpenUrl(filePath) {
  return `/pdf/file?path=${encodeURIComponent(filePath)}`;
}

function filePathFromOpenUrl(openUrl) {
  if (!openUrl) return "";
  try {
    const parsed = new URL(openUrl, window.location.origin);
    return parsed.searchParams.get("path") || "";
  } catch (_error) {
    return "";
  }
}

function normalizeDocumentPath(filePath) {
  return String(filePath || "").trim();
}

function documentKindFromPath(filePath) {
  const suffix = normalizeDocumentPath(filePath).split(".").pop()?.toLowerCase() || "";
  if (suffix === "pdf") return "pdf";
  if (suffix === "xml") return "xml";
  return "text";
}

function artifactPathsFromValue(value) {
  if (!value) return {};
  if (typeof value === "object" && !Array.isArray(value)) {
    return {
      pdf: normalizeDocumentPath(value.pdf || value.PDF || value["pdf"]),
      xml: normalizeDocumentPath(value.xml || value.XML || value["xml"]),
    };
  }
  try {
    const parsed = JSON.parse(String(value));
    if (parsed && typeof parsed === "object") {
      return {
        pdf: normalizeDocumentPath(parsed.pdf || parsed.PDF || parsed["pdf"]),
        xml: normalizeDocumentPath(parsed.xml || parsed.XML || parsed["xml"]),
      };
    }
  } catch (_error) {
    return {};
  }
  return {};
}

function availableDocumentKinds(artifactPaths = {}) {
  const kinds = [];
  if (normalizeDocumentPath(artifactPaths.pdf)) kinds.push("pdf");
  if (normalizeDocumentPath(artifactPaths.xml)) kinds.push("xml");
  return kinds;
}

function documentTitleFromPath(filePath) {
  const normalized = normalizeDocumentPath(filePath);
  if (!normalized) return "Document";
  return normalized.split("/").pop() || "Document";
}

function configurePdfJsWorker(pdfjsLib) {
  if (!pdfjsLib?.GlobalWorkerOptions) return;
  if (!pdfjsLib.GlobalWorkerOptions.workerSrc) {
    pdfjsLib.GlobalWorkerOptions.workerSrc = pdfJsWorkerUrl;
  }
}

async function loadPdfJs() {
  if (window.pdfjsLib) {
    configurePdfJsWorker(window.pdfjsLib);
    return window.pdfjsLib;
  }
  if (!pdfJsLoadPromise) {
    pdfJsLoadPromise = new Promise((resolve, reject) => {
      const existing = document.querySelector('script[data-pdfjs-loader="true"]');
      if (existing && window.pdfjsLib) {
        configurePdfJsWorker(window.pdfjsLib);
        resolve(window.pdfjsLib);
        return;
      }
      const script = document.createElement("script");
      script.src = pdfJsScriptUrl;
      script.async = true;
      script.dataset.pdfjsLoader = "true";
      script.onload = () => {
        if (!window.pdfjsLib) {
          reject(new Error("PDF.js loaded but pdfjsLib is unavailable."));
          return;
        }
        configurePdfJsWorker(window.pdfjsLib);
        resolve(window.pdfjsLib);
      };
      script.onerror = () => reject(new Error("PDF.js could not be loaded."));
      document.head.appendChild(script);
    });
  }
  return pdfJsLoadPromise;
}

async function loadPdfJsViewer() {
  if (window.pdfjsViewer) {
    return window.pdfjsViewer;
  }
  if (!pdfJsViewerLoadPromise) {
    pdfJsViewerLoadPromise = new Promise((resolve, reject) => {
      const existing = document.querySelector('script[data-pdfjs-viewer-loader="true"]');
      if (existing && window.pdfjsViewer) {
        resolve(window.pdfjsViewer);
        return;
      }
      const script = document.createElement("script");
      script.src = pdfJsViewerScriptUrl;
      script.async = true;
      script.dataset.pdfjsViewerLoader = "true";
      script.onload = () => {
        if (!window.pdfjsViewer) {
          reject(new Error("PDF.js viewer loaded but pdfjsViewer is unavailable."));
          return;
        }
        resolve(window.pdfjsViewer);
      };
      script.onerror = () => reject(new Error("PDF.js viewer could not be loaded."));
      document.head.appendChild(script);
    });
  }
  return pdfJsViewerLoadPromise;
}

function cleanXmlText(value) {
  return String(value ?? "")
    .replace(/<\s*\/?\s*[A-Za-z][^>]*>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function xmlTextFromNode(node) {
  return cleanXmlText(node?.textContent || "");
}

function xmlTextFromSelector(root, selector) {
  return xmlTextFromNode(root?.querySelector(selector));
}

function getDocumentViewerState() {
  return state.documentViewer || null;
}

function setDocumentViewerOpen(next, { immediate = false } = {}) {
  void immediate;
  state.documentViewerMode = next ? "document" : "table";
  document.body.classList.toggle("is-document-viewer-open", Boolean(next));
  if (els.resultsCard) {
    els.resultsCard.hidden = Boolean(next);
    els.resultsCard.style.display = next ? "none" : "";
    els.resultsCard.classList.toggle("is-hidden", Boolean(next));
  }
  if (els.documentViewerCard) {
    els.documentViewerCard.hidden = !next;
  }
}

function setDocumentViewerRawMode(next) {
  const viewer = getDocumentViewerState();
  if (!viewer) return;
  state.documentViewerContentMode = next ? "raw" : "structured";
  renderDocumentViewer();
}

function closeDocumentViewer() {
  state.documentViewerRenderToken += 1;
  state.documentViewer = null;
  state.documentViewerContentMode = "structured";
  state.documentViewerArtifactPaths = {};
  setDocumentViewerOpen(false);
  if (els.documentViewerBody) {
    els.documentViewerBody.innerHTML = "";
  }
}

async function openDocumentViewer(filePath, options = {}) {
  const normalizedPath = normalizeDocumentPath(filePath);
  if (!normalizedPath) return;
  const kind = options.kind || documentKindFromPath(normalizedPath);
  const artifactPaths = artifactPathsFromValue(options.artifactPaths);
  state.documentViewer = {
    path: normalizedPath,
    kind,
    title: options.title || documentTitleFromPath(normalizedPath),
    source: options.source || "",
    displayName: options.displayName || documentTitleFromPath(normalizedPath),
  };
  state.documentViewerArtifactPaths = artifactPaths;
  state.documentViewerContentMode = kind === "xml" ? "structured" : "pdf";
  setDocumentViewerOpen(true);
  await renderDocumentViewer();
}

async function switchDocumentViewerKind(nextKind) {
  const viewer = getDocumentViewerState();
  if (!viewer) return;
  const artifactPath = normalizeDocumentPath(state.documentViewerArtifactPaths?.[nextKind]);
  if (!artifactPath) return;
  state.documentViewer = {
    ...viewer,
    path: artifactPath,
    kind: nextKind,
    displayName: documentTitleFromPath(artifactPath),
  };
  state.documentViewerContentMode = nextKind === "xml" ? "structured" : "pdf";
  await renderDocumentViewer();
}

function xmlSectionTitle(node) {
  const titles = [];
  const titleNodes = node.querySelectorAll(":scope > title, :scope > sec-title");
  titleNodes.forEach((item) => {
    const text = xmlTextFromNode(item);
    if (text) titles.push(text);
  });
  const heading = titles[0] || xmlTextFromSelector(node, "title, sec-title") || "";
  return heading || "Section";
}

function textContentLines(node) {
  if (!node) return [];
  const text = xmlTextFromNode(node);
  return text
    .split(/\n+/)
    .map((line) => line.replace(/\s+/g, " ").trim())
    .filter(Boolean);
}

function xmlSectionParagraphs(node) {
  const paragraphs = [];
  node.querySelectorAll(":scope > p").forEach((item) => {
    const text = xmlTextFromNode(item);
    if (text) paragraphs.push(text);
  });
  if (!paragraphs.length) {
    node.querySelectorAll(":scope > list > list-item").forEach((item) => {
      const text = xmlTextFromNode(item);
      if (text) paragraphs.push(text);
    });
  }
  if (!paragraphs.length) {
    const fallback = textContentLines(node);
    if (fallback.length) paragraphs.push(...fallback);
  }
  return paragraphs;
}

function xmlSectionNode(node) {
  return {
    title: xmlSectionTitle(node),
    paragraphs: xmlSectionParagraphs(node),
    children: Array.from(node.children || [])
      .filter((item) => item.localName === "sec")
      .map((child) => xmlSectionNode(child)),
  };
}

function xmlOutlineSections(root) {
  const body = root.querySelector("body") || root;
  const sections = [];
  const topLevelSecs = Array.from(body.children || []).filter((item) => item.localName === "sec");
  if (topLevelSecs.length) {
    topLevelSecs.forEach((sec) => sections.push(xmlSectionNode(sec)));
    return sections;
  }

  const bodyParagraphs = Array.from(body.children || [])
    .filter((item) => item.localName === "p")
    .map((item) => xmlTextFromNode(item))
    .filter(Boolean);
  if (bodyParagraphs.length) {
    sections.push({
      title: "Body",
      paragraphs: bodyParagraphs,
      nested: 0,
    });
  }
  return sections;
}

function renderXmlSectionTree(sections, depth = 0) {
  return sections.map((section) => {
    const childMarkup = section.children?.length ? renderXmlSectionTree(section.children, depth + 1) : "";
    const paragraphMarkup = section.paragraphs?.length
      ? section.paragraphs.map((paragraph) => `<p class="native-document-paragraph">${escapeHtml(paragraph)}</p>`).join("")
      : '<p class="native-document-paragraph native-document-paragraph-empty">No textual content found in this section.</p>';
    return `
      <section class="native-document-section native-document-section-depth-${Math.min(depth, 4)}">
        <div class="native-document-section-title">${escapeHtml(section.title)}</div>
        ${paragraphMarkup}
        ${childMarkup ? `<div class="native-document-section-children">${childMarkup}</div>` : ""}
      </section>
    `;
  }).join("");
}

function xmlDocumentSummary(xmlDoc) {
  const root = xmlDoc.querySelector("article") || xmlDoc.documentElement;
  const isElsevierResponse = root?.localName === "full-text-retrieval-response";
  const title = cleanXmlText(
    xmlTextFromSelector(root, "article-title")
    || xmlTextFromSelector(root, "coredata > dc\\:title")
    || xmlTextFromSelector(root, "title")
    || "XML Document",
  );
  const journal = cleanXmlText(
    xmlTextFromSelector(root, "journal-title")
    || xmlTextFromSelector(root, "prism\\:publicationName")
    || "",
  );
  const abstract = cleanXmlText(
    xmlTextFromSelector(root, "abstract")
    || xmlTextFromSelector(root, "summary")
    || "",
  );
  return { title, journal, abstract, isElsevierResponse };
}

function xmlMetadataEntries(xmlDoc) {
  const root = xmlDoc.querySelector("full-text-retrieval-response") || xmlDoc.documentElement;
  const entries = [];
  const add = (label, value) => {
    const text = cleanXmlText(value);
    if (text) entries.push({ label, value: text });
  };

  add("DOI", xmlTextFromSelector(root, "prism\\:doi") || xmlTextFromSelector(root, "article-id[pub-id-type='doi']"));
  add("PII", xmlTextFromSelector(root, "pii"));
  add("Journal", xmlTextFromSelector(root, "prism\\:publicationName") || xmlTextFromSelector(root, "journal-title"));
  add("Date", xmlTextFromSelector(root, "prism\\:coverDisplayDate") || xmlTextFromSelector(root, "pub-date"));
  add("Access", xmlTextFromSelector(root, "openaccessType") || xmlTextFromSelector(root, "openaccessArticle"));
  add("Publisher", xmlTextFromSelector(root, "publisher-name") || xmlTextFromSelector(root, "publisher"));
  const scidirLink = root.querySelector("link[rel='scidir']")?.getAttribute("href") || "";
  add("Landing", scidirLink);
  return entries;
}

function renderXmlStructuredMarkup(xmlText) {
  const parser = new DOMParser();
  const xmlDoc = parser.parseFromString(xmlText, "application/xml");
  if (xmlDoc.querySelector("parsererror")) {
    throw new Error("XML document could not be parsed.");
  }
  const summary = xmlDocumentSummary(xmlDoc);
  const sections = xmlOutlineSections(xmlDoc);
  const abstractText = summary.abstract
    ? summary.abstract
    : xmlTextFromSelector(xmlDoc, "abstract") || "Abstract not available.";
  const metadataEntries = xmlMetadataEntries(xmlDoc);
  const metadataMarkup = metadataEntries.length
    ? `
      <section class="native-document-section">
        <div class="native-document-section-title">XML Metadata</div>
        <div class="native-document-metadata-grid">
          ${metadataEntries.map((entry) => `
            <div class="native-document-metadata-item">
              <div class="native-document-metadata-label">${escapeHtml(entry.label)}</div>
              <div class="native-document-metadata-value">${escapeHtml(entry.value)}</div>
            </div>
          `).join("")}
        </div>
      </section>
    `
    : "";
  const secMarkup = sections.length
    ? renderXmlSectionTree(sections)
    : `<div class="native-document-empty">No article sections were found in this XML file.</div>`;

  return `
    <div class="native-document-scroll">
      <section class="native-document-summary">
        <div class="native-document-summary-title">${escapeHtml(summary.title)}</div>
        ${summary.journal ? `<div class="native-document-summary-meta">${escapeHtml(summary.journal)}</div>` : ""}
        <div class="native-document-summary-body">${escapeHtml(abstractText)}</div>
      </section>
      ${summary.isElsevierResponse ? `
        <div class="native-document-empty">
          <div class="native-document-empty-title">Metadata-only XML</div>
          <div class="native-document-empty-copy">This XML payload exposes article metadata but not a structured body. Use the landing page or another source for the full text body.</div>
        </div>
      ` : ""}
      ${metadataMarkup}
      <section class="native-document-section">
        <div class="native-document-section-title">Structured Sections</div>
        ${secMarkup}
      </section>
    </div>
  `;
}

async function resolvePdfOutlineNode(pdfDoc, item, pageLabels = null) {
  const title = cleanXmlText(item?.title || "") || "Bookmark";
  let pageNumber = null;
  let pageLabel = "";
  const destination = item?.dest ?? null;
  try {
    const explicitDestination = typeof item?.dest === "string"
      ? await pdfDoc.getDestination(item.dest)
      : item?.dest;
    if (Array.isArray(explicitDestination) && explicitDestination.length) {
      const first = explicitDestination[0];
      if (typeof first === "object" && first) {
        pageNumber = (await pdfDoc.getPageIndex(first)) + 1;
      } else if (Number.isFinite(first)) {
        pageNumber = first + 1;
      }
      if (Number.isFinite(pageNumber) && Array.isArray(pageLabels) && pageLabels[pageNumber - 1]) {
        pageLabel = String(pageLabels[pageNumber - 1]);
      }
    }
  } catch (_error) {
    pageNumber = null;
  }

  const children = item?.items?.length
    ? await Promise.all(item.items.map((child) => resolvePdfOutlineNode(pdfDoc, child, pageLabels)))
    : [];
  return {
    title,
    pageNumber,
    pageLabel,
    destination,
    children,
  };
}

function appendResolvedPdfOutline(container, nodes, lookup, depth = 0, pathPrefix = "root") {
  nodes.forEach((node, index) => {
    const key = `${pathPrefix}.${index}`;
    const button = document.createElement("button");
    button.type = "button";
    button.className = `native-pdf-outline-item native-pdf-outline-depth-${Math.min(depth, 4)}`;
    if (Number.isFinite(node.pageNumber)) {
      button.dataset.outlineKey = key;
      lookup.set(key, node);
    } else {
      button.disabled = true;
    }

    const title = document.createElement("span");
    title.className = "native-pdf-outline-item-title";
    title.textContent = node.title;
    button.appendChild(title);

    if (Number.isFinite(node.pageNumber)) {
      const badge = document.createElement("span");
      badge.className = "native-pdf-outline-item-page";
      badge.textContent = node.pageLabel || String(node.pageNumber);
      button.appendChild(badge);
    }

    container.appendChild(button);

    if (node.children?.length) {
      const childrenWrap = document.createElement("div");
      childrenWrap.className = "native-pdf-outline-children";
      container.appendChild(childrenWrap);
      appendResolvedPdfOutline(childrenWrap, node.children, lookup, depth + 1, key);
    }
  });
}

async function renderPdfDocumentViewer(fileUrl, token) {
  const pdfjsLib = await loadPdfJs();
  const pdfjsViewer = await loadPdfJsViewer();
  if (token !== state.documentViewerRenderToken) return;
  if (!els.documentViewerBody) return;
  els.documentViewerBody.innerHTML = `
    <div class="native-document-pdf-shell">
      <aside class="native-document-pdf-outline-panel">
        <div class="native-document-pdf-outline-header">
          <div class="native-document-pdf-outline-title">Bookmarks</div>
          <div class="native-document-pdf-outline-status" id="documentViewerPdfOutlineStatus">Loading outline...</div>
        </div>
        <div class="native-document-pdf-outline-list" id="documentViewerPdfOutlineList"></div>
      </aside>
      <div class="native-document-pdf-pages-panel">
        <div class="native-document-pdf-status" id="documentViewerPdfStatus">Loading PDF…</div>
        <div class="native-document-pdf-stage">
          <div id="documentViewerPdfContainer" class="native-document-pdf-container">
            <div class="pdfViewer"></div>
          </div>
        </div>
      </div>
    </div>
  `;

  const outlineStatusEl = document.getElementById("documentViewerPdfOutlineStatus");
  const outlineListEl = document.getElementById("documentViewerPdfOutlineList");
  const pagesEl = document.getElementById("documentViewerPdfContainer");
  const statusEl = document.getElementById("documentViewerPdfStatus");
  if (!outlineStatusEl || !outlineListEl || !pagesEl || !statusEl) return;

  try {
    configurePdfJsWorker(pdfjsLib);
    const eventBus = new pdfjsViewer.EventBus();
    const linkService = new pdfjsViewer.PDFLinkService({ eventBus });
    const findController = new pdfjsViewer.PDFFindController({ eventBus, linkService });
    const viewer = new pdfjsViewer.PDFViewer({
      container: pagesEl,
      viewer: pagesEl.querySelector(".pdfViewer"),
      eventBus,
      linkService,
      findController,
      textLayerMode: 1,
      removePageBorders: true,
    });
    linkService.setViewer(viewer);

    const loadingTask = pdfjsLib.getDocument(fileUrl);
    const pdfDoc = await loadingTask.promise;
    if (token !== state.documentViewerRenderToken) return;
    viewer.setDocument(pdfDoc);
    linkService.setDocument(pdfDoc, null);

    const pageLabels = await pdfDoc.getPageLabels().catch(() => null);
    const outlineItems = await pdfDoc.getOutline();
    if (token !== state.documentViewerRenderToken) return;

    if (outlineItems?.length) {
      const outlineLookup = new Map();
      const resolvedOutline = await Promise.all(outlineItems.map((item) => resolvePdfOutlineNode(pdfDoc, item, pageLabels)));
      if (token !== state.documentViewerRenderToken) return;
      outlineStatusEl.textContent = "Bookmarks available";
      outlineListEl.innerHTML = "";
      appendResolvedPdfOutline(outlineListEl, resolvedOutline, outlineLookup);
      outlineListEl.querySelectorAll("[data-outline-key]").forEach((button) => {
        button.addEventListener("click", async () => {
          const key = button.getAttribute("data-outline-key") || "";
          const node = outlineLookup.get(key);
          if (!node) return;
          if (node.destination != null) {
            await linkService.goToDestination(node.destination);
            return;
          }
          if (Number.isFinite(node.pageNumber)) {
            viewer.currentPageNumber = node.pageNumber;
          }
        });
      });
    } else {
      outlineStatusEl.textContent = "No bookmarks found";
      outlineListEl.innerHTML = `
        <div class="native-document-empty native-document-pdf-empty">
          <div class="native-document-empty-title">No outline available</div>
          <div class="native-document-empty-copy">This PDF does not expose bookmark metadata. Page rendering still works.</div>
        </div>
      `;
    }

    eventBus.on("pagesinit", () => {
      if (token !== state.documentViewerRenderToken) return;
      viewer.currentScaleValue = "page-width";
      statusEl.textContent = `Rendered ${pdfDoc.numPages} page${pdfDoc.numPages === 1 ? "" : "s"}`;
    });
    eventBus.on("pagechanging", ({ pageNumber }) => {
      if (token !== state.documentViewerRenderToken) return;
      statusEl.textContent = `Page ${pageNumber} of ${pdfDoc.numPages}`;
    });
    if (token !== state.documentViewerRenderToken) return;
    statusEl.textContent = `Loading ${pdfDoc.numPages} page${pdfDoc.numPages === 1 ? "" : "s"}…`;
  } catch (error) {
    if (token !== state.documentViewerRenderToken) return;
    pagesEl.innerHTML = `
      <div class="native-document-empty">
        <div class="native-document-empty-title">PDF could not be rendered</div>
        <div class="native-document-empty-copy">${escapeHtml(error.message || "Unable to load PDF.")}</div>
      </div>
    `;
    outlineStatusEl.textContent = "Unavailable";
    statusEl.textContent = "Failed to render";
  }
}

async function renderDocumentViewer() {
  const viewer = getDocumentViewerState();
  if (!viewer) return;
  const renderToken = ++state.documentViewerRenderToken;
  const availableKinds = availableDocumentKinds(state.documentViewerArtifactPaths);
  if (els.documentViewerEyebrow) {
    els.documentViewerEyebrow.textContent = viewer.kind === "xml"
      ? "XML Viewer"
      : availableKinds.includes("xml")
        ? "PDF Viewer"
        : "PDF Viewer";
  }
  if (els.documentViewerTitle) {
    els.documentViewerTitle.textContent = viewer.title || viewer.displayName || "Document";
  }
  if (els.documentViewerMeta) {
    els.documentViewerMeta.textContent = viewer.source ? `Source ${viewer.source}` : documentTitleFromPath(viewer.path);
  }
  if (els.documentViewerPdfBtn) {
    els.documentViewerPdfBtn.hidden = !availableKinds.includes("pdf") || viewer.kind === "pdf";
    els.documentViewerPdfBtn.textContent = viewer.kind === "pdf" ? "PDF" : "PDF";
  }
  if (els.documentViewerXmlBtn) {
    els.documentViewerXmlBtn.hidden = !availableKinds.includes("xml") || viewer.kind === "xml";
    els.documentViewerXmlBtn.textContent = viewer.kind === "xml" ? "XML" : "XML";
  }
  if (!els.documentViewerBody) return;
  const fileUrl = buildFileOpenUrl(viewer.path);
  if (viewer.kind === "pdf") {
    if (els.documentViewerRawBtn) els.documentViewerRawBtn.hidden = true;
    els.documentViewerBody.innerHTML = `
      <div class="native-document-empty">
        <div class="native-document-empty-title">Loading PDF viewer</div>
        <div class="native-document-empty-copy">Rendering pages and bookmarks...</div>
      </div>
    `;
    await renderPdfDocumentViewer(fileUrl, renderToken);
    return;
  }

  if (els.documentViewerRawBtn) {
    els.documentViewerRawBtn.hidden = false;
    els.documentViewerRawBtn.textContent = state.documentViewerContentMode === "raw" ? "Structured View" : "Raw XML";
  }

  try {
    const response = await fetch(fileUrl, { headers: { Accept: "application/xml,text/xml,text/plain,*/*" } });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const xmlText = await response.text();
    if (renderToken !== state.documentViewerRenderToken) return;
    if (state.documentViewerContentMode === "raw") {
      els.documentViewerBody.innerHTML = `
        <pre class="native-document-raw">${escapeHtml(xmlText)}</pre>
      `;
    } else {
      els.documentViewerBody.innerHTML = renderXmlStructuredMarkup(xmlText);
    }
  } catch (error) {
    els.documentViewerBody.innerHTML = `
      <div class="native-document-empty">
        <div class="native-document-empty-title">Document could not be loaded</div>
        <div class="native-document-empty-copy">${escapeHtml(error.message || "Unable to load document.")}</div>
      </div>
    `;
  }
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
    ? `<button type="button" class="btn btn-primary btn-xs file-open-btn" data-file-path="${escapeHtml(filePathFromOpenUrl(info.openUrl))}" data-file-title="${escapeHtml(article.title || "Document")}">Open</button>`
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
        article.pmc_id
          || article.doi
          || article.pmid
          || article.oa_pdf_url
          || article.landing_page_url
          || article.source_record_id
          ? {
            status: "high",
            label: downloadabilityLabels.high,
            detail: "Ready to download.",
            openUrl: null,
          }
          : {
            status: "unavailable",
            label: downloadabilityLabels.unavailable,
            detail: "No download signal is available for this article.",
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
        downloader_mode: normalizePdfDownloaderMode(runtime.pdfDownloaderMode, "pdf_xml"),
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
        downloader_mode: normalizePdfDownloaderMode(runtime.pdfDownloaderMode, "pdf_xml"),
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
    return { status: "success", info: next };
  }
  const current = getDownloadability(article.id);
  if (current.status === "downloaded" && current.openUrl) {
    return { status: "preserved", info: current };
  }
  const next = {
    status: "failed",
    label: downloadabilityLabels.failed,
    detail: result?.error || "Download failed.",
    openUrl: null,
  };
  setArticleDownloadability(article.id, next);
  return { status: "failed", info: next };
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
    const outcome = applyDownloadResultState(article, result);
    if (outcome.status === "success" || outcome.status === "preserved") {
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
    const result = { success: false, error: error.message || "Download failed." };
    const outcome = applyDownloadResultState(article, result);
    if (outcome.status === "success" || outcome.status === "preserved") {
      trackAppEvent("info", "pdf_downloaded", article.title || "File downloaded.", {
        article_id: article.id,
        pmid: article.pmid || "",
        project_id: state.projectId || "",
      });
    } else {
      trackAppEvent("error", "pdf_download_failed", result.error, {
        pmid: article.pmid || "",
        article_id: article.id,
      });
    }
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
  if (article?.pmid) return article.pmid;
  if (article?.doi) return article.doi;
  if (article?.pmc_id) return article.pmc_id;
  if (article?.source_name && article?.source_record_id) return `${article.source_name}:${article.source_record_id}`;
  return article?.title || "";
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
    const outcome = applyDownloadResultState(article, result);
    if (outcome.status === "success" || outcome.status === "preserved") {
      successes.push({ article, result });
    } else {
      failures.push({ article, result });
    }
  });
  chosen.forEach((article) => {
    const key = articleIdentityKey(article);
    if (seenKeys.has(key)) return;
    const result = { success: false, error: "Download result was not returned." };
    const outcome = applyDownloadResultState(article, result);
    if (outcome.status === "success" || outcome.status === "preserved") {
      successes.push({ article, result });
    } else {
      failures.push({ article, result });
    }
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
  const concurrency = clampDownloadWorkers(runtime.downloadWorkers);
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
    const smallBatchMode = chosen.length <= 20;
    const smallBatchSize = 5;

    const refreshDownloads = async () => {
      await Promise.allSettled([loadProjectDownloads(), touchProjectActivity()]);
    };

    const updateButtonLabel = () => {
      if (els.quickDownloadSelectedBtn) {
        els.quickDownloadSelectedBtn.textContent = `Downloading ${completed} / ${chosen.length}`;
      }
    };

    const recordBatchOutcomes = (entries, tracker) => {
      entries.forEach(({ article, result }) => {
        tracker.push({ article, result });
        if (tracker === successes) {
          trackAppEvent("info", "pdf_downloaded", article.title || "File downloaded.", {
            article_id: article.id,
            pmid: article.pmid || "",
            project_id: state.projectId || "",
          });
        } else {
          trackAppEvent("error", "pdf_download_failed", result?.error || "Download failed.", {
            article_id: article.id,
            pmid: article.pmid || "",
            project_id: state.projectId || "",
          });
        }
      });
    };

    const processArticle = async (article, index) => {
      try {
        const result = await requestArticleDownload(article, { timeoutMs: singleTimeoutMs });
        const outcome = applyDownloadResultState(article, result);
        if (outcome.status === "success" || outcome.status === "preserved") {
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
        const outcome = applyDownloadResultState(article, result);
        if (outcome.status === "success" || outcome.status === "preserved") {
          successes.push({ article, result });
          trackAppEvent("info", "pdf_downloaded", article.title || "File downloaded.", {
            article_id: article.id,
            pmid: article.pmid || "",
            project_id: state.projectId || "",
          });
        } else {
          failures.push({ article, result });
          trackAppEvent("error", "pdf_download_failed", result.error, {
            article_id: article.id,
            pmid: article.pmid || "",
            project_id: state.projectId || "",
          });
        }
      }
      completed += 1;
      updateButtonLabel();
      scheduleResultsRender();
      if (completed === chosen.length || completed % concurrency === 0 || index < concurrency) {
        await refreshDownloads();
      }
    };

    const processBatchChunk = async (chunk, chunkIndex) => {
      try {
        const response = await requestBatchDownload(chunk, { timeoutMs: 90000 });
        const outcome = applyBatchDownloadResults(chunk, response?.results || []);
        recordBatchOutcomes(outcome.successes, successes);
        recordBatchOutcomes(outcome.failures, failures);
      } catch (_batchError) {
        for (let offset = 0; offset < chunk.length; offset += 1) {
          await processArticle(chunk[offset], (chunkIndex * smallBatchSize) + offset);
        }
        return;
      }
      completed += chunk.length;
      updateButtonLabel();
      scheduleResultsRender();
      await refreshDownloads();
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
    if (smallBatchMode) {
      for (let start = 0; start < chosen.length; start += smallBatchSize) {
        const chunk = chosen.slice(start, start + smallBatchSize);
        await processBatchChunk(chunk, Math.floor(start / smallBatchSize));
      }
    } else {
      await Promise.all(Array.from({ length: concurrency }, () => worker()));
    }
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
  lines.push(`Source ${articleResearchSourcesLabel(article) || currentSearchSourceLabel()}`);
  if (articleResearchBranchLabel(article)) lines.push(`Branch ${articleResearchBranchLabel(article)}`);
  if (articleResearchScore(article) !== null) lines.push(`Score ${formatResearchScore(articleResearchScore(article))}`);
  if (article.year) lines.push(`Year ${article.year}`);
  if (article.pmid) lines.push(`PMID ${article.pmid}`);
  if (sourceRecordLabel(article)) lines.push(sourceRecordLabel(article));
  if (article.doi) lines.push(`DOI ${article.doi}`);
  if (article.pmc_id) lines.push(`PMC ${article.pmc_id}`);
  return lines.map((item) => `<span class="detail-meta-chip">${item}</span>`).join("");
}

function detailMetaText(article) {
  const lines = [];
  if (article.title) lines.push(article.title);
  lines.push(`Source ${articleResearchSourcesLabel(article) || currentSearchSourceLabel()}`);
  if (articleResearchBranchLabel(article)) lines.push(`Branch ${articleResearchBranchLabel(article)}`);
  if (articleResearchScore(article) !== null) lines.push(`Score ${formatResearchScore(articleResearchScore(article))}`);
  if (article.year) lines.push(`Year ${article.year}`);
  if (article.pmid) lines.push(`PMID ${article.pmid}`);
  if (sourceRecordLabel(article)) lines.push(sourceRecordLabel(article));
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
        meta: detailMetaText(article),
        body: [
          `Database Source: ${currentSearchSourceLabel()}`,
          `Journal: ${article.journal || "-"}`,
          `Publication: ${article.publication_date || "-"}`,
          `Q Rank: ${journalQuartileLabel(article)}`,
          `SJR: ${typeof article.journal_sjr === "number" ? article.journal_sjr.toFixed(3) : "-"}`,
          `Metric Year: ${Number.isInteger(article.journal_metric_year) ? article.journal_metric_year : "-"}`,
        ].join("\n"),
      };
    case "journal_metrics":
      return {
        eyebrow: "Journal Metrics",
        title: article.journal || "Journal Rank",
        meta: detailMetaText(article),
        body: [
          `Q Rank: ${journalQuartileLabel(article)}`,
          `SJR: ${typeof article.journal_sjr === "number" ? article.journal_sjr.toFixed(3) : "-"}`,
          `Metric Year: ${Number.isInteger(article.journal_metric_year) ? article.journal_metric_year : "-"}`,
          `Metrics Source: ${article.journal_metrics_source || "-"}`,
        ].join("\n"),
      };
    case "authors":
      return {
        eyebrow: "Article Detail",
        title: "Authors",
        meta: detailMetaText(article),
        body: article.authors?.length ? article.authors.join("\n") : "Author information not available.",
      };
    case "mesh":
      {
        const presentation = detailFieldPresentation("mesh");
        return {
          eyebrow: "Article Detail",
          title: presentation.title,
          meta: detailMetaText(article),
          body: article.mesh_terms?.length ? article.mesh_terms.join(", ") : presentation.empty,
        };
      }
    case "keywords":
      {
        const presentation = detailFieldPresentation("keywords");
        return {
          eyebrow: "Article Detail",
          title: presentation.title,
          meta: detailMetaText(article),
          body: article.keywords?.length ? article.keywords.join(", ") : presentation.empty,
        };
      }
    case "article_types":
      return {
        eyebrow: "Article Detail",
        title: "Article Types",
        meta: detailMetaText(article),
        body: article.article_types?.length ? article.article_types.join(", ") : "Article type information not available.",
      };
    case "research_sources":
      return {
        eyebrow: "Research Trace",
        title: "Branch, Score & Sources",
        meta: detailMetaText(article),
        body: articleResearchSourceDetails(article),
      };
    case "related_articles":
      {
        const presentation = detailFieldPresentation("related_articles");
        return {
          eyebrow: "Article Detail",
          title: presentation.title,
          meta: detailMetaText(article),
          body: article.related_articles?.length ? article.related_articles.join("\n") : presentation.empty,
        };
      }
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

function researchPlanDetailAction(messageId, actionIndex) {
  const message = state.assistantMessages.find((item) => item.id === messageId);
  if (!message || !Array.isArray(message.actions)) return null;
  const action = message.actions[Number(actionIndex)];
  return action?.name === "create_research_plan" ? action : null;
}

function researchPlanListMarkup(items, emptyText = "Not specified.") {
  const list = Array.isArray(items) ? items.filter((item) => String(item || "").trim()) : [];
  if (!list.length) return `<p>${escapeHtml(emptyText)}</p>`;
  return `<ul>${list.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
}

function researchPlanDatabases(plan) {
  const values = Array.isArray(plan?.active_databases) && plan.active_databases.length
    ? plan.active_databases
    : Array.isArray(plan?.databases) ? plan.databases : [];
  return values.filter((item) => String(item || "").trim());
}

function researchPlanSearchBranches(plan) {
  const branches = Array.isArray(plan?.search_branches) ? plan.search_branches : [];
  if (branches.length) return branches;
  const legacyTopics = Array.isArray(plan?.search_topics) ? plan.search_topics : [];
  if (legacyTopics.length) {
    return legacyTopics.map((item) => ({
      id: item.id,
      label: item.label || "Branch",
      query: item.query || [...(item.must_include || []), ...(item.synonyms || [])].filter(Boolean).join(" OR "),
    }));
  }
  return [{
    id: "main_branch",
    label: plan?.topic || "Main topic",
    query: plan?.topic || "Main topic",
  }];
}

function researchPlanSharedConcepts(plan) {
  const concepts = Array.isArray(plan?.shared_query_concepts) ? plan.shared_query_concepts : [];
  return concepts.map((item, index) => {
    if (typeof item === "string") {
      return { id: `concept_${index + 1}`, label: `Shared query ${index + 1}`, query: item };
    }
    return {
      id: item.id || `concept_${index + 1}`,
      label: item.label || `Shared query ${index + 1}`,
      query: item.query || (item.terms || []).join(" OR ") || item.label || "",
    };
  });
}

function researchPlanRawSearchQueries(plan) {
  const concepts = researchPlanSharedConcepts(plan).filter((item) => item.query);
  const databases = researchPlanDatabases(plan);
  const branches = researchPlanSearchBranches(plan);
  const categoryQuery = concepts.map((concept) => concept.query).filter(Boolean).map((query) => `(${query})`).join(" OR ");
  const perDatabase = Number(plan?.candidate_budget?.per_database || (Number(plan?.target_count_per_branch || plan?.target_count || 20) * 2));
  return databases.flatMap((database) => branches.map((branch) => {
    const rawQuery = branch.query || branch.label || "";
    const parts = [rawQuery, categoryQuery].filter(Boolean);
    const extractedQuery = parts.map((part) => `(${part})`).join(" AND ");
    return {
      database,
      branch_id: branch.id || "",
      branch_label: branch.label || "",
      category_ids: concepts.map((concept) => concept.id || "").filter(Boolean),
      category_labels: concepts.map((concept) => concept.label || "").filter(Boolean),
      category_id: "",
      category_label: concepts.length ? "Combined categories" : "",
      raw_query: rawQuery,
      extracted_query: extractedQuery,
      query: extractedQuery,
      candidate_limit: Math.max(1, perDatabase),
    };
  }));
}

function researchPlanGroupedSearchQueries(rawSearchQueries) {
  const groups = new Map();
  (Array.isArray(rawSearchQueries) ? rawSearchQueries : []).forEach((item) => {
    const key = [
      item.branch_id || "",
      item.branch_label || "",
      item.category_id || "",
      item.category_label || "",
      item.query || "",
      item.candidate_limit || "",
    ].join("::");
    const current = groups.get(key) || {
      branch_id: item.branch_id || "",
      branch_label: item.branch_label || "Branch",
      category_id: item.category_id || "",
      category_label: item.category_label || "",
      raw_query: item.raw_query || "",
      extracted_query: item.extracted_query || item.query || "",
      query: item.query || "",
      candidate_limit: item.candidate_limit || "",
      databases: [],
    };
    if (item.database && !current.databases.includes(item.database)) {
      current.databases.push(item.database);
    }
    groups.set(key, current);
  });
  return [...groups.values()];
}

function researchPlanDisplayPlan(plan, rawSearchQueries, totalQueries, estimatedCandidates, estimatedSeconds) {
  const { database_queries: _databaseQueries, search_topics: _searchTopics, ...basePlan } = plan || {};
  return {
    ...basePlan,
    search_branches: researchPlanSearchBranches(plan).map((branch) => ({
      id: branch.id || "",
      label: branch.label || "",
      query: branch.query || branch.label || "",
    })),
    shared_query_concepts: researchPlanSharedConcepts(plan).map((concept) => ({
      id: concept.id || "",
      label: concept.label || "",
      query: concept.query || "",
    })),
    total_queries: totalQueries,
    estimated_candidates: estimatedCandidates,
    estimated_time_seconds: estimatedSeconds,
    raw_search_queries: rawSearchQueries,
  };
}

function researchPlanTotalQueries(plan) {
  const rawSearchQueries = researchPlanRawSearchQueries(plan);
  if (rawSearchQueries.length) return rawSearchQueries.length;
  if (Number.isFinite(Number(plan?.total_queries))) return Number(plan.total_queries);
  return Math.max(1, researchPlanDatabases(plan).length) * Math.max(1, researchPlanSearchBranches(plan).length);
}

function researchPlanEstimatedCandidates(plan) {
  const rawSearchQueries = researchPlanRawSearchQueries(plan);
  if (Number.isFinite(Number(plan?.estimated_candidates))) return Number(plan.estimated_candidates);
  const perDatabase = Number(plan?.candidate_budget?.per_database || (Number(plan?.target_count || 20) * 2));
  return Math.max(1, rawSearchQueries.length || researchPlanTotalQueries(plan)) * Math.max(1, perDatabase);
}

function researchPlanEstimatedSeconds(plan) {
  if (Number.isFinite(Number(plan?.estimated_time_seconds))) return Number(plan.estimated_time_seconds);
  return Math.max(20, Math.ceil(researchPlanEstimatedCandidates(plan) / 40) * 20);
}

function formatResearchPlanDuration(seconds) {
  const value = Math.max(0, Number(seconds || 0));
  if (value < 60) return `${Math.ceil(value)} sec`;
  const minutes = Math.ceil(value / 60);
  return `${minutes} min`;
}

function recomputeResearchPlanEstimates(plan) {
  const targetCount = Math.max(1, Number.parseInt(String(plan.target_count || 20), 10) || 20);
  if (!plan.candidate_budget || typeof plan.candidate_budget !== "object") plan.candidate_budget = {};
  plan.target_count = targetCount;
  plan.target_count_per_branch = targetCount;
  plan.active_databases = researchPlanDatabases(plan);
  plan.databases = plan.active_databases;
  plan.search_branches = researchPlanSearchBranches(plan);
  plan.shared_query_concepts = researchPlanSharedConcepts(plan);
  plan.candidate_budget.target_count = targetCount;
  plan.candidate_budget.per_database = Math.max(1, Number.parseInt(String(plan.candidate_budget.per_database || targetCount * 2), 10) || targetCount * 2);
  plan.raw_search_queries = researchPlanRawSearchQueries(plan);
  plan.total_queries = plan.raw_search_queries.length || (Math.max(1, plan.search_branches.length) * Math.max(1, plan.active_databases.length));
  plan.estimated_candidates = plan.total_queries * plan.candidate_budget.per_database;
  plan.estimated_time_seconds = Math.max(20, Math.ceil(plan.estimated_candidates / 40) * 20);
  return plan;
}

function researchPlanEditableListMarkup(kind, items, placeholder) {
  const list = Array.isArray(items) ? items : [];
  return `
    <div class="research-plan-edit-list" data-plan-list="${escapeHtml(kind)}">
      ${list.map((item, index) => `
        <label class="research-plan-edit-line">
          <span>${escapeHtml(index + 1)}</span>
          <input type="text" value="${escapeHtml(item)}" data-plan-list-item="${escapeHtml(kind)}" data-list-index="${escapeHtml(index)}">
          <button class="btn btn-secondary btn-sm" type="button" data-plan-list-delete="${escapeHtml(kind)}" data-list-index="${escapeHtml(index)}">Delete</button>
        </label>
      `).join("")}
      <label class="research-plan-edit-line is-new">
        <span>+</span>
        <input type="text" placeholder="${escapeHtml(placeholder)}" data-plan-list-new="${escapeHtml(kind)}">
      </label>
    </div>
  `;
}

function researchPlanBranchEditMarkup(branches) {
  return `
    <div class="research-plan-branch-edit-list">
      ${branches.map((branch, index) => `
        <div class="research-plan-branch-edit" data-branch-index="${escapeHtml(index)}">
          <div class="research-plan-edit-row-head">
            <span>Branch ${escapeHtml(index + 1)}</span>
            <button class="btn btn-secondary btn-sm" type="button" data-branch-delete="${escapeHtml(index)}">Delete</button>
          </div>
          <label><span>Branch label</span><input type="text" value="${escapeHtml(branch.label || "")}" data-branch-label="${escapeHtml(index)}"></label>
          <label><span>Search query</span><textarea rows="3" data-branch-query="${escapeHtml(index)}">${escapeHtml(branch.query || "")}</textarea></label>
        </div>
      `).join("")}
      <div class="research-plan-branch-edit is-new">
        <label><span>New branch</span><input type="text" placeholder="Branch label" data-new-branch-label></label>
        <label><span>Search query</span><textarea rows="3" placeholder="Detailed query for this branch, including aliases and synonyms" data-new-branch-query></textarea></label>
      </div>
    </div>
  `;
}

function researchPlanConceptEditMarkup(concepts) {
  return `
    <div class="research-plan-branch-edit-list">
      ${concepts.map((concept, index) => `
        <div class="research-plan-branch-edit" data-concept-index="${escapeHtml(index)}">
          <div class="research-plan-edit-row-head">
            <span>Category ${escapeHtml(index + 1)}</span>
            <button class="btn btn-secondary btn-sm" type="button" data-concept-delete="${escapeHtml(index)}">Delete</button>
          </div>
          <label><span>Category label</span><input type="text" value="${escapeHtml(concept.label || `Shared query ${index + 1}`)}" data-concept-label="${escapeHtml(index)}"></label>
          <label><span>Search query</span><textarea rows="3" data-concept-query="${escapeHtml(index)}">${escapeHtml(concept.query || "")}</textarea></label>
        </div>
      `).join("")}
      <div class="research-plan-branch-edit is-new">
        <label><span>New category</span><input type="text" placeholder="Category label" data-new-concept-label></label>
        <label><span>Search query</span><textarea rows="3" placeholder="Query block added to every branch" data-new-concept-query></textarea></label>
      </div>
    </div>
  `;
}

function researchPlanDetailMarkup(action, messageId = "", actionIndex = 0) {
  const plan = action?.details?.plan || {};
  const databases = researchPlanDatabases(plan);
  const criteria = Array.isArray(plan.screening_criteria) ? plan.screening_criteria : [];
  const searchBranches = researchPlanSearchBranches(plan);
  const sharedConcepts = researchPlanSharedConcepts(plan);
  const rawSearchQueries = researchPlanRawSearchQueries(plan);
  const groupedSearchQueries = researchPlanGroupedSearchQueries(rawSearchQueries);
  const totalQueries = rawSearchQueries.length || researchPlanTotalQueries(plan);
  const perDatabase = Number(plan?.candidate_budget?.per_database || (Number(plan?.target_count_per_branch || plan?.target_count || 20) * 2));
  const estimatedCandidates = totalQueries * Math.max(1, perDatabase);
  const estimatedSeconds = researchPlanEstimatedSeconds(plan);
  const effectivePlan = researchPlanDisplayPlan(plan, rawSearchQueries, totalQueries, estimatedCandidates, estimatedSeconds);
  const rawJson = JSON.stringify(
    {
      action: {
        title: action.title,
        status: action.status,
        execution_state: action.details?.execution_state,
        revision_state: action.details?.revision_state,
      },
      plan: effectivePlan,
    },
    null,
    2,
  );
  return `
    <div class="research-plan-detail" data-message-id="${escapeHtml(messageId)}" data-action-index="${escapeHtml(actionIndex)}">
      <section class="research-plan-detail-section research-plan-edit-panel">
        <div class="research-plan-edit-head">
          <h4>Editable Plan Basics</h4>
          <button class="btn btn-primary btn-sm" type="button" data-research-plan-save-edits="true">Save manual edits</button>
        </div>
        <div class="research-plan-edit-grid">
          <label>
            <span>Target / branch</span>
            <input type="number" min="1" max="100" value="${escapeHtml(plan.target_count_per_branch || plan.target_count || 20)}" data-plan-edit="target_count">
          </label>
          <label>
            <span>Per database</span>
            <input type="number" min="1" max="500" value="${escapeHtml(plan.candidate_budget?.per_database || Number(plan.target_count || 20) * 2)}" data-plan-edit="per_database">
          </label>
        </div>
        <div class="research-plan-db-edit">
          <span>Active databases</span>
          <div>
            ${researchPlanDatabaseOptions.map((database) => `
              <label>
                <input type="checkbox" value="${escapeHtml(database)}" data-plan-db-edit ${databases.includes(database) ? "checked" : ""}>
                <span>${escapeHtml(database)}</span>
              </label>
            `).join("")}
          </div>
        </div>
      </section>
      <section class="research-plan-detail-section">
        <h4>Objective</h4>
        <p>${escapeHtml(plan.objective || "No objective provided.")}</p>
      </section>
      <section class="research-plan-detail-section">
        <h4>Search Branches</h4>
        ${researchPlanBranchEditMarkup(searchBranches)}
      </section>
      <section class="research-plan-detail-section">
        <h4>Shared Query Blocks</h4>
        <p>Each category is searched with every branch during execution.</p>
        ${researchPlanConceptEditMarkup(sharedConcepts)}
      </section>
      <section class="research-plan-detail-section">
        <h4>Candidate Budget</h4>
        <div class="research-plan-detail-grid">
          <div><span>Target / branch</span><strong>${escapeHtml(plan.target_count_per_branch || plan.target_count || 20)}</strong></div>
          <div><span>Per database</span><strong>${escapeHtml(plan.candidate_budget?.per_database || "-")}</strong></div>
          <div><span>Sources</span><strong>${escapeHtml(databases.length)}</strong></div>
          <div><span>Total queries</span><strong>${escapeHtml(totalQueries)}</strong></div>
          <div><span>Estimated pull</span><strong>${escapeHtml(estimatedCandidates)}</strong></div>
          <div><span>Estimated time</span><strong>${escapeHtml(formatResearchPlanDuration(estimatedSeconds))}</strong></div>
        </div>
        <p>${escapeHtml(plan.candidate_budget?.rule || "Fetch target_count * 2 candidates per enabled database in the first pass.")}</p>
      </section>
      <section class="research-plan-detail-section">
        <h4>Screening Criteria</h4>
        <div class="research-plan-criteria-list">
          ${criteria.length ? criteria.map((item, index) => `
              <div class="research-plan-criterion" data-criterion-index="${escapeHtml(index)}">
                <div>
                  <strong>${escapeHtml(item.label || item.id || "Criterion")}</strong>
                  <span>${escapeHtml(item.id || "")}${item.required ? " · required" : ""}${item.weight ? ` · weight ${escapeHtml(item.weight)}` : ""}</span>
                </div>
                <button class="btn btn-secondary btn-sm" type="button" data-criterion-delete="${escapeHtml(index)}">Delete</button>
                <p>${escapeHtml(item.description || "")}</p>
                <p>${escapeHtml(item.scoring_guidance || "")}</p>
                <div class="research-plan-criterion-edit">
                  <label><span>Weight</span><input type="number" step="0.1" min="0" max="10" value="${escapeHtml(item.weight ?? 1)}" data-criterion-weight="${escapeHtml(index)}"></label>
                  <label><input type="checkbox" ${item.required ? "checked" : ""} data-criterion-required="${escapeHtml(index)}"><span>Required</span></label>
                </div>
              </div>
            `).join("") : "<p>No screening criteria provided.</p>"}
          <div class="research-plan-criterion is-new">
            <div>
              <strong>New criterion</strong>
              <span>Add scoring signal</span>
            </div>
            <label><span>Label</span><input type="text" placeholder="Criterion label" data-new-criterion-label></label>
            <label><span>Description</span><textarea rows="2" placeholder="What the screener should score" data-new-criterion-description></textarea></label>
            <label><span>Guidance</span><textarea rows="2" placeholder="Score 1.0 when..." data-new-criterion-guidance></textarea></label>
            <div class="research-plan-criterion-edit">
              <label><span>Weight</span><input type="number" step="0.1" min="0" max="10" value="1" data-new-criterion-weight></label>
              <label><input type="checkbox" data-new-criterion-required><span>Required</span></label>
            </div>
          </div>
        </div>
      </section>
      <section class="research-plan-detail-section">
        <h4>Exclusion Criteria</h4>
        ${researchPlanEditableListMarkup("exclusion_criteria", plan.exclusion_criteria, "Add exclusion rule")}
      </section>
      <section class="research-plan-detail-section">
        <h4>Scoring Rule</h4>
        <code>${escapeHtml(plan.scoring_rule || "-")}</code>
      </section>
      <section class="research-plan-detail-section">
        <h4>Generated Search Queries</h4>
        <p>Readonly execution preview. Databases: ${escapeHtml(databases.join(", ") || "not specified")}.</p>
        ${groupedSearchQueries.length ? `
          <div class="research-plan-query-list">
            ${groupedSearchQueries.map((item) => `
              <div class="research-plan-query-item">
                <div class="research-plan-query-head">
                  <strong>${escapeHtml(item.category_label ? `${item.branch_label || "Branch"} · ${item.category_label}` : item.branch_label || "Branch")}</strong>
                  <span>${escapeHtml(item.candidate_limit || plan.candidate_budget?.per_database || "-")} candidates</span>
                </div>
                <div class="research-plan-query-databases">
                  ${item.databases.map((database) => `<span>${escapeHtml(database)}</span>`).join("")}
                </div>
                <span>Raw query</span>
                <code>${escapeHtml(item.raw_query || item.branch_query || item.branch_label || "-")}</code>
                <span>Extracted query</span>
                <code>${escapeHtml(item.extracted_query || item.query || "")}</code>
              </div>
            `).join("")}
          </div>
        ` : "<p>No executable queries are available yet.</p>"}
      </section>
      <section class="research-plan-detail-section">
        <h4>Raw JSON</h4>
        <pre>${escapeHtml(rawJson)}</pre>
      </section>
    </div>
  `;
}

function openResearchPlanPopup(messageId, actionIndex) {
  const action = researchPlanDetailAction(messageId, actionIndex);
  if (!action) return;
  const plan = action.details?.plan || {};
  els.detailPopupEyebrow.textContent = "Research Agent Plan";
  els.detailPopupTitle.textContent = plan.topic || "Structured Research Plan";
  els.detailPopupMeta.textContent = [
    action.details?.revision_state ? `Revision ${action.details.revision_state}` : "",
    action.details?.execution_state ? `State ${action.details.execution_state}` : "",
    plan.target_count ? `Target ${plan.target_count}` : "",
  ].filter(Boolean).join(" • ");
  els.detailPopupBody.innerHTML = researchPlanDetailMarkup(action, messageId, actionIndex);
  bindResearchPlanManualEditEvents(els.detailPopupBody);
  setDetailPopupOpen(true);
}

function openResearchExecutionReportPopup(response) {
  const trace = response?.run_trace || {};
  const meta = trace.meta || {};
  const distribution = meta.distribution || {};
  const selectedCount = Array.isArray(response?.articles) ? response.articles.length : 0;
  const candidateCount = Number(meta.candidate_article_count || meta.candidate_count || 0);
  const queryCount = Number(meta.normalized_query_count || meta.raw_query_count || 0);
  const normalizedQueries = meta.normalized_queries || trace.executed_queries || [];
  const report = {
    summary: {
      run_id: trace.id || "",
      topic: trace.topic || "",
      objective: trace.objective || "",
      normalized_query_count: queryCount,
      candidate_article_count: candidateCount,
      selected_article_count: selectedCount,
      sources_used: response?.meta?.sources_used || [],
      elapsed_ms: response?.meta?.elapsed_ms || meta.elapsed_ms || 0,
    },
    distribution,
    normalized_queries: normalizedQueries,
    selected_candidate_ids: trace.selected_candidate_ids || [],
    backup_candidate_ids: trace.backup_candidate_ids || [],
    excluded_candidate_ids: trace.excluded_candidate_ids || [],
    screening: trace.screening || [],
    selections: trace.selections || [],
  };
  els.detailPopupEyebrow.textContent = "Report";
  els.detailPopupTitle.textContent = trace.topic || "Research Execution Report";
  els.detailPopupMeta.textContent = `${selectedCount} selected · ${candidateCount} candidates · ${queryCount} queries`;
  els.detailPopupBody.innerHTML = `
    <div class="research-plan-detail">
      <section class="research-plan-detail-section">
        <h4>Execution Summary</h4>
        <div class="research-plan-detail-grid">
          <div><span>Selected</span><strong>${escapeHtml(selectedCount)}</strong></div>
          <div><span>Candidates</span><strong>${escapeHtml(candidateCount)}</strong></div>
          <div><span>Queries</span><strong>${escapeHtml(queryCount)}</strong></div>
          <div><span>Sources</span><strong>${escapeHtml((response?.meta?.sources_used || []).join(", ") || "-")}</strong></div>
        </div>
      </section>
      <section class="research-plan-detail-section">
        <h4>Branch Distribution</h4>
        <div class="research-plan-detail-grid">
          ${(distribution.branch_distribution || []).map((row) => `
            <div>
              <span>${escapeHtml(row.branch_label || row.branch_id || "Branch")}</span>
              <strong>${escapeHtml(row.selected_count || 0)}/${escapeHtml(row.target_count || 0)}</strong>
              <small>${escapeHtml(row.candidate_count || 0)} candidates · ${escapeHtml(row.excluded_count || 0)} excluded</small>
            </div>
          `).join("") || "<p>No branch distribution available.</p>"}
        </div>
        ${(distribution.warnings || []).length ? `<p>${escapeHtml(distribution.warnings.join(" "))}</p>` : ""}
      </section>
      <section class="research-plan-detail-section">
        <h4>Query Mapping</h4>
        ${(normalizedQueries || []).length ? `
          <div class="research-plan-query-list">
            ${normalizedQueries.map((query) => `
              <div class="research-plan-query-item">
                <strong>${escapeHtml(query.database || query.source || "Database")} · ${escapeHtml(query.branch_label || "Branch")}</strong>
                <span>Raw query</span>
                <code>${escapeHtml(query.raw_query || query.branch_query || "-")}</code>
                <span>Extracted query</span>
                <code>${escapeHtml(query.extracted_query || query.query || "-")}</code>
              </div>
            `).join("")}
          </div>
        ` : "<p>No query mapping available.</p>"}
      </section>
      <section class="research-plan-detail-section">
        <h4>Source Distribution</h4>
        <div class="research-plan-detail-grid">
          ${(distribution.source_distribution || []).map((row) => `
            <div><span>${escapeHtml(row.database || row.source || "Source")}</span><strong>${escapeHtml(row.candidate_matches || 0)}</strong></div>
          `).join("") || "<p>No source distribution available.</p>"}
        </div>
      </section>
      <section class="research-plan-detail-section">
        <h4>Report JSON</h4>
        <pre>${escapeHtml(JSON.stringify(report, null, 2))}</pre>
      </section>
    </div>
  `;
  setDetailPopupOpen(true);
}

function saveResearchPlanManualEdits(messageId, actionIndex, root) {
  const action = researchPlanDetailAction(messageId, actionIndex);
  if (!action) return;
  const plan = cloneJson(action.details?.plan || {});
  const targetInput = root.querySelector("[data-plan-edit='target_count']");
  const perDatabaseInput = root.querySelector("[data-plan-edit='per_database']");
  const targetCount = Number.parseInt(String(targetInput?.value || ""), 10);
  const perDatabase = Number.parseInt(String(perDatabaseInput?.value || ""), 10);
  if (Number.isFinite(targetCount)) plan.target_count = Math.min(100, Math.max(1, targetCount));
  if (!plan.candidate_budget || typeof plan.candidate_budget !== "object") plan.candidate_budget = {};
  if (Number.isFinite(perDatabase)) plan.candidate_budget.per_database = Math.min(500, Math.max(1, perDatabase));
  const activeDatabases = [...root.querySelectorAll("[data-plan-db-edit]:checked")]
    .map((node) => node.value)
    .filter(Boolean);
  if (activeDatabases.length) {
    plan.active_databases = activeDatabases;
    plan.databases = activeDatabases;
  }
  if (Array.isArray(plan.screening_criteria)) {
    plan.screening_criteria = [...root.querySelectorAll("[data-criterion-index]")].map((node) => {
      if (node.dataset.deleted === "true") return null;
      const index = Number(node.dataset.criterionIndex);
      const item = cloneJson(plan.screening_criteria[index] || {});
      const weightInput = root.querySelector(`[data-criterion-weight='${index}']`);
      const requiredInput = root.querySelector(`[data-criterion-required='${index}']`);
      const nextWeight = Number.parseFloat(String(weightInput?.value || ""));
      if (Number.isFinite(nextWeight)) item.weight = Math.max(0, Math.min(10, nextWeight));
      if (requiredInput) item.required = Boolean(requiredInput.checked);
      return item;
    }).filter(Boolean);
  }
  const newCriterionLabel = root.querySelector("[data-new-criterion-label]")?.value.trim();
  if (newCriterionLabel) {
    if (!Array.isArray(plan.screening_criteria)) plan.screening_criteria = [];
    const newCriterionWeight = Number.parseFloat(String(root.querySelector("[data-new-criterion-weight]")?.value || ""));
    plan.screening_criteria.push({
      id: newCriterionLabel.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || `criterion_${plan.screening_criteria.length + 1}`,
      label: newCriterionLabel,
      description: root.querySelector("[data-new-criterion-description]")?.value.trim() || newCriterionLabel,
      required: Boolean(root.querySelector("[data-new-criterion-required]")?.checked),
      weight: Number.isFinite(newCriterionWeight) ? Math.max(0, Math.min(10, newCriterionWeight)) : 1,
      scoring_guidance: root.querySelector("[data-new-criterion-guidance]")?.value.trim() || "Score 1.0 for explicit evidence, 0.5 for partial evidence, and 0.0 when absent.",
    });
  }
  const branches = [...root.querySelectorAll("[data-branch-index]")].map((node) => {
    if (node.dataset.deleted === "true") return null;
    const index = node.dataset.branchIndex;
    const label = root.querySelector(`[data-branch-label='${index}']`)?.value.trim();
    if (!label) return null;
    const query = root.querySelector(`[data-branch-query='${index}']`)?.value.trim() || label;
    return {
      id: label.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || `branch_${Number(index) + 1}`,
      label,
      query,
    };
  }).filter(Boolean);
  const newBranchLabel = root.querySelector("[data-new-branch-label]")?.value.trim();
  if (newBranchLabel) {
    branches.push({
      id: newBranchLabel.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || `branch_${branches.length + 1}`,
      label: newBranchLabel,
      query: root.querySelector("[data-new-branch-query]")?.value.trim() || newBranchLabel,
    });
  }
  if (branches.length) plan.search_branches = branches;
  const concepts = [...root.querySelectorAll("[data-concept-index]")].map((node) => {
    if (node.dataset.deleted === "true") return null;
    const index = node.dataset.conceptIndex;
    const query = root.querySelector(`[data-concept-query='${index}']`)?.value.trim();
    if (!query) return null;
    const label = root.querySelector(`[data-concept-label='${index}']`)?.value.trim() || `Shared query ${Number(index) + 1}`;
    return {
      id: label.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || `concept_${Number(index) + 1}`,
      label,
      query,
    };
  }).filter(Boolean);
  const newConceptQuery = root.querySelector("[data-new-concept-query]")?.value.trim();
  if (newConceptQuery) {
    const label = root.querySelector("[data-new-concept-label]")?.value.trim() || `Shared query ${concepts.length + 1}`;
    concepts.push({
      id: label.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || `concept_${concepts.length + 1}`,
      label,
      query: newConceptQuery,
    });
  }
  plan.shared_query_concepts = concepts;
  ["exclusion_criteria"].forEach((key) => {
    const values = [...root.querySelectorAll(`[data-plan-list-item='${key}']`)]
      .filter((node) => node.closest(".research-plan-edit-line")?.dataset.deleted !== "true")
      .map((node) => node.value.trim())
      .filter(Boolean);
    const newValue = root.querySelector(`[data-plan-list-new='${key}']`)?.value.trim();
    if (newValue) values.push(newValue);
    plan[key] = values;
  });
  recomputeResearchPlanEstimates(plan);
  action.details = {
    ...(action.details || {}),
    plan,
    revision_state: "manual",
  };
  action.title = "Research plan edited";
  const message = state.assistantMessages.find((item) => item.id === messageId);
  if (message) {
    scheduleAssistantMessageUpdate(message);
  }
  syncCurrentSession();
  openResearchPlanPopup(messageId, actionIndex);
}

function bindResearchPlanManualEditEvents(root = document) {
  root.querySelectorAll("[data-branch-delete], [data-concept-delete], [data-criterion-delete], [data-plan-list-delete]").forEach((node) => {
    if (node.dataset.boundPlanDelete === "true") return;
    node.dataset.boundPlanDelete = "true";
    node.addEventListener("click", (event) => {
      event.preventDefault();
      const row = node.closest("[data-branch-index], [data-concept-index], [data-criterion-index], .research-plan-edit-line");
      if (!row) return;
      row.dataset.deleted = "true";
      row.hidden = true;
    });
  });
  root.querySelectorAll("[data-research-plan-save-edits]").forEach((node) => {
    if (node.dataset.boundManualPlanSave === "true") return;
    node.dataset.boundManualPlanSave = "true";
    node.addEventListener("click", (event) => {
      event.preventDefault();
      const container = node.closest(".research-plan-detail");
      if (!container) return;
      saveResearchPlanManualEdits(container.dataset.messageId || "", container.dataset.actionIndex || "0", container);
    });
  });
}

async function executeResearchPlan(messageId, actionIndex, trigger = null) {
  const action = researchPlanDetailAction(messageId, actionIndex);
  if (!action) return;
  if (!state.projectId) {
    await ensureActiveProject();
  }
  if (!state.projectId) {
    throw new Error("Active project is required for research plan execution.");
  }
  const plan = recomputeResearchPlanEstimates(cloneJson(action.details?.plan || {}));
  const previousLabel = trigger?.textContent || "";
  if (trigger) {
    trigger.disabled = true;
    trigger.textContent = "Executing...";
  }
  action.details = {
    ...(action.details || {}),
    plan,
    execution_state: "running",
  };
  syncCurrentSession();
  trackAppEvent("info", "research_plan_execution_started", plan.topic || "Research plan execution", {
    project_id: state.projectId || "",
    total_queries: plan.total_queries || 0,
    estimated_candidates: plan.estimated_candidates || 0,
  });
  const traceMessage = pushAssistantMessage({
    role: "assistant",
    text: "",
    pending: true,
    actions: [],
    liveThinking: "Starting research plan execution...\n",
    thinkingEnabled: true,
  });
  const appendTrace = (text) => {
    const stamp = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    traceMessage.liveThinking = `${traceMessage.liveThinking || ""}[${stamp}] ${text}\n`;
    scheduleAssistantMessageUpdate(traceMessage);
  };
  const showLocalRequestLoading = isLocalAssistantModel(runtime.assistantModel);
  const clearLocalRequestLoading = () => {
    if (showLocalRequestLoading && runtime.assistantModelLoading) {
      setAssistantModelLoading(false);
      updateAssistantModelUI();
    }
  };
  try {
    let response = null;
    await streamJsonEvents(
      `/app/projects/${encodeURIComponent(state.projectId)}/research-plan/execute/stream`,
      {
        method: "POST",
        idleTimeoutMs: 180000,
        responseTimeoutMs: 30000,
        body: JSON.stringify({
          plan,
          screening_model: runtime.assistantModel,
          api_key: isLocalAssistantModel(runtime.assistantModel) ? "" : runtime.apiKey,
          thinking_level: state.thinkingLevel || "off",
        }),
      },
      (event) => {
        if (event.type === "trace") {
          appendTrace(event.message || event.stage || "Working...");
          if (event.stage === "screening_agent_request" && showLocalRequestLoading) {
            setAssistantModelLoading(true, runtime.assistantModel);
          }
          if ((event.stage === "screening_agent_first_token" || event.stage === "screening_agent_done" || event.stage === "screening_complete") && showLocalRequestLoading) {
            clearLocalRequestLoading();
          }
          if (event.stage === "queries_complete" && Array.isArray(event.articles) && event.articles.length) {
            const queryId = action.details?.agent_query_id || `research_agent_${Date.now().toString(36)}`;
            action.details = {
              ...(action.details || {}),
              agent_query_id: queryId,
            };
            upsertResearchExecutionCandidateQuery(
              { meta: event.meta || {}, candidate_articles: event.articles },
              plan,
              {
                id: queryId,
                title: `${plan.topic || plan.objective || "Research plan execution"} · Agent Query`,
                articles: event.articles,
                meta: event.meta || {},
              },
            );
            state.activeQueryId = queryId;
            state.queryDetailId = queryId;
            state.selectedQueryIds = new Set();
            state.lastSearchPayload = {
              query: plan.topic || plan.objective || "Research plan execution",
              year_start: null,
              year_end: null,
              max_results: Math.max(1, event.articles.length),
              batch_size: null,
              min_cite: null,
              article_type: null,
              use_cache: true,
              preferred_source: "pubmed",
            };
            applyArticleDataset({ meta: event.meta || {}, articles: event.articles }, { persist: false });
            renderQueryHistory();
            syncCurrentSession();
            scheduleProjectStateSave();
          }
          return;
        }
        if (event.type === "error") {
          throw new Error(event.message || "Research plan execution failed.");
        }
        if (event.type === "final") {
          response = event.response;
        }
      },
    );
    if (!response) {
      throw new Error("Research plan execution finished without a final response.");
    }
    if (response.run_trace) {
      state.researchRuns = [response.run_trace, ...state.researchRuns.filter((item) => item.id !== response.run_trace.id)].slice(0, 20);
    }
    const finalQueryId = upsertResearchExecutionCandidateQuery(response, plan, {
      id: action.details?.agent_query_id || (response.run_trace?.id ? `research_${response.run_trace.id}` : ""),
      title: `${plan.topic || plan.objective || "Research plan execution"} · Agent Query`,
    });
    state.activeQueryId = finalQueryId || null;
    state.queryDetailId = finalQueryId || null;
    state.selectedQueryIds = new Set();
    state.lastSearchPayload = {
      query: plan.topic || plan.objective || "Research plan execution",
      year_start: 1900,
      year_end: new Date().getFullYear(),
      max_results: Math.max(1, response.articles?.length || plan.target_count || 20),
      batch_size: null,
      min_cite: null,
      article_type: null,
      use_cache: true,
      preferred_source: "openalex",
    };
    applyArticleDataset(response, { persist: false });
    openResearchExecutionReportPopup(response);
    action.details = {
      ...(action.details || {}),
      plan,
      execution_state: "executed",
      run_id: response.run_trace?.id || "",
      selected_count: response.articles?.length || 0,
    };
    action.title = "Research plan executed";
    traceMessage.pending = false;
    traceMessage.text = `Research plan execution completed. ${response.articles?.length || 0} articles selected.`;
    traceMessage.meta = response.run_trace?.id || "";
    syncCurrentSession();
    scheduleAssistantMessageUpdate(traceMessage);
    renderAssistantMessages();
    renderQueryHistory();
    trackAppEvent("info", "research_plan_execution_completed", `${response.articles?.length || 0} articles selected`, {
      project_id: state.projectId || "",
      run_id: response.run_trace?.id || "",
      selected_count: response.articles?.length || 0,
      candidate_count: response.run_trace?.meta?.candidate_count || 0,
    });
    void enrichCitationsInBackground();
  } catch (error) {
    clearLocalRequestLoading();
    action.details = {
      ...(action.details || {}),
      execution_state: "error",
      error: error.message || "Research plan execution failed.",
    };
    traceMessage.pending = false;
    traceMessage.text = `Research plan execution failed: ${error.message || "Unknown error."}`;
    scheduleAssistantMessageUpdate(traceMessage);
    syncCurrentSession();
    renderAssistantMessages();
    trackAppEvent("error", "research_plan_execution_failed", error.message || "Research plan execution failed.", {
      project_id: state.projectId || "",
    });
    alert(error.message || "Research plan execution failed.");
  } finally {
    clearLocalRequestLoading();
    if (trigger) {
      trigger.disabled = false;
      trigger.textContent = previousLabel || "Execute";
    }
  }
}

function bindResearchPlanPreviewEvents(root = document) {
  root.querySelectorAll("[data-research-plan-action='execute']").forEach((node) => {
    if (node.dataset.boundResearchPlanExecute === "true") return;
    node.dataset.boundResearchPlanExecute = "true";
    node.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const container = node.closest(".research-plan-preview");
      void executeResearchPlan(container?.dataset.messageId || "", container?.dataset.actionIndex || "0", node);
    });
  });
  root.querySelectorAll(".research-plan-preview[data-research-plan-details]").forEach((node) => {
    if (node.dataset.boundResearchPlan === "true") return;
    node.dataset.boundResearchPlan = "true";
    const open = (event) => {
      if (event.target.closest("[data-research-plan-action='execute']")) return;
      event.preventDefault();
      event.stopPropagation();
      openResearchPlanPopup(node.dataset.messageId || "", node.dataset.actionIndex || "0");
    };
    node.addEventListener("click", open);
    node.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      open(event);
    });
  });
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
  const meshPresentation = detailFieldPresentation("mesh");
  const keywordsPresentation = detailFieldPresentation("keywords");
  const relatedPresentation = detailFieldPresentation("related_articles");
  const link = bestArticleLink(article);
  return `
    <tr class="detail-row">
      <td colspan="11">
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
            ${detailBlockMarkup(article, "research_sources", "Research Branch", articleResearchBranchLabel(article) || "-", articleResearchScore(article) !== null ? `Score ${formatResearchScore(articleResearchScore(article))}` : "")}
            ${detailBlockMarkup(article, "research_sources", "Database Sources", articleResearchSourcesLabel(article) || currentSearchSourceLabel(), currentSearchSourcesUsed())}
            ${detailBlockMarkup(article, "journal", "Journal & Publication", article.journal || "-", article.publication_date || "-")}
            ${detailBlockMarkup(article, "journal_metrics", "Q Rank", journalQuartileLabel(article), journalQuartileSubtext(article))}
            ${detailBlockMarkup(article, "authors", "Authors", compactList(article.authors, 10))}
            ${detailBlockMarkup(article, "mesh", meshPresentation.label, compactList(article.mesh_terms, 12))}
            ${detailBlockMarkup(article, "keywords", keywordsPresentation.label, compactList(article.keywords, 12))}
            ${detailBlockMarkup(article, "article_types", "Article Types", compactList(article.article_types, 8))}
            ${detailBlockMarkup(article, "related_articles", relatedPresentation.label, compactList(article.related_articles, 8))}
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
    branch: "asc",
    score: "desc",
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
    case "branch":
      return articleResearchBranchLabel(article) || null;
    case "score":
      return articleResearchScore(article);
    default:
      return null;
  }
}

function emptyTableFilters() {
  return {
    years: [],
    articleTypes: [],
    citationBuckets: [],
    journalQuartiles: [],
    meshTerms: [],
    keywords: [],
  };
}

function normalizeFilterOption(value) {
  return String(value ?? "").trim();
}

function selectedFilterSet(key) {
  return new Set((state.tableFilters?.[key] || []).map(normalizeFilterOption).filter(Boolean));
}

function citationBucketForArticle(article) {
  const count = Number.isInteger(article?.citation_count) ? article.citation_count : null;
  if (count === null) return "unknown";
  if (count < 25) return "0-24";
  if (count < 50) return "25-49";
  if (count < 100) return "50-99";
  if (count < 200) return "100-199";
  if (count < 500) return "200-499";
  return "500+";
}

function citationBucketLabel(bucket) {
  return {
    "0-24": "0-24",
    "25-49": "25-49",
    "50-99": "50-99",
    "100-199": "100-199",
    "200-499": "200-499",
    "500+": "500+",
    unknown: "Unknown",
  }[bucket] || bucket;
}

function articleFilterValues(article, key) {
  switch (key) {
    case "years":
      return [normalizeFilterOption(article.year || "Unknown")];
    case "articleTypes":
      return (article.article_types?.length ? article.article_types : [article.article_type || "Unknown"])
        .map(normalizeFilterOption)
        .filter(Boolean);
    case "citationBuckets":
      return [citationBucketForArticle(article)];
    case "journalQuartiles":
      return [normalizeFilterOption(article.journal_quartile || "Unranked")];
    case "meshTerms":
      return (article.mesh_terms || []).map(normalizeFilterOption).filter(Boolean);
    case "keywords":
      return (article.keywords || []).map(normalizeFilterOption).filter(Boolean);
    default:
      return [];
  }
}

function tableFilterActiveCount() {
  return Object.values(state.tableFilters || {}).reduce((sum, values) => sum + (Array.isArray(values) ? values.length : 0), 0);
}

function articleMatchesTableFilters(article) {
  const filters = state.tableFilters || emptyTableFilters();
  return Object.keys(filters).every((key) => {
    const selected = selectedFilterSet(key);
    if (!selected.size) return true;
    return articleFilterValues(article, key).some((value) => selected.has(value));
  });
}

function applyArticleFilters() {
  state.articles = state.allArticles.filter((article) => articleMatchesTableFilters(article));
  applyArticleSort();
  const visibleIds = new Set(state.articles.map((article) => article.id));
  state.selectedIds = new Set([...state.selectedIds].filter((id) => visibleIds.has(id)));
  if (state.detailArticleId && !visibleIds.has(state.detailArticleId)) {
    state.detailArticleId = null;
  }
}

function countFilterOptions(key) {
  const counts = new Map();
  state.allArticles.forEach((article) => {
    articleFilterValues(article, key).forEach((value) => {
      const normalized = normalizeFilterOption(value || "Unknown");
      if (!normalized) return;
      counts.set(normalized, (counts.get(normalized) || 0) + 1);
    });
  });
  return [...counts.entries()]
    .map(([value, count]) => ({ value, count }))
    .sort((left, right) => {
      if (key === "years") {
        return (parseOptionalNumber(right.value) || 0) - (parseOptionalNumber(left.value) || 0);
      }
      if (key === "journalQuartiles") {
        const rank = { Q1: 1, Q2: 2, Q3: 3, Q4: 4, Unranked: 5 };
        return (rank[left.value] || 99) - (rank[right.value] || 99);
      }
      if (key === "citationBuckets") {
        const rank = { "0-24": 1, "25-49": 2, "50-99": 3, "100-199": 4, "200-499": 5, "500+": 6, unknown: 7 };
        return (rank[left.value] || 99) - (rank[right.value] || 99);
      }
      return right.count - left.count || left.value.localeCompare(right.value, "en", { sensitivity: "base" });
    });
}

function tableFilterSections() {
  return [
    { key: "years", title: "Year", options: countFilterOptions("years") },
    {
      key: "citationBuckets",
      title: "Citations",
      options: ["0-24", "25-49", "50-99", "100-199", "200-499", "500+", "unknown"]
        .map((value) => countFilterOptions("citationBuckets").find((item) => item.value === value) || { value, count: 0 })
        .filter((item) => item.count > 0),
      label: citationBucketLabel,
    },
    { key: "articleTypes", title: "Article Type", options: countFilterOptions("articleTypes") },
    { key: "journalQuartiles", title: "Q Rank", options: countFilterOptions("journalQuartiles") },
    { key: "meshTerms", title: "MeSH Terms", options: countFilterOptions("meshTerms") },
    { key: "keywords", title: "Keywords", options: countFilterOptions("keywords") },
  ];
}

function renderTableFilterPopup() {
  if (!els.tableFilterBody) return;
  const activeCount = tableFilterActiveCount();
  if (els.tableFilterMeta) {
    els.tableFilterMeta.textContent = `${activeCount} active · ${state.articles.length} of ${state.allArticles.length} shown`;
  }
  const sections = tableFilterSections();
  els.tableFilterBody.innerHTML = sections
    .map((section) => {
      const selected = selectedFilterSet(section.key);
      const labelFor = section.label || ((value) => value);
      return `
        <details class="native-filter-section" open>
          <summary class="native-filter-section-summary">
            <span>${escapeHtml(section.title)}</span>
            <span>${escapeHtml(String(section.options.length))}</span>
          </summary>
          <div class="native-filter-options">
            ${section.options.length ? section.options.map((option) => `
              <label class="native-filter-option">
                <input type="checkbox" data-filter-key="${escapeHtml(section.key)}" value="${escapeHtml(option.value)}" ${selected.has(option.value) ? "checked" : ""}>
                <span class="native-filter-option-label">${escapeHtml(labelFor(option.value))}</span>
                <span class="native-filter-option-count">${escapeHtml(String(option.count))}</span>
              </label>
            `).join("") : '<div class="native-filter-empty">No values</div>'}
          </div>
        </details>
      `;
    })
    .join("");
}

function readTableFiltersFromPopup() {
  const next = emptyTableFilters();
  els.tableFilterBody?.querySelectorAll("input[data-filter-key]:checked").forEach((input) => {
    const key = input.dataset.filterKey;
    if (!Object.hasOwn(next, key)) return;
    next[key].push(input.value);
  });
  return next;
}

function setTableFilterOpen(next) {
  if (!els.tableFilterPopup || !els.tableFilterOverlay) return;
  els.tableFilterPopup.hidden = !next;
  els.tableFilterOverlay.hidden = !next;
  els.tableFilterPopup.classList.toggle("is-open", next);
  els.tableFilterOverlay.classList.toggle("is-open", next);
  if (next) renderTableFilterPopup();
}

function applyTableFiltersFromPopup() {
  state.tableFilters = readTableFiltersFromPopup();
  applyArticleFilters();
  renderMeta(state.lastPubmedResponse?.meta || null);
  renderResults();
  setTableFilterOpen(false);
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
  applyArticleFilters();
  renderResults();
}

function renderMeta(meta) {
  if (!meta) {
    els.metaStrip.innerHTML = "";
    return;
  }
  const yearBits = [];
  if (state.lastSearchPayload?.year_start) yearBits.push(`from ${state.lastSearchPayload.year_start}`);
  if (state.lastSearchPayload?.year_end) yearBits.push(`to ${state.lastSearchPayload.year_end}`);
  const chips = [
    ["Total results", meta.total_results_found],
    ["Fetched", meta.fetched_results],
    ["Shown", state.allArticles.length ? `${state.articles.length}/${state.allArticles.length}` : state.articles.length],
    ["Database", currentSearchSourceLabel()],
    ["Sources", currentSearchSourcesUsed()],
    ["Years", yearBits.join(" ") || "last 5 years"],
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
  const activeFilters = tableFilterActiveCount();
  els.articleCount.textContent = String(state.articles.length);
  els.selectedCount.textContent = String(state.selectedIds.size);
  els.selectAllBtn.disabled = state.articles.length === 0;
  els.clearSelectionBtn.disabled = !hasSelection;
  if (els.tableFilterBtn) {
    els.tableFilterBtn.disabled = state.allArticles.length === 0;
    els.tableFilterBtn.textContent = activeFilters ? `Filters (${activeFilters})` : "Filters";
    els.tableFilterBtn.classList.toggle("is-active", activeFilters > 0);
  }
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
        if (state.lastPubmedResponse) {
          state.lastPubmedResponse = {
            ...state.lastPubmedResponse,
            articles: cloneJson(state.allArticles),
          };
        }
        applyArticleFilters();
        renderMeta(state.lastPubmedResponse?.meta || null);
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
  const { persist = true, mode = "query" } = options;
  state.datasetRevision += 1;
  closeDocumentViewer();
  state.lastPubmedResponse = data;
  state.articleDatasetMode = mode;
  state.allArticles = Array.isArray(data.articles) ? data.articles : [];
  if (data?.meta?.primary_source === "research_plan" && state.allArticles.some((article) => articleResearchScore(article) !== null)) {
    state.sortKey = "score";
    state.sortDirection = "desc";
  }
  state.tableFilters = emptyTableFilters();
  state.downloadabilityRunId += 1;
  seedDownloadability(state.allArticles);
  state.selectedIds.clear();
  state.detailArticleId = null;
  closeDetailPopup();
  applyArticleFilters();
  renderMeta(data.meta || null);
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
                  <td colspan="11" class="empty-cell">
          <div class="native-empty-state">
            <div class="native-empty-state-title">No search yet</div>
            <div class="native-empty-state-copy">Start with a topic in Searcher AI. Default search covers the most recent 5 years.</div>
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
          <td>${escapeHtml(tableIdentifier(article))}</td>
          <td class="year-cell">${escapeHtml(article.year || "-")}</td>
          <td class="type-cell">${escapeHtml(articleTypeLabel(article))}</td>
          <td class="count-cell">${escapeHtml(citationLabel(article))}</td>
          <td class="type-cell">${escapeHtml(articleResearchBranchLabel(article) || "-")}</td>
          <td class="count-cell">${escapeHtml(formatResearchScore(articleResearchScore(article)))}</td>
          <td class="title-cell">
            <div class="table-title-main">${escapeHtml(article.title || "-")}</div>
            <div class="table-title-sub">${escapeHtml(articleTitleMeta(article) || currentSearchSourceLabel())}</div>
          </td>
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
    preferred_source: normalizeSearchResource(
      els.searchResource?.value || runtime.searchResource,
      "pubmed",
    ),
  };
  if (!payload.query) {
    throw new Error("Search query cannot be empty.");
  }
  els.searchBtn.disabled = true;
  state.activeQueryId = null;
  state.queryDetailId = null;
  state.selectedQueryIds = new Set();
  state.lastSearchPayload = payload;
  trackAppEvent("info", "literature_search_started", payload.query, {
    project_id: state.projectId || "",
    max_results: payload.max_results,
    pubmed_oa_only: Boolean(runtime.pubmedOaOnly),
    preferred_source: payload.preferred_source,
  });
  try {
    const response = await fetchJson("/pubmed/search", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.citationsLoading = response.articles?.length > 0;
    applyArticleDataset(response);
    syncSidebarQuickControls();
    trackAppEvent("info", "literature_search_completed", `${response.meta?.fetched_results || 0} articles`, {
      project_id: state.projectId || "",
      fetched_results: response.meta?.fetched_results || 0,
      elapsed_ms: response.meta?.elapsed_ms || 0,
      pubmed_oa_only: Boolean(response.meta?.oa_only),
      primary_source: response.meta?.primary_source || "",
      sources_used: response.meta?.sources_used || [],
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
  const yearStart = els.sidebarQuickYearStart?.value ? Number(els.sidebarQuickYearStart.value) : null;
  const yearEnd = els.sidebarQuickYearEnd?.value ? Number(els.sidebarQuickYearEnd.value) : null;
  const preferredSource = normalizeSearchResource(
    els.sidebarQuickSearchResource?.value || runtime.searchResource,
    "pubmed",
  );
  if (els.sidebarQuickSearchBtn) els.sidebarQuickSearchBtn.disabled = true;
  state.activeQueryId = null;
  state.queryDetailId = null;
  state.selectedQueryIds = new Set();
  if (els.sidebarQuickStatus) {
    els.sidebarQuickStatus.textContent = `Running ${searchResourceLabel(preferredSource)} search…`;
  }
  els.query.value = query;
  els.maxResults.value = String(maxResults);
  els.yearStart.value = yearStart ? String(yearStart) : "";
  els.yearEnd.value = yearEnd ? String(yearEnd) : "";
  if (els.searchResource) {
    els.searchResource.value = preferredSource;
  }
  runtime.searchResource = preferredSource;
  localStorage.setItem(searchResourceStorageKey, preferredSource);
  autoResizeTextarea(els.query);
  autoResizeTextarea(els.sidebarQuickQuery);
  try {
    await runSearch();
    if (els.sidebarQuickStatus) {
      const actualSource = searchResourceLabel(state.lastPubmedResponse?.meta?.primary_source || preferredSource);
      els.sidebarQuickStatus.textContent = `${state.articles.length} articles loaded via ${actualSource}.`;
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
  const options = assistantModelOptions();
  const activeModel = normalizeAssistantModel(runtime.assistantModel);
  runtime.assistantModel = activeModel;
  ensureAssistantModelVisible(activeModel);
  localStorage.setItem(assistantModelStorageKey, activeModel);
  if (els.assistantModelMenu) {
    els.assistantModelMenu.innerHTML = options.map((item) => `
      <button class="assistant-toolbar-menu-item assistant-model-item" type="button" data-model="${escapeHtml(item.value)}">${escapeHtml(item.label)}</button>
    `).join("");
  }
  if (els.assistantModelBtn) {
    els.assistantModelBtn.disabled = Boolean(runtime.assistantModelLoading);
    els.assistantModelBtn.setAttribute("aria-busy", runtime.assistantModelLoading ? "true" : "false");
  }
  els.assistantModelLabel.textContent = runtime.assistantModelLoading
    ? `Loading ${assistantModelDisplayLabel(runtime.assistantModelLoadingTarget) || "model"}...`
    : (assistantModelDisplayLabel(activeModel)
      || options.find((item) => item.value === activeModel)?.label
      || activeModel);
  document.querySelectorAll(".assistant-model-item").forEach((item) => {
    item.classList.toggle("is-selected", item.dataset.model === runtime.assistantModel);
  });
  updateThinkingControlsUI();
  updateOllamaThinkingControlUI();
}

function currentModelSupportsThinking() {
  return !isLocalAssistantModel(runtime.assistantModel) && Boolean(assistantModelThinkingSupport[runtime.assistantModel]);
}

function effectiveThinkingLevel() {
  return currentModelSupportsThinking() ? state.thinkingLevel : "off";
}

function assistantThinkingLevelForRequest() {
  if (isOllamaAssistantModel(runtime.assistantModel)) {
    return normalizeOllamaThinkingLevel(runtime.ollamaThinkingLevel, "off");
  }
  if (isLlamaCppAssistantModel(runtime.assistantModel)) {
    return "off";
  }
  return effectiveThinkingLevel();
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
  document.querySelectorAll(".think-menu-item[data-level]").forEach((item) => {
    item.classList.toggle("is-selected", item.dataset.level === state.thinkingLevel);
  });
}

function updateOllamaThinkingControlUI() {
  const isOllamaModel = isOllamaAssistantModel(runtime.assistantModel);
  if (els.assistantOllamaThinkingWrap) {
    els.assistantOllamaThinkingWrap.hidden = !isOllamaModel;
  }
  if (els.assistantOllamaThinkingLabel) {
    els.assistantOllamaThinkingLabel.textContent = `Thinking: ${ollamaThinkingLevelLabel(runtime.ollamaThinkingLevel)}`;
  }
  document.querySelectorAll(".think-menu-item[data-ollama-think]").forEach((item) => {
    item.classList.toggle("is-selected", item.dataset.ollamaThink === normalizeOllamaThinkingLevel(runtime.ollamaThinkingLevel, "off"));
  });
  if (!isOllamaModel && els.assistantOllamaThinkingMenu) els.assistantOllamaThinkingMenu.hidden = true;
  if (els.assistantOllamaThinkingBtn) els.assistantOllamaThinkingBtn.setAttribute("aria-expanded", "false");
}

function assistantActionLabel(action) {
  const details = action.details || {};
  const sourceLabel = searchResourceLabel(details.meta?.primary_source || runtime.aiPrimarySearchResource || "pubmed");
  const running = {
    search_pubmed: `Searching ${sourceLabel}`,
    get_article_details: "Reading article details",
    list_catalog_articles: "Scanning catalog",
    create_research_plan: "Creating research plan",
  };
  const success = {
    search_pubmed: `Searched ${sourceLabel}`,
    get_article_details: "Read article details",
    list_catalog_articles: "Scanned catalog",
    create_research_plan: "Created research plan",
  };
  const error = {
    search_pubmed: `${sourceLabel} search failed`,
    get_article_details: "Article detail read failed",
    list_catalog_articles: "Catalog scan failed",
    create_research_plan: "Research plan failed",
  };
  if (action.status === "running") return running[action.name] || "Running tool";
  if (action.status === "error") return error[action.name] || "Tool failed";
  return success[action.name] || "Tool completed";
}

function assistantActionDetail(action) {
  const details = action.details || {};
  if (action.name === "search_pubmed") {
    return details.query || "Building literature query";
  }
  if (action.name === "get_article_details") {
    const ids = details.requested_ids || details.returned_ids || details.ids || [];
    return ids.length ? `ID ${ids.join(", ")}` : "Opening article details";
  }
  if (action.name === "list_catalog_articles") {
    return details.query || "Scanning loaded catalog";
  }
  if (action.name === "create_research_plan") {
    return details.plan?.topic || "Structured plan";
  }
  return action.name || "Tool";
}

function assistantActionKindLabel(action) {
  const map = {
    search_pubmed: "Search",
    get_article_details: "Evidence",
    list_catalog_articles: "Catalog",
    create_research_plan: "Plan",
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

function researchPlanActionMarkup(action, messageId = "", actionIndex = 0) {
  const plan = action?.details?.plan || {};
  const databases = researchPlanDatabases(plan);
  const criteria = Array.isArray(plan.screening_criteria) ? plan.screening_criteria : [];
  const branches = researchPlanSearchBranches(plan);
  const totalQueries = researchPlanTotalQueries(plan);
  const exclusions = Array.isArray(plan.exclusion_criteria) ? plan.exclusion_criteria : [];
  return `
    <div
      class="research-plan-preview"
      role="button"
      tabindex="0"
      data-research-plan-details="true"
      data-message-id="${escapeHtml(messageId)}"
      data-action-index="${escapeHtml(actionIndex)}"
      title="Open full plan details"
    >
      <div class="research-plan-preview-head">
        <div>
          <div class="research-plan-preview-kicker">Research Agent Plan</div>
          <div class="research-plan-preview-title">${escapeHtml(plan.topic || "Research topic")}</div>
        </div>
        <span class="research-plan-preview-state">${escapeHtml(action.details?.execution_state || "planned")}</span>
      </div>
      <div class="research-plan-preview-objective">${escapeHtml(plan.objective || "No objective provided.")}</div>
      <div class="research-plan-preview-grid">
        <div><span>Target / branch</span><strong>${escapeHtml(plan.target_count_per_branch || plan.target_count || 20)}</strong></div>
        <div><span>Databases</span><strong>${escapeHtml(databases.length || 0)}</strong></div>
        <div><span>Criteria</span><strong>${escapeHtml(criteria.length || 0)}</strong></div>
        <div><span>Branches</span><strong>${escapeHtml(branches.length || 0)}</strong></div>
        <div><span>Total queries</span><strong>${escapeHtml(totalQueries)}</strong></div>
        <div><span>Est. pull</span><strong>${escapeHtml(researchPlanEstimatedCandidates(plan))}</strong></div>
      </div>
      <div class="research-plan-preview-section">
        <span>Sources</span>
        <p>${escapeHtml(databases.join(", ") || "Not specified")}</p>
      </div>
      <div class="research-plan-preview-section">
        <span>Search branches</span>
        <p>${escapeHtml(branches.map((item) => item.label).join(", ") || "Main branch")}</p>
      </div>
      <div class="research-plan-preview-section">
        <span>First exclusion rules</span>
        <ul>${(exclusions.slice(0, 4).length ? exclusions.slice(0, 4) : ["No exclusion criteria provided."]).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
      </div>
      <div class="research-plan-preview-actions">
        <button class="btn btn-secondary btn-sm research-plan-details-btn" type="button" data-research-plan-action="details">Details</button>
        <button class="btn btn-primary btn-sm research-plan-execute-btn" type="button" data-research-plan-action="execute">Execute</button>
        <span>Runs the generated queries, deduplicates candidates, then screens title and abstract against the plan.</span>
      </div>
    </div>
  `;
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
  if (item.role === "user") return "";
  const liveThinking = item.pending ? item.liveThinking || "" : "";
  const thinkingText = item.pending ? liveThinking : item.thinking || "";
  const pendingLabel = item.thinkingEnabled ? "Thinking" : "Analyzing request";

  if (item.role !== "user" && thinkingText) {
    if (item.pending) {
      return `
        <div class="ai-thinking-live-panel">
          <div class="ai-thinking-live-head">
            <span class="ai-thinking-live-label">Live trace</span>
            <span class="ai-thinking-live-pill">Thinking</span>
          </div>
          <pre class="ai-thinking-live-text">${escapeHtml(thinkingText)}</pre>
        </div>
      `;
    }
    return `
      <div class="ai-thinking-block" data-think-idx="${item.id || ""}">
        <button class="ai-thinking-toggle" type="button" onclick="this.closest('.ai-thinking-block').classList.toggle('is-open')">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a7 7 0 0 1 7 7c0 2.4-1.2 4.5-3 5.7V17a2 2 0 0 1-2 2h-4a2 2 0 0 1-2-2v-2.3C6.2 13.5 5 11.4 5 9a7 7 0 0 1 7-7z"/></svg>
          <span>Reasoning trace</span>
          <svg class="ai-thinking-chevron" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
        </button>
        <div class="ai-thinking-body">
          <pre class="ai-thinking-text">${escapeHtml(thinkingText)}</pre>
        </div>
      </div>
    `;
  }

  if (item.pending && !item.text) {
    return `
      <div class="ai-thinking-live">
        <svg class="ai-thinking-live-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a7 7 0 0 1 7 7c0 2.4-1.2 4.5-3 5.7V17a2 2 0 0 1-2 2h-4a2 2 0 0 1-2-2v-2.3C6.2 13.5 5 11.4 5 9a7 7 0 0 1 7-7z"/></svg>
        <span>${pendingLabel}</span>
        <span class="ai-thinking-dots"><span></span><span></span><span></span></span>
      </div>
    `;
  }

  return "";
}

function assistantActionsMarkup(item) {
  return item.role !== "user" && item.actions?.length
    ? `<div class="ai-action-list">${item.actions.map((act, actionIndex) => act.name === "create_research_plan" && act.status === "success"
        ? researchPlanActionMarkup(act, item.id || "", actionIndex)
        : `
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

function scrollAssistantThinkingToBottom(root = els.assistantMessages) {
  if (!root) return;
  root.querySelectorAll(".ai-thinking-live-text").forEach((node) => {
    node.scrollTop = node.scrollHeight;
  });
}

function scrollAssistantMessagesToBottom() {
  if (!els.assistantMessages) return;
  scrollAssistantThinkingToBottom();
  els.assistantMessages.scrollTop = els.assistantMessages.scrollHeight;
  requestAnimationFrame(() => {
    if (els.assistantMessages) {
      scrollAssistantThinkingToBottom();
      els.assistantMessages.scrollTop = els.assistantMessages.scrollHeight;
    }
  });
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
  bindResearchPlanPreviewEvents(node);
  if (message.pending) {
    scrollAssistantThinkingToBottom(node);
  }
}

function scheduleAssistantMessageUpdate(message) {
  if (!message) return;
  if (!message.id) message.id = generateAssistantMessageId();
  assistantMessageUpdateQueue.add(message);
  if (assistantMessageUpdateFrame !== null) return;
  assistantMessageUpdateFrame = requestAnimationFrame(() => {
    assistantMessageUpdateFrame = null;
    const shouldStick = message.pending || assistantShouldStickToBottom();
    assistantMessageUpdateQueue.forEach((item) => updateAssistantMessageNode(item));
    assistantMessageUpdateQueue.clear();
    if (shouldStick) {
      scrollAssistantMessagesToBottom();
    }
  });
}

function assistantEmptyStateMarkup() {
  const emptyTitle = state.assistantMode === "research_agent" ? "Research Agent Mode" : "Ready";
  const emptyCopy = state.assistantMode === "research_agent"
    ? "Send a research topic to create the first structured plan."
    : "Start a new chat or open a recent one from history.";
  return `
    <div class="native-assistant-empty">
      <div class="native-assistant-empty-icon" aria-hidden="true">
        <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
          <path d="M9.5 4.5c1.7-1.3 3.8-1.3 5.5 0 .9.7 1.5 1.8 1.7 3 .9.1 1.7.5 2.3 1.1a4 4 0 0 1 0 5.6 4 4 0 0 1-2.4 1.1 4.7 4.7 0 0 1-9.1.7A3.6 3.6 0 0 1 5 15.2a3.7 3.7 0 0 1-.7-5.1 3.6 3.6 0 0 1 2.8-1.5c.2-1.7 1-3 2.4-4.1Z" />
          <path d="M10 11h4" />
          <path d="M12 9v4" />
        </svg>
      </div>
      <div class="native-assistant-empty-title">${escapeHtml(emptyTitle)}</div>
      <div class="native-assistant-empty-copy">${escapeHtml(emptyCopy)}</div>
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
  if (hasMessages) {
    bindResearchPlanPreviewEvents(els.assistantMessages);
    scrollAssistantMessagesToBottom();
  } else {
    els.assistantMessages.scrollTop = 0;
  }
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
      state.activeQueryId = null;
      state.queryDetailId = null;
      state.selectedQueryIds = new Set();
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

async function sendAssistantMessage(options = {}) {
  const message = typeof options.message === "string"
    ? options.message.trim()
    : els.assistantInput.value.trim();
  const displayMessage = typeof options.displayMessage === "string"
    ? options.displayMessage.trim()
    : message;
  if (!message) return;
  if (runtime.assistantModelLoading) {
    trackAppEvent("error", "assistant_model_loading_blocked", "Assistant model is still loading.", {
      project_id: state.projectId || "",
      model: runtime.assistantModelLoadingTarget || runtime.assistantModel,
    });
    pushAssistantMessage({
      role: "assistant",
      text: "Assistant error: model is still loading.",
    });
    return;
  }
  if (!isLocalAssistantModel(runtime.assistantModel) && !runtime.apiKey) {
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
  setAssistantSendButtonStreaming(true);

  pushAssistantMessage({ role: "user", text: displayMessage || message });
  const pendingMessage = pushAssistantMessage({
    role: "assistant",
    text: "",
    pending: true,
    actions: [],
    liveThinking: "",
    thinkingEnabled: assistantThinkingLevelForRequest() !== "off",
  });
  let searchAppliedDuringStream = false;
  const showLocalRequestLoading = isLocalAssistantModel(runtime.assistantModel);
  if (showLocalRequestLoading) {
    setAssistantModelLoading(true, runtime.assistantModel);
  }
  const clearLocalRequestLoading = () => {
    if (showLocalRequestLoading && runtime.assistantModelLoading) {
      setAssistantModelLoading(false);
      updateAssistantModelUI();
    }
  };
  if (!options.preserveComposer) {
    els.assistantInput.value = "";
    autoResizeTextarea(els.assistantInput);
  }

  try {
    const isResearchAgentRequest = state.assistantMode === "research_agent";
    await streamJsonEvents(
      "/assistant/chat/stream",
      {
        method: "POST",
        signal: controller.signal,
        idleTimeoutMs: isResearchAgentRequest ? 180000 : 45000,
        responseTimeoutMs: isResearchAgentRequest ? 30000 : 20000,
        body: JSON.stringify({
          api_key: isLocalAssistantModel(runtime.assistantModel) ? "" : runtime.apiKey,
          message,
          model: runtime.assistantModel,
          mode: state.assistantMode === "research_agent" ? "research_agent" : "fast",
          thread_id: state.assistantThreadId,
          thinking_level: assistantThinkingLevelForRequest(),
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
          clearLocalRequestLoading();
          pendingMessage.liveThinking = `${pendingMessage.liveThinking || ""}${event.text || ""}`;
          scheduleAssistantMessageUpdate(pendingMessage);
          return;
        }
        if (event.type === "answer_delta") {
          clearLocalRequestLoading();
          pendingMessage.text = `${pendingMessage.text || ""}${event.text || ""}`;
          scheduleAssistantMessageUpdate(pendingMessage);
          return;
        }
        if (event.type === "tool_call") {
          clearLocalRequestLoading();
          pendingMessage.actions = upsertAssistantAction(
            pendingMessage.actions,
            event.action || {},
            event.call_id,
          );
          scheduleAssistantMessageUpdate(pendingMessage);
          return;
        }
        if (event.type === "tool_result") {
          clearLocalRequestLoading();
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
          clearLocalRequestLoading();
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
          clearLocalRequestLoading();
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
    const stoppedByUser = controller.signal.aborted;
    pendingMessage.text = stoppedByUser
      ? (pendingMessage.text || "Stopped.")
      : `Assistant error: ${error.message || "Unknown error."}`;
    if (stoppedByUser) {
      pendingMessage.meta = "Stopped by user.";
    } else {
      trackAppEvent("error", "assistant_stream_failed", error.message || "Unknown assistant error.", {
        project_id: state.projectId || "",
        model: runtime.assistantModel,
      });
    }
    scheduleAssistantMessageUpdate(pendingMessage);
    syncCurrentSession();
  } finally {
    clearLocalRequestLoading();
    if (state.assistantStreamAbort === controller) {
      state.assistantStreamAbort = null;
      setAssistantSendButtonStreaming(false);
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
  try {
    await loadOllamaSettings();
  } catch (_error) {
    applyOllamaValues({
      ollama_base_url: runtime.ollamaBaseUrl || "http://localhost:11434",
      ollama_model: runtime.ollamaModel || "",
      connected: false,
      models: [],
      error: "Ollama settings could not be loaded.",
    });
  }
  try {
    await loadLlamaCppSettings();
  } catch (_error) {
    applyLlamaCppValues({
      llamacpp_base_url: runtime.llamacppBaseUrl || "http://localhost:8098",
      llamacpp_model: runtime.llamacppModel || "local",
      connected: false,
      models: [],
      error: "llama.cpp settings could not be loaded.",
    });
  }
}

function bindEvents() {
  els.searchBtn.addEventListener("click", async () => {
    try {
      await runSearch();
    } catch (error) {
      trackAppEvent("error", "literature_search_failed", error.message || "Literature search failed.", {
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
      trackAppEvent("error", "sidebar_literature_search_failed", error.message || "Sidebar literature search failed.", {
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
    if (state.assistantStreamAbort) {
      state.assistantStreamAbort.abort(new Error("Stopped by user."));
      setAssistantSendButtonStreaming(false);
      return;
    }
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
  els.tableFilterBtn?.addEventListener("click", () => {
    setTableFilterOpen(true);
  });
  els.tableFilterOverlay?.addEventListener("click", () => {
    setTableFilterOpen(false);
  });
  els.tableFilterClose?.addEventListener("click", () => {
    setTableFilterOpen(false);
  });
  els.tableFilterClear?.addEventListener("click", () => {
    state.tableFilters = emptyTableFilters();
    applyArticleFilters();
    renderMeta(state.lastPubmedResponse?.meta || null);
    renderResults();
    renderTableFilterPopup();
  });
  els.tableFilterApply?.addEventListener("click", () => {
    applyTableFiltersFromPopup();
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
  els.sidebarOpenModelSettingsBtn?.addEventListener("click", async () => {
    setModelSettingsDialogOpen(true);
    await loadApiKeys().catch(() => {});
    await loadOllamaSettings().catch(() => {});
    await loadLlamaCppSettings().catch(() => {});
    renderSettingsPanel();
  });
  els.modelSettingsOverlay?.addEventListener("click", () => {
    setModelSettingsDialogOpen(false);
  });
  els.modelSettingsClose?.addEventListener("click", () => {
    setModelSettingsDialogOpen(false);
  });
  els.assistantDraftBtn?.addEventListener("click", () => {
    setAssistantModeMenuOpen(els.assistantModeMenu?.hidden);
  });
  els.assistantNormalModeBtn?.addEventListener("click", startNormalMode);
  els.assistantResearchModeBtn?.addEventListener("click", startResearchAgentMode);
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (els.assistantModeMenu && !els.assistantModeMenu.hidden) {
      setAssistantModeMenuOpen(false);
      return;
    }
    if (els.modelSettingsPopup && !els.modelSettingsPopup.hidden) {
      setModelSettingsDialogOpen(false);
      return;
    }
    if (els.apiKeysPopup && !els.apiKeysPopup.hidden) {
      setApiKeysDialogOpen(false);
    }
  });
  els.apiKeysForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    await saveApiKeys({
      assistant_api_key: els.assistantApiKeyInput?.value || "",
      ncbi_api_key: els.ncbiApiKeyInput?.value || "",
      openalex_api_key: els.openalexApiKeyInput?.value || "",
      core_api_key: els.coreApiKeyInput?.value || "",
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
  els.aiPrimarySearchResourceInput?.addEventListener("change", async () => {
    const nextValue = normalizeSearchResource(els.aiPrimarySearchResourceInput?.value, "pubmed");
    if (els.aiPrimarySearchResourceInput) els.aiPrimarySearchResourceInput.disabled = true;
    try {
      runtime.aiPrimarySearchResource = nextValue;
      await saveApiKeys({ ai_primary_search_resource: nextValue }, { closeDialog: false });
      trackAppEvent("info", "ai_primary_search_resource_updated", "AI primary search resource updated.", {
        ai_primary_search_resource: nextValue,
      });
    } catch (error) {
      renderSettingsPanel();
      trackAppEvent("error", "ai_primary_search_resource_failed", error.message || "AI primary search resource could not be saved.", {
        ai_primary_search_resource: nextValue,
      });
    } finally {
      if (els.aiPrimarySearchResourceInput) els.aiPrimarySearchResourceInput.disabled = false;
    }
  });
  els.pdfDownloaderModeInput?.addEventListener("change", async () => {
    const nextValue = normalizePdfDownloaderMode(els.pdfDownloaderModeInput?.value, "pdf_xml");
    if (els.pdfDownloaderModeInput) els.pdfDownloaderModeInput.disabled = true;
    try {
      runtime.pdfDownloaderMode = nextValue;
      await saveApiKeys({ pdf_downloader_mode: nextValue }, { closeDialog: false });
      trackAppEvent("info", "pdf_downloader_mode_updated", "PDF downloader mode updated.", {
        pdf_downloader_mode: nextValue,
      });
    } catch (error) {
      renderSettingsPanel();
      trackAppEvent("error", "pdf_downloader_mode_failed", error.message || "PDF downloader mode could not be saved.", {
        pdf_downloader_mode: nextValue,
      });
    } finally {
      if (els.pdfDownloaderModeInput) els.pdfDownloaderModeInput.disabled = false;
    }
  });
  els.ollamaBaseUrlInput?.addEventListener("input", () => {
    runtime.ollamaBaseUrl = String(els.ollamaBaseUrlInput?.value || "").trim() || "http://localhost:11434";
  });
  els.assistantOllamaThinkingBtn?.addEventListener("click", () => {
    const next = els.assistantOllamaThinkingMenu.hidden;
    els.assistantOllamaThinkingMenu.hidden = !next;
    els.assistantOllamaThinkingBtn.setAttribute("aria-expanded", next ? "true" : "false");
    els.thinkMenu.hidden = true;
    els.thinkToggleBtn.setAttribute("aria-expanded", "false");
  });
  els.assistantOllamaThinkingMenu?.addEventListener("click", async (event) => {
    const item = event.target.closest(".think-menu-item[data-ollama-think]");
    if (!item) return;
    const nextValue = normalizeOllamaThinkingLevel(item.dataset.ollamaThink, "off");
    const previousValue = runtime.ollamaThinkingLevel || "off";
    runtime.ollamaThinkingLevel = nextValue;
    if (els.assistantOllamaThinkingMenu) els.assistantOllamaThinkingMenu.hidden = true;
    if (els.assistantOllamaThinkingBtn) els.assistantOllamaThinkingBtn.setAttribute("aria-expanded", "false");
    try {
      await saveOllamaSettings({ ollama_thinking_level: nextValue });
      trackAppEvent("info", "ollama_thinking_level_updated", "Ollama thinking level updated from the native UI.", {
        ollama_thinking_level: nextValue,
      });
    } catch (error) {
      runtime.ollamaThinkingLevel = previousValue;
      renderSettingsPanel();
      trackAppEvent("error", "ollama_thinking_level_failed", error.message || "Ollama thinking level could not be saved.", {
        ollama_thinking_level: nextValue,
      });
    } finally {
      updateOllamaThinkingControlUI();
    }
  });
  els.settingsAssistantApiKeyInput?.addEventListener("input", () => {
    runtime.apiKey = String(els.settingsAssistantApiKeyInput?.value || "").trim();
    if (els.settingsAssistantApiKeyStatus) {
      els.settingsAssistantApiKeyStatus.textContent = runtime.apiKey
        ? "Gemini cloud models will use the saved API key."
        : "Add a Gemini API key to unlock the cloud models.";
    }
  });
  els.settingsAssistantApiKeySaveBtn?.addEventListener("click", async () => {
    runtime.apiKey = String(els.settingsAssistantApiKeyInput?.value || "").trim();
    if (els.settingsAssistantApiKeySaveBtn) els.settingsAssistantApiKeySaveBtn.disabled = true;
    try {
      await saveApiKeys({ assistant_api_key: runtime.apiKey }, { closeDialog: false });
      trackAppEvent("info", "assistant_api_key_saved_ui", "Gemini API key updated from the native UI.", {
        has_assistant_api_key: Boolean(runtime.apiKey),
      });
    } catch (error) {
      renderSettingsPanel();
      trackAppEvent("error", "assistant_api_key_save_failed", error.message || "Gemini API key could not be saved.", {
        has_assistant_api_key: Boolean(runtime.apiKey),
      });
    } finally {
      if (els.settingsAssistantApiKeySaveBtn) els.settingsAssistantApiKeySaveBtn.disabled = false;
    }
  });
  els.ollamaSaveBtn?.addEventListener("click", async () => {
    const nextBaseUrl = String(els.ollamaBaseUrlInput?.value || "").trim() || "http://localhost:11434";
    runtime.ollamaBaseUrl = nextBaseUrl;
    if (els.ollamaSaveBtn) els.ollamaSaveBtn.disabled = true;
    try {
      await saveOllamaSettings({
        ollama_base_url: nextBaseUrl,
        ollama_model: runtime.ollamaModel,
        ollama_thinking_level: normalizeOllamaThinkingLevel(runtime.ollamaThinkingLevel, "off"),
      });
      trackAppEvent("info", "ollama_saved_ui", "Ollama settings updated from the native UI.", {
        ollama_base_url: nextBaseUrl,
        ollama_model: runtime.ollamaModel,
        ollama_thinking_level: normalizeOllamaThinkingLevel(runtime.ollamaThinkingLevel, "off"),
        connected: Boolean(runtime.ollamaConnected),
      });
    } catch (error) {
      renderSettingsPanel();
      trackAppEvent("error", "ollama_save_failed", error.message || "Ollama settings could not be saved.", {
        ollama_base_url: nextBaseUrl,
        ollama_model: runtime.ollamaModel,
      });
    } finally {
      if (els.ollamaSaveBtn) els.ollamaSaveBtn.disabled = false;
    }
  });
  els.ollamaConnectBtn?.addEventListener("click", async () => {
    try {
      await connectOllamaSettings();
    } catch (_error) {
      // The error is already reported via the app event log and settings panel.
    }
  });
  const syncLlamaCppInputs = () => {
    runtime.llamacppBaseUrl = normalizeLlamaCppBaseUrl(els.llamacppBaseUrlInput?.value, "http://localhost:8098");
    runtime.llamacppModel = String(els.llamacppModelInput?.value || "local").trim() || "local";
    runtime.llamacppExecutable = String(els.llamacppExecutableInput?.value || "").trim();
    runtime.llamacppModelPath = String(els.llamacppModelPathInput?.value || "").trim();
    runtime.llamacppLibraryPath = String(els.llamacppLibraryPathInput?.value || "").trim();
    runtime.llamacppServerArgs = buildLlamaCppArgsFromControls();
    if (els.llamacppServerArgsInput) els.llamacppServerArgsInput.value = runtime.llamacppServerArgs;
  };
  [
    els.llamacppBaseUrlInput,
    els.llamacppModelInput,
    els.llamacppExecutableInput,
    els.llamacppModelPathInput,
    els.llamacppLibraryPathInput,
  ].forEach((input) => {
    input?.addEventListener("input", syncLlamaCppInputs);
  });
  els.llamacppServerArgsInput?.addEventListener("input", () => {
    runtime.llamacppServerArgs = String(els.llamacppServerArgsInput?.value || "").trim();
    const parsed = parseLlamaCppArgs(runtime.llamacppServerArgs);
    if (els.llamacppProfileInput) els.llamacppProfileInput.value = parsed.profile;
    if (els.llamacppContextInput) els.llamacppContextInput.value = parsed.context;
    if (els.llamacppBatchInput) els.llamacppBatchInput.value = parsed.batch;
    if (els.llamacppUbatchInput) els.llamacppUbatchInput.value = parsed.ubatch;
    if (els.llamacppCpuMoeInput) els.llamacppCpuMoeInput.value = parsed.cpuMoe;
    if (els.llamacppCacheKInput) els.llamacppCacheKInput.value = parsed.cacheK;
    if (els.llamacppCacheVInput) els.llamacppCacheVInput.value = parsed.cacheV;
    if (els.llamacppCacheRamInput) els.llamacppCacheRamInput.value = parsed.cacheRam;
    if (els.llamacppReasoningInput) els.llamacppReasoningInput.value = parsed.reasoning;
    if (els.llamacppReasoningBudgetInput) els.llamacppReasoningBudgetInput.value = parsed.reasoningBudget;
    if (els.llamacppFitTargetInput) els.llamacppFitTargetInput.value = parsed.fitTarget;
  });
  els.llamacppProfileInput?.addEventListener("change", () => {
    const profile = llamaCppProfiles[els.llamacppProfileInput?.value || ""];
    if (profile) {
      if (els.llamacppContextInput) els.llamacppContextInput.value = profile.context;
      if (els.llamacppBatchInput) els.llamacppBatchInput.value = profile.batch;
      if (els.llamacppUbatchInput) els.llamacppUbatchInput.value = profile.ubatch;
      if (els.llamacppCpuMoeInput) els.llamacppCpuMoeInput.value = profile.cpuMoe;
      if (els.llamacppCacheKInput) els.llamacppCacheKInput.value = profile.cacheK;
      if (els.llamacppCacheVInput) els.llamacppCacheVInput.value = profile.cacheV;
      if (els.llamacppCacheRamInput) els.llamacppCacheRamInput.value = profile.cacheRam;
      if (els.llamacppReasoningInput) els.llamacppReasoningInput.value = profile.reasoning;
      if (els.llamacppReasoningBudgetInput) els.llamacppReasoningBudgetInput.value = profile.reasoningBudget;
      if (els.llamacppFitTargetInput) els.llamacppFitTargetInput.value = profile.fitTarget;
    }
    syncLlamaCppInputs();
    renderSettingsPanel();
  });
  [
    els.llamacppContextInput,
    els.llamacppBatchInput,
    els.llamacppUbatchInput,
    els.llamacppCpuMoeInput,
    els.llamacppCacheKInput,
    els.llamacppCacheVInput,
    els.llamacppCacheRamInput,
    els.llamacppReasoningInput,
    els.llamacppReasoningBudgetInput,
    els.llamacppFitTargetInput,
  ].forEach((input) => {
    input?.addEventListener("change", () => {
      syncLlamaCppInputs();
      if (els.llamacppProfileInput) els.llamacppProfileInput.value = parseLlamaCppArgs(runtime.llamacppServerArgs).profile;
    });
  });
  els.llamacppSaveBtn?.addEventListener("click", async () => {
    syncLlamaCppInputs();
    if (els.llamacppSaveBtn) els.llamacppSaveBtn.disabled = true;
    try {
      await saveLlamaCppSettings();
    } catch (error) {
      renderSettingsPanel();
      trackAppEvent("error", "llamacpp_save_failed", error.message || "llama.cpp settings could not be saved.", {
        llamacpp_base_url: runtime.llamacppBaseUrl,
        llamacpp_model: runtime.llamacppModel,
      });
    } finally {
      if (els.llamacppSaveBtn) els.llamacppSaveBtn.disabled = false;
    }
  });
  els.llamacppConnectBtn?.addEventListener("click", async () => {
    syncLlamaCppInputs();
    if (els.llamacppConnectBtn) els.llamacppConnectBtn.disabled = true;
    try {
      await saveLlamaCppSettings({ warmup: false });
    } catch (error) {
      renderSettingsPanel();
      trackAppEvent("error", "llamacpp_connect_failed", error.message || "llama.cpp connection failed.", {
        llamacpp_base_url: runtime.llamacppBaseUrl,
      });
    } finally {
      if (els.llamacppConnectBtn) els.llamacppConnectBtn.disabled = false;
    }
  });
  els.llamacppStartBtn?.addEventListener("click", async () => {
    syncLlamaCppInputs();
    if (els.llamacppStartBtn) els.llamacppStartBtn.disabled = true;
    try {
      await saveLlamaCppSettings({ start: true, warmup: true });
    } catch (error) {
      renderSettingsPanel();
      trackAppEvent("error", "llamacpp_start_failed", error.message || "llama.cpp server could not be started.", {
        llamacpp_base_url: runtime.llamacppBaseUrl,
        model_path_configured: Boolean(runtime.llamacppModelPath),
      });
    } finally {
      if (els.llamacppStartBtn) els.llamacppStartBtn.disabled = false;
    }
  });
  els.availableModelsList?.addEventListener("change", (event) => {
    const input = event.target.closest('input[type="checkbox"][data-model]');
    if (!input) return;
    const model = String(input.dataset.model || "").trim();
    if (!model) return;
    const visible = Boolean(input.checked);
    setAssistantModelVisibility(model, visible);
    if (!visible && normalizeAssistantModel(runtime.assistantModel) === model) {
      runtime.assistantModel = assistantModelDefaultValue();
      localStorage.setItem(assistantModelStorageKey, runtime.assistantModel);
    }
    if (visible) {
      ensureAssistantModelVisible(model);
    }
    updateAssistantModelUI();
    updateThinkingLabel();
    renderSettingsPanel();
    trackAppEvent("info", "assistant_model_visibility_updated", "Assistant model visibility updated.", {
      assistant_model: model,
      visible,
      provider: isOllamaAssistantModel(model) ? "ollama" : (isLlamaCppAssistantModel(model) ? "llamacpp" : "gemini"),
    });
  });
  const saveFallbackToggle = async (key, value, element, eventName) => {
    if (element) element.disabled = true;
    const previous = runtime[key];
    runtime[key] = value;
    try {
      await saveApiKeys({
        pdf_unpaywall_fallback_enabled: Boolean(runtime.pdfUnpaywallFallbackEnabled),
        pdf_core_fallback_enabled: Boolean(runtime.pdfCoreFallbackEnabled),
        pdf_arxiv_fallback_enabled: Boolean(runtime.pdfArxivFallbackEnabled),
      }, { closeDialog: false });
      trackAppEvent("info", eventName, "PDF fallback setting updated.", {
        pdf_unpaywall_fallback_enabled: Boolean(runtime.pdfUnpaywallFallbackEnabled),
        pdf_core_fallback_enabled: Boolean(runtime.pdfCoreFallbackEnabled),
        pdf_arxiv_fallback_enabled: Boolean(runtime.pdfArxivFallbackEnabled),
      });
    } catch (error) {
      runtime[key] = previous;
      renderSettingsPanel();
      trackAppEvent("error", `${eventName}_failed`, error.message || "PDF fallback setting could not be saved.", {});
    } finally {
      if (element) element.disabled = false;
    }
  };
  els.pdfUnpaywallFallbackToggle?.addEventListener("change", async () => {
    await saveFallbackToggle(
      "pdfUnpaywallFallbackEnabled",
      Boolean(els.pdfUnpaywallFallbackToggle?.checked),
      els.pdfUnpaywallFallbackToggle,
      "pdf_unpaywall_fallback_updated",
    );
  });
  els.pdfCoreFallbackToggle?.addEventListener("change", async () => {
    await saveFallbackToggle(
      "pdfCoreFallbackEnabled",
      Boolean(els.pdfCoreFallbackToggle?.checked),
      els.pdfCoreFallbackToggle,
      "pdf_core_fallback_updated",
    );
  });
  els.pdfArxivFallbackToggle?.addEventListener("change", async () => {
    await saveFallbackToggle(
      "pdfArxivFallbackEnabled",
      Boolean(els.pdfArxivFallbackToggle?.checked),
      els.pdfArxivFallbackToggle,
      "pdf_arxiv_fallback_updated",
    );
  });
  els.downloadWorkerCountInput?.addEventListener("change", () => {
    const nextValue = clampDownloadWorkers(els.downloadWorkerCountInput?.value);
    runtime.downloadWorkers = nextValue;
    localStorage.setItem(downloadWorkersStorageKey, String(nextValue));
    renderSettingsPanel();
    trackAppEvent("info", "download_worker_setting_updated", "Batch download worker count updated.", {
      download_workers: nextValue,
    });
  });
  els.sidebarQuickSearchResource?.addEventListener("change", () => {
    const nextValue = normalizeSearchResource(els.sidebarQuickSearchResource?.value, "pubmed");
    runtime.searchResource = nextValue;
    localStorage.setItem(searchResourceStorageKey, nextValue);
    if (els.searchResource) els.searchResource.value = nextValue;
    syncSidebarQuickControls();
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
  els.assistantModelMenu?.addEventListener("click", (event) => {
    const item = event.target.closest(".assistant-model-item");
    if (!item) return;
    const nextModel = normalizeAssistantModel(item.dataset.model);
    els.assistantModelMenu.hidden = true;
    els.assistantModelBtn.setAttribute("aria-expanded", "false");
    void selectAssistantModel(nextModel);
  });

  els.thinkToggleBtn.addEventListener("click", () => {
    const next = els.thinkMenu.hidden;
    els.thinkMenu.hidden = !next;
    els.thinkToggleBtn.setAttribute("aria-expanded", next ? "true" : "false");
    els.assistantModelMenu.hidden = true;
    els.assistantModelBtn.setAttribute("aria-expanded", "false");
  });
  document.querySelectorAll(".think-menu-item[data-level]").forEach((item) => {
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
    if (!event.target.closest("#assistantDraftBtn") && !event.target.closest("#assistantModeMenu")) {
      setAssistantModeMenuOpen(false);
    }
    if (!event.target.closest("#assistantOllamaThinkingWrap")) {
      els.assistantOllamaThinkingMenu.hidden = true;
      els.assistantOllamaThinkingBtn.setAttribute("aria-expanded", "false");
    }
    if (!event.target.closest("#thinkToggleWrap")) {
      els.thinkMenu.hidden = true;
      els.thinkToggleBtn.setAttribute("aria-expanded", "false");
    }
  });

  els.detailPopupOverlay.addEventListener("click", closeDetailPopup);
  els.detailPopupClose.addEventListener("click", closeDetailPopup);
  els.documentViewerBackBtn?.addEventListener("click", () => {
    closeDocumentViewer();
  });
  els.documentViewerPdfBtn?.addEventListener("click", () => {
    void switchDocumentViewerKind("pdf");
  });
  els.documentViewerXmlBtn?.addEventListener("click", () => {
    void switchDocumentViewerKind("xml");
  });
  els.documentViewerReloadBtn?.addEventListener("click", () => {
    void renderDocumentViewer();
  });
  els.documentViewerRawBtn?.addEventListener("click", () => {
    const next = state.documentViewerContentMode !== "raw";
    setDocumentViewerRawMode(next);
  });

  document.addEventListener("click", (event) => {
    const fileButton = event.target.closest(".file-open-btn");
    if (fileButton) {
      event.preventDefault();
      event.stopPropagation();
      void openDocumentViewer(fileButton.dataset.filePath, {
        title: fileButton.dataset.fileTitle || "Document",
      });
      return;
    }
    const downloadItem = event.target.closest(".native-workspace-download-item");
    if (downloadItem) {
      event.preventDefault();
      void openDocumentViewer(downloadItem.dataset.filePath, {
        title: downloadItem.dataset.fileTitle || "Document",
        artifactPaths: artifactPathsFromValue(downloadItem.dataset.artifactPaths),
      });
    }
  });
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
  setAssistantMode(state.assistantMode);
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
