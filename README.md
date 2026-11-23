# 📱 Manga Studio Mobile — Aplicativo Android (APK)

[![Compilar APK](https://github.com/Jos9011/MANGA-STUDIO-ANDROID/actions/workflows/build-apk.yml/badge.svg)](https://github.com/Jos9011/MANGA-STUDIO-ANDROID/actions/workflows/build-apk.yml)
[![Download APK](https://img.shields.io/badge/Download-APK%20Android-brightgreen.svg?logo=android)](https://github.com/Jos9011/MANGA-STUDIO-ANDROID/releases)

Versão nativa independente do **Manga Studio** empacotada em um único arquivo `.apk` para smartphones Android, permitindo traduzir, limpar balões e diagramar mangás diretamente pelo celular sem depender do Google Colab ou de um computador ligado.

---

## ⚡ Arquitetura Mobile (Sem Dependência de Colab)

Para rodar suavemente em qualquer smartphone moderno sem drenar bateria e sem sobrecarregar a memória RAM:

1. **Cérebro de Tradução na Nuvem (Zero RAM no Celular):**
   - Utiliza as chaves de API do **Google Gemini Vision** e **Groq** para ler os balões japoneses e traduzir em menos de 1 segundo.
   - A regra de IA local pesada (Ollama 8GB) foi desativada por padrão nesta versão mobile.
2. **Motor de Processamento Local (ARM64 Nativo):**
   - Limpeza de balões (Inpainting com OpenCV) e renderização tipográfica (Pillow com fontes TTF) rodam diretamente no processador do celular através do **Chaquopy** (Python 3.11 embutido).
3. **Leitor Integrado & Exportação em .CBZ:**
   - Cria automaticamente um pacote `.cbz` e um leitor HTML offline na pasta `MANGAS [PT-BR]` para visualização direta no Tachiyomi, Mihon ou pelo próprio aplicativo.

---

## 📥 Como Baixar e Instalar no Celular

1. Acesse a aba **[Releases](https://github.com/Jos9011/MANGA-STUDIO-ANDROID/releases)** deste repositório pelo celular.
2. Baixe o arquivo **`app-debug.apk`** da release mais recente.
3. Toque no arquivo baixado e confirme a instalação (se o Android solicitar, permita a instalação a partir do navegador).
4. Abra o aplicativo **Manga Studio**.
5. No ícone de engrenagem (⚙️), insira sua chave gratuita do **Google Gemini Vision** (`AIza...`).
6. Escolha a pasta com o mangá e toque em **"Iniciar Tradução"**!

---

## 🛠️ Estrutura do Projeto

```
MANGA-STUDIO-ANDROID/
├── app/
│   ├── src/main/java/com/mangastudio/mobile/  # Código nativo Kotlin (WebView, Service, Permissões)
│   ├── src/main/python/                      # Motor Python embutido (Flask, OpenCV, Tradutor)
│   └── src/main/res/                         # Layouts, temas escuros e ícones Android
├── .github/workflows/build-apk.yml           # Compilação e geração automática do APK via GitHub Actions
└── build.gradle                              # Configuração de compilação Gradle + Chaquopy
```

---

## 🔒 Repositório e Isolamento

Este repositório foi criado especificamente para a versão **Mobile APK**, mantendo o sistema clássico para PC e Google Colab salvo e intacto no repositório principal:
👉 [SKILL-TRADUCAO-MANGA](https://github.com/Jos9011/SKILL-TRADUCAO-MANGA)
