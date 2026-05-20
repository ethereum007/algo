const state = {
  projects: [],
  refs: [],
  market: null,
  marketTimer: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const type = response.headers.get("content-type") || "";
  if (!type.includes("application/json")) return response;
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

function setView(name) {
  $$(".nav-btn").forEach((button) => button.classList.toggle("active", button.dataset.view === name));
  $$(".view").forEach((view) => view.classList.toggle("active", view.id === name));
}

function bindNavigation() {
  $$(".nav-btn").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
  $("#refreshBtn").addEventListener("click", refreshAll);
  $("#loadMarketBtn").addEventListener("click", refreshMarketData);
  $("#autoMarketBtn").addEventListener("click", toggleMarketRefresh);
}

function bindRiskOutputs() {
  const pairs = [
    ["riskPerTrade", "riskPerTradeOut"],
    ["dailyLoss", "dailyLossOut"],
    ["maxDrawdown", "maxDrawdownOut"],
  ];
  for (const [name, outputId] of pairs) {
    const input = document.querySelector(`[name="${name}"]`);
    const output = document.getElementById(outputId);
    const update = () => { output.value = `${input.value}%`; };
    input.addEventListener("input", update);
    update();
  }
}

function formPayload(form) {
  return Object.fromEntries(new FormData(form).entries());
}

function compactValidation(validation) {
  const status = validation.exitCode === 0 ? "PASS" : validation.exitCode === 1 ? "WARN" : "FAIL";
  return `${status}\n\n${validation.stdout || validation.stderr}`;
}

async function generateProject(event) {
  event.preventDefault();
  const log = $("#generateLog");
  log.textContent = "Generating scaffold and running validator...";
  try {
    const data = await api("/api/generate", {
      method: "POST",
      body: JSON.stringify(formPayload(event.currentTarget)),
    });
    log.textContent = `Created ${data.name}\n${data.path}\n\n${compactValidation(data.validation)}`;
    await refreshProjects();
    setView("projects");
  } catch (error) {
    log.textContent = `Error: ${error.message}`;
  }
}

function renderProjects() {
  $("#projectCount").textContent = String(state.projects.length);
  const list = $("#projectList");
  const selector = $("#reviewProject");
  list.innerHTML = "";
  selector.innerHTML = "";

  if (!state.projects.length) {
    list.innerHTML = `<div class="item"><strong>No projects yet</strong><small>Generate one from Builder.</small></div>`;
    return;
  }

  for (const project of state.projects) {
    const option = document.createElement("option");
    option.value = project.name;
    option.textContent = project.name;
    selector.appendChild(option);

    const item = document.createElement("div");
    item.className = "item";
    item.innerHTML = `
      <strong>${project.name}</strong>
      <small>${project.path}</small>
      <div class="file-row">
        <a class="download" href="/api/download?project=${encodeURIComponent(project.name)}">Zip</a>
        <button data-validate="${project.name}">Validate</button>
      </div>
    `;

    for (const file of project.files) {
      const row = document.createElement("div");
      row.className = "file-row";
      row.innerHTML = `<small>${file.name}</small><button data-project="${project.name}" data-file="${file.name}">Open</button>`;
      item.appendChild(row);
    }
    list.appendChild(item);
  }

  $$("[data-file]").forEach((button) => {
    button.addEventListener("click", () => openFile(button.dataset.project, button.dataset.file));
  });
  $$("[data-validate]").forEach((button) => {
    button.addEventListener("click", () => validateProject(button.dataset.validate));
  });
}

async function openFile(project, file) {
  const data = await api(`/api/file?project=${encodeURIComponent(project)}&file=${encodeURIComponent(file)}`);
  $("#fileTitle").textContent = data.file;
  $("#fileMeta").textContent = data.project;
  $("#filePreview").textContent = data.content;
}

async function refreshProjects() {
  state.projects = await api("/api/projects");
  renderProjects();
}

function renderReferences() {
  const list = $("#referenceList");
  list.innerHTML = "";
  if (!state.refs.length) {
    list.innerHTML = `<div class="item"><strong>No references found</strong><small>Check the skill repository path.</small></div>`;
    return;
  }
  for (const ref of state.refs) {
    const item = document.createElement("button");
    item.className = "item";
    item.innerHTML = `<strong>${ref.title}</strong><small>${ref.id}</small>`;
    item.addEventListener("click", () => openReference(ref.id, ref.title));
    list.appendChild(item);
  }
}

async function openReference(id, title) {
  const data = await api(`/api/reference?id=${encodeURIComponent(id)}`);
  $("#referenceTitle").textContent = title;
  $("#referencePreview").textContent = data.content;
}

async function refreshReferences() {
  state.refs = await api("/api/references");
  renderReferences();
}

function drawChart(quote) {
  const canvas = $("#marketChart");
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fbfdfb";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "#dfe7df";
  ctx.lineWidth = 1;
  for (let i = 0; i < 5; i += 1) {
    const y = 30 + i * ((height - 60) / 4);
    ctx.beginPath();
    ctx.moveTo(50, y);
    ctx.lineTo(width - 24, y);
    ctx.stroke();
  }
  if (!quote || !quote.candles.length) {
    ctx.fillStyle = "#68736c";
    ctx.fillText("No chart data available.", 50, 56);
    return;
  }
  const closes = quote.candles.map((candle) => candle.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const span = Math.max(0.01, max - min);
  ctx.strokeStyle = quote.change >= 0 ? "#0f766e" : "#b42318";
  ctx.lineWidth = 2;
  ctx.beginPath();
  quote.candles.forEach((candle, index) => {
    const x = 50 + (index / Math.max(1, quote.candles.length - 1)) * (width - 82);
    const y = height - 32 - ((candle.close - min) / span) * (height - 72);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.fillStyle = "#17211c";
  ctx.font = "13px system-ui";
  ctx.fillText(`${quote.inputSymbol} ${quote.currency} ${quote.price ?? "NA"}`, 50, 24);
  ctx.fillStyle = "#68736c";
  ctx.fillText(`Low ${min.toFixed(2)}  High ${max.toFixed(2)}`, 50, height - 10);
}

function renderMarketData() {
  const data = state.market;
  const grid = $("#quoteGrid");
  grid.innerHTML = "";
  if (!data) return;
  $("#marketProvider").textContent = data.provider;
  $("#marketNotice").textContent = data.disclaimer;
  $("#marketLog").textContent = `${data.mode}\nFetched: ${data.fetchedAt}\n\n${data.errors.map((e) => `${e.symbol}: ${e.error}`).join("\n") || "No feed errors."}`;

  for (const quote of data.quotes) {
    const card = document.createElement("button");
    const direction = quote.change >= 0 ? "up" : "down";
    card.className = `quote-card ${direction}`;
    card.innerHTML = `
      <strong>${quote.inputSymbol}</strong>
      <span>${quote.providerSymbol}</span>
      <b>${quote.currency || "INR"} ${quote.price ?? "NA"}</b>
      <small>${quote.change ?? "NA"} (${quote.changePct ?? "NA"}%) · ${quote.marketState || "unknown"} · delay ${quote.dataDelay ?? "?"}m</small>
    `;
    card.addEventListener("click", () => {
      $("#chartTitle").textContent = `${quote.inputSymbol} Intraday Trace`;
      $("#chartMeta").textContent = quote.providerSymbol;
      drawChart(quote);
    });
    grid.appendChild(card);
  }
  drawChart(data.quotes[0]);
}

async function refreshMarketData() {
  $("#marketLog").textContent = "Fetching market data...";
  try {
    const symbols = encodeURIComponent($("#marketSymbols").value);
    state.market = await api(`/api/market-data?symbols=${symbols}`);
    renderMarketData();
  } catch (error) {
    $("#marketLog").textContent = `Error: ${error.message}`;
  }
}

function toggleMarketRefresh() {
  const button = $("#autoMarketBtn");
  if (state.marketTimer) {
    clearInterval(state.marketTimer);
    state.marketTimer = null;
    button.textContent = "Auto Refresh";
    return;
  }
  refreshMarketData();
  state.marketTimer = setInterval(refreshMarketData, 60000);
  button.textContent = "Stop Auto";
}

async function validateProject(projectName = $("#reviewProject").value) {
  if (!projectName) return;
  setView("review");
  $("#reviewStatus").textContent = "Running";
  $("#reviewOutput").textContent = "Validating...";
  try {
    const data = await api("/api/validate", {
      method: "POST",
      body: JSON.stringify({ project: projectName }),
    });
    $("#reviewStatus").textContent = data.exitCode === 0 ? "Pass" : data.exitCode === 1 ? "Warnings" : "Failures";
    $("#reviewOutput").textContent = compactValidation(data);
  } catch (error) {
    $("#reviewStatus").textContent = "Error";
    $("#reviewOutput").textContent = error.message;
  }
}

async function refreshHealth() {
  try {
    const data = await api("/api/health");
    $("#healthDot").classList.add("ok");
    $("#healthText").textContent = "Connected";
    return data;
  } catch {
    $("#healthDot").classList.remove("ok");
    $("#healthText").textContent = "Offline";
  }
}

async function refreshAll() {
  await refreshHealth();
  await Promise.all([refreshProjects(), refreshReferences(), refreshMarketData()]);
}

function boot() {
  bindNavigation();
  bindRiskOutputs();
  $("#builderForm").addEventListener("submit", generateProject);
  $("#validateBtn").addEventListener("click", () => validateProject());
  refreshAll();
}

boot();
