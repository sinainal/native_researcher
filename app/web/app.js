const state = {
  allArticles: [],
  articles: [],
  selectedIds: new Set(),
  sortKey: null,
  sortDirection: "asc",
  lastSearchPayload: null,
  lastPubmedResponse: null,
  lastOutput: {},
  processedPreview: null,
  detailArticleId: null,
  detailPopup: null,
  downloadabilityById: {},
  citationRunId: 0,
  assistantThreadId: localStorage.getItem("researcher2_helper_thread_id") || null,
  assistantMessages: [],
  assistantOpen: false,
  assistantMode: localStorage.getItem("researcher2_assistant_mode") || "fast",
  thinkingLevel: localStorage.getItem("researcher2_thinking_level") || "off",
  assistantStreamAbort: null,
  assistantStreamSeq: 0,
};

const els = {
  healthStatus: document.getElementById("healthStatus"),
  articleCount: document.getElementById("articleCount"),
  selectedCount: document.getElementById("selectedCount"),
  articleInfo: document.getElementById("articleInfo"),
  query: document.getElementById("query"),
  yearStart: document.getElementById("yearStart"),
  yearEnd: document.getElementById("yearEnd"),
  maxResults: document.getElementById("maxResults"),
  batchSize: document.getElementById("batchSize"),
  minCite: document.getElementById("minCite"),
  articleTypeFilter: document.getElementById("articleTypeFilter"),
  downloadDir: document.getElementById("downloadDir"),
  maxDownload: document.getElementById("maxDownload"),
  searchBtn: document.getElementById("searchBtn"),
  loadJsonBtn: document.getElementById("loadJsonBtn"),
  saveJsonBtn: document.getElementById("saveJsonBtn"),
  downloadArticlesBtn: document.getElementById("downloadArticlesBtn"),
  resolvePdfBtn: document.getElementById("resolvePdfBtn"),
  jsonFileInput: document.getElementById("jsonFileInput"),
  apiKey: document.getElementById("apiKey"),
  saveKeyBtn: document.getElementById("saveKeyBtn"),
  modelSelect: document.getElementById("modelSelect"),
  assistantModelBtn: document.getElementById("assistantModelBtn"),
  assistantModelLabel: document.getElementById("assistantModelLabel"),
  assistantModelMenu: document.getElementById("assistantModelMenu"),
  assistantModelWrap: document.getElementById("assistantModelWrap"),
  assistantModelItems: document.querySelectorAll(".assistant-model-item"),
  modelInfo: document.getElementById("modelInfo"),
  dynamicBatch: document.getElementById("dynamicBatch"),
  maxTokens: document.getElementById("maxTokens"),
  llmBatch: document.getElementById("llmBatch"),
  retryCount: document.getElementById("retryCount"),
  promptBox: document.getElementById("promptBox"),
  tokenInfo: document.getElementById("tokenInfo"),
  batchInfo: document.getElementById("batchInfo"),
  processBtn: document.getElementById("processBtn"),
  saveProcessedBtn: document.getElementById("saveProcessedBtn"),
  runAllBtn: document.getElementById("runAllBtn"),
  logBox: document.getElementById("logBox"),
  selectAllBtn: document.getElementById("selectAllBtn"),
  clearSelectionBtn: document.getElementById("clearSelectionBtn"),
  metaStrip: document.getElementById("metaStrip"),
  resultsBody: document.getElementById("resultsBody"),
  sortButtons: document.querySelectorAll(".table-sort-btn"),
  jsonBox: document.getElementById("jsonBox"),
  detailPopupOverlay: document.getElementById("detailPopupOverlay"),
  detailPopup: document.getElementById("detailPopup"),
  detailPopupEyebrow: document.getElementById("detailPopupEyebrow"),
  detailPopupTitle: document.getElementById("detailPopupTitle"),
  detailPopupMeta: document.getElementById("detailPopupMeta"),
  detailPopupBody: document.getElementById("detailPopupBody"),
  detailPopupClose: document.getElementById("detailPopupClose"),
  assistantLauncher: document.getElementById("assistantLauncher"),
  assistantOverlay: document.getElementById("assistantOverlay"),
  assistantPanel: document.getElementById("assistantPanel"),
  assistantModeButtons: document.querySelectorAll(".assistant-mode-btn"),
  assistantCloseBtn: document.getElementById("assistantCloseBtn"),
  assistantMessages: document.getElementById("assistantMessages"),
  assistantInput: document.getElementById("assistantInput"),
  assistantSendBtn: document.getElementById("assistantSendBtn"),
  assistantResetBtn: document.getElementById("assistantResetBtn"),
  thinkToggleBtn: document.getElementById("thinkToggleBtn"),
  thinkLabel: document.getElementById("thinkLabel"),
  thinkMenu: document.getElementById("thinkMenu"),
  thinkToggleWrap: document.getElementById("thinkToggleWrap"),
};

const modelInfoMap = {
  "Gemini 3.1 Pro": "En yuksek kalite odakli 3.1 Pro preview modeli.",
  "Gemini 3 Flash": "Hiz, olcek ve genel amacli kullanim icin dengeli Gemini 3 Flash preview modeli.",
  "Gemini 3.1 Flash Lite": "Dusuk gecikme ve dusuk maliyetli gorevler icin Gemini 3.1 Flash-Lite preview modeli.",
  "Gemini 2.5 Pro": "Yuksek kalite ve daha kararlı reasoning icin Gemini 2.5 Pro modeli.",
  "Gemini 2.5 Flash": "Genel hiz ve maliyet dengesi icin Gemini 2.5 Flash modeli.",
  "Gemini 2.5 Flash Lite": "Dusuk gecikme ve hafif gorevler icin Gemini 2.5 Flash-Lite modeli.",
};

const assistantModelLabelMap = {
  "Gemini 3.1 Pro": "Gemini 3.1 Pro",
  "Gemini 3 Flash": "Gemini 3 Flash",
  "Gemini 3.1 Flash Lite": "Gemini 3.1 Flash Lite",
  "Gemini 2.5 Pro": "Gemini 2.5 Pro",
  "Gemini 2.5 Flash": "Gemini 2.5 Flash",
  "Gemini 2.5 Flash Lite": "Gemini 2.5 Flash Lite",
};

let assistantRenderScheduled = false;
let assistantLastMarkup = null;
let assistantMessageIdSeed = 0;
let assistantPatchScheduled = false;
const assistantDirtyMessages = new Set();

const downloadabilityLabels = {
  idle: "Yok",
  loading: "İndiriliyor",
  high: "Hazır",
  medium: "Hazır",
  low: "Hazır",
  blocked: "Yok",
  unavailable: "Yok",
  downloaded: "İndirildi",
  failed: "Başarısız",
};

function isDownloadReadyStatus(status) {
  return ["high", "medium", "low", "downloaded"].includes(status);
}

function buildFileOpenUrl(filePath) {
  return `/pdf/file?path=${encodeURIComponent(filePath)}`;
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

function downloadabilityDisplay(articleId) {
  const info = getDownloadability(articleId);
  if (info.status === "loading") {
    return { tone: "pending", text: "İndiriliyor" };
  }
  if (info.status === "downloaded") {
    return { tone: "ready", text: "Hazır" };
  }
  if (isDownloadReadyStatus(info.status)) {
    return { tone: "ready", text: "Hazır" };
  }
  return { tone: "blocked", text: "Yok" };
}

function log(message) {
  const timestamp = new Date().toLocaleTimeString("tr-TR", { hour12: false });
  const existing = els.logBox.textContent.trim();
  els.logBox.textContent = existing ? `${existing}\n${timestamp} - ${message}` : `${timestamp} - ${message}`;
  els.logBox.scrollTop = els.logBox.scrollHeight;
}

function summarizeAssistantLogEntry(entry) {
  const event = entry.event || "assistant_event";
  if (event === "assistant_stream_start" || event === "assistant_chat_start") {
    return `Assistant request started | mode=${entry.mode || "-"} | model=${entry.model || "-"} | msg=${entry.message || ""}`;
  }
  if (event === "assistant_tool_call") {
    return `Assistant tool call | ${entry.name || "-"} | ${JSON.stringify(entry.args || {})}`;
  }
  if (event === "assistant_tool_result") {
    const action = entry.action || {};
    return `Assistant tool result | ${action.name || "-"} | status=${action.status || "-"} | ${JSON.stringify(action.details || {})}`;
  }
  if (event === "assistant_stream_final" || event === "assistant_chat_final") {
    return `Assistant completed | used_ids=${(entry.used_article_ids || []).join(",") || "-"} | answer=${String(entry.answer || "").slice(0, 180)}`;
  }
  if (event === "assistant_stream_error" || event === "assistant_chat_error") {
    return `Assistant error | ${entry.error || "-"}`;
  }
  return `Assistant ${event} | ${JSON.stringify(entry)}`;
}

async function loadAssistantHistory() {
  try {
    await fetchJson("/assistant/history?limit=40");
  } catch (_error) {
    return;
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function mergeAssistantErrorText(existingText, message) {
  const base = String(existingText || "").trim();
  if (!base) return message;
  if (base.includes(message)) return base;
  return `${base}\n\n${message}`;
}

function setJson(data) {
  state.lastOutput = data;
  els.jsonBox.textContent = JSON.stringify(data, null, 2);
}

function estimatedTokenCount(text) {
  if (!text) return 0;
  return Math.floor(text.length / 4) + 1;
}

function totalArticleTokens(articles) {
  return articles.reduce((sum, article) => sum + estimatedTokenCount(article.abstract || ""), 0);
}

function normalizedNumber(node, fallback) {
  const value = Number(node.value);
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

function autoResizeTextarea(node) {
  if (!node) return;
  node.style.height = "0px";
  node.style.height = `${node.scrollHeight}px`;
}

function selectedArticles() {
  return state.articles.filter((article) => state.selectedIds.has(article.id));
}

function activeArticles() {
  return selectedArticles().length ? selectedArticles() : state.articles;
}

function estimatedLlmBatchSize() {
  const manualBatch = normalizedNumber(els.llmBatch, 20);
  if (!els.dynamicBatch.checked || !state.articles.length) {
    return manualBatch;
  }

  const averageTokens = Math.max(1, Math.ceil(totalArticleTokens(state.articles) / state.articles.length));
  const tokenLimit = normalizedNumber(els.maxTokens, 750);
  return Math.max(1, Math.floor(tokenLimit / averageTokens));
}

function updateCounters() {
  const selectedCount = state.selectedIds.size;
  els.articleCount.textContent = String(state.articles.length);
  els.selectedCount.textContent = String(selectedCount);
  if (els.articleInfo) {
    els.articleInfo.textContent = `Islenen Makale Sayisi: ${state.articles.length}`;
  }
  els.saveJsonBtn.disabled = state.articles.length === 0;
  els.downloadArticlesBtn.disabled = state.articles.length === 0;
  els.selectAllBtn.disabled = state.articles.length === 0;
  els.clearSelectionBtn.disabled = selectedCount === 0;
  els.resolvePdfBtn.disabled = selectedCount !== 1;
  els.saveProcessedBtn.disabled = !state.processedPreview;
}

function updateTokenInfo() {
  const articles = activeArticles();
  const total = totalArticleTokens(articles);
  const average = articles.length ? (total / articles.length).toFixed(1) : "0";
  const promptTokens = estimatedTokenCount(els.promptBox.value);
  const batchSize = estimatedLlmBatchSize();
  const batchCount = articles.length ? Math.ceil(articles.length / batchSize) : 0;
  const scope = selectedArticles().length ? "Secili" : "Toplam";

  els.tokenInfo.textContent = `${scope} token tahmini: ${total.toLocaleString("tr-TR")} | Makale basina ort. ${average} | Prompt: ${promptTokens}`;
  els.batchInfo.textContent = `LLM'e gonderilen kume sayisi: ${batchCount} | Kume boyutu: ${batchSize}`;
}

function renderMeta(meta) {
  if (!meta) {
    els.metaStrip.innerHTML = "";
    return;
  }

  const chips = [
    ["Toplam sonuc", meta.total_results_found],
    ["Cekilen", meta.fetched_results],
    ["Batch", meta.batch_size_used],
    ["Istek", meta.request_count],
    ["Sure", `${meta.elapsed_ms} ms`],
    ["Cache", meta.cache_hit ? "hit" : "miss"],
  ];

  els.metaStrip.innerHTML = chips
    .map(([label, value]) => `<span class="meta-chip">${label}: ${value}</span>`)
    .join("");
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

function compactList(items, limit = 6) {
  if (!items?.length) return "-";
  const visible = items.slice(0, limit);
  const suffix = items.length > limit ? ` +${items.length - limit}` : "";
  return `${visible.join(", ")}${suffix}`;
}

function articleTypeLabel(article) {
  return article.article_type || article.article_types?.[0] || "-";
}

function citationLabel(article) {
  if (Number.isInteger(article.citation_count)) {
    return String(article.citation_count);
  }
  return "-";
}

function parseOptionalNumber(value) {
  const parsed = Number.parseInt(String(value ?? "").trim(), 10);
  return Number.isFinite(parsed) ? parsed : null;
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

    const textCompare = String(leftValue).localeCompare(String(rightValue), "tr", {
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

function currentFilters() {
  return {
    minCite: els.minCite.value ? normalizedNumber(els.minCite, 0) : null,
    articleType: els.articleTypeFilter.value || null,
  };
}

function populateArticleTypeOptions() {
  const previousValue = els.articleTypeFilter.value || "";
  const counts = new Map();
  state.allArticles.forEach((article) => {
    const label = articleTypeLabel(article);
    if (!label || label === "-") return;
    counts.set(label, (counts.get(label) || 0) + 1);
  });

  const options = ['<option value="">Tümü</option>'];
  [...counts.entries()]
    .sort((a, b) => a[0].localeCompare(b[0], "tr"))
    .forEach(([label, count]) => {
      const selected = previousValue === label ? "selected" : "";
      options.push(`<option value="${label}" ${selected}>${label} (${count})</option>`);
    });
  els.articleTypeFilter.innerHTML = options.join("");
  if (previousValue && !counts.has(previousValue)) {
    els.articleTypeFilter.value = "";
  }
}

function applyArticleFilters() {
  const filters = currentFilters();
  const source = state.allArticles.length ? state.allArticles : state.articles;
  state.articles = source.filter((article) => {
    if (filters.articleType) {
      const normalized = filters.articleType.toLowerCase();
      const inTypes = (article.article_types || []).some((item) => item.toLowerCase().includes(normalized));
      const inPrimary = article.article_type ? article.article_type.toLowerCase().includes(normalized) : false;
      if (!inTypes && !inPrimary) {
        return false;
      }
    }
    if (filters.minCite !== null && (article.citation_count ?? -1) < filters.minCite) {
      return false;
    }
    return true;
  });
  if (state.detailArticleId && !state.articles.some((article) => article.id === state.detailArticleId)) {
    state.detailArticleId = null;
  }
  applyArticleSort();
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

function getDownloadability(articleId) {
  return state.downloadabilityById[articleId] || {
    status: "unavailable",
    label: downloadabilityLabels.unavailable,
    detail: "PMC sinyali yok.",
    openUrl: null,
  };
}

function renderDownloadabilityCell(article) {
  const display = downloadabilityDisplay(article.id);
  const info = getDownloadability(article.id);
  const canOpen = Boolean(info.openUrl);
  const disabled = display.tone !== "ready" ? "disabled" : "";
  return `
    <div class="download-action-cell">
      <span class="availability-dot-shell ${display.tone}" title="${display.text}">
        <span class="availability-dot"></span>
      </span>
      ${canOpen
        ? `<a class="btn btn-primary btn-xs file-open-btn" href="${info.openUrl}" target="_blank" rel="noreferrer">PDF</a>`
        : `<button class="btn btn-secondary btn-xs row-download-btn" data-id="${article.id}" ${disabled}>İndir</button>`}
    </div>
  `;
}

function detailMetaMarkup(article) {
  const lines = [];
  if (article.year) lines.push(`Yıl ${article.year}`);
  if (article.pmid) lines.push(`PMID ${article.pmid}`);
  if (article.doi) lines.push(`DOI ${article.doi}`);
  if (article.pmc_id) lines.push(`PMC ${article.pmc_id}`);
  return lines.map((item) => `<span class="detail-meta-chip">${item}</span>`).join("");
}

function detailMetaText(article) {
  const lines = [];
  if (article.title) lines.push(article.title);
  if (article.year) lines.push(`Yıl ${article.year}`);
  if (article.pmid) lines.push(`PMID ${article.pmid}`);
  if (article.doi) lines.push(`DOI ${article.doi}`);
  return lines.join(" • ");
}

function detailPopupPayload(article, field) {
  switch (field) {
    case "abstract":
      return {
        eyebrow: "Makale Özeti",
        title: article.title || "Abstract",
        meta: detailMetaText(article),
        body: article.abstract?.trim() || "Abstract bulunamadı.",
      };
    case "journal":
      return {
        eyebrow: "Makale Detayı",
        title: "Dergi ve Yayın",
        meta: article.title || "",
        body: [article.journal || "-", article.publication_date || "-"].join("\n"),
      };
    case "authors":
      return {
        eyebrow: "Makale Detayı",
        title: "Yazarlar",
        meta: article.title || "",
        body: article.authors?.length ? article.authors.join("\n") : "Yazar bilgisi bulunamadı.",
      };
    case "mesh":
      return {
        eyebrow: "Makale Detayı",
        title: "MeSH",
        meta: article.title || "",
        body: article.mesh_terms?.length ? article.mesh_terms.join(", ") : "MeSH bilgisi bulunamadı.",
      };
    case "keywords":
      return {
        eyebrow: "Makale Detayı",
        title: "Keywords",
        meta: article.title || "",
        body: article.keywords?.length ? article.keywords.join(", ") : "Keyword bilgisi bulunamadı.",
      };
    case "article_types":
      return {
        eyebrow: "Makale Detayı",
        title: "Makale Türleri",
        meta: article.title || "",
        body: article.article_types?.length ? article.article_types.join(", ") : "Makale türü bilgisi bulunamadı.",
      };
    case "related_articles":
      return {
        eyebrow: "Makale Detayı",
        title: "Related Articles",
        meta: article.title || "",
        body: article.related_articles?.length ? article.related_articles.join("\n") : "Bağlı makale bulunamadı.",
      };
    default:
      return {
        eyebrow: "Makale Detayı",
        title: article.title || "Detay",
        meta: detailMetaText(article),
        body: "-",
      };
  }
}

function setDetailPopupOpen(next) {
  if (!els.detailPopup || !els.detailPopupOverlay) return;
  els.detailPopup.hidden = !next;
  els.detailPopupOverlay.hidden = !next;
  els.detailPopup.classList.toggle("is-open", next);
  els.detailPopupOverlay.classList.toggle("is-open", next);
  if (next) {
    requestAnimationFrame(() => {
      els.detailPopupClose?.focus();
    });
  }
}

function closeDetailPopup() {
  state.detailPopup = null;
  setDetailPopupOpen(false);
}

function openDetailPopup(articleId, field) {
  const article = state.allArticles.find((item) => item.id === articleId) || state.articles.find((item) => item.id === articleId);
  if (!article || !els.detailPopupTitle || !els.detailPopupBody || !els.detailPopupMeta || !els.detailPopupEyebrow) return;
  const payload = detailPopupPayload(article, field);
  state.detailPopup = { articleId, field };
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
  const info = getDownloadability(article.id);
  const display = downloadabilityDisplay(article.id);
  const link = bestArticleLink(article);
  const disabled = display.tone !== "ready" ? "disabled" : "";
  return `
    <tr class="detail-row">
      <td colspan="9">
        <div class="inline-detail">
          <div class="inline-detail-top">
            <div>
              <div class="detail-kicker">Makale Özeti</div>
              <div class="detail-meta">${detailMetaMarkup(article)}</div>
            </div>
            <div class="detail-actions">
              ${link ? `<a class="detail-link" href="${link}" target="_blank" rel="noreferrer">Link</a>` : ""}
              ${info.openUrl
                ? `<a class="btn btn-primary btn-xs file-open-btn" href="${info.openUrl}" target="_blank" rel="noreferrer">PDF</a>`
                : `<button class="btn btn-secondary btn-xs row-download-btn" data-id="${article.id}" ${disabled}>İndir</button>`}
            </div>
          </div>
          <button
            type="button"
            class="inline-abstract-card detail-popup-trigger"
            data-article-id="${article.id}"
            data-popup-field="abstract"
          >
            <div class="detail-label">Abstract</div>
            <div class="inline-abstract">${article.abstract?.trim() || "Abstract bulunamadı."}</div>
          </button>
          <div class="detail-grid">
            ${detailBlockMarkup(article, "journal", "Dergi ve Yayın", article.journal || "-", article.publication_date || "-")}
            ${detailBlockMarkup(article, "authors", "Yazarlar", compactList(article.authors, 10))}
            ${detailBlockMarkup(article, "mesh", "MeSH", compactList(article.mesh_terms, 12))}
            ${detailBlockMarkup(article, "keywords", "Keywords", compactList(article.keywords, 12))}
            ${detailBlockMarkup(article, "article_types", "Makale Türleri", compactList(article.article_types, 8))}
            ${detailBlockMarkup(article, "related_articles", "Related Articles", compactList(article.related_articles, 8))}
          </div>
          <div class="inline-downloadability">
            <span class="availability-dot-shell ${display.tone}" title="${display.text}">
              <span class="availability-dot"></span>
            </span>
            <span class="detail-inline-text">${info.detail}</span>
          </div>
        </div>
      </td>
    </tr>
  `;
}

function assistantActionKindLabel(action) {
  const map = {
    search_pubmed: "PubMed",
    get_article_details: "Evidence",
    list_catalog_articles: "Catalog",
  };
  return map[action.name] || "TOOL";
}

function assistantActionTitle(action) {
  const details = action.details || {};
  const running = {
    search_pubmed: "Searching PubMed",
    get_article_details: "Reading evidence",
    list_catalog_articles: "Scanning catalog",
  };
  const success = {
    search_pubmed: details.retry_used ? "Broadened PubMed search" : "Searched PubMed",
    get_article_details: "Read evidence",
    list_catalog_articles: "Scanned catalog",
  };
  const error = {
    search_pubmed: "PubMed search failed",
    get_article_details: "Evidence read failed",
    list_catalog_articles: "Catalog scan failed",
  };
  const status = action.status || "success";
  if (status === "running") return running[action.name] || "Running tool";
  if (status === "error") return error[action.name] || "Tool failed";
  return success[action.name] || "Tool completed";
}

function assistantActionStatusIcon(action) {
  const status = action.status || "success";
  if (status === "error") return "!";
  if (status === "success") return "✓";
  return "";
}

function describeAssistantAction(action) {
  const details = action.details || {};
  if (action.name === "search_pubmed") {
    if (details.retry_used && details.retry_query) return details.retry_query;
    if (details.query) return details.query;
    return "Building PubMed query";
  }
  if (action.name === "get_article_details") {
    const ids = details.requested_ids || details.returned_ids || details.ids || [];
    return ids.length ? `ID ${ids.join(", ")}` : "Opening article evidence";
  }
  if (action.name === "list_catalog_articles") {
    if (details.query) return details.query;
    return "Scanning loaded catalog";
  }
  return action.name || "";
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
  if (index >= 0) {
    next[index] = merged;
  } else {
    next.push(merged);
  }
  return next;
}

function ensureAssistantMessageId(item) {
  if (!item._messageId) {
    assistantMessageIdSeed += 1;
    item._messageId = `assistant_msg_${assistantMessageIdSeed}`;
  }
  return item._messageId;
}

function assistantMessageMarkup(item, idx) {
  const messageId = ensureAssistantMessageId(item);
  const roleName = item.role === "user" ? "Sen" : "Researcher AI";
  const liveThinking = item.pending ? item.liveThinking || "" : "";
  const thinkingText = item.pending ? liveThinking : item.thinking || "";
  const pendingLabel = item.thinkingEnabled ? "Düşünülüyor" : "İstek analiz ediliyor";

  let thinkingHtml = "";
  if (item.role !== "user" && thinkingText) {
    if (item.pending) {
      thinkingHtml = `
        <div class="ai-thinking-live-panel">
          <div class="ai-thinking-live-head">
            <span class="ai-thinking-live-label">Live trace</span>
            <span class="ai-thinking-live-pill">Thinking</span>
          </div>
          <pre class="ai-thinking-live-text">${escapeHtml(thinkingText)}</pre>
        </div>`;
    } else {
      thinkingHtml = `
        <div class="ai-thinking-block" data-think-idx="${idx}">
          <button class="ai-thinking-toggle" type="button" onclick="this.closest('.ai-thinking-block').classList.toggle('is-open')">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a7 7 0 0 1 7 7c0 2.4-1.2 4.5-3 5.7V17a2 2 0 0 1-2 2h-4a2 2 0 0 1-2-2v-2.3C6.2 13.5 5 11.4 5 9a7 7 0 0 1 7-7z"/></svg>
            <span>Düşünme süreci</span>
            <svg class="ai-thinking-chevron" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
          </button>
          <div class="ai-thinking-body">
            <pre class="ai-thinking-text">${escapeHtml(thinkingText)}</pre>
          </div>
        </div>`;
    }
  } else if (item.pending && !item.text) {
    thinkingHtml = `
      <div class="ai-thinking-live">
        <svg class="ai-thinking-live-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a7 7 0 0 1 7 7c0 2.4-1.2 4.5-3 5.7V17a2 2 0 0 1-2 2h-4a2 2 0 0 1-2-2v-2.3C6.2 13.5 5 11.4 5 9a7 7 0 0 1 7-7z"/></svg>
        <span>${pendingLabel}</span>
        <span class="ai-thinking-dots"><span></span><span></span><span></span></span>
      </div>`;
  }

  let actionsHtml = "";
  if (item.role !== "user" && item.actions && item.actions.length > 0) {
    const rows = item.actions.map((act) => `
      <div class="ai-action-row ${act.status || "success"}">
        <span class="ai-action-row-status ${act.status || "success"}">${assistantActionStatusIcon(act)}</span>
        <span class="ai-action-row-kind">${escapeHtml(assistantActionKindLabel(act))}</span>
        <span class="ai-action-row-text">${escapeHtml(assistantActionTitle(act))}</span>
        <span class="ai-action-row-sep">·</span>
        <span class="ai-action-row-detail" title="${escapeHtml(describeAssistantAction(act))}">${escapeHtml(describeAssistantAction(act))}</span>
      </div>`).join("");
    actionsHtml = `<div class="ai-action-list">${rows}</div>`;
  }

  const contentHtml = item.text
    ? `<div class="assistant-message-text ${item.pending ? "is-streaming" : ""}">${escapeHtml(item.text)}${item.pending ? '<span class="assistant-stream-caret"></span>' : ""}</div>`
    : "";

  return `
    <div class="assistant-message ${item.role}" data-message-id="${messageId}">
      <div class="assistant-message-role" data-slot="role">${escapeHtml(roleName)}</div>
      <div class="assistant-message-thinking-slot" data-slot="thinking">${thinkingHtml}</div>
      <div class="assistant-message-actions-slot" data-slot="actions">${actionsHtml}</div>
      <div class="assistant-message-content-slot" data-slot="content">${contentHtml}</div>
      <div class="assistant-message-meta-slot" data-slot="meta">${item.meta ? `<div class="assistant-message-meta">${escapeHtml(item.meta)}</div>` : ""}</div>
    </div>`;
}

function patchAssistantMessageNow(item) {
  if (!els.assistantMessages) return;
  const messageId = ensureAssistantMessageId(item);
  const index = state.assistantMessages.indexOf(item);
  if (index === -1) {
    renderAssistantMessages();
    return;
  }
  const node = els.assistantMessages.querySelector(`[data-message-id="${messageId}"]`);
  if (!node) {
    renderAssistantMessages();
    return;
  }
  const wrapper = document.createElement("div");
  wrapper.innerHTML = assistantMessageMarkup(item, index).trim();
  const nextNode = wrapper.firstElementChild;
  if (!nextNode) {
    renderAssistantMessages();
    return;
  }
  node.className = nextNode.className;
  ["role", "thinking", "actions", "content", "meta"].forEach((slotName) => {
    const currentSlot = node.querySelector(`[data-slot="${slotName}"]`);
    const nextSlot = nextNode.querySelector(`[data-slot="${slotName}"]`);
    if (!currentSlot || !nextSlot) return;
    if (currentSlot.innerHTML !== nextSlot.innerHTML) {
      currentSlot.innerHTML = nextSlot.innerHTML;
    }
  });
  if (item.pending) {
    scrollAssistantThinkingToBottom(node);
  }
  els.assistantMessages.scrollTop = els.assistantMessages.scrollHeight;
  assistantLastMarkup = null;
}

function scrollAssistantThinkingToBottom(root = els.assistantMessages) {
  if (!root) return;
  root.querySelectorAll(".ai-thinking-live-text").forEach((node) => {
    node.scrollTop = node.scrollHeight;
  });
}

function patchAssistantMessage(item) {
  assistantDirtyMessages.add(item);
  if (assistantPatchScheduled) return;
  assistantPatchScheduled = true;
  const flush = () => {
    assistantPatchScheduled = false;
    const pendingItems = [...assistantDirtyMessages];
    assistantDirtyMessages.clear();
    pendingItems.forEach((message) => patchAssistantMessageNow(message));
  };
  if (typeof window !== "undefined" && typeof window.requestAnimationFrame === "function") {
    window.requestAnimationFrame(flush);
  } else {
    setTimeout(flush, 0);
  }
}

function markPendingAssistantMessagesAsError(message) {
  let changed = false;
  state.assistantMessages.forEach((item) => {
    if (item.role !== "assistant" || !item.pending) return;
    item.pending = false;
    item.liveStatus = "";
    item.liveThinking = "";
    item.text = mergeAssistantErrorText(item.text, message);
    patchAssistantMessage(item);
    changed = true;
  });
  if (changed) {
    assistantLastMarkup = null;
  }
}

function renderAssistantMessagesNow() {
  if (!els.assistantMessages) return;
  els.assistantPanel?.classList.toggle("is-pristine", state.assistantMessages.length === 0);
  if (!state.assistantMessages.length) {
    if (assistantLastMarkup !== "") {
      els.assistantMessages.innerHTML = "";
      assistantLastMarkup = "";
    }
    return;
  }
  const markup = state.assistantMessages
    .map((item, idx) => assistantMessageMarkup(item, idx))
    .join("");
  if (assistantLastMarkup !== markup) {
    els.assistantMessages.innerHTML = markup;
    assistantLastMarkup = markup;
    assistantDirtyMessages.clear();
  }
  scrollAssistantThinkingToBottom();
  els.assistantMessages.scrollTop = els.assistantMessages.scrollHeight;
}

function renderAssistantMessages() {
  if (assistantRenderScheduled) return;
  assistantRenderScheduled = true;
  const flush = () => {
    assistantRenderScheduled = false;
    renderAssistantMessagesNow();
  };
  if (typeof window !== "undefined" && typeof window.requestAnimationFrame === "function") {
    window.requestAnimationFrame(flush);
  } else {
    setTimeout(flush, 0);
  }
}

function setAssistantOpen(next) {
  state.assistantOpen = next;
  if (!els.assistantPanel || !els.assistantLauncher || !els.assistantOverlay) return;
  els.assistantPanel.hidden = !next;
  els.assistantOverlay.hidden = !next;
  els.assistantLauncher.classList.toggle("is-active", next);
  els.assistantPanel.classList.toggle("is-open", next);
  els.assistantOverlay.classList.toggle("is-open", next);
  if (next) {
    requestAnimationFrame(() => {
      els.assistantInput?.focus();
    });
  }
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

function applyArticleDataset(data) {
  state.lastPubmedResponse = data;
  state.processedPreview = null;
  state.allArticles = data.articles || [];
  state.articles = [...state.allArticles];
  state.selectedIds.clear();
  state.downloadabilityById = Object.fromEntries(
    state.allArticles.map((article) => [
      article.id,
      {
        status: article.pmc_id ? "high" : "unavailable",
        label: article.pmc_id ? downloadabilityLabels.high : downloadabilityLabels.unavailable,
        detail: article.pmc_id ? "PMC sinyali bulundu. Doğrudan indirme denenebilir." : "PMC sinyali yok.",
        openUrl: null,
      },
    ]),
  );
  state.detailArticleId = null;
  closeDetailPopup();
  populateArticleTypeOptions();
  applyArticleFilters();
  renderMeta(data.meta || null);
  renderResults();
  setJson(data);
}

function applyAssistantActions(actions) {
  if (!Array.isArray(actions) || !actions.length) return;
  actions.forEach((action) => {
    if (action.name !== "search_pubmed" || !action.details) return;
    const details = action.details;
    const articles = Array.isArray(details.articles) ? details.articles : [];
    const meta = details.meta || null;
    const nextArticleType = typeof details.article_type === "string" ? details.article_type : "";
    const nextMinCite = Number.isInteger(details.min_cite) ? String(details.min_cite) : "";

    if (typeof details.query === "string" && els.query) {
      els.query.value = details.query;
      autoResizeTextarea(els.query);
    }
    if (els.yearStart) {
      els.yearStart.value = details.year_start ? String(details.year_start) : "";
    }
    if (els.yearEnd) {
      els.yearEnd.value = details.year_end ? String(details.year_end) : "";
    }
    if (els.maxResults) {
      els.maxResults.value = String(details.max_results || articles.length || 10);
    }

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
    applyArticleDataset({ articles, meta });
    if (els.minCite) {
      els.minCite.value = nextMinCite;
    }
    if (els.articleTypeFilter) {
      const hasOption = [...els.articleTypeFilter.options].some((option) => option.value === nextArticleType);
      els.articleTypeFilter.value = hasOption ? nextArticleType : "";
    }
    applyArticleFilters();
    renderResults();
    log(`AI aramasi UI'a aktarıldı: ${details.query} | ${articles.length} makale`);
    if (articles.length) {
      void enrichCitationsInBackground();
    }
  });
}

function updateAssistantModeButtons() {
  els.assistantModeButtons.forEach((button) => {
    const isActive = button.dataset.mode === state.assistantMode;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-pressed", isActive ? "true" : "false");
  });
}

function llmArticlePayload() {
  return activeArticles().map((article) => ({
    id: article.id,
    title: article.title,
    abstract: article.abstract || "",
    year: article.year || null,
    journal: article.journal || null,
    publication_date: article.publication_date || null,
    article_type: articleTypeLabel(article) !== "-" ? articleTypeLabel(article) : null,
    article_types: article.article_types || [],
    citation_count: Number.isInteger(article.citation_count) ? article.citation_count : null,
    authors: article.authors || [],
    keywords: article.keywords || [],
    mesh_terms: article.mesh_terms || [],
    related_articles: article.related_articles || [],
    doi: article.doi || null,
    pmid: article.pmid || null,
    pmc_id: article.pmc_id || null,
  }));
}

function renderResults() {
  updateCounters();
  updateTokenInfo();
  updateSortButtons();

  if (!state.articles.length) {
    els.resultsBody.innerHTML = '<tr><td colspan="9" class="placeholder-cell">Henuz veri yok.</td></tr>';
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
        <td>${article.pmid || "-"}</td>
        <td class="year-cell">${article.year || "-"}</td>
        <td class="type-cell">${articleTypeLabel(article)}</td>
        <td class="count-cell">${citationLabel(article)}</td>
        <td class="title-cell">${article.title || "-"}</td>
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
      if (node.checked) {
        state.selectedIds.add(id);
      } else {
        state.selectedIds.delete(id);
      }
      updateCounters();
      updateTokenInfo();
    });
  });

  document.querySelectorAll(".article-row").forEach((node) => {
    node.addEventListener("click", (event) => {
      if (event.target.closest(".row-check") || event.target.closest(".table-link") || event.target.closest(".row-download-btn") || event.target.closest(".file-open-btn")) {
        return;
      }
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

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail || `HTTP ${response.status}`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return payload;
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

  let responseTimeoutId = null;
  responseTimeoutId = setTimeout(() => {
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
    if (responseTimeoutId) clearTimeout(responseTimeoutId);
    if (requestController.signal.aborted && !externalSignal?.aborted) {
      throw new Error("Model stream timed out.");
    }
    throw error;
  }
  if (responseTimeoutId) clearTimeout(responseTimeoutId);

  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail = payload.detail || `HTTP ${response.status}`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  if (!response.body) {
    throw new Error("Canlı yanıt akışı alınamadı.");
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

function searchPayload() {
  const filters = currentFilters();
  return {
    query: els.query.value.trim(),
    year_start: els.yearStart.value ? Number(els.yearStart.value) : null,
    year_end: els.yearEnd.value ? Number(els.yearEnd.value) : null,
    max_results: normalizedNumber(els.maxResults, 20),
    batch_size: els.batchSize.value ? normalizedNumber(els.batchSize, 50) : null,
    min_cite: filters.minCite,
    article_type: filters.articleType,
    use_cache: true,
  };
}

async function runSearch() {
  els.searchBtn.disabled = true;
  const payload = searchPayload();
  state.lastSearchPayload = payload;
  log(`PubMed sorgusu baslatildi: ${payload.query}`);

  try {
    const data = await fetchJson("/pubmed/search", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    applyArticleDataset(data);
    log(`${data.meta.fetched_results} makale basariyla cekildi.`);
    void enrichCitationsInBackground();
  } catch (error) {
    state.lastPubmedResponse = null;
    state.processedPreview = null;
    state.allArticles = [];
    state.articles = [];
    state.selectedIds.clear();
    state.detailArticleId = null;
    state.downloadabilityById = {};
    populateArticleTypeOptions();
    renderMeta(null);
    renderResults();
    setJson({ error: error.message });
    log(`PubMed hatasi: ${error.message}`);
  } finally {
    els.searchBtn.disabled = false;
  }
}

async function resolveSelected() {
  const chosen = selectedArticles();
  if (chosen.length !== 1) {
    log("PDF adaylarini gormek icin tam olarak 1 makale secmelisin.");
    return;
  }

  const article = chosen[0];
  log(`PDF adaylari cozumleniyor: PMID ${article.pmid || "-"}`);
  try {
    const data = await fetchJson("/pdf/resolve", {
      method: "POST",
      body: JSON.stringify(articleReference(article)),
    });
    setJson(data);
    log(`${data.candidates.length} PDF adayi bulundu.`);
  } catch (error) {
    setJson({ error: error.message });
    log(`PDF cozumleme hatasi: ${error.message}`);
  }
}

async function downloadSingleArticle(articleId) {
  const article = state.articles.find((item) => item.id === articleId);
  if (!article) return;
  const current = getDownloadability(article.id);
  if (!isDownloadReadyStatus(current.status) && current.status !== "downloaded") {
    return;
  }

  state.downloadabilityById[article.id] = {
    status: "loading",
    label: "İndiriliyor",
    detail: "Dosya kaydediliyor.",
    openUrl: current.openUrl || null,
  };
  renderResults();

  try {
    const data = await fetchJson("/pdf/download", {
      method: "POST",
      body: JSON.stringify({
        articles: [articleReference(article)],
        download_dir: els.downloadDir.value.trim() || null,
        max_articles: 1,
        mode: "fast",
      }),
    });
    const result = data.results?.[0];
    if (result?.success) {
      state.downloadabilityById[article.id] = {
        status: "downloaded",
        label: downloadabilityLabels.downloaded,
        detail: result.file_path ? "Dosya indirildi. PDF düğmesinden açabilirsin." : "Dosya indirildi.",
        openUrl: result.file_path ? buildFileOpenUrl(result.file_path) : null,
      };
      log(`Makale indirildi: ${article.title}`);
      setJson(result);
    } else {
      state.downloadabilityById[article.id] = {
        status: "failed",
        label: downloadabilityLabels.failed,
        detail: result?.error || "İndirme başarısız.",
        openUrl: null,
      };
      log(`Makale indirilemedi: ${article.title}`);
      setJson(result || data);
    }
  } catch (error) {
    state.downloadabilityById[article.id] = {
      status: "failed",
      label: downloadabilityLabels.failed,
      detail: error.message || "İndirme başarısız.",
      openUrl: null,
    };
    log(`Makale indirme hatasi: ${error.message}`);
    setJson({ error: error.message });
  }
  renderResults();
}

async function downloadCurrentSelection() {
  const chosen = activeArticles();
  if (!chosen.length) {
    log("Indirme icin makale bulunamadi.");
    return;
  }

  const payload = {
    articles: chosen.map(articleReference),
    download_dir: els.downloadDir.value.trim() || null,
    max_articles: els.maxDownload.value ? normalizedNumber(els.maxDownload, chosen.length) : null,
    mode: "balanced",
  };

  log(
    `PDF indirme baslatildi. Hedef klasor: ${payload.download_dir || "varsayilan"} | Mod: balanced`,
  );
  try {
    const data = await fetchJson("/pdf/download", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    setJson(data);
    log(`PDF indirme tamamlandi. Basarili: ${data.success_count}, Basarisiz: ${data.failed_count}`);
  } catch (error) {
    setJson({ error: error.message });
    log(`PDF indirme hatasi: ${error.message}`);
  }
}

async function enrichCitationsInBackground() {
  if (!state.allArticles.length) return;
  const runId = Date.now();
  state.citationRunId = runId;
  const queue = [...state.allArticles];
  const chunkSize = 10;

  for (let index = 0; index < queue.length; index += chunkSize) {
    if (state.citationRunId !== runId) return;
    const chunk = queue.slice(index, index + chunkSize);
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
      applyArticleFilters();
      renderResults();
    } catch (_error) {
      return;
    }
  }
}

async function runAll() {
  log("Tum islem akisi baslatildi.");
  await runSearch();
  if (!state.articles.length) {
    log("Arama sonucu olmadigi icin akisin geri kalani atlandi.");
    return;
  }

  state.articles.forEach((article) => state.selectedIds.add(article.id));
  renderResults();
  log("Tum makaleler secildi.");
  await downloadCurrentSelection();
  await runLlmProcessing();
}

function downloadJson(filename, data) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function importArticlesPayload(parsed) {
  if (Array.isArray(parsed)) {
    return { articles: parsed, meta: null, raw: parsed };
  }
  if (parsed && Array.isArray(parsed.articles)) {
    return { articles: parsed.articles, meta: parsed.meta || null, raw: parsed };
  }
  throw new Error("JSON listesi veya { articles: [...] } yapisi bekleniyor.");
}

function handleJsonImport(event) {
  const [file] = event.target.files || [];
  if (!file) return;

  const reader = new FileReader();
  reader.onload = () => {
    try {
      const parsed = JSON.parse(String(reader.result));
      const imported = importArticlesPayload(parsed);
      state.allArticles = imported.articles;
      state.articles = [...state.allArticles];
      state.lastPubmedResponse = imported.meta ? imported.raw : null;
      state.processedPreview = null;
      state.selectedIds.clear();
      renderMeta(imported.meta);
      state.downloadabilityById = Object.fromEntries(
        state.allArticles.map((article) => [
          article.id,
          {
            status: article.pmc_id ? "high" : "unavailable",
            label: article.pmc_id ? downloadabilityLabels.high : downloadabilityLabels.unavailable,
            detail: article.pmc_id ? "PMC sinyali bulundu. Doğrudan indirme denenebilir." : "PMC sinyali yok.",
            openUrl: null,
          },
        ]),
      );
      state.detailArticleId = null;
      populateArticleTypeOptions();
      applyArticleFilters();
      renderResults();
      setJson(imported.raw);
      log(`${imported.articles.length} makale JSON dosyasindan yuklendi.`);
      void enrichCitationsInBackground();
    } catch (error) {
      log(`JSON yukleme hatasi: ${error.message}`);
    }
  };
  reader.readAsText(file, "utf-8");
  event.target.value = "";
}

function saveApiKey() {
  localStorage.setItem("researcher2_api_key", els.apiKey.value);
  log("API anahtari tarayici icinde kaydedildi.");
}

function syncModelSelectors(nextValue) {
  const resolved = modelInfoMap[nextValue] ? nextValue : els.modelSelect.value;
  if (els.modelSelect && els.modelSelect.value !== resolved) {
    els.modelSelect.value = resolved;
  }
  if (els.assistantModelLabel) {
    els.assistantModelLabel.textContent = assistantModelLabelMap[resolved] || resolved;
  }
  if (els.assistantModelBtn) {
    els.assistantModelBtn.title = modelInfoMap[resolved] || "Model bilgisi yok.";
  }
  els.assistantModelItems.forEach((button) => {
    button.classList.toggle("is-active", button.dataset.model === resolved);
    button.setAttribute("aria-pressed", button.dataset.model === resolved ? "true" : "false");
  });
  if (els.assistantModelMenu) {
    els.assistantModelMenu.hidden = true;
  }
  if (els.assistantModelBtn) {
    els.assistantModelBtn.setAttribute("aria-expanded", "false");
  }
  updateModelInfo();
  updateTokenInfo();
}

function updateModelInfo() {
  els.modelInfo.textContent = modelInfoMap[els.modelSelect.value] || "Model bilgisi yok.";
}

async function runLlmProcessing() {
  if (!state.articles.length) {
    log("LLM islemi icin once makale yukle veya ara.");
    return;
  }
  if (!els.apiKey.value.trim()) {
    log("LLM islemi icin once API anahtarini kaydet.");
    return;
  }
  if (!els.promptBox.value.trim()) {
    log("LLM islemi icin prompt bos olamaz.");
    return;
  }

  els.processBtn.disabled = true;
  const payload = {
    api_key: els.apiKey.value.trim(),
    model: els.modelSelect.value,
    prompt: els.promptBox.value.trim(),
    selected_ids: [...state.selectedIds],
    articles: llmArticlePayload(),
    max_abstract_tokens: normalizedNumber(els.maxTokens, 750),
    llm_batch: normalizedNumber(els.llmBatch, 20),
    dynamic_batch: els.dynamicBatch.checked,
    retry_count: normalizedNumber(els.retryCount, 3),
  };
  log(
    `LLM batch islemi basladi: ${payload.articles.length} makale | batch ${payload.llm_batch} | dynamic ${
      payload.dynamic_batch ? "on" : "off"
    }`,
  );

  try {
    const data = await fetchJson("/llm/process", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.processedPreview = data;
    updateCounters();
    setJson(data);
    (data.logs || []).forEach((entry) => log(`LLM: ${entry}`));
    if (data.errors?.length) {
      data.errors.forEach((entry) => log(`LLM hata: ${entry}`));
    } else {
      log(
        `LLM islemi tamamlandi. Islenen: ${data.processed_count}, birlesen: ${data.merged_count}, batch: ${data.batch_count}`,
      );
    }
  } catch (error) {
    state.processedPreview = null;
    updateCounters();
    setJson({ error: error.message });
    log(`LLM hatasi: ${error.message}`);
  } finally {
    els.processBtn.disabled = false;
  }
}

function saveProcessedPreview() {
  if (!state.processedPreview) {
    log("Kaydetmek icin once LLM islem onizlemesi uret.");
    return;
  }

  downloadJson("processed_preview.json", state.processedPreview);
  log("LLM onizleme cikti JSON olarak kaydedildi.");
}

async function checkHealth() {
  try {
    const data = await fetchJson("/health");
    els.healthStatus.textContent = data.status === "ok" ? "Hazir" : "Hata";
  } catch (error) {
    els.healthStatus.textContent = "Hata";
    log(`Servis saglik kontrolu basarisiz: ${error.message}`);
  }
}

async function loadBootstrap() {
  try {
    const data = await fetchJson("/app/bootstrap");
    if (data.api_key && !els.apiKey.value.trim()) {
      els.apiKey.value = data.api_key;
      localStorage.setItem("researcher2_api_key", data.api_key);
    }
  } catch (_error) {
    return;
  }
}

async function sendAssistantMessage() {
  const message = els.assistantInput.value.trim();
  if (!message) return;
  if (!els.apiKey.value.trim()) {
    log("Helper AI icin once API anahtarini kaydet.");
    return;
  }
  if (state.assistantStreamAbort) {
    state.assistantStreamAbort.abort();
    markPendingAssistantMessagesAsError("Assistant error: Previous request was interrupted.");
  }

  setAssistantOpen(true);
  state.assistantMessages.push({ role: "user", text: message });
  const pendingMessage = {
    role: "assistant",
    text: "",
    pending: true,
    liveStatus: "",
    liveThinking: "",
    thinkingEnabled: state.thinkingLevel !== "off",
    actions: [],
    meta: "",
  };
  state.assistantMessages.push(pendingMessage);
  renderAssistantMessages();
  els.assistantInput.value = "";
  autoResizeTextarea(els.assistantInput);
  els.assistantSendBtn.disabled = true;

  const controller = new AbortController();
  state.assistantStreamAbort = controller;
  const streamSeq = state.assistantStreamSeq + 1;
  state.assistantStreamSeq = streamSeq;
  let finalResponse = null;

  try {
    await streamJsonEvents("/assistant/chat/stream", {
      method: "POST",
      signal: controller.signal,
      idleTimeoutMs: 45000,
      responseTimeoutMs: 20000,
      body: JSON.stringify({
        api_key: els.apiKey.value.trim(),
        model: els.modelSelect.value,
        message,
        thread_id: state.assistantThreadId,
        mode: state.assistantMode,
        selected_ids: [...state.selectedIds],
        articles: helperArticlePayload(),
        thinking_level: state.thinkingLevel,
      }),
    }, (event) => {
      if (streamSeq !== state.assistantStreamSeq) return;
      if (event.type === "start") {
        if (event.thread_id) {
          state.assistantThreadId = event.thread_id;
          localStorage.setItem("researcher2_helper_thread_id", event.thread_id);
        }
      } else if (event.type === "status") {
        pendingMessage.liveStatus = event.text || pendingMessage.liveStatus;
      } else if (event.type === "thinking_delta") {
        pendingMessage.liveThinking = `${pendingMessage.liveThinking || ""}${event.text || ""}`;
        pendingMessage.liveStatus = "";
      } else if (event.type === "tool_call") {
        pendingMessage.actions = upsertAssistantAction(
          pendingMessage.actions,
          {
            ...(event.action || {}),
            call_id: event.call_id,
          },
          event.call_id,
        );
      } else if (event.type === "tool_result") {
        pendingMessage.actions = upsertAssistantAction(
          pendingMessage.actions,
          {
            ...(event.action || {}),
            call_id: event.call_id,
          },
          event.call_id,
        );
      } else if (event.type === "answer_delta") {
        pendingMessage.text = `${pendingMessage.text || ""}${event.text || ""}`;
      } else if (event.type === "final") {
        finalResponse = event.response || null;
      } else if (event.type === "error") {
        throw new Error(event.message || "Canlı akış sırasında hata oluştu.");
      }
      patchAssistantMessage(pendingMessage);
    });

    if (!finalResponse) {
      throw new Error("Canlı yanıt tamamlanmadı.");
    }

    state.assistantThreadId = finalResponse.thread_id;
    localStorage.setItem("researcher2_helper_thread_id", finalResponse.thread_id);
    pendingMessage.pending = false;
    pendingMessage.text = finalResponse.answer || pendingMessage.text || "Yanit uretilemedi.";
    pendingMessage.thinking = finalResponse.thinking || pendingMessage.liveThinking || null;
    pendingMessage.liveThinking = "";
    pendingMessage.liveStatus = "";
    pendingMessage.actions = finalResponse.executed_actions || pendingMessage.actions || null;
    pendingMessage.meta = finalResponse.used_article_ids?.length
      ? `Kaynak ID: ${finalResponse.used_article_ids.join(", ")}`
      : "";
    applyAssistantActions(finalResponse.executed_actions || []);
    patchAssistantMessage(pendingMessage);
  } catch (error) {
    if (error.name === "AbortError") {
      return;
    }
    controller.abort();
    pendingMessage.pending = false;
    pendingMessage.liveStatus = "";
    pendingMessage.liveThinking = "";
    pendingMessage.text = mergeAssistantErrorText(
      pendingMessage.text,
      `Assistant error: ${error.message}`,
    );
    patchAssistantMessage(pendingMessage);
  } finally {
    if (state.assistantStreamAbort === controller) {
      state.assistantStreamAbort = null;
    }
    els.assistantSendBtn.disabled = false;
  }
}

async function resetAssistantThread() {
  state.assistantStreamAbort?.abort();
  state.assistantStreamAbort = null;
  const threadId = state.assistantThreadId;
  state.assistantThreadId = null;
  state.assistantMessages = [];
  localStorage.removeItem("researcher2_helper_thread_id");
  renderAssistantMessages();
  if (!threadId) return;
  try {
    await fetchJson("/assistant/reset", {
      method: "POST",
      body: JSON.stringify({ thread_id: threadId }),
    });
  } catch (_error) {
    return;
  }
}

function handleSelectAll() {
  state.articles.forEach((article) => state.selectedIds.add(article.id));
  renderResults();
  log("Tum makaleler secildi.");
}

function handleClearSelection() {
  state.selectedIds.clear();
  renderResults();
  log("Makale secimi temizlendi.");
}

function savePubmedJson() {
  if (!state.articles.length) {
    return;
  }

  const payload = state.lastPubmedResponse || { articles: state.articles };
  downloadJson("pubmed_results.json", payload);
  log("PubMed verisi JSON olarak kaydedildi.");
}

function bindLivePreviewUpdates() {
  [els.dynamicBatch, els.maxTokens, els.llmBatch, els.retryCount, els.promptBox].forEach((node) => {
    const eventName = node.tagName === "TEXTAREA" ? "input" : "change";
    node.addEventListener(eventName, updateTokenInfo);
  });
}

function bindSearchFilters() {
  [els.minCite, els.articleTypeFilter].forEach((node) => {
    const eventName = node.tagName === "INPUT" ? "input" : "change";
    node.addEventListener(eventName, () => {
      applyArticleFilters();
      renderResults();
    });
  });
}

function bindTextareaAutosize() {
  [els.query, els.promptBox, els.assistantInput].forEach((node) => {
    if (!node) return;
    autoResizeTextarea(node);
    node.addEventListener("input", () => autoResizeTextarea(node));
  });

  window.addEventListener("resize", () => {
    [els.query, els.promptBox, els.assistantInput].forEach((node) => autoResizeTextarea(node));
  });
}

function init() {
  els.apiKey.value = localStorage.getItem("researcher2_api_key") || "";
  updateAssistantModeButtons();
  syncModelSelectors(els.modelSelect.value);
  bindTextareaAutosize();
  populateArticleTypeOptions();
  renderResults();
  renderAssistantMessages();
  setAssistantOpen(false);
  setJson({});
  log("Uygulama hazir.");
  checkHealth();
  loadBootstrap();
  loadAssistantHistory();

  els.searchBtn.addEventListener("click", runSearch);
  els.downloadArticlesBtn.addEventListener("click", downloadCurrentSelection);
  els.resolvePdfBtn.addEventListener("click", resolveSelected);
  els.loadJsonBtn.addEventListener("click", () => els.jsonFileInput.click());
  els.jsonFileInput.addEventListener("change", handleJsonImport);
  els.saveJsonBtn.addEventListener("click", savePubmedJson);
  els.saveKeyBtn.addEventListener("click", saveApiKey);
  els.modelSelect.addEventListener("change", () => syncModelSelectors(els.modelSelect.value));
  if (els.assistantModelBtn && els.assistantModelMenu) {
    els.assistantModelBtn.addEventListener("click", () => {
      const nextHidden = !els.assistantModelMenu.hidden;
      els.assistantModelMenu.hidden = nextHidden;
      els.assistantModelBtn.setAttribute("aria-expanded", nextHidden ? "false" : "true");
      if (!nextHidden && els.thinkMenu) {
        els.thinkMenu.hidden = true;
        els.thinkToggleBtn?.setAttribute("aria-expanded", "false");
      }
    });
  }
  els.assistantModelItems.forEach((button) => {
    button.addEventListener("click", () => {
      if (!button.dataset.model) return;
      syncModelSelectors(button.dataset.model);
      log(`AI modeli degisti: ${button.dataset.model}`);
    });
  });
  if (els.assistantModelWrap) {
    document.addEventListener("mousedown", (event) => {
      if (els.assistantModelWrap && !els.assistantModelWrap.contains(event.target)) {
        if (els.assistantModelMenu) {
          els.assistantModelMenu.hidden = true;
        }
        els.assistantModelBtn?.setAttribute("aria-expanded", "false");
      }
    });
  }
  els.processBtn.addEventListener("click", runLlmProcessing);
  els.saveProcessedBtn.addEventListener("click", saveProcessedPreview);
  els.runAllBtn.addEventListener("click", runAll);
  els.selectAllBtn.addEventListener("click", handleSelectAll);
  els.clearSelectionBtn.addEventListener("click", handleClearSelection);
  els.sortButtons.forEach((button) => {
    button.addEventListener("click", () => toggleArticleSort(button.dataset.sortKey));
  });
  els.assistantLauncher.addEventListener("click", () => setAssistantOpen(!state.assistantOpen));
  els.assistantOverlay.addEventListener("click", () => setAssistantOpen(false));
  els.assistantSendBtn.addEventListener("click", sendAssistantMessage);
  els.assistantModeButtons.forEach((button) => {
    button.addEventListener("click", () => {
      state.assistantMode = button.dataset.mode || "fast";
      localStorage.setItem("researcher2_assistant_mode", state.assistantMode);
      updateAssistantModeButtons();
      log(`AI mode degisti: ${state.assistantMode}`);
    });
  });
  if (els.assistantCloseBtn) {
    els.assistantCloseBtn.addEventListener("click", () => setAssistantOpen(false));
  }
  if (els.assistantResetBtn) {
    els.assistantResetBtn.addEventListener("click", resetAssistantThread);
  }
  if (els.detailPopupClose) {
    els.detailPopupClose.addEventListener("click", closeDetailPopup);
  }
  if (els.detailPopupOverlay) {
    els.detailPopupOverlay.addEventListener("click", closeDetailPopup);
  }
  els.assistantInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendAssistantMessage();
    }
  });

  // Thinking toggle
  function updateThinkLabel() {
    const labels = { off: "Think: Off", low: "Think: Low", max: "Think: Max" };
    if (els.thinkLabel) els.thinkLabel.textContent = labels[state.thinkingLevel] || labels.off;
    document.querySelectorAll(".think-menu-item").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.level === state.thinkingLevel);
    });
  }
  updateThinkLabel();

  if (els.thinkToggleBtn && els.thinkMenu) {
    els.thinkToggleBtn.addEventListener("click", () => {
      els.thinkMenu.hidden = !els.thinkMenu.hidden;
      els.thinkToggleBtn.setAttribute("aria-expanded", els.thinkMenu.hidden ? "false" : "true");
      if (!els.thinkMenu.hidden && els.assistantModelMenu) {
        els.assistantModelMenu.hidden = true;
        els.assistantModelBtn?.setAttribute("aria-expanded", "false");
      }
    });
    document.querySelectorAll(".think-menu-item").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.thinkingLevel = btn.dataset.level || "off";
        localStorage.setItem("researcher2_thinking_level", state.thinkingLevel);
        updateThinkLabel();
        els.thinkMenu.hidden = true;
        els.thinkToggleBtn.setAttribute("aria-expanded", "false");
      });
    });
    document.addEventListener("mousedown", (event) => {
      if (els.thinkToggleWrap && !els.thinkToggleWrap.contains(event.target)) {
        els.thinkMenu.hidden = true;
        els.thinkToggleBtn.setAttribute("aria-expanded", "false");
      }
    });
  }

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.detailPopup) {
      closeDetailPopup();
    }
  });

  bindLivePreviewUpdates();
  bindSearchFilters();
}

init();
