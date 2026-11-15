document.addEventListener("DOMContentLoaded", () => {
  const folderSelect = document.getElementById("folderSelect");
  const customPathInput = document.getElementById("customPath");
  const btnRefreshFolders = document.getElementById("btnRefreshFolders");
  const btnTranslate = document.getElementById("btnTranslate");

  const progressCard = document.getElementById("progressCard");
  const progressBar = document.getElementById("progressBar");
  const progressCount = document.getElementById("progressCount");
  const progressPercent = document.getElementById("progressPercent");
  const progressMessage = document.getElementById("progressMessage");
  const resultBox = document.getElementById("resultBox");

  const btnSettings = document.getElementById("btnSettings");
  const settingsModal = document.getElementById("settingsModal");
  const btnCloseModal = document.getElementById("btnCloseModal");
  const btnSaveConfig = document.getElementById("btnSaveConfig");
  const geminiKeyInput = document.getElementById("geminiKey");
  const groqKeyInput = document.getElementById("groqKey");

  let pollInterval = null;

  async function loadFolders() {
    folderSelect.innerHTML = '<option value="">Buscando pastas de mangás...</option>';
    try {
      const res = await fetch("/api/folders");
      const data = await res.json();
      folderSelect.innerHTML = "";
      if (data.folders && data.folders.length > 0) {
        folderSelect.innerHTML = '<option value="">-- Escolha uma pasta encontrada --</option>';
        data.folders.forEach(f => {
          const opt = document.createElement("option");
          opt.value = f.path;
          opt.textContent = `${f.name} (${f.path})`;
          folderSelect.appendChild(opt);
        });
      } else {
        folderSelect.innerHTML = '<option value="">Nenhuma pasta padrão encontrada</option>';
      }
    } catch (e) {
      folderSelect.innerHTML = '<option value="">Erro ao buscar pastas</option>';
    }
  }

  folderSelect.addEventListener("change", () => {
    if (folderSelect.value) {
      customPathInput.value = folderSelect.value;
    }
  });

  btnRefreshFolders.addEventListener("click", loadFolders);

  async function loadConfig() {
    try {
      const res = await fetch("/api/config");
      const cfg = await res.json();
      if (cfg.gemini_api_key) geminiKeyInput.value = cfg.gemini_api_key;
      if (cfg.groq_api_key) groqKeyInput.value = cfg.groq_api_key;
    } catch (e) {
      console.error("Erro ao carregar config:", e);
    }
  }

  btnSaveConfig.addEventListener("click", async () => {
    const payload = {
      gemini_api_key: geminiKeyInput.value.trim(),
      groq_api_key: groqKeyInput.value.trim()
    };
    try {
      const res = await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (data.success) {
        alert("✅ Chaves salvas com sucesso!");
        settingsModal.classList.add("hidden");
      }
    } catch (e) {
      alert("❌ Erro ao salvar chaves: " + e.message);
    }
  });

  btnSettings.addEventListener("click", () => {
    settingsModal.classList.remove("hidden");
  });

  btnCloseModal.addEventListener("click", () => {
    settingsModal.classList.add("hidden");
  });

  async function checkStatus() {
    try {
      const res = await fetch("/api/status");
      const st = await res.json();

      if (st.status === "translating" || st.status === "running") {
        progressCard.classList.remove("hidden");
        btnTranslate.disabled = true;
        btnTranslate.style.opacity = "0.5";

        const pct = st.total > 0 ? Math.round((st.current / st.total) * 100) : 10;
        progressBar.style.width = `${pct}%`;
        progressPercent.textContent = `${pct}%`;
        progressCount.textContent = `${st.current} / ${st.total}`;
        progressMessage.textContent = st.message || "Processando...";
      } else if (st.status === "done") {
        progressBar.style.width = "100%";
        progressPercent.textContent = "100%";
        progressMessage.textContent = "✅ Tradução concluída com sucesso!";
        btnTranslate.disabled = false;
        btnTranslate.style.opacity = "1";

        if (st.result && st.result.output) {
          resultBox.innerHTML = `<strong>Pronto!</strong> Obra salva em:<br><code>${st.result.output}</code>`;
          resultBox.classList.remove("hidden");
        }
        clearInterval(pollInterval);
        pollInterval = null;
      } else if (st.status === "error") {
        progressMessage.textContent = "❌ " + st.message;
        progressMessage.style.color = "#ff4d4d";
        btnTranslate.disabled = false;
        btnTranslate.style.opacity = "1";
        clearInterval(pollInterval);
        pollInterval = null;
      }
    } catch (e) {
      console.warn("Polling error:", e);
    }
  }

  btnTranslate.addEventListener("click", async () => {
    const selectedPath = customPathInput.value.trim() || folderSelect.value;
    if (!selectedPath) {
      alert("Por favor, selecione ou digite o caminho da pasta com o mangá!");
      return;
    }

    resultBox.classList.add("hidden");
    progressCard.classList.remove("hidden");
    progressBar.style.width = "5%";
    progressPercent.textContent = "5%";
    progressMessage.textContent = "Iniciando processamento no celular...";
    btnTranslate.disabled = true;

    try {
      const res = await fetch("/api/translate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: selectedPath })
      });
      const data = await res.json();
      if (!data.success) {
        alert("Erro: " + data.error);
        btnTranslate.disabled = false;
        return;
      }

      if (!pollInterval) {
        pollInterval = setInterval(checkStatus, 1000);
      }
    } catch (e) {
      alert("Falha na requisição: " + e.message);
      btnTranslate.disabled = false;
    }
  });

  loadFolders();
  loadConfig();
  checkStatus();
});
