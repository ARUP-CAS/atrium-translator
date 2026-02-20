# 🏛️ ATRIUM - Lindat Translation Wrapper 🌍

A modular Python wrapper for the **Lindat Translation API** [^1]. This tool processes various document types 
(including PDF, ALTO XML, DOCX, HTML, CSV, and JSON), extracts text in the correct reading order using **LayoutReader** 
(LayoutLMv3) [^3] for complex layouts, identifies the source language, and translates the content to English (or other supported languages).

## 📚 Table of Contents

- [Features](#-features)
- [Prerequisites](#-prerequisites)
  - [LayoutReader Dependency](#1--layoutreader-dependency)
  - [Python Dependencies](#2--python-dependencies)
- [Project Structure](#-project-structure)
- [Usage](#-usage)
  - [Basic Usage](#-basic-usage-flat-text-extraction)
  - [Specifying Output and Target Language](#-targeted-xml-translation-in-place)
  - [Supported Arguments](#-supported-arguments)
- [Logic Overview](#-logic-overview)
- [Acknowledgements](#-acknowledgements)

---

## ✨ Features

* 📄 **Multi-Format Support**: Accepts `.pdf`, `.xml` (ALTO), `.txt`, `.docx`, `.html`/`.htm`, `.csv`, and `.json` files.
* 🎯 **Targeted In-Place XML Translation**: Translates specific, user-defined XML fields (e.g., ALTO `CONTENT` attributes or standard tags) while strictly preserving the original document structure and namespaces.
* 🧠 **Intelligent Layout Analysis**: Uses **LayoutReader** to reconstruct the correct reading order for PDFs and standard ALTO XML extractions, ensuring that multi-column or complex layouts are translated coherently [^3]).
* 🕵️ **Language Detection with Intelligent Fallback**: Automatically identifies the source language using **FastText** (Facebook) [^6]. If the detection confidence is low (< 0.4), it automatically defaults to Czech (`cs`) to ensure the pipeline continues.
* 🔗 **Lindat API Integration**: Seamlessly connects to the Lindat Translation API (v2) for high-quality translation, including automatic cache handling to minimize redundant requests for identical XML strings [^1]).
* 📐 **ALTO XML Parsing**: Native support for ALTO standards, including coordinate normalization and hyphenation handling.

## 🛠️ Prerequisites

### 1. 📚 LayoutReader Dependency

This project relies on the `v3` helper library from the official **LayoutReader** repository [^3]). You must manually
include this in your project root.

1. Clone the [LayoutReader](https://github.com/ppaanngggg/layoutreader)) repository:
```bash
git clone https://github.com/ppaanngggg/layoutreader.git
```

2. Copy the `v3` folder from the cloned repository into the root of this project.
```bash
cp -r layoutreader/v3/ ./v3/
rm -rf layoutreader/  
```

3. Create virtual environment and activate it (optional but recommended):
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 2. 🐍 Python Dependencies

Install the required Python packages:
```bash
pip install -r requirements.txt
```

## 📂 Project Structure

```text
lindat-wrapper/
├── main.py                 # 🚀 Entry point for the CLI, routing standard vs. in-place XML processing
├── requirements.txt        # 📦 Python dependencies
├── xml-fields.txt          # 📄 List of XML tags to extract text from (for targeted XML translation)
├── v3/                     # ⚠️ [REQUIRED] Helper folder from LayoutReader repo
├── processors/
│   ├── extractor.py        # 📄 Text extraction (ALTO/PDF/DOCX/HTML/CSV/JSON) + LayoutReader inference
│   ├── identifier.py       # 🌍 FastText language identification (ISO 639-3 to 639-1 mapping)
│   └── translator.py       # 🔄 Lindat API client with dynamic model fetching
└── utils.py                # 🔧 ALTO parsing, box normalization, and XML tree reconstruction
```

## 💻 Usage

Run the wrapper from the command line. The default target language is English (`en`).

### ▶️ Basic Usage (Flat Text Extraction)

```bash
python main.py input_file.pdf
```

### 🎯 Targeted XML Translation (In-Place)

Use this mode to translate specific XML elements while outputting a fully intact `.xml` file:

```bash
python main.py document.xml --fields xml-fields.txt --target_lang en
```

### ⚙️ Supported Arguments

* `input_file`: Path to the source file (`.pdf`, `.xml`, `.txt`, `.docx`, `.html`, `.csv`, `.json`).
* `--fields`: Path to a `.txt` file containing XML tags to translate (one per line). Triggers the in-place XML processing mode.
* `--output`: Path to save the translated text. Defaults to `<input_name>_<target_lang>.txt` (or `.xml` if using `--fields`) in the same directory.
* `--target_lang`: Target language code (e.g., `en`, `cs`, `fr`). Default is `en`.

## 🧠 Logic Overview

1. **📥 Standard Extraction**:
   * **PDF**: Uses `pdfplumber` to extract words and bounding boxes.
   * **DOCX**: Extracts paragraph text linearly.
   * **HTML**: Uses `BeautifulSoup` to safely extract text without merging words across tags.
   * **CSV**: Uses `pandas` to isolate and concatenate text specifically from columns containing "text" in their headers.
   * **JSON**: Recursively searches for and extracts string values from keys containing the word "text".
2. **🧩 Reordering**: For PDFs and raw XML extractions, bounding boxes are passed to the **LayoutReader** model. It predicts the correct reading sequence in chunks of 350 tokens, fixing issues common in OCR outputs (e.g., reading across columns).
3. **🏛️ Targeted XML Processing** : When `--fields` is provided, the script parses the XML tree, matches the specified tags, and extracts the target text (prioritizing ALTO's `CONTENT` attributes over standard inner text). The translated text is directly injected back into the tree, and the file is saved with its original namespaces intact.
4. **🔎 Identification**: The text is analyzed by **FastText** to determine the source language (mapping ISO 639-3 to ISO 639-1). If the confidence score is below `0.4`, the system automatically defaults to Czech (`cs`).
5. **🗣️ Translation**: Text is passed to the **Lindat Translation API**. In XML mode, unique strings are cached to minimize API limits; otherwise, long texts are chunked into 5,000-character segments to respect Lindat's payload constraints.

## 🙏 Acknowledgements

**For support write to:** lutsai.k@gmail.com responsible for this GitHub repository [^2] 🔗

- **Developed by** UFAL [^7] 👥
- **Funded by** ATRIUM [^4]  💰
- **Shared by** ATRIUM [^4] & UFAL [^7] 🔗
- **Translation API**: Lindat/CLARIAH-CZ Translation Service [^1] 🔗
- **Layout Analysis**: LayoutReader (LayoutLMv3) [^3] 🔗
- **Language Identification**: Facebook FastText [^5] 🔗

**©️ 2026 UFAL & ATRIUM**

[^1]: https://lindat.mff.cuni.cz/services/translation/
[^2]: https://github.com/K4TEL/atrium-translator
[^3]: https://github.com/FreeOCR-AI/layoutreader
[^4]: https://atrium-research.eu/
[^5]: https://huggingface.co/facebook/fasttext-language-identification
[^8]: https://github.com/K4TEL/atrium-nlp-enrich
[^7]: https://ufal.mff.cuni.cz/home-page