const landingEls = {
  createProjectForm: document.getElementById("createProjectForm"),
  createProjectNameInput: document.getElementById("createProjectNameInput"),
  createProjectButton: document.getElementById("createProjectButton"),
  projectList: document.getElementById("projectList"),
};

const activeProjectStorageKey = "native_researcher_active_project";
let landingErrorLoggingBound = false;

async function landingFetchJson(url, options = {}) {
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

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function trackLandingEvent(level, event, message, context = {}) {
  fetch("/app/events", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      level,
      event,
      message: String(message || "").slice(0, 240),
      context,
    }),
    keepalive: true,
  }).catch(() => {});
}

function bindLandingErrorLogging() {
  if (landingErrorLoggingBound || typeof window === "undefined") return;
  landingErrorLoggingBound = true;
  window.addEventListener("error", (event) => {
    trackLandingEvent("error", "landing_window_error", event.message || "Unhandled landing error.", {
      filename: event.filename || "",
      lineno: event.lineno || 0,
    });
  });
  window.addEventListener("unhandledrejection", (event) => {
    const reason = event.reason;
    trackLandingEvent(
      "error",
      "landing_unhandled_rejection",
      typeof reason === "string" ? reason : reason?.message || "Unhandled promise rejection.",
    );
  });
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

function projectOpenUrl(projectId) {
  return `/native_researcher?project=${encodeURIComponent(projectId)}`;
}

async function createProjectAndOpen(projectName = "") {
  try {
    const project = await landingFetchJson("/app/projects", {
      method: "POST",
      body: JSON.stringify({ name: String(projectName || "").trim() }),
    });
    if (!project?.id) return;
    localStorage.setItem(activeProjectStorageKey, project.id);
    window.location.href = projectOpenUrl(project.id);
  } catch (error) {
    trackLandingEvent("error", "project_create_failed", error.message || "Project creation failed.");
    throw error;
  }
}

async function deleteProject(projectId, projectName) {
  const label = String(projectName || "this project").trim();
  const confirmed = window.confirm(`Delete ${label}?`);
  if (!confirmed) return;
  try {
    await landingFetchJson(`/app/projects/${encodeURIComponent(projectId)}`, {
      method: "DELETE",
    });
    if (localStorage.getItem(activeProjectStorageKey) === projectId) {
      localStorage.removeItem(activeProjectStorageKey);
    }
    await loadProjects();
  } catch (error) {
    trackLandingEvent("error", "project_delete_failed", error.message || "Project deletion failed.", {
      project_id: projectId,
    });
    throw error;
  }
}

function projectCardMarkup(project) {
  return `
    <div class="landing-minimal-project">
      <button class="landing-minimal-project-main" type="button" data-project-id="${project.id}">
        <span class="landing-minimal-project-name">${escapeHtml(project.name)}</span>
        <span class="landing-minimal-project-time">${formatRelativeTime(project.updated_at)}</span>
      </button>
      <button
        class="landing-minimal-project-delete"
        type="button"
        data-delete-project="${project.id}"
        data-project-name="${escapeHtml(project.name)}"
        aria-label="Delete ${escapeHtml(project.name)}"
      >
        Delete
      </button>
    </div>
  `;
}

function emptyProjectsMarkup() {
  return `
      <div class="landing-minimal-empty">
      <div class="landing-minimal-empty-title">No recent projects</div>
      <button class="landing-minimal-empty-link" type="button" data-create-project="true">New project</button>
    </div>
  `;
}

function renderProjects(projects) {
  if (!landingEls.projectList) return;
  landingEls.projectList.innerHTML = projects.length
    ? projects.map(projectCardMarkup).join("")
    : emptyProjectsMarkup();

  landingEls.projectList.querySelectorAll("[data-project-id]").forEach((node) => {
    node.addEventListener("click", () => {
      const projectId = node.dataset.projectId;
      if (!projectId) return;
      localStorage.setItem(activeProjectStorageKey, projectId);
      window.location.href = projectOpenUrl(projectId);
    });
  });
  landingEls.projectList.querySelectorAll("[data-delete-project]").forEach((node) => {
    node.addEventListener("click", () => {
      const projectId = node.dataset.deleteProject;
      if (!projectId) return;
      void deleteProject(projectId, node.dataset.projectName || "");
    });
  });
  landingEls.projectList.querySelector("[data-create-project]")?.addEventListener("click", () => {
    void createProjectAndOpen(landingEls.createProjectNameInput?.value || "");
  });
}

async function loadProjects() {
  try {
    const payload = await landingFetchJson("/app/projects");
    renderProjects(Array.isArray(payload.projects) ? payload.projects : []);
  } catch (error) {
    trackLandingEvent("error", "project_list_failed", error.message || "Project list could not be loaded.");
    renderProjects([]);
  }
}

function initLanding() {
  bindLandingErrorLogging();
  landingEls.createProjectForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    void createProjectAndOpen(landingEls.createProjectNameInput?.value || "");
  });
  void loadProjects();
  window.addEventListener("pageshow", () => {
    void loadProjects();
  });
  window.addEventListener("focus", () => {
    void loadProjects();
  });
}

initLanding();
