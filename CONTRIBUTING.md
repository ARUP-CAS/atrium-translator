
# 🤝 Contributing to the LINDAT Translation Wrapper of the ATRIUM project

Welcome! This repository [^2] provides a robust workflow for translating archival XML records 
(specifically ALTO XML and AMCR metadata) into English and other target languages. It addresses common challenges 
in digital archives, such as safely translating highly nested XMLs without breaking tags, namespaces, 
or OAI-PMH envelopes.

## 🏗️ Project Contributions & Capabilities

This pipeline contributes 4 major capabilities to the data translation lifecycle, 
as detailed in the section of the main [README 🧠 Logic Overview](README.md#-logic-overview).

### 1. Dedicated Archival XML Processing

The pipeline allows archives to safely translate structured documents without altering their spatial coordinates or metadata schemas.

* **ALTO XML Handling:** Specifically targets and translates only the `CONTENT` attributes 
within `TextBlock` and `TextLine` elements natively.
* **AMCR Metadata Handling:** Uses deep recursive namespace extraction to parse specific elements 
based on custom XPaths and safely replace the text content.

### 2. Multi-Mode Translation Execution

Archive managers can choose processing modes based on their specific document types and workflows:

| Mode                      | Best For...               | Key Feature                                                                              |
|---------------------------|---------------------------|------------------------------------------------------------------------------------------|
| **ALTO XML Mode**         | Scanned document archives | Perfect redistribution of translated words back into exact spatial `CONTENT` attributes. |
| **AMCR Mode**             | Highly nested metadata    | Safely handles OAI-PMH envelopes and translates specific targeted XPath fields.          |
| **Batch & URL Ingestion** | Large-scale collections   | Scans entire directories or downloads/sanitizes XMLs directly from REST URLs.            |

### 3. Automated Language & Quality Controls

A core contribution of this project is minimizing manual preprocessing and providing immediate review tools:

* **Language Identification:** Source text is automatically analyzed using **FastText** [^5]. If the 
confidence score is low (< 0.2), the system safely defaults to Czech (`cs`) to keep the pipeline moving.
* **Space-Aware Chunking:** Intelligently chunks long texts at word boundaries (max 4,000 characters) 
before sending them to the translation API, preventing mid-word truncation errors.
* **QA Logging:** Automatically produces a supplementary CSV file (`file, page_num, line_num, text_src,
text_tgt`) for easy line-by-line manual QA review.
* **Schema Validation:** Optionally validates AMCR outputs against an XSD schema to 
guarantee post-translation structural integrity.

### 4. Seamless API & Configuration Integration

The project includes streamlined interfaces for reproducible archival processing:

* **LINDAT Integration:** Direct connection to the LINDAT/CLARIAH-CZ Translation 
Service API (v2) [^1].
* **Standardized Configs:** Support for `config.txt` to define default input 
paths, target languages, and XPath lists, ensuring consistency across different archival teams.

---

## 📞 Contacts & Acknowledgements

For support or specific archival integration questions, contact **lutsai.k@gmail.com** responsible for this GitHub repository [^2].

* **Developed by:** UFAL [^3]
* **Funded by:** ATRIUM [^4]
* **APIs & Models:** 
  * LINDAT/CLARIAH-CZ Translation Service [^1]
  * Facebook's FastText model [^5]

**©️ 2026 UFAL & ATRIUM**


[^1]: https://lindat.mff.cuni.cz/services/translation/
[^2]: https://github.com/ARUP-CAS/atrium-translator
[^3]: https://ufal.mff.cuni.cz/home-page
[^4]: https://atrium-research.eu/
[^5]: https://huggingface.co/facebook/fasttext-language-identification
