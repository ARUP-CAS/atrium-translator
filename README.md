# ATRIUM - Lindat Translation Wrapper

A modular Python wrapper for the **Lindat Translation API** [^1]. This tool processes documents with complex layouts 
(PDF, ALTO XML), extracts text in the correct reading order using **LayoutReader** (LayoutLMv3) [^3], 
identifies the source language, and translates the content to English (or other supported languages).

## Features

* **Multi-Format Support**: Accepts `.pdf`, `.txt`, and **ALTO XML** (`.xml`) files.
* **Intelligent Layout Analysis**: Uses **LayoutReader** to reconstruct the correct reading order for PDFs and ALTO XML files, ensuring that multi-column or complex layouts are translated coherently [^3].
* **Language Detection**: Automatically identifies the source language using **FastText** (Facebook) [^5].
* **Lindat API Integration**: Seamlessly connects to the Lindat Translation API (v2) for high-quality translation [^1].
* **ALTO XML Parsing**: Native support for ALTO standards, including coordinate normalization and hyphenation handling.

## Prerequisites

### 1. LayoutReader Dependency
This project relies on the `v3` helper library from the official **LayoutReader** repository [^3]. You must manually 
include this in your project root.

1.  Clone the [LayoutReader]((https://github.com/ppaanngggg/layoutreader.git)) repository:
    ```bash
    git clone https://github.com/ppaanngggg/layoutreader.git
    ```
2.  Copy the `v3` folder from the cloned repository into the root of this project.
    ```bash
    cp -r layoutreader/v3/ ./v3/
    rm -rf layoutreader/  
    ```
3. Create virtual environment and activate it (optional but recommended):
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

### 2. Python Dependencies
Install the required Python packages:

```bash
pip install -r requirements.txt
```

## Project Structure

```text
lindat-wrapper/
├── main.py                 # Entry point for the CLI
├── requirements.txt        # Python dependencies
├── v3/                     # [REQUIRED] Helper folder from LayoutReader repo
├── processors/
│   ├── extractor.py        # Text extraction (ALTO/PDF) + LayoutReader inference
│   ├── identifier.py       # FastText language identification
│   └── translator.py       # Lindat API client
└── utils.py                # ALTO parsing, box normalization, and text reconstruction
```

## Usage

Run the wrapper from the command line. The default target language is English (`en`).

### Basic Usage

```bash
python main.py input_file.pdf
```

### Specifying Output and Target Language

```bash
python main.py document.xml --output translated_doc.txt --target_lang en
```

### Supported Arguments

* `input_file`: Path to the source file (`.pdf`, `.xml`, or `.txt`).
* `--output`: Path to save the translated text (default: `output.txt`).
* `--target_lang`: Target language code (e.g., `en`, `cs`, `fr`). Default is `en`.

## Logic Overview

1. **Extraction**:
* **PDF**: Uses `pdfplumber` to extract words and bounding boxes.
* **ALTO XML**: Parses XML tags to extract content strings and coordinates, normalizing them to the 0-1000 scale required by LayoutLM.


2. **Reordering**: The extracted bounding boxes are passed to the **LayoutReader** model. It predicts the correct reading sequence (0-512 token chunks), fixing issues common in OCR outputs (e.g., reading across columns).
3. **Identification**: The reordered text is analyzed by **FastText** to determine the source language (e.g., `cs`, `de`, `fr`).
4. **Translation**: The text is chunked (to fit API limits) and sent to the **Lindat Translation API**. The results are reassembled into the final output file.


## Acknowledgements 🙏

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