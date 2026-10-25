# failure-analysis-v1.md

Root-cause analysis of the dev-v1-r1/dev-v1-r2 failures (`docs/results-dev.md`),
done as the first step of P3's prompt v2. DEV split only; aggregate counts and
categories, with dev question ids as pointers for anyone re-reviewing the raw
traces -- no TEST content anywhere below, per CLAUDE.md's test-set-discipline
rule.

Per CLAUDE.md rule 6 (anti-overfitting), only patterns seen in at least 3 dev
questions, or a clear general bug independent of count, were turned into
prompt-v2 changes. Everything else below is recorded as an observed, but
*not* actioned, root cause -- fixing it would mean reading a prompt-v2 change
off a single dev example, which is exactly the overfitting this rule exists
to prevent.

## Failure categories (tolerant grading, pooled across dev-v1-r1 + dev-v1-r2)

| category (harness label) | count (both runs) | example dev ids | root cause bucket |
|---|---|---|---|
| wrong_format_or_name | 13 | 34, 39, 58, 66, 176, 210, 282, 523, 721, 722, 724 | answer-name bracket contamination (fixed, v2) |
| wrong_value | 15 | 62, 142, 214, 252, 254, 255, 516, 521, 523, 662, 722 | several distinct root causes, see below |
| budget | 3 | 254, 273 | one evidence-checker bug (fixed) + one latency-driven timeout (not fixed) |
| max_attempts / failed | 1 | 64 | file-path guessing spiral (fixed, v2) |
| repeated_failure | 1 | 69 | file-path guessing spiral (fixed, v2) |

(Counts are failure-taxonomy *entries*, not distinct questions -- the same
question id can appear in different categories across the two runs, e.g. a
question that got the right value in r1 but a bracket-contaminated name in
r2.)

## Root causes found, and what prompt v2 does about each

### 1. Literal-value fidelity -- the model substitutes a guessed value for a literal one it was given or shown

**Evidence:** ids 64, 66, 69 all share one dev CSV; across both runs, every
attempt at all three ignored the exact `data_path` given in the system
prompt and instead guessed a plausible-looking alternate path (splitting the
file name into an imagined subdirectory, then trying several made-up
spelling variants after the first guess failed). id 214 shows the same
failure mode on a categorical filter value: one run guessed a differently
-capitalized/punctuated category label than what the data preview actually
showed, silently filtering to zero rows and producing `nan`; the other run
used the value as shown and passed. 4 distinct dev ids, both runs.

**Root cause:** the model pattern-matches a "familiar-looking" literal
(a file path, a category label) instead of copying the exact one it was
given or shown, and a plausible-but-wrong guess fails silently (empty
filter) or loudly (`FileNotFoundError`) followed by a multi-attempt
guessing spiral that itself tends to trip the checker (`exit()` escape
hatches, `__name__` guards -- see `docs/security.md`).

**Fix (v2, `code_system_prompt`):** the file-path instruction now gives an
exact, literal `df = pd.read_csv(r"...")` line to copy character-for-
character, explicitly forbids guessing alternate names/folders, and tells
the model that a `FileNotFoundError` on that exact path means "re-copy it,"
not "try another name." A second new line asks for the same literal
fidelity when filtering/comparing a text column, pointing at the DATA
PREVIEW's own example values.

### 2. Answer-name bracket contamination

**Evidence:** by far the most common pattern -- 11 distinct dev ids across
both runs (34, 39, 58, 66, 176, 210, 282, 523, 721, 722, 724). The model's
JSON answer sometimes echoes the whole `@name[hint]` placeholder, or even
`@name[<the value it just computed>]`, into the `name` field instead of
giving the bare name the grader expects. The grader only scores an answer
whose name exactly matches the label's name, so this always grades as a
wrong answer even when the value itself was correct.

**Fix:**
- `answer_system_prompt` (v2) spells out the rule with a worked contrast
  (`"foo"`, never `"foo[hint]"` or `"foo[<value>]"`).
- `AnswerItem` name-normalization (version-independent, in `answer.py`,
  D-095) now also strips a trailing `[...]` suffix defensively. Every real
  placeholder name is a bare word-identifier with no brackets of its own,
  so stripping one is always removing contamination, never real content --
  this protects dev AND test, under both prompt versions, even if the model
  still slips.

### 3. The evidence checker rejects a correct empty-collection answer

**Evidence:** id 273, reproducibly, in both runs. The model correctly
computed `outlier_list = []` and printed it, but `check_evidence`'s
bracket-unwrap path turns `"[]"` into an empty string and then rejects any
empty value outright as "the answer value is empty" -- so a genuinely
correct empty-list answer could never pass, and the run burned its entire
repair budget (`budget_exceeded`) resubmitting the same correct code and
answer.

**Fix (`evidence.py`, D-095, version-independent):** an explicit empty-
collection literal (`"[]"` or `"()"`) is now checked as a literal substring
of stdout instead of going through the generic unwrap-then-reject path.

### 4. Sample vs. population standard deviation

**Evidence:** id 255. Two runs computed the same mean from the same code
shape; the run that used `ddof=0` (population std) was graded wrong, the
run that used `ddof=1` (sample std) was graded correct.

**Fix (`code_system_prompt`, v2):** a new line names sample statistics
(`ddof=1`, pandas' own default) as the default convention unless the
question explicitly asks for a population statistic.

### 5. Hand-rolled approximations instead of the standard statistical function

**Evidence:** id 516, both runs. Both attempts hand-derived skewness from
`(mean - median) / std` (one run with a factor of 3, one without) instead
of calling a real skewness function -- neither approximation is the
standard moment-based skewness definition, and both were graded wrong.

**Fix (`code_system_prompt`, v2):** a new line asks for the library's own
function (pandas `.skew()`/`.std()`/`.corr()`/etc., or `scipy.stats`) for
named statistical measures, rather than a hand-derived formula. This is
folded into the same new line as fix 4 above.

### 6. Unseeded stochastic methods

**Evidence:** id 521: both runs set a fixed `random_state` on
`train_test_split` but not on the classifier itself, and got different
test-set accuracy (0.77 vs. 0.76) from what reads as the same approach.

**Fix (`code_system_prompt`, v2):** a new line asks for a fixed
`random_state` on every method with inherent randomness, not just the
train/test split.

## Observed, but not actioned (single dev-question instances; not a clear general bug)

Changing prompt text for any of these would mean tuning against one dev
example, which is exactly what rule 6 forbids:

- **id 252** -- skewness-per-country computed consistently (same code
  shape, same library call, `bias=False`) but wrong both runs; most likely
  a misread of which axis the question wants skewness computed over, not a
  computational-convention bug like fix 5.
- **id 254** -- `budget_exceeded` from `TIME_BUDGET_S` (wall-clock), not the
  token budget: one attempt's code executed fine but the answer-extraction
  step needed a JSON retry, and NIM's latency that session (`docs/results-
  dev.md`'s own note) pushed the single attempt's wall time past 300s before
  a second attempt could even start. An external-latency effect, not a
  prompt bug.
- **id 662** -- "price change" computed consistently (median/stdev
  agreeing to 2dp across both runs) but wrong both times; likely a
  definitional mismatch (e.g. absolute vs. relative change) specific to
  this question's wording, not a general pattern.
- **id 722** -- a two-digit model-year column (classic auto-mpg style
  data) read as a four-digit year in one run and a two-digit one in the
  other; a single dataset's column-encoding quirk, not a general bug.
- **id 523** -- age-bracket counts shifted by a few between runs; most
  likely a boundary-inclusivity reading of the question's own bracket
  definitions, which is inherent to that question's wording, not something
  a general instruction can resolve without being dev-specific.

## Checker-blocked attempts

The 6 checker-blocked attempts recorded across both runs are reviewed
separately in `docs/security.md` (Task 2) -- 5 of them are a direct
downstream effect of the file-path guessing spiral in root cause 1 above
(the model reaching for `exit()`/`if __name__ == "__main__":` partway
through a multi-attempt guessing loop), so fix 1 is expected to reduce how
often the checker-block pattern recurs, on top of the checker policy change
itself.
