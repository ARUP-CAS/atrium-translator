## Sample outputs

The same inputs (`my_documents/`) translated in both output modes of issue #46, one folder per mode and per
input kind:

```
data_samples/
├── my_documents/                 inputs: 15 AMCR metadata records + MTX201501307_anon.alto.xml
├── in-place_translated_files/    --output-mode replace (the default)
│   ├── alto/                     the ALTO sample                         (lindat)
│   └── xml/                      the AMCR records                        (ct2 — EuroLLM-1.7B, see below)
└── appended_translated_files/    --output-mode append
    ├── alto/                                                             (lindat)
    └── xml/                                                              (lindat)
```

Which run produced each folder — each `paradata/` folder holds that run's record:

| Folder                           | Backend                                          | `--source_lang` | `--xsd`  | Run             | Log `status`             |
|----------------------------------|--------------------------------------------------|-----------------|----------|-----------------|--------------------------|
| `in-place_translated_files/alto` | `lindat` (LINDAT CUBBITT)                        | `auto`          | —        | `260926-122251` | 2095 `ok`                |
| `appended_translated_files/alto` | `lindat`                                         | `auto`          | —        | `260926-120736` | 2095 `ok`                |
| `in-place_translated_files/xml`  | **`ct2`** — EuroLLM-1.7B-Instruct, int8, CPU     | `cs`            | AMCR 2.2 | `260927-084401` | 30 `ok`, 7 `untranslated` |
| `appended_translated_files/xml`  | `lindat`                                         | `auto`          | —        | `260926-140310` | 37 `ok`                  |

> **The AMCR replace folder is a `ct2` run, not the LINDAT default** that AMČR's production run uses. It was
> made on 2026-09-27 with the self-hosted backend of issue #4 (EuroLLM-1.7B-Instruct converted to CTranslate2 int8,
> `--vocabulary data_samples/vocabulary.csv`, all 15 records valid against AMCR 2.2). Two things to know when reading
> it:
>
> * **13 of its 30 `ok` fields contain the prompt glossary**, not only the translation — e.g. `C-N1000019`
>   `poznamka` starts with `Use these exact terms: point = point`, and `C-DT-100003326` `popis` is nothing but
>   `Terrain edge = terrain edge; Hillfort = hillfort`. That run predates the fix in `processors/ct2_translator.py`
>   (glossary moved out of the text, echoed prompt removed, a glossary-only or copied reply re-requested without the
>   glossary). Replayed on these 37 replies, the fix cleans 6, re-requests 7 and leaves the other 17 as they are.
>   Regenerate the folder with the command below before quoting it.
> * The 7 `untranslated` fields were still rejected after the end-of-document re-run (a length ratio of 0.12–0.21
>   on long fields, 5.9 and 88 on two short `nazev` fields, a runaway reply for a one-word `poznamka`): their Czech
>   is kept and the target cell of the log is empty, as the guard intends.
>
> For the LINDAT replace output of the same records, use `--backend lindat` (the default) with the replace command
> below; the last committed LINDAT replace set is in git history at `3bc8a0e` (run `260926-140045`).

Each folder holds, per input document:

| File                                 | Content                                                                                                                     |
|--------------------------------------|-----------------------------------------------------------------------------------------------------------------------------|
| `<doc>_en.alto.xml` / `<doc>_en.xml` | the translated document                                                                                                     |
| `<doc>_log.csv`                      | QA log: `file, page_num, line_num, text_<src>, text_en, status` — one row per ALTO line / metadata field, in document order |
| `<doc>.document.json`                | the ATRIUM Document record (`translations.output_mode`, `translations.detected_source_lang` with `source_lang=auto`)        |
| `paradata/<run>_translator.json`     | the run's provenance record (configuration incl. the language policy, licences, counts)                                     |

What the two modes look like:

* **replace, ALTO** — every `String/@CONTENT` holds the English words aligned to that box; an existing block
  `LANG` is moved to `en`.
* **append, ALTO** — every `CONTENT` is the scanned Czech, untouched; the English for that box is in
  `<ALTERNATIVE PURPOSE="translation:en">` inside the `String`.
* **replace, AMCR** — the targeted field's text is English.
* **append, AMCR** — the Czech field is kept (and gets `xml:lang="cs"`), followed by a sibling with the same tag
  and `xml:lang="en"`.

Against the published schemas: the ALTO source, replace and append files all validate against **ALTO 3.1**; the AMCR
records validate against **AMCR 2.2** as source (15/15) and as replace output (15/15), and **not** as append output
(0/15 — `xml:lang` is not declared on the free-text fields and the repeated element is not allowed there). Check a
folder with `--xsd https://api.aiscr.cz/schema/amcr/2.2/amcr.xsd` on a metadata run.

`status` in the log is `ok`, `rerun` (the backend's reply was degenerate and the end-of-document re-run
recovered it), `approx_alignment` (ALTO: the line's anchor was unusable, so its words were placed by word count)
or `untranslated` (still degenerate after the re-run — the source text was kept, the target cell is empty). A table
column whose block translation merged repeated cells (page 76 of the ALTO sample) is placed line by line, each cell
from its own translation, so no number moves to its neighbour's row.

> The `.document.json` of both ALTO samples and of the first AMCR record of the append folder state **CC BY-NC 4.0**
> (`fasttext` only): they were written before the backend's licence components were recorded, which later code
> fixes. Those runs' paradata and their other records state the run's actual licence, **CC BY-NC-SA 4.0**. The next
> LINDAT refresh below rewrites them. The `ct2` replace folder states **CC BY-NC 4.0** because of the AMCR/TEATER
> vocabulary, which was labelled CC BY-NC 4.0 when it ran. AMČR, the rights holder, has since stated that both
> vocabularies are CC0 ([atrium-project#6](https://github.com/ufal/atrium-project/issues/6#issuecomment-5867861653),
> 2026-09-28), so the same run now resolves to **MIT** (CTranslate2; EuroLLM is Apache-2.0). The committed records keep
> the label they were written with.
>
> **`vocabulary.csv`** (AMCR `heslo` + TEATER terms, harvested by `load_vocab.py`) is **CC0** per that statement. The
> other files here stay under [LICENSE](LICENSE) (CC BY-NC 4.0).

### Regenerating them

Run from the repository root, **one command at a time** — concurrent runs against the public LINDAT endpoint
coincided with the degenerate replies that motivated the guard — and commit a folder only after its run has printed
`PROCESSING COMPLETE`: each document's log, XML and record are replaced only when that document is finished. Remove
the old run records first so each `paradata/` folder holds the record of the run that produced its files:

```bash
rm -f data_samples/*/*/paradata/*.json

# ALTO
python main.py data_samples/my_documents/MTX201501307_anon.alto.xml --alto \
    --source_lang auto --vocabulary data_samples/vocabulary.csv \
    --output data_samples/in-place_translated_files/alto --output-mode replace
python main.py data_samples/my_documents/MTX201501307_anon.alto.xml --alto \
    --source_lang auto --vocabulary data_samples/vocabulary.csv \
    --output data_samples/appended_translated_files/alto --output-mode append

# AMCR metadata (a metadata run leaves *.alto.xml out of a directory scan) — LINDAT
python main.py data_samples/my_documents --xpaths amcr-fields.txt --formats xml \
    --source_lang auto --vocabulary data_samples/vocabulary.csv \
    --output data_samples/in-place_translated_files/xml --output-mode replace
python main.py data_samples/my_documents --xpaths amcr-fields.txt --formats xml \
    --source_lang auto --vocabulary data_samples/vocabulary.csv \
    --output data_samples/appended_translated_files/xml --output-mode append
```

The committed AMCR replace folder is the `ct2` run instead — the self-hosted EuroLLM backend (issue #4; install
`requirements-ct2.txt`, convert the model as in [docs/translation-backends.md](../docs/translation-backends.md)):

```bash
export CT2_MODEL_DIR="$PWD/models/ct2/eurollm-1.7b-int8" CT2_MODEL_FAMILY=eurollm \
       CT2_TOKENIZER_DIR="$PWD/models/hf/EuroLLM-1.7B-Instruct" \
       CT2_DEVICE=cpu CT2_COMPUTE_TYPE=int8 CT2_LANGUAGES=cs,en
rm -f data_samples/in-place_translated_files/xml/paradata/*.json
python main.py data_samples/my_documents --xpaths amcr-fields.txt --formats xml \
    --backend ct2 --source_lang cs --vocabulary data_samples/vocabulary.csv \
    --xsd https://api.aiscr.cz/schema/amcr/2.2/amcr.xsd \
    --output data_samples/in-place_translated_files/xml --output-mode replace
```

## Sample inputs

### MTX201501307.alto.xml anonymized to be used as a translator test input:

Only `String CONTENT="..."` values were touched. All XML structure, namespaces, schema reference, ParagraphStyle IDs,
block/line/glyph geometry (HPOS/VPOS/HEIGHT/WIDTH), coordinates, and the survey-point dump at the end are byte-identical.
The BOM and CRLF line endings are preserved exactly, and the file still validates as ALTO v3 XML and has the same **5527** lines.

Grammar preserved via inflection-aware mapping. Czech declines names heavily, so each inflected surface form maps to
a matching invented form in the same case/paradigm — e.g. `Nového Města` → `Starého Sídla`, `Nedvědička`/`Nedvědičkou`
→ `Vrbice`/`Vrbicí`, `Heralt`/`Heraltovi`/`Heraltově` → `Načerat`/`Načeratovi`/`Načeratově`. Punctuation attached to
tokens (commas, periods, citation parens, quotes) is stripped, matched, and reattached, so bibliography entries and
parenthetical citations keep their shape.

#### Entities replaced (95 distinct surface forms):

- Village `Zubří` → `Vraní`, with the etymology line kept coherent (`"místo kde jsou zubři"` → `"místo kde jsou vrány"`,
both matching the new crow-derived name).

- Places/hydronyms: `Nové Město na Moravě`, `Praha-Chodov`, `Žďár nad Sázavou`, `Jihlava`, `Brno`,
`Bítešská vrchovina`, `Harusův kopec`, `Nedvědička`/`Divišovský potok`, `Olešná`, `Lažínek`, `Jevišovka`,
`Střelice`, `Loučka`, `Olešínky`, `Pohledec`, `Jimramov`, plus historical estates (`Bystřice`, `Pyšolec`,
`Kunštát`, `Pernštejn`, `Ditrichštejn`, `Boskovice`, etc.).

- Team members (`Baier`, `Kaiser`, `Bařinka`, `Švácha`, `Hrušková`, `Hoffmannová`, `Kossl`) and historical figures
(`Jimram`, `Jošt`, `Heralt`, the `Lucemburks`, etc.) all given invented equivalents.

- Deliberately left generic words that merely resemble entities (`moravský`, `bystřické`, `plynové`, `pánové`, etc.)
untouched.

- The company name `Pueblo – archeologická společnost` was left as-is since it's the
[report producer](https://www.pueblo-archaeology.org/home), not a personal or place name.
