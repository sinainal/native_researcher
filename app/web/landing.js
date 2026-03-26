const landingEls = {
  projectList: document.getElementById("projectList"),
  projectCreateForm: document.getElementById("projectCreateForm"),
  projectNameInput: document.getElementById("projectNameInput"),
  projectDescriptionInput: document.getElementById("projectDescriptionInput"),
  projectCreateStatus: document.getElementById("projectCreateStatus"),
  createProjectBtn: document.getElementById("createProjectBtn"),
};

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

function projectCardMarkup(project) {
  const description = project.description?.trim() || "Project workspace is ready for PDFs, derived notes, and future indexes.";
  return `
    <button class="landing-project-card" type="button" data-project-id="${project.id}">
      <div class="landing-project-card-main">
        <div class="landing-project-name">${project.name}</div>
        <div class="landing-project-description">${description}</div>
        <div class="landing-project-meta">
          <span>${project.pdf_count} PDFs</span>
          <span>${project.note_count} notes</span>
        </div>
      </div>
      <div class="landing-project-side">
        <span class="landing-project-time">${formatRelativeTime(project.updated_at)}</span>
      </div>
    </button>
  `;
}

function emptyProjectsMarkup() {
  return `
    <div class="landing-project-empty">
      <div class="landing-project-empty-title">No projects yet</div>
      <div class="landing-project-empty-copy">Create the first workspace to start organizing downloads, evidence, and project-specific research state.</div>
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
      localStorage.setItem("native_researcher_active_project", projectId);
      window.location.href = projectOpenUrl(projectId);
    });
  });
}

async function loadProjects() {
  const payload = await landingFetchJson("/app/projects");
  renderProjects(Array.isArray(payload.projects) ? payload.projects : []);
}

async function handleProjectCreate(event) {
  event.preventDefault();
  const name = landingEls.projectNameInput?.value.trim() || "";
  const description = landingEls.projectDescriptionInput?.value.trim() || "";
  if (!name) return;

  landingEls.createProjectBtn.disabled = true;
  landingEls.projectCreateStatus.textContent = "Creating project...";
  try {
    const project = await landingFetchJson("/app/projects", {
      method: "POST",
      body: JSON.stringify({ name, description }),
    });
    localStorage.setItem("native_researcher_active_project", project.id);
    landingEls.projectCreateStatus.textContent = "Project created.";
    window.location.href = projectOpenUrl(project.id);
  } catch (error) {
    landingEls.projectCreateStatus.textContent = `Project error: ${error.message}`;
  } finally {
    landingEls.createProjectBtn.disabled = false;
  }
}

function initLanding() {
  landingEls.projectCreateForm?.addEventListener("submit", (event) => {
    void handleProjectCreate(event);
  });
  void loadProjects();
  landingEls.projectNameInput?.focus();
}

initLanding();
