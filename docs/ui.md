# ui.md

The React (Vite + TypeScript) frontend in `web/`: how to run it locally,
what each screen/component does, the security choices behind it, and the
results of one real local end-to-end run against Groq + Modal.

## Running it locally

Two terminals, from the repo root:

```powershell
# terminal 1: the API
uv run sa serve

# terminal 2: the frontend dev server (proxies /api to localhost:8000)
cd web
npm run dev
```

Open the URL `npm run dev` prints (typically `http://localhost:5173`).
The dev server's Vite config proxies every `/api/...` request to
`http://localhost:8000`, so both pieces behave exactly like the single
production container, just served from two processes.

For a production-shaped check instead (one process, the real built
assets):

```powershell
cd web
npm run build
cd ..
uv run sa serve   # serves web/dist/ at "/", since it now exists
```

## Screens and components

- **Header** (`Header.tsx`) -- title, tagline, links to GitHub and
  "How it works" (an in-page anchor to the `<details>` below).
- **How it works** (`HowItWorks.tsx`) -- a native `<details>` disclosure:
  the pipeline in plain words, the trust boundaries, and the live
  model/provider from `GET /api/health`. No accuracy numbers.
- **Step 1: data** (`DataStep.tsx`) -- drag-and-drop or file-picker CSV
  upload (client-side `.csv` + 5 MB checks before the request is even
  sent), or one of three example cards (`GET /api/examples`). Once a
  dataset is loaded, shows the file name, row/column counts, a
  columns/dtypes list, and a 5-row preview table.
- **Step 2: question** (`QuestionStep.tsx`) -- a 3-500 char textarea
  with a live counter, suggested-question chips (populated from the
  loaded example's own questions), and a Run button that's disabled
  while a run is active. A 429 from `POST /api/runs` is shown using the
  API's own `detail` text (`api.ts`'s `friendlyMessage`).
- **Live timeline** (`TimelineView.tsx` + `AttemptCard.tsx`) -- one card
  per attempt, built from the SSE stream via a pure reducer
  (`timeline.ts`): writing code (collapsible, syntax-highlighted) or a
  line diff for a repair's code, the static-check result, exec
  output (stdout/stderr tail, timeout/crash badges, chart count), the
  answer, and evidence badges. Every step shows elapsed time since the
  attempt started.
- **Result panel** (`ResultPanel.tsx`) -- final status badge, answers,
  explanation, chart images, the final code with a Copy button, stats
  (attempts/tokens/time), and a trace (JSONL) download link. A
  non-answered status gets its own honest message, not a generic error.
- **Footer** (`Footer.tsx`) -- demo rate limits, a privacy note (only a
  column summary and 5 sample rows ever reach the model provider), and
  the version from `/api/health`.

## Security choices

- **No `dangerouslySetInnerHTML`, anywhere.** Every piece of model
  output -- code, stdout/stderr, the explanation, answer values -- is
  rendered as plain React text children. React escapes text children
  automatically, so a value like `<script>...</script>` appearing
  inside an explanation renders as the literal four characters `<`,
  `s`, `c`, ... on the page; it is never parsed as markup. See
  `ResultPanel.test.tsx` for a test that asserts exactly this.
- **Syntax highlighting without HTML injection.** `highlight.ts` uses
  Prism's `tokenize()` (string in, a token tree out) rather than its
  `highlight()`-to-HTML-string API, so `CodeBlock.tsx` renders each
  token as its own React `<span>` text child -- colored by a CSS class
  chosen from the token's *type*, never by interpreting the token's
  *content* as markup.
- **Images only from same-origin artifact URLs.** A live `exec_result`
  SSE event's `images` field is the backend's own local file path, not
  a URL -- the live timeline only shows how many images an attempt
  produced. Actual `<img>` tags only ever appear in the Result panel,
  sourced from `GET /api/runs/{id}`'s `chart_urls`, which are real,
  same-origin, served paths (see DECISIONS.md D-086).
- **SSE replay dedupe by `seq`.** Both the SSE hook (`useRunEvents.ts`)
  and the pure reducer (`timeline.ts`) independently dedupe by event
  `seq`, since a reconnected `EventSource` gets every past event
  replayed from the server.

## Manual test checklist (do this in a browser)

1. Run `uv run sa serve` and `npm run dev` (two terminals, see above).
   Open the dev server's URL.
2. Confirm the header, tagline, and "How it works" link render; click
   "How it works" and confirm it expands with the pipeline description.
3. Drag a `.csv` file onto the dropzone, and separately try the
   "Choose a file" button -- both should load it and show the preview
   table. Try a non-CSV file and a file over 5 MB; confirm a clear
   error message rather than a crash.
4. Load one of the three example datasets instead; confirm the
   suggested-question chips appear and clicking one fills the textarea.
5. Type a question under 3 characters; confirm the Run button is
   disabled. Type a real question and click Run.
6. Watch the live timeline: code appears (syntax-highlighted), the
   static check result, then execution, then the answer with evidence
   badges. If a repair happens, confirm a line diff is shown instead of
   a fresh code block.
7. Once finished, confirm the Result panel shows the status badge,
   answers, explanation, any chart image, the final code with a working
   Copy button, and stats. Click "Download trace (JSONL)" and confirm a
   file downloads.
8. Ask a chart question (e.g. one of the example suggestions) and
   confirm the chart image renders in the Result panel.
9. Resize the window down to a phone width; confirm no horizontal
   scrollbar and that everything stays usable.
10. Toggle your OS/browser dark mode and confirm the page switches
    palettes with readable contrast in both.
11. Tab through the whole page with the keyboard only; confirm every
    interactive element gets a visible focus outline and nothing is
    unreachable.

## Local live smoke (real Groq + Modal)

**Date:** 2026-10-25. **Provider/model:** Groq, `openai/gpt-oss-20b`
(same as every other reported number -- D-065). **Sandbox:** Modal,
real. Server started with `SA_LLM_PROVIDER=groq`,
`SA_DATA_DIR=runs/e2e-task5`, `PORT=8011`; stopped afterward.

Verified: `GET /` served the real built `index.html` (not the
placeholder -- its `<script>`/`<link>` tags point at the real
hashed asset files); both the JS and CSS assets returned `200` with
correct content types; `GET /api/health` reported
`{"status": "ok", "provider": "groq", "model": "openai/gpt-oss-20b",
"sandbox": "modal"}`.

One real example question, run through the exact same calls the UI
makes (`POST /api/examples/sales/load` -> `POST /api/runs` -> drain
`GET /api/runs/{id}/events` -> `GET /api/runs/{id}`):

| Question | Status | Attempts | LLM requests | Chart |
|---|---|---|---|---|
| "Plot total units sold per region as a bar chart." | answered | 1 | 2 | yes -- 800x600 PNG, 19,001 bytes |

All four answer values (`East`/`North`/`South`/`West` totals) passed
evidence checking. The chart artifact endpoint served a valid PNG; the
trace endpoint served a 13-line JSONL file ending in `run_finished`.
Total for this run: 2 LLM requests, 1 sandbox run (well inside this
task's 6-request/4-run live budget), sandbox spend ≈ $0.00016.
