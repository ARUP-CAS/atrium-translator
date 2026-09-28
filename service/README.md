# ATRIUM Translator API service 🌐

Structure-preserving translation of ALTO/AMCR XML. Chunks the document, translates each
chunk through the configured backend (LINDAT CUBBITT by default), and returns the
rewritten XML with its markup intact. The service version is read from
`para_config.txt` `[tool]` (single source of truth, never hard-coded).

## Quick start

```bash
pip install -r requirements.txt -r service/requirements.txt
python -m service.api                          # honours PORT/HOST; default 0.0.0.0:8000
# or, for development with auto-reload:
uvicorn service.api:app --host 0.0.0.0 --port 8000
# or:
docker compose --profile api up -d
```

## Endpoints

| Method | Path         | Purpose                                                                                                                                                                                |
|--------|--------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| GET    | `/info`      | service identity + capabilities: `service`, `version`, `endpoints`, `limits` (every [limit](#limits), current value), `limits_meta` (the variable that sets each), `supported_formats` |
| GET    | `/health`    | liveness probe — 200 always, even mid-shutdown. `?deep=true` additionally checks the translation backend warmed up (503 on failure or while draining)                                  |
| GET    | `/ready`     | readiness probe (issue #55) — 503 until the backend has warmed up, 200 while serving, 503 the instant `SIGTERM` arrives. The Kubernetes `readinessProbe`/`startupProbe` target         |
| POST   | `/translate` | translate one XML document (multipart upload; optional baseline ATRIUM Document JSON)                                                                                                  |

Machine-readable schemas: `GET /openapi.json`, or the Swagger UI at `/docs`, from a
running server. The repo-root `README.md` covers the CLI and the translation logic itself.

### `POST /translate` (multipart form)

| Field           | In            | Type    | Default       | Meaning                                                                                                                                                                      |
|-----------------|---------------|---------|---------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `file`          | form          | file    | —             | **Required.** The XML document. Filename must end in `.xml`.                                                                                                                 |
| `document_json` | form          | file    | —             | Optional baseline ATRIUM Document JSON to accrete onto.                                                                                                                      |
| `source_lang`   | form or query | string  | `auto`        | ISO 639-1 code, or `auto`: FastText per block/field, trusted only when confident and translatable, else the element's label, the document's language, `DEFAULT_SOURCE_LANG`. |
| `target_lang`   | form or query | string  | `en`          | ISO 639-1 code.                                                                                                                                                              |
| `is_alto`       | form or query | boolean | `true`        | `true` → ALTO dual-pass reconstruction; `false` → XPath metadata mode.                                                                                                       |
| `output_mode`   | form or query | string  | `OUTPUT_MODE` | `replace` or `append` (issue #46). Unset → the `OUTPUT_MODE` env var, then `replace`; an unknown value degrades to the default with a warning.                               |

Every field is read from the multipart body first and the query string second (issue #46), so either calling
style works.

```bash
curl -sf -F "file=@page.alto.xml" \
     "localhost:8000/translate?source_lang=cs&target_lang=en&is_alto=true" \
     -o page_en.alto.xml
```

### Response

**200** with `Content-Type: application/xml` and
`Content-Disposition: attachment; filename="<doc>_<lang>.alto.xml"` — the body is
the translated document, structurally identical to the input.

When `document_json` is supplied the response is instead `multipart/mixed`: the
translated XML first, then the updated ATRIUM Document JSON, then `limits_applied.json`
(see [Limits](#limits)), each with its own `Content-Disposition` filename.

**Limits applied.** When a limit shaped the translation without refusing it — a segment
split into chunks, a language decided on a sample, a segment left in the source language
after its retries — the response carries an `X-Atrium-Limits-Applied` header,
`<key>=<effect>:<count>` pairs joined by `; ` (ASCII only; e.g.
`lang_id_document_chars=sampled:1; translation_rerun_rounds=skipped:3`). No header means
no limit applied. The full notes, with a sentence each, are the multipart response's
`limits_applied.json` part and the run's paradata `limits_applied`.

The response carries no JSON envelope by design — the document is the payload, so
the endpoint composes with `curl -o` and with the pipeline's other stages.

### Errors

Harmonised across all five ATRIUM services (`agent_skill_strategy.md` §4.4), so a
client can treat them uniformly:

| Status | `reason`         | Meaning                | When                                                                                                                                                                                                                                                                                                                 |
|--------|------------------|------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `413`  | `limit_exceeded` | Payload too large      | A part exceeds `MAX_UPLOAD_MB`, or the declared request exceeds `max_request_mb` (2 × `MAX_UPLOAD_MB` + 1 MB). Checked in the handler, after FastAPI has parsed the multipart body (Starlette spools a large part to a temporary file first), so cap the body at the ingress too, e.g. nginx `client_max_body_size`. |
| `415`  | `null`           | Unsupported media type | `Content-Type` is neither `multipart/form-data` nor `application/json`.                                                                                                                                                                                                                                              |
| `422`  | `null`           | Unusable input         | Missing filename, a filename not ending in `.xml`, metadata mode with no XPath targets, or request validation.                                                                                                                                                                                                       |
| `500`  | `null`           | Translation failed     | The pipeline raised — malformed XML, or the backend failed after retries.                                                                                                                                                                                                                                            |
| `503`  | `null`           | Shutting down          | After `SIGTERM`. **Retryable** against another replica.                                                                                                                                                                                                                                                              |

Every error has one JSON body (hub `docs/agent_skill_strategy.md` §4.4, atrium-project#32
item 2): `{"status": <int>, "reason": <code or null>, "detail": "<text>"}`. `detail` is
always a string; a `limit_exceeded` body adds `limit` (`key`, `env`, `value`, `observed`,
`unit`), and a request-validation 422 adds `errors`, FastAPI's list of problems:

```json
{"status": 413, "reason": "limit_exceeded", "detail": "File too large: over 50 MB (MAX_UPLOAD_MB).",
 "limit": {"key": "max_upload_mb", "env": "MAX_UPLOAD_MB", "value": 50.0, "observed": null, "unit": "MB"}}
```

## How it works

1. **Guard** — `verify_content_type` rejects a wrong `Content-Type` with 415;
   `_refuse_if_draining()` answers 503 once a shutdown signal has arrived, which
   bounds the set of requests the drain has to wait for.
2. **Read** — the upload is read in 1 MiB chunks and abandoned the moment it
   crosses `MAX_UPLOAD_MB`, then written into a per-request
   `TemporaryDirectory()`. Nothing is retained between requests: that is what
   makes the service horizontally scalable.
3. **Translate** — the handler calls the *same* `main.process_single_file()` the
   batch CLI uses, in a worker thread via `asyncio.to_thread`. The thread is not
   a tidy-up: uvicorn's `SIGTERM` handler is an event-loop callback, so a
   synchronous translation holding the loop would make the shutdown contract
   unenforceable.
4. **Record** — a paradata JSON is written for the run, including the translation
   endpoint *actually resolved* (issue #63) rather than a literal, and the
   effective licence computed from the components the run exercised.
5. **Return** — the rewritten XML streams back as an attachment; the
   `TemporaryDirectory` is removed as the request ends.

## Configuration (environment)

| Variable                    | Default           | Meaning                                                                                                                                                                                                                                                   |
|-----------------------------|-------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `MAX_UPLOAD_MB`             | `50`              | canonical upload limit                                                                                                                                                                                                                                    |
| `ALLOWED_ORIGINS`           | `*`               | CSV of CORS origins. The code default is the `*` wildcard (credentials are then disabled, per the CORS spec); `.env.example` ships it commented (`# ALLOWED_ORIGINS=*`) so the default stays `*` until an operator narrows it.                            |
| `TRANSLATION_BACKEND`       | `lindat`          | backend seam shared with the CLI (issue #4)                                                                                                                                                                                                               |
| `OUTPUT_MODE`               | `replace`         | `replace` overwrites the source-language field; `append` keeps it and adds an `xml:lang`-marked sibling (ALTO: keeps every `String`'s `CONTENT` and adds `<ALTERNATIVE PURPOSE="translation:<lang>">`). Shared with the CLI's `--output-mode` (issue #46) |
| `DEFAULT_SOURCE_LANG`       | `cs`              | with `source_lang=auto` (the `/translate` default): the language used when detection cannot be trusted and neither the element's label nor the document's language settles it                                                                             |
| `LANG_ID_MIN_CONFIDENCE`    | `0.5`             | FastText score a detected language needs before it is used (`auto` only)                                                                                                                                                                                  |
| `LANG_ID_MIN_LETTERS`       | `20`              | texts with fewer letters are not sent to FastText; they inherit their label / the document language (`auto` only)                                                                                                                                         |
| `TRANSLATION_RERUN_DELAY_S` | `10.0`            | cool-down before each re-run round — **added to the request's duration** whenever a document has a flagged segment                                                                                                                                        |
| `AMCR_FIELDS_PATH`          | `amcr-fields.txt` | file of AMCR XPath targets for metadata mode, one per line; relative paths resolve against the repo root. Absent ⇒ metadata requests are refused 422, ALTO unaffected (issue #46)                                                                         |
| `TRANSLATION_URL`           | LINDAT            | translation API base URL for the `lindat` backend; `LINDAT_BASE_URL` is an alias (issue #63)                                                                                                                                                              |
| `UDPIPE_URL`                | LINDAT            | UDPipe 2 endpoint for vocabulary lemma matching (the CLI's Tag-and-Protect); same name as atrium-nlp-enrich (issue #63). `/translate` applies no vocabulary, so the service never calls it                                                                |
| `PORT`                      | `8000`            | port the service **binds**, and the one `service/healthcheck.py` probes (issues #55, #58)                                                                                                                                                                 |
| `HOST`                      | `0.0.0.0`         | bind address (issue #58). ⚠️ see the warning below                                                                                                                                                                                                        |
| `GRACEFUL_SHUTDOWN_S`       | `20`              | seconds uvicorn waits for in-flight requests (issue #55)                                                                                                                                                                                                  |
| `RELOAD`                    | `false`           | filesystem auto-reload — development only, never in a deployment                                                                                                                                                                                          |
| `LOG_LEVEL`                 | `INFO`            | root logger level for the `python -m service.api` start path (issue #61)                                                                                                                                                                                  |

`TRANSLATION_URL` and `UDPIPE_URL` make the two LINDAT-hosted backing services
attachable (12-factor IV): set either to reach a self-hosted or stubbed instance
without a code change. Unset, both reach the same hosts as before. The endpoint
the `lindat` backend actually resolved is what `/translate` writes into the
`translation_api` paradata field — the record names the host the request went
to, never a literal, since a provenance claim that is confidently wrong is worse
than one that is absent. The `LINDAT_MIN_INTERVAL_S` / `LINDAT_MAX_RETRIES` /
`LINDAT_BACKOFF_BASE_S` transport dials are separate and unchanged.

**Degenerate replies cost time, not correctness.** A LINDAT reply that comes back as a repetition loop is
re-requested (`LINDAT_GUARD_RETRIES`; the first time immediately, then with back-off), and a segment still degenerate after that is re-run once
the document is done (`TRANSLATION_RERUN_ROUNDS` × `TRANSLATION_RERUN_DELAY_S`); one that never recovers keeps
its source text. All of that happens inside the synchronous `/translate` request, so on a bad day for the
backend a request takes longer — size `GRACEFUL_SHUTDOWN_S` (and the orchestrator's grace period) with that in
mind, or lower `TRANSLATION_RERUN_DELAY_S` for the service.

`PORT` and `HOST` are read by `service/api.py`'s `__main__` block, which is what the `api`
image's `ENTRYPOINT` (`python -m service.api`) runs. Before issue #58 the entrypoint baked
`--port 8000` into an exec-form array — which runs no shell, so `$PORT` could not expand —
while `service/healthcheck.py` read it. Setting `PORT` therefore moved the health *probe*
and not the listener, and the container reported unhealthy forever.

> ⚠️ `HOST=127.0.0.1` yields a container that reports **healthy** and serves nobody:
> `service/healthcheck.py` always probes loopback by design and never reads `HOST`, so a
> loopback bind passes every probe while being unreachable from outside the container.

## Limits

Every limit this service has (atrium-project#53). Each is an environment setting, declared once
in [`tool_limits.py`](../tool_limits.py) (the CLI reads the same declaration), reported with its
current value in `GET /info` `limits` and with the variable that sets it in `limits_meta`. A
malformed value stops the service at startup, naming the variable. Over a limit the service
**refuses** (`reason: "limit_exceeded"`) or **translates the input in full** and says how the
limit shaped the result (`X-Atrium-Limits-Applied`, `limits_applied`). The LLM and CT2 rows
apply only when `TRANSLATION_BACKEND` selects that backend. `tests/test_limits_contract.py`
checks this table against `tool_limits.py` and `.env.example`.

| Key (`/info`)              | Variable                                     | Default | Unit    | Over the limit                                                                                         |
|----------------------------|----------------------------------------------|---------|---------|--------------------------------------------------------------------------------------------------------|
| `max_upload_mb`            | `MAX_UPLOAD_MB`                              | 50      | MB      | 413 `limit_exceeded` — per part: the XML and the baseline document JSON                                |
| `max_request_mb`           | — (derived from `MAX_UPLOAD_MB`: 2 × it + 1) | —       | MB      | 413 `limit_exceeded`, from the declared `Content-Length`, once the multipart body has been parsed      |
| `translation_chunk_chars`  | `TRANSLATION_CHUNK_CHARS`                    | 4000    | chars   | translated in full, in pieces re-joined with a line break — `split` note                               |
| `lang_id_segment_chars`    | `LANG_ID_SEGMENT_CHARS`                      | 2000    | chars   | `source_lang=auto`: the segment's language is decided on its first N characters — `sampled` note       |
| `lang_id_document_chars`   | `LANG_ID_DOCUMENT_CHARS`                     | 20000   | chars   | `source_lang=auto`: the document's language is decided on its first N characters — `sampled` note      |
| `lindat_timeout_s`         | `LINDAT_TIMEOUT_S`                           | 60      | s       | the call is retried (`LINDAT_MAX_RETRIES`)                                                             |
| `lindat_max_retries`       | `LINDAT_MAX_RETRIES`                         | 4       | retries | the file fails → 500                                                                                   |
| `lindat_guard_retries`     | `LINDAT_GUARD_RETRIES`                       | 2       | retries | the segment is flagged for the end-of-document re-run                                                  |
| `translation_rerun_rounds` | `TRANSLATION_RERUN_ROUNDS`                   | 1       | rounds  | the segment keeps its source text (logged `untranslated`) — `skipped` note with the count              |
| `udpipe_timeout_s`         | `UDPIPE_TIMEOUT_S`                           | 30      | s       | CLI with a vocabulary (LINDAT): the chunk is not lemmatised, its terms go unprotected — `skipped` note |
| `llm_timeout_s`            | `LLM_TIMEOUT_S`                              | 120     | s       | the call is retried (`LLM_MAX_RETRIES`)                                                                |
| `llm_max_tokens`           | `LLM_MAX_TOKENS`                             | 2048    | tokens  | a reply cut at it (`finish_reason=length`) is degenerate: re-run, else kept as source — never used     |
| `llm_max_retries`          | `LLM_MAX_RETRIES`                            | 4       | retries | the file fails → 500                                                                                   |
| `llm_max_glossary_terms`   | `LLM_MAX_GLOSSARY_TERMS`                     | 40      | terms   | CLI `--vocab`: the longest terms are kept — `trimmed` note                                             |
| `ct2_max_input_tokens`     | `CT2_MAX_INPUT_TOKENS`                       | 1024    | tokens  | the chunk is re-split and translated in full — `split` note                                            |
| `ct2_max_decoding_tokens`  | `CT2_MAX_DECODING_TOKENS`                    | 2048    | tokens  | a reply that reaches it is degenerate: re-run, else kept as source — never used                        |
| `ct2_max_glossary_terms`   | `CT2_MAX_GLOSSARY_TERMS`                     | 40      | terms   | CLI `--vocab`: the longest terms are kept — `trimmed` note                                             |

Platform limits (not settings): libxml2's default limits (parsed without `huge_tree`: nesting
depth, a 10 MB text node) — a document over them fails as malformed XML (500); Starlette's
multipart defaults.

## Shutdown behavior (issue #55)

The published `api` image (`ghcr.io/ufal/atrium-translator-api:<version>`, new in that
issue — before it this service was only reachable via a compose entrypoint override, so no
API image existed to deploy) declares `HEALTHCHECK` (shallow `GET /health`, via the
vendored `service/healthcheck.py`) and `STOPSIGNAL SIGTERM`, and sets
`ENV GRACEFUL_SHUTDOWN_S=20`, which `service/api.py`'s `__main__` block passes to uvicorn
as `timeout_graceful_shutdown`. (It was the `--timeout-graceful-shutdown 20` CLI flag until
issue #58 moved the whole start command into that block so `$PORT` could be honoured.)

On `SIGTERM` the service flips `GET /ready` to **503** at once so an orchestrator stops
routing to it, answers new `/translate` calls with 503, and lets in-flight translation
finish before `models.clear()` tears the backend down. `GET /health` deliberately stays
200 throughout — a liveness probe failing mid-shutdown would get the container killed
before the drain completed.

Translation now runs in a worker thread (`asyncio.to_thread`) rather than inline on the
event loop. That was a prerequisite, not a tidy-up: uvicorn's `SIGTERM` handler is an
event-loop callback, so while a synchronous `process_single_file()` held the loop the
signal could not be processed at all.

⚠️ This is the fleet's slowest request shape: one **retried** LINDAT call per chunk, so a
large document can legitimately run for minutes and outlive the 20s drain budget. Raise
`GRACEFUL_SHUTDOWN_S` and the deployment's grace period together for that workload — see
`docs/k8s_deployment.md` ("Known limits") in the hub.

A clean shutdown exits **143** (128 + SIGTERM), not 0: uvicorn re-raises the captured
signal on purpose so a supervisor sees the real cause. That is a normal stop, not a crash.

## Tests

```bash
pytest -q tests/test_api_contract.py tests/test_service_api_contract.py tests/test_api.py
```

`tests/test_api_contract.py` asserts the §4 meta-contract (including `/ready` and the
liveness-stays-200-while-draining rule) against the in-process app; the container-level
equivalent runs in CI via `docker-tool.reusable.yml`'s `probe-targets: '["api"]'`.
