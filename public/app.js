const form = document.querySelector("#download-form");
const input = document.querySelector("#media-url");
const button = document.querySelector("#download-button");
const buttonLabel = button.querySelector("span");
const result = document.querySelector("#result");
const platform = document.querySelector("#platform");
const mediaTitle = document.querySelector("#media-title");
const formats = document.querySelector("#formats");
const status = document.querySelector("#status");

let analysis = null;
let selectedKey = "";
let debounceTimer = 0;
let requestController = null;

function normalizeUrl(value) {
  const trimmed = value.trim();
  if (!trimmed) return "";
  return /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
}

function isValidUrl(value) {
  try {
    const parsed = new URL(normalizeUrl(value));
    return ["http:", "https:"].includes(parsed.protocol) && Boolean(parsed.hostname);
  } catch {
    return false;
  }
}

function setStatus(message = "", kind = "info") {
  status.textContent = message;
  status.dataset.kind = kind;
}

function setBusy(busy, label = "Baixar") {
  buttonLabel.textContent = label;
  button.disabled = busy || !analysis || !selectedKey;
  input.setAttribute("aria-busy", String(busy));
}

function clearResult() {
  analysis = null;
  selectedKey = "";
  result.hidden = true;
  formats.replaceChildren();
  platform.textContent = "";
  mediaTitle.textContent = "";
  button.disabled = true;
}

function chooseOption(key) {
  selectedKey = key;
  for (const optionButton of formats.querySelectorAll(".format")) {
    optionButton.setAttribute("aria-checked", String(optionButton.dataset.key === key));
  }
  button.disabled = false;
  setStatus("Pronto para baixar.");
}

function renderAnalysis(data) {
  analysis = data;
  result.hidden = false;
  platform.textContent = data.platform || "Mídia";
  mediaTitle.textContent = data.title || "Conteúdo identificado";
  formats.replaceChildren();

  for (const option of data.options) {
    const optionButton = document.createElement("button");
    optionButton.type = "button";
    optionButton.className = "format";
    optionButton.dataset.key = option.key;
    optionButton.setAttribute("role", "radio");
    optionButton.setAttribute("aria-checked", "false");

    const label = document.createElement("span");
    label.className = "format-label";
    label.textContent = option.label;

    const detail = document.createElement("span");
    detail.className = "format-detail";
    detail.textContent = option.detail;

    optionButton.append(label, detail);
    optionButton.addEventListener("click", () => chooseOption(option.key));
    formats.append(optionButton);
  }

  const recommended = data.options.find((option) => option.recommended) || data.options[0];
  chooseOption(recommended.key);
}

async function analyze() {
  const url = normalizeUrl(input.value);
  if (!isValidUrl(url)) {
    clearResult();
    setStatus(input.value.trim() ? "Cole um link válido." : "");
    return;
  }

  requestController?.abort();
  requestController = new AbortController();
  clearResult();
  buttonLabel.textContent = "Analisando…";
  setStatus("Identificando a mídia e os formatos disponíveis…");

  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
      signal: requestController.signal,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Não foi possível analisar esse link.");
    if (!Array.isArray(data.options) || data.options.length === 0) {
      throw new Error("Nenhum formato compatível foi encontrado.");
    }
    renderAnalysis(data);
  } catch (error) {
    if (error.name === "AbortError") return;
    clearResult();
    setStatus(error.message, "error");
  } finally {
    buttonLabel.textContent = "Baixar";
  }
}

async function startDownload() {
  const option = analysis?.options.find((item) => item.key === selectedKey);
  if (!option) return;
  setBusy(true, "Preparando…");
  setStatus("Preparando o arquivo. Isso pode levar alguns instantes…");

  try {
    const response = await fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: normalizeUrl(input.value),
        selection: option.selection,
        mode: option.mode,
        ext: option.ext,
        quality: option.quality || "",
      }),
    });
    const data = await response.json();
    if (!response.ok || !data.downloadUrl) {
      throw new Error(data.error || "Não foi possível preparar o arquivo.");
    }

    const link = document.createElement("a");
    link.href = data.downloadUrl;
    link.download = data.filename || "all-web-down";
    link.hidden = true;
    document.body.append(link);
    link.click();
    link.remove();
    setStatus("Download iniciado. Você pode continuar nesta página.");
  } catch (error) {
    setStatus(error.message || "Não foi possível preparar o arquivo.", "error");
  } finally {
    setBusy(false);
  }
}

input.addEventListener("input", () => {
  window.clearTimeout(debounceTimer);
  clearResult();
  setStatus("");
  if (isValidUrl(input.value)) debounceTimer = window.setTimeout(analyze, 550);
});

form.addEventListener("submit", (event) => {
  event.preventDefault();
  if (analysis && selectedKey) startDownload();
  else analyze();
});

