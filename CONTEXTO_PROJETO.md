# 📖 Manga Studio — Documento de Contexto do Projeto (Handoff para IA)

> **Finalidade deste documento:** Permitir que qualquer Inteligência Artificial (Claude, ChatGPT, Gemini, Cursor ou Antigravity em nova sessão) compreenda imediatamente todo o escopo, arquitetura técnica, regras mandatórias do projeto, histórico recente e o estado operacional atual do **Manga Studio**.

---

## 1. Identificação Geral do Projeto

* **Nome do Sistema:** **Manga Studio (PT-BR)**
* **Versão Oficial Atual:** **`v0.8.1 Beta` (`0.8.1-beta`)** / APK Android: **`v1.0.15-mobile` (versionCode 16)**
* **Autor / Proprietário:** **Jos9011**
* **Objetivo:** Plataforma completa de scanlation automatizado de alta fidelidade para mangás (japonês), manhwas (coreano), manhuas (chinês) e quadrinhos em inglês/espanhol com destino em **Português do Brasil (PT-BR)**.
* **Repositórios Oficiais no GitHub:**
  1. **`https://github.com/Jos9011/SKILL-TRADUCAO-MANGA`** (Versão PC Desktop e Google Colab Cloud com WebUI).
  2. **`https://github.com/Jos9011/MANGA-STUDIO-ANDROID`** (Aplicativo Nativo Android APK com backend Python embutido via Chaquopy).

---

## 2. Regras de Ouro do Projeto (MANDATÓRIAS PARA QUALQUER IA)

Qualquer IA que atuar neste projeto **DEVE OBEDECER RIGOROSAMENTE** às seguintes regras:

1. **A Regra das 300 Linhas (300-Line Rule):**
   * Nenhum arquivo de código novo ou refatorado deve ultrapassar **300 linhas**.
   * Módulos devem ser pequenos, coesos e desacoplados. Se um módulo crescer, divida-o (ex: separação entre rotas, limpeza de cavidade, diagramação, checagem de cotas).
2. **Regra de Versionamento SemVer Oficial:**
   * **Toda alteração publicada no sistema DEVE atualizar a versão** (`python version.py bump pequeno | medio | grande`).
   * A versão deve ser sincronizada em: `version.py`, `README.md`, `Colab_Manga_WebUI.ipynb`, `studio/server.py`, `studio/templates/index.html` e, no Android, `app/build.gradle`, `mobile_server.py`, `mobile_routes_translation.py`, `.github/workflows/build-apk.yml`.
3. **Zero Secrets no Git:**
   * **NUNCA** commitar chaves de API, tokens ou caminhos com senhas no GitHub.
   * O arquivo `config.json`, pastas de `uploads/`, caches e logs são estritamente cobertos pelo `.gitignore`.
4. **Isolamento de Repositórios:**
   * Manter `SKILL-TRADUCAO-MANGA` (PC/Colab) e `MANGA-STUDIO-ANDROID` (APK) como projetos independentes, porém com suas lógicas de negócio e versões perfeitamente alinhadas.
5. **Links Clicáveis no Chat:**
   * Sempre referenciar arquivos com formato markdown `[arquivo](file:///caminho/com/barras/normais)`.

---

## 3. Arquitetura e Pilares Técnicos do Sistema

O sistema é dividido em submódulos cooperativos:

### A. Arquitetura Cooperativa de Duas IAs (Dual Engine)
* **Agente 1 — Cartógrafo Espacial:**
  * Detecta a disposição geométrica de todos os balões da página.
  * Define a ordem de leitura correta (RTL - Direita para Esquerda / Cima para Baixo para mangás orientais).
  * Calcula o **orçamento de caracteres** de cada balão para impedir que o texto em português transborde a área útil.
* **Agente 2 — Sintetizador Literário / Contextualizador:**
  * Recebe o dossiê da página inteira de uma vez.
  * Compreende gênero dos personagens, duplo sentido, tom emocional e gírias de scanlation em PT-BR sem censura (+18).
  * Gera a tradução de todas as falas em bloco com coerência de cena.

### A2. Ficha da Obra + Líder do Capítulo (Fase 1)
* **PC/Colab:** o Líder roda depois do OCR e antes da tradução (`lider_capitulo.py`, `ficha_obra.py`, `ficha_caminho.py`).
* **Android (v1.0.12):** como a IA Vision lê e traduz cada página numa chamada só, `mobile_ficha.py` anexa a ficha ao prompt da IA Vision, recebe o texto `original` de cada balão e roda o Líder no fim do capítulo, atualizando a ficha para os próximos.
* `ficha_obra.py`, `ficha_caminho.py` e `lider_capitulo.py` são **cópias idênticas** nos dois repositórios: altere nos dois juntos (teste `TestSharedModulesInSync` compara quando `MANGA_PC_REPO` aponta para o repositório do PC).
* Ficha em `.fichas_obra/<obra>.json` na pasta que contém os capítulos soltos ("Obra Ch.1", "Obra Ch.2").

### A4. Contexto entre páginas e espera de cota (Android v1.0.15)
* `chapter_context.py` e `quota_wait.py` são cópias idênticas dos módulos do PC (v0.8.1).
* `mobile_translator._translate_page_waiting_quota`: o prompt de cada página leva a Ficha mais as últimas falas (original => tradução) das `context_pages` páginas anteriores (padrão 2).
* Se TODAS as IAs falharem por cota (429, quota, rate limit), a página espera e é tentada de novo: a 1ª espera é de 60 s e as seguintes de 10 min, até 12 h. Parar e Pausar valem durante a espera. Com `"quota_fallback": "skip"`, a página fica no original como antes.
* A tela Configurações tem o cartão "Tradução" com as duas opções.

### A3. Google Drive dentro do app (Android v1.0.14)
* Login do Google no Android (`DriveAuthHelper.kt`, Google Identity Services, `play-services-auth`), escopo **somente leitura** (`drive.readonly`). O token vai do Kotlin direto para o Python (`mobile_gdrive.set_token`), fica só na memória e nunca passa pelo JavaScript.
* `mobile_gdrive.py` + `mobile_routes_gdrive.py` (`/api/gdrive/*`): lista pastas e `.zip/.cbz` da pasta `MANGAS` do Drive (configurável em `"gdrive_root_folder"`) e baixa a obra escolhida para `/sdcard/MANGAS` em segundo plano.
* Requisitos fora do código: chave FIXA de assinatura nos Secrets do GitHub (`ANDROID_KEYSTORE_*`) e um cliente OAuth "Android" no Google Cloud com o pacote `com.mangastudio.mobile` + SHA-1 dessa chave (API Google Drive ativada; tela de consentimento em modo Teste com o e-mail do usuário).
* Próxima etapa planejada: enviar as traduções de volta para `MANGAS [PT-BR]` no Drive.

### B. OCR IA Vision Híbrido
* Combina um **detector geométrico local (RapidOCR / PP-OCR)** para traçar as caixas com uma **IA Vision Multimodal** para transcrever o texto original direto da imagem (reconhecendo fontes estilizadas e onomatopeias).
* Suporta **Google Gemini**, **Groq Vision**, **OpenRouter Vision** e **Ollama Vision**.
* **Fallback Automático e Silencioso:** Se a visão na nuvem sofrer bloqueio de segurança (+18) ou esgotamento de cota, o sistema recua imediatamente para o OCR clássico sem travar a tradução.

### C. Limpeza de Cavidade do Balão & Proteção Anti-Vazamento P&B
* Módulos: `balloon_cavity.py` (PC) e `mobile_balloon_cleaner.py` (Android).
* Varre 100% da cavidade interna fechada de balões brancos, apagando letras órfãs, "I" solto e ruídos de escaneamento sem danificar o contorno preto.
* **5 Travas Matemáticas Anti-Vazamento:** Impede que balões abertos/nuvem em mangás preto e branco vazem flood-fill branco para pele e cabelo claro dos personagens. Em caso de vazamento detectado (`open_sides >= 2`, `holes_ratio > 0.26`, `fill_ratio > 0.72`), aborta a expansão e aplica limpeza cirúrgica restrita à caixa do texto.

### D. Tipografia PT-BR e Diagramação Responsiva
* Módulos: `typography_ptbr.py` (PC) e `mobile_typesetter.py` (Android).
* Fontes embutidas: `Anime Ace`, `Komika Axis`, `Shout` e `Dialogue`.
* Calibração fina de entrelinha (`1.22` normal, `1.15` apertado), medição real de altura de acentos maiúsculos em português (`ÁÇÃÊÓÚg`) e filtro anti-hifenização em palavras curtas (`min_len=8`).

### E. Colorização Automática por IA (ONNX)
* Módulo: `studio/colorizer_engine.py` (PC/Colab).
* Utiliza modelo leve de rede neural em ONNX para colorir páginas P&B automaticamente em segundos, com suporte a imagem de referência para ancorar as cores dos personagens.

### F. Leitor Web Offline e Exportação CBZ
* Ao término da tradução, gera um leitor interativo HTML standalone (`leitor.html`) e um arquivo compactado `.cbz` com as páginas tratadas e traduzidas.

---

## 4. Onde Ficam as Configurações e Chaves de API

* **Local do Perfil Persistente:** `G:\Meu Drive\.manga_studio\config.json`
  * Este arquivo é compartilhado entre PC, Google Colab e celular via Google Drive.
* **Chaves e Provedores Configurados Atualmente:**
  1. **Google Gemini (Vision & Tradução):**
     * Modelo Ativo: **`gemini-3.1-flash-lite`** (Ultra-rápido, gratuito, sem limites de TPM severos).
     * Chave Configurada: Chave oficial Google AI Studio com prefixo `AQ.` ativa e operacional.
  2. **Groq Cloud:**
     * Modelo Padrão: **`qwen/qwen3.8-27b`** (Fallback: `openai/gpt-oss-120b`).
     * Chaves Cadastradas: 5 chaves (observação: chaves de uma mesma organização compartilham a cota diária de 200k tokens).
  3. **OpenRouter:**
     * Modelo Padrão: **`nvidia/nemotron-3.5-lightning:free`**.
  4. **Ollama (Local / GPU):**
     * Suporte a servidor local (`http://localhost:11434`), ativo no PC e no Colab, desativado no Android.

---

## 5. Como Executar Cada Ambiente

* **No PC Desktop (Windows):**
  * Iniciar via `C:\Users\ja329\Desktop\Manga_Studio.bat` ou rodando `python studio/server.py` no repositório.
* **No Google Colab (Cloud):**
  * Abrir o notebook `Colab_Manga_WebUI.ipynb` no Google Colab, selecionar GPU e executar as células.
  * O servidor sobe via Cloudflare Tunnel com token secreto criptográfico: `https://xxxx.trycloudflare.com/?token=SEU_TOKEN`.
* **No Celular Android:**
  * Instalar o APK gerado no GitHub Actions (`MANGA-STUDIO-ANDROID/releases/download/v1.0.15-mobile/app-debug.apk`).
  * O app roda um servidor Flask em segundo plano via Chaquopy na porta interna `8080` e abre a WebView nativa.
