"""
utils.py – ALTO and metadata XML processing utilities for the ATRIUM translation pipeline.

Security note (review finding #2)
---------------------------------
Every input document is parsed with ``_SECURE_PARSER``, which disables external
entity resolution and network access for DTDs and caps tree size, so the tool is
safe to point at untrusted / semi-trusted XML (including files fetched by URL).
XSD schema documents (an explicit, trusted ``--xsd`` input) are parsed with
``_XSD_PARSER``, which still disables entity resolution but permits the network
access that ``xs:import``-based schemas may require.
"""

import difflib
import logging
import sys
import urllib.request

from lxml import etree

from atrium_document import canonical_doc_id

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Output mode (issue #46 — the "replace vs append" question)
# ──────────────────────────────────────────────────────────────────────────────
#
# REPLACE is what this tool has always done and stays the default: the source
# text node is overwritten, so the artifact is a monolingual mirror of the input
# and the Czech survives only in the sidecar `_log.csv`.
#
# APPEND keeps the source and adds the translation beside it. For AMCR metadata
# that is a sibling element distinguished by `xml:lang` — the shape AMCR's own
# thesaurus already uses for `heslo` / `heslo_en`, which `load_vocab.py` reads on
# every glossary build. See `agent_dev_logs/digests/46.digest.md`.
#
# The two modes are a genuine fork in the OUTPUT CONTRACT, not a formatting
# preference, which is why the choice is recorded in paradata and in the document
# record's `translations` block rather than being left implicit.
OUTPUT_MODE_REPLACE = "replace"
OUTPUT_MODE_APPEND = "append"
OUTPUT_MODES = (OUTPUT_MODE_REPLACE, OUTPUT_MODE_APPEND)
DEFAULT_OUTPUT_MODE = OUTPUT_MODE_REPLACE

#: The XML-namespace `lang` attribute in Clark notation. `xml:lang` is a GLOBAL
#: attribute from the XML namespace rather than anything AMCR declares, and the
#: AMCR corpus already carries it on 23 controlled-vocabulary element types — so
#: the schema's import of the XML namespace demonstrably exists. Whether the
#: schema also permits the repeated ELEMENT that append mode emits is the open
#: `maxOccurs` question (#46): this code does not guess, it emits the pair and
#: lets `--xsd` report.
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def normalize_output_mode(value, *, source="output mode"):
    """Coerce *value* to a member of :data:`OUTPUT_MODES`.

    Falls back to the default with a warning rather than raising: an unreadable
    mode string arriving from a config file or an env var should not take a batch
    run down mid-corpus, and the effective mode is recorded in paradata either
    way, so a run is never ambiguous about what it produced.
    """
    if value is None:
        return DEFAULT_OUTPUT_MODE
    candidate = str(value).strip().lower()
    if not candidate:
        return DEFAULT_OUTPUT_MODE
    if candidate not in OUTPUT_MODES:
        logger.warning(
            "Unknown %s %r; falling back to %r (valid: %s).",
            source,
            value,
            DEFAULT_OUTPUT_MODE,
            ", ".join(OUTPUT_MODES),
        )
        return DEFAULT_OUTPUT_MODE
    return candidate


class BatchFallbackCounter:
    """Counts how often page-level batching degraded to one call per item.

    `_translate_batch` sends a whole page's blocks (and separately its lines) as
    ONE newline-joined request, then silently reverts to one request per item when
    the reply does not come back with the same number of lines. The difference is
    roughly 2 calls per page versus one per block plus one per line — for the
    79-page sample in `data_samples/`, ~158 calls against ~3288 — and until this
    counter existed nothing distinguished the two. A run that took twenty minutes
    and a run that took one looked identical in the logs.

    That matters most for the in-production experiment (#46): "it was slow" is not
    actionable feedback, "it fell back on 61 of 79 pages because CUBBITT collapsed
    the newlines" is.
    """

    __slots__ = ("batched", "fallback_mismatch", "fallback_error", "items_retried")

    def __init__(self):
        self.batched = 0
        self.fallback_mismatch = 0
        self.fallback_error = 0
        self.items_retried = 0

    @property
    def fallbacks(self) -> int:
        return self.fallback_mismatch + self.fallback_error

    def as_dict(self) -> dict:
        return {
            "batched": self.batched,
            "fallback_mismatch": self.fallback_mismatch,
            "fallback_error": self.fallback_error,
            "fallbacks": self.fallbacks,
            "items_retried": self.items_retried,
        }

    def summary(self) -> str:
        total = self.batched + self.fallbacks
        return (
            f"{self.batched}/{total} batch calls held their line count; "
            f"{self.fallbacks} fell back to per-item requests "
            f"({self.fallback_mismatch} line-count mismatch, {self.fallback_error} transport error), "
            f"costing {self.items_retried} extra requests"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Hardened parsers
# ──────────────────────────────────────────────────────────────────────────────

# For untrusted input documents: no external entities, no network DTD fetches.
_SECURE_PARSER = etree.XMLParser(
    resolve_entities=False,
    no_network=True,
    load_dtd=False,
    dtd_validation=False,
    huge_tree=False,
)

# For the trusted, explicitly-supplied XSD schema document: still refuse to
# expand entities, but allow network so xs:import/xs:include can resolve.
_XSD_PARSER = etree.XMLParser(
    resolve_entities=False,
    huge_tree=False,
)


# ──────────────────────────────────────────────────────────────────────────────
# XSD validation
# ──────────────────────────────────────────────────────────────────────────────


def load_xsd(xsd_url_or_path: str) -> "etree.XMLSchema":
    """Fetch and compile an XSD schema into an ``etree.XMLSchema`` object.

    Separating network I/O from per-file validation means the schema is
    fetched exactly once per run rather than once per document (M2).
    Raises on any error so callers can abort the run cleanly.
    """
    if not xsd_url_or_path:
        raise ValueError("xsd_url_or_path must be a non-empty string.")
    if xsd_url_or_path.startswith("http"):
        req = urllib.request.Request(
            xsd_url_or_path,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        # 30-second timeout to prevent infinite network hangs.
        with urllib.request.urlopen(req, timeout=30) as f:
            xmlschema_doc = etree.parse(f, parser=_XSD_PARSER)
    else:
        xmlschema_doc = etree.parse(xsd_url_or_path, parser=_XSD_PARSER)
    return etree.XMLSchema(xmlschema_doc)


def validate_xml_with_xsd(xml_tree, xmlschema: "etree.XMLSchema") -> tuple:
    """Validate *xml_tree* against a precompiled *xmlschema*.

    Accepts an ``etree.XMLSchema`` produced by :func:`load_xsd` rather than a
    URL or path, so the caller controls when and how often the schema is
    compiled.
    """
    try:
        if xmlschema.validate(xml_tree):
            return True, ""
        return False, xmlschema.error_log
    except Exception as e:
        return False, f"Validation error: {e}"


# ──────────────────────────────────────────────────────────────────────────────
# Metadata XML processing
# ──────────────────────────────────────────────────────────────────────────────

_AMCR_NS_FALLBACK = "https://api.aiscr.cz/schema/amcr/2.2/"


def _resolve_namespaces(root) -> dict:
    xpath_ns: dict = {}

    for elem in root.iter():
        for prefix, uri in (elem.nsmap or {}).items():
            if not uri:
                continue
            if "amcr" in uri and "amcr" not in xpath_ns:
                xpath_ns["amcr"] = uri
            if "OAI-PMH" in uri and "oai" not in xpath_ns:
                xpath_ns["oai"] = uri
        if "amcr" in xpath_ns and "oai" in xpath_ns:
            break

    if "amcr" not in xpath_ns:
        xpath_ns["amcr"] = _AMCR_NS_FALLBACK
        print(f"[WARN] AMCR namespace not detected in document; falling back to '{_AMCR_NS_FALLBACK}'.")

    return xpath_ns


def _append_translation_sibling(elem, translated, src_lang, tgt_lang):
    """Insert a translated sibling straight after *elem*, keeping the source intact.

    The shape follows AMCR's own multilingual convention: the same tag, the same
    attributes, distinguished by `xml:lang`. AMCR's thesaurus records a concept as
    `<heslo xml:lang="cs">` beside `<heslo_en>` under one `@id`, and
    `load_vocab.py:124-134` reads exactly that pair on every glossary build — so
    this repo already CONSUMES append-shaped AMCR data while, in replace mode, it
    emits replace-shaped output.

    Attributes are copied rather than dropped. For the controlled-vocabulary
    elements that carry `id="HES-…"`, the id identifies the CONCEPT, not the
    string, so the English sibling belongs under the same one — dropping it would
    leave the translation unattributable. `xml:lang` is the single exception: it
    is overwritten with the target language, which is the whole point of the pair.

    Returns the new element, or ``None`` when an equivalent sibling is already
    present (see :func:`_already_appended`).
    """
    if _already_appended(elem, tgt_lang):
        return None

    sibling = etree.Element(elem.tag, nsmap=elem.nsmap)
    for key, value in elem.attrib.items():
        if key != XML_LANG:
            sibling.set(key, value)
    sibling.set(XML_LANG, tgt_lang)
    sibling.text = translated

    # Carry the source element's trailing whitespace onto the new node so the
    # inserted line inherits the document's existing indentation. `pretty_print`
    # is deliberately OFF for this writer (finding #10), so whitespace is ours to
    # get right rather than the serialiser's.
    sibling.tail = elem.tail

    # A bilingual pair is only self-describing if BOTH halves are labelled. The
    # three free-text fields this tool targets (nazev/popis/poznamka) carry no
    # `xml:lang` in any of the 15 shipped AMCR samples, so without this the output
    # would assert English on one element and nothing on its Czech twin.
    if not elem.get(XML_LANG) and src_lang and src_lang != "auto":
        elem.set(XML_LANG, src_lang)

    elem.addnext(sibling)
    return sibling


def _already_appended(elem, tgt_lang) -> bool:
    """True when *elem* is itself a translation, or already has one beside it.

    This is the idempotency guard the tool has never had. In replace mode,
    re-running over an `_en` output silently re-translates English into English —
    with an explicit `--source_lang` there is not even language detection to
    notice. Append mode can do better because its output is self-describing: the
    `xml:lang` marker that makes the pair readable also makes a second pass a
    no-op instead of a duplicate.
    """
    if elem.get(XML_LANG) == tgt_lang:
        return True
    nxt = elem.getnext()
    return nxt is not None and nxt.tag == elem.tag and nxt.get(XML_LANG) == tgt_lang


def process_metadata_xml(
    input_path,
    output_path,
    xpaths,
    translator,
    src_lang,
    tgt_lang,
    xsd_schema=None,
    csv_writer=None,
    identifier=None,
    doc=None,
    backend=None,
    doc_id=None,
    output_mode=DEFAULT_OUTPUT_MODE,
):
    output_mode = normalize_output_mode(output_mode)
    try:
        tree = etree.parse(str(input_path), parser=_SECURE_PARSER)
        root = tree.getroot()
        xpath_ns = _resolve_namespaces(root)

        # D3 (atrium-project#10): the CSV log's `file` column carries the SAME doc_id the
        # caller keyed the document record on, passed in rather than re-derived per row.
        # main.py already computed it via canonical_doc_id(); the old inline
        # `input_path.name.split(".")[0]` was a third independent derivation of the same
        # value, which is how a multi-dot filename ends up logged under one id and recorded
        # under another. `doc_id=None` (a direct caller, e.g. a unit test) still derives it —
        # through the shared function, never by hand.
        log_doc_id = doc_id or canonical_doc_id(input_path)

        translated_texts = []
        appended = 0
        skipped_existing = 0

        for xpath in xpaths:
            try:
                elements = root.xpath(xpath, namespaces=xpath_ns)
                for elem in elements:
                    original_text = elem.text
                    if not original_text or not original_text.strip():
                        continue

                    actual_src_lang = src_lang
                    if src_lang == "auto":
                        if identifier:
                            detected_lang, conf = identifier.detect(original_text)
                            actual_src_lang = detected_lang if conf > 0.2 else "cs"
                        else:
                            actual_src_lang = "cs"

                    # Issue #46, the big question, decided here and nowhere else.
                    # REPLACE overwrites the Czech text node; APPEND leaves it and
                    # inserts a `xml:lang`-marked sibling beside it. Everything
                    # upstream of this point is identical in both modes.
                    if output_mode == OUTPUT_MODE_APPEND and _already_appended(elem, tgt_lang):
                        # Second pass over an already-appended document: skip the
                        # API call entirely rather than translate and discard.
                        skipped_existing += 1
                        continue

                    translated = translator.translate(original_text, actual_src_lang, tgt_lang)

                    if output_mode == OUTPUT_MODE_APPEND:
                        _append_translation_sibling(elem, translated, actual_src_lang, tgt_lang)
                        appended += 1
                    else:
                        elem.text = translated

                    translated_texts.append(translated)

                    if csv_writer:
                        csv_writer.writerow([log_doc_id, "", xpath, original_text, translated])

            except etree.XPathError as e:
                print(f"[WARN] XPath error for '{xpath}': {e}")

        # ATRIUM Document JSON accretion update for metadata blocks.
        #
        # `translations` is metadata about the language pair/backend, per the
        # schema (`{source_lang, target_lang, backend}`) — NOT the translated
        # corpus text itself, which already persists via `derived_from.translated_xml`.
        #
        # Entity translation (`entities[].translation_en`) is NOT attempted here, and as of
        # today no code path in this repo writes that field at all — it is UNIMPLEMENTED,
        # not merely deferred (atrium-project#10, finding D7).
        #
        # Why it is absent here: in the declared pipeline order (pc→alto→translate→nlp→llm),
        # `entities[]` is produced by nlp-enrich, which runs AFTER the translator. `entities`
        # does not exist yet at this point in any real run, so a per-entity translation pass
        # in this function would be unreachable dead code (issue #13 alignment audit, P0.6).
        #
        # This repo is nonetheless the field's declared OWNER — see the ownership table in the
        # hub's `docs/document_schema.md` and `BLOCK_FIELD_OWNERS["entities"]["translator"]` in
        # atrium_document.py — so the gap is ours to close, not another tool's. Resolving it
        # needs a SECOND pass over an already-enriched record: read `entities` via
        # `doc.get_block("entities")`, translate each `surface`, and `merge_block("entities",
        # rows, own_fields=["translation_en"])` back (followed by
        # `assert_fields_survived("entities", rows, ["translation_en"])`, so a grant mistake
        # cannot silently drop the field). That is a feature, tracked as still-open; the
        # earlier citation here pointed at `agent_dev_logs/digests/13.digest.md`, which does
        # not exist in this repo.
        if output_mode == OUTPUT_MODE_APPEND:
            logger.info(
                "%s: append mode wrote %d translated sibling(s); %d field(s) already carried one.",
                log_doc_id,
                appended,
                skipped_existing,
            )

        if doc is not None:
            doc.set_block(
                "translations",
                {
                    "source_lang": src_lang,
                    "target_lang": tgt_lang,
                    "backend": backend or "lindat",
                    # #46: which shape this artifact actually has. `additionalProperties`
                    # is true on this block, so recording it needs no schema change —
                    # and a consumer that finds English in a field needs to know whether
                    # the Czech was kept beside it or overwritten.
                    "output_mode": output_mode,
                },
            )

        if xsd_schema:
            print(f"[INFO] Validating {output_path.name} against XSD …")
            is_valid, error_log = validate_xml_with_xsd(tree, xsd_schema)
            if is_valid:
                print(f"[SUCCESS] XSD validation passed for {output_path.name}")
            else:
                print(f"[WARN] XSD validation failed:\n{error_log}")

        # pretty_print is intentionally OFF: it reflows whitespace and can perturb
        # significant whitespace in mixed-content elements (finding #10). Leaving
        # it off keeps the output diff minimal against the source tree.
        tree.write(
            str(output_path),
            encoding="utf-8",
            xml_declaration=True,
            pretty_print=False,
        )
        print(f"[SUCCESS] Saved metadata translation → {output_path}")

    except Exception as e:
        print(f"[ERROR] Failed to process metadata XML '{input_path}': {e}")
        raise


# ──────────────────────────────────────────────────────────────────────────────
# ALTO XML processing Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _align_tokens_to_lines(block_text, line_translations):
    """
    Partitions the high-quality block translation into buckets corresponding
    to physical XML lines, using the lower-quality line translations as anchors.
    """
    block_tokens = block_text.split() if block_text else []
    if not block_tokens:
        return [[] for _ in line_translations]
    if len(line_translations) <= 1:
        return [block_tokens]

    assigned_buckets = []
    remaining_tokens = block_tokens

    for line_tgt in line_translations[:-1]:
        line_tokens = line_tgt.split() if line_tgt else []
        expected_len = len(line_tokens)

        # If the original line had no text, assign 0 tokens
        if expected_len == 0 or not remaining_tokens:
            assigned_buckets.append([])
            continue

        # Define a sliding window search range (+/- 50% of expected words)
        min_idx = max(0, int(expected_len * 0.5) - 1)
        max_idx = min(len(remaining_tokens), int(expected_len * 1.5) + 2)

        best_idx = 0
        best_ratio = -1.0

        # Find the split point that maximizes similarity to the line translation anchor
        for split_idx in range(min_idx, max_idx + 1):
            candidate_str = " ".join(remaining_tokens[:split_idx])
            ratio = difflib.SequenceMatcher(None, candidate_str, line_tgt).ratio()

            if ratio > best_ratio:
                best_ratio = ratio
                best_idx = split_idx

        assigned_buckets.append(remaining_tokens[:best_idx])
        remaining_tokens = remaining_tokens[best_idx:]

    # The final line gets whatever tokens are left over
    assigned_buckets.append(remaining_tokens)
    return assigned_buckets


def _align_tokens_proportional(block_text, source_line_texts):
    """
    Anchor-free alternative to :func:`_align_tokens_to_lines` (review finding #4).

    Distributes the Pass-1 block tokens across physical lines in proportion to
    each line's *source* word count, so no per-line translation API call is
    needed. Honours the same invariants the reconstruction relies on:
      * token conservation (no token lost, reordered, or duplicated);
      * one bucket per line;
      * empty source line → empty bucket;
      * the final line absorbs the remainder.

    Used only when ``process_alto_xml(..., line_anchors=False)`` (the ``--fast-align``
    CLI flag). The default path still uses the similarity-anchored aligner.
    """
    block_tokens = block_text.split() if block_text else []
    if not block_tokens:
        return [[] for _ in source_line_texts]
    if len(source_line_texts) <= 1:
        return [block_tokens]

    counts = [len(t.split()) if t else 0 for t in source_line_texts]
    total = sum(counts)

    # No source words anywhere: dump everything into the last line.
    if total == 0:
        return [[] for _ in source_line_texts[:-1]] + [block_tokens]

    buckets = []
    remaining = block_tokens
    for cnt in counts[:-1]:
        if cnt == 0 or not remaining:
            buckets.append([])
            continue
        take = round(len(block_tokens) * cnt / total)
        take = max(0, min(take, len(remaining)))
        buckets.append(remaining[:take])
        remaining = remaining[take:]
    buckets.append(remaining)  # final line takes the remainder
    return buckets


# ──────────────────────────────────────────────────────────────────────────────
# ALTO XML processing
# ──────────────────────────────────────────────────────────────────────────────


def _label_alto_language(root, tgt_lang) -> int:
    """Stamp the target language on ALTO text elements. Returns how many were touched.

    ALTO 4 defines a ``LANG`` attribute on ``TextBlock``, ``TextLine`` and
    ``String``; ALTO 3 defines ``language`` on ``TextBlock``. This writes ``LANG``
    on the block level only — one attribute per block rather than per word, which
    is where the claim is actually true: the block text IS a translation of the
    block, while the per-``String`` split is manufactured (see the caller's
    docstring).

    Without this the output is unlabelled English. That is the defect worth fixing
    regardless of which way the replace/append question is finally settled: a
    consumer currently cannot distinguish a translated ALTO from a Czech original
    except by reading the text.
    """
    if not tgt_lang:
        return 0
    touched = 0
    # `root.iter()` yields comments and processing instructions as well as elements,
    # and their `.tag` is a callable rather than a string — `etree.QName` raises
    # ValueError on those. Real ALTO from a scanner routinely carries comments, so
    # this guard is what keeps append mode from dying on ordinary production input.
    for elem in root.iter():
        if not isinstance(elem.tag, str):
            continue
        if etree.QName(elem).localname == "TextBlock":
            elem.set("LANG", tgt_lang)
            touched += 1
    return touched


def process_alto_xml(
    input_path,
    output_path,
    translator,
    src_lang,
    tgt_lang,
    csv_writer=None,
    identifier=None,
    line_anchors=True,
    doc=None,
    backend=None,
    doc_id=None,
    output_mode=DEFAULT_OUTPUT_MODE,
):
    """
    Translate an ALTO XML document in place (dual-pass reconstruction).

    Implements Page-Level Batching (Issue #16): Pools block and line translation
    requests per page to eliminate heavy API call overhead, falling back to
    1-by-1 processing if the NMT model modifies layout boundaries.

    *doc_id* is the caller's canonical doc_id for this document, used verbatim as the CSV
    log's ``file`` column; see the metadata-path twin for why it is passed in (D3).

    OUTPUT MODE (issue #46). ALTO honours the flag by LABELLING, never by
    duplicating. Appending a translation per ``String`` would be incoherent here:
    the word-to-box correspondence in the output is manufactured by
    :func:`_align_tokens_to_lines`, which splits ONE block translation on
    whitespace and re-buckets it by ``difflib`` similarity — so a per-``String``
    English "alternative" would not be an alternative reading of that word, it
    would be whichever token the bucketing happened to land there. Duplicating it
    would multiply a fiction rather than preserve evidence.

    What append mode does instead is make the artifact honest about itself: the
    target language is stamped on the text elements and a processing step is
    recorded, so a consumer can tell the file is machine-translated English rather
    than inferring it by reading. The ``String`` inventory stays 1:1 with the
    source in BOTH modes. See ``agent_dev_logs/digests/46.digest.md`` for the
    measurement behind this (224 blanked and 304 over-filled boxes of 7229 on the
    shipped sample, none resized).
    """
    output_mode = normalize_output_mode(output_mode)
    fallback_counter = BatchFallbackCounter()
    try:
        # D3: one doc_id per document, supplied by the caller (main.py) or derived through
        # the shared canonical_doc_id() — never hand-rolled here. See process_metadata_xml.
        log_doc_id = doc_id or canonical_doc_id(input_path)

        tree = etree.parse(str(input_path), parser=_SECURE_PARSER)
        root = tree.getroot()

        nsmap = root.nsmap
        ns = {"alto": nsmap[None]} if None in nsmap else nsmap
        use_ns = "alto" in ns

        pages = root.xpath("//alto:Page", namespaces=ns) if use_ns else root.xpath("//Page")
        total_pages = len(pages)

        full_translated_blocks = []

        for page_idx, page in enumerate(pages, 1):
            text_blocks = page.xpath(".//alto:TextBlock", namespaces=ns) if use_ns else page.xpath(".//TextBlock")
            page_lines = page.xpath(".//alto:TextLine", namespaces=ns) if use_ns else page.xpath(".//TextLine")

            num_blocks = len(text_blocks)
            num_lines = len(page_lines)

            print(f"[INFO] Page {page_idx}/{total_pages} - Found {num_blocks} text blocks and {num_lines} text lines.")

            # ──────────────────────────────────────────────────────────────────
            # PHASE 1: Gather original line structures and block text
            # ──────────────────────────────────────────────────────────────────
            page_blocks_data = []
            for block_idx, block in enumerate(text_blocks, 1):
                lines = block.xpath(".//alto:TextLine", namespaces=ns) if use_ns else block.xpath(".//TextLine")

                all_strings = []
                lines_data = []

                for line_idx, line in enumerate(lines, 1):
                    line_id = line.get("ID", str(line_idx))
                    strings = line.xpath(".//alto:String", namespaces=ns) if use_ns else line.xpath(".//String")

                    orig_line_text = " ".join(s.get("CONTENT", "") for s in strings if s.get("CONTENT")).strip()
                    lines_data.append(
                        {
                            "id": line_id,
                            "strings": strings,
                            "orig_text": orig_line_text,
                            "trans_line_text": "",
                        }
                    )
                    all_strings.extend(strings)

                block_text = " ".join(ld["orig_text"] for ld in lines_data if ld["orig_text"]).strip()
                if not block_text or not all_strings:
                    continue

                actual_src_lang = src_lang
                if src_lang == "auto":
                    if identifier:
                        detected_lang, _ = identifier.detect(block_text)
                        actual_src_lang = detected_lang
                    else:
                        actual_src_lang = "cs"

                page_blocks_data.append(
                    {
                        "block_idx": block_idx,
                        "lines_data": lines_data,
                        "block_text": block_text,
                        "actual_src_lang": actual_src_lang,
                        "block_tgt": "",
                    }
                )

            if not page_blocks_data:
                continue

            # ──────────────────────────────────────────────────────────────────
            # PHASE 2: Page-Level Batch Translation (Grouped by Language)
            # ──────────────────────────────────────────────────────────────────
            lang_groups = {}
            for bdata in page_blocks_data:
                lang_groups.setdefault(bdata["actual_src_lang"], []).append(bdata)

            def _translate_batch(texts, lang):
                """Helper to join texts with newlines, translate, and validate boundaries."""
                if not texts:
                    return []

                # Filter out empty line/block placeholders to preserve spacing structures
                valid_map = [(i, t) for i, t in enumerate(texts) if t.strip()]
                if not valid_map:
                    return [""] * len(texts)

                valid_indices, valid_texts = zip(*valid_map)
                joined_text = "\n".join(valid_texts)

                try:
                    translated_joined = translator.translate(joined_text, lang, tgt_lang)
                    translated_lines = [t.strip() for t in translated_joined.split("\n")]

                    # Validate the layout structure matches original elements exactly
                    if len(translated_lines) == len(valid_texts):
                        fallback_counter.batched += 1
                        results = [""] * len(texts)
                        for idx, res_line in zip(valid_indices, translated_lines):
                            results[idx] = res_line
                        return results

                    # The model answered, but collapsed or added newlines, so the
                    # reply cannot be mapped back onto the layout. Counted, not
                    # silent: this is the common degradation and it is invisible in
                    # the output — only the wall-clock changes (issue #46).
                    fallback_counter.fallback_mismatch += 1
                    logger.debug(
                        "Batch line count %d != %d expected; retrying %d item(s) individually.",
                        len(translated_lines),
                        len(valid_texts),
                        len(valid_texts),
                    )
                except Exception as exc:
                    # Was `except Exception: pass`. Swallowing the reason is what
                    # made a 20x slowdown indistinguishable from a fast run.
                    fallback_counter.fallback_error += 1
                    logger.warning(
                        "Batch translation call failed (%s: %s); retrying %d item(s) individually.",
                        type(exc).__name__,
                        exc,
                        len(valid_texts),
                    )

                # Safe fallback: revert to 1-by-1 requests for this batch if layout breaks
                fallback_counter.items_retried += len(valid_texts)
                return [translator.translate(t, lang, tgt_lang) if t.strip() else "" for t in texts]

            for lang, group in lang_groups.items():
                # Pass 1: Batch translate full blocks
                block_texts = [b["block_text"] for b in group]
                translated_blocks = _translate_batch(block_texts, lang)
                for bdata, tgt in zip(group, translated_blocks):
                    bdata["block_tgt"] = tgt

                # Pass 2: Batch translate lines as structural anchors
                if line_anchors:
                    line_texts = []
                    line_refs = []
                    for bdata in group:
                        for ld in bdata["lines_data"]:
                            line_texts.append(ld["orig_text"])
                            line_refs.append(ld)

                    translated_lines = _translate_batch(line_texts, lang)
                    for ld, tgt in zip(line_refs, translated_lines):
                        ld["line_tgt"] = tgt

            # ──────────────────────────────────────────────────────────────────
            # PHASE 3: Redistribution & Logging (Downstream Logic Untouched)
            # ──────────────────────────────────────────────────────────────────
            for bdata in page_blocks_data:
                sys.stdout.write(
                    f"\r[INFO] Page {page_idx}/{total_pages} | Processing block {bdata['block_idx']}/{num_blocks}"
                )
                sys.stdout.flush()

                block_tgt = bdata["block_tgt"]
                if block_tgt:
                    full_translated_blocks.append(block_tgt)

                lines_data = bdata["lines_data"]

                if line_anchors:
                    line_translations = [ld.get("line_tgt", "") for ld in lines_data]
                    aligned_token_buckets = _align_tokens_to_lines(block_tgt, line_translations)
                else:
                    aligned_token_buckets = _align_tokens_proportional(
                        block_tgt, [ld["orig_text"] for ld in lines_data]
                    )

                for ld, assigned_tokens in zip(lines_data, aligned_token_buckets):
                    num_strings = len(ld["strings"])
                    if num_strings == 0:
                        continue

                    for i, string_elem in enumerate(ld["strings"]):
                        if i < num_strings - 1:
                            if i < len(assigned_tokens):
                                string_elem.set("CONTENT", assigned_tokens[i])
                            else:
                                string_elem.set("CONTENT", "")
                        else:
                            string_elem.set("CONTENT", " ".join(assigned_tokens[i:]))

                    ld["trans_line_text"] = " ".join(assigned_tokens)

                if csv_writer:
                    for ld in lines_data:
                        if ld["orig_text"] or ld["trans_line_text"]:
                            csv_writer.writerow(
                                [log_doc_id, page_idx, ld["id"], ld["orig_text"], ld["trans_line_text"]]
                            )

            if num_blocks > 0:
                print()

        # Throughput reality, reported once per document. A run that batched cleanly
        # and a run that fell back on every page differ by an order of magnitude in
        # LINDAT calls and by nothing at all in the output — this line is the only
        # place that difference is visible (issue #46).
        if fallback_counter.fallbacks:
            logger.warning("%s: %s.", log_doc_id, fallback_counter.summary())
        else:
            logger.info("%s: %s.", log_doc_id, fallback_counter.summary())

        if output_mode == OUTPUT_MODE_APPEND:
            labelled = _label_alto_language(root, tgt_lang)
            logger.info(
                "%s: append mode labelled %d ALTO element(s) as '%s'. Per-String append is "
                "deliberately not implemented — see process_alto_xml's docstring.",
                log_doc_id,
                labelled,
                tgt_lang,
            )

        # ATRIUM Document JSON accretion update for ALTO blocks. See the metadata-path
        # twin above for why `translations` carries language-pair metadata (not the
        # translated corpus text), and for the state of `entities[].translation_en` — a
        # field this repo owns and no code path here writes (D7, still open).
        if doc is not None:
            doc.set_block(
                "translations",
                {
                    "source_lang": src_lang,
                    "target_lang": tgt_lang,
                    "backend": backend or "lindat",
                    # Batch-vs-fallback telemetry deliberately does NOT go here.
                    # `translations` is a schema-governed block in a record shared
                    # across all six repos; per-run throughput counts are transient
                    # diagnostics, not a durable fact about the document. They are
                    # reported on the log stream instead (see the summary above),
                    # which is where an operator running the #46 experiment reads
                    # them. ParadataLogger has no per-document fact API to put them
                    # in — only skips, successes and components.
                    "output_mode": output_mode,
                },
            )

        tree.write(str(output_path), encoding="utf-8", xml_declaration=True)
        print(f"[SUCCESS] Saved ALTO translation → {output_path}")

    except Exception as e:
        print(f"\n[ERROR] Failed to process ALTO XML '{input_path}': {e}")
        raise
