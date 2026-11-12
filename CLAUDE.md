# CLAUDE.md

Guidance for Claude Code (and humans) working in this repository.

## Language rules

- The user communicates in **Russian** — reply in Russian.
- Everything written to the repo is in **English**: code, identifiers, comments,
  docstrings, CLI messages, log output, commit messages, and documentation.
- Ukrainian text appears only as *data* (Scripture text, word lists, test fixtures).
- Reports and check messages use **simple English**: many readers know little English (user decision,
  2026-10-30; no translated reports). Short common words, no jargon such as "unlisted" or "mid-sentence".

## Multilingual design (hard rule)

The checker must work for **any language / Paratext project**, not only Ukrainian (`urk/` is
just the current test project).
- All rules come from the project files (Settings.xml, SpellingStatus.xml, hyphenatedWords.txt)
  or from Unicode properties (categories, script names) — never hard-code letters of a language.
- The only place for language knowledge is `checker/languages.py` (`LanguageProfile`: vowels,
  `no_break_before`, `glides`), selected by Settings.xml `<LanguageIsoCode>` (`uk:::` -> `uk`)
  or `--language CODE`. Unknown language -> `GENERIC`: rules that need it are skipped.
- Ukrainian examples in comments/tests are fine; Ukrainian data in logic is not.
- Second test project: `us/` (English NIV, `en::US:`). Always re-run both projects after a change:
  `main.py` (urk) and `main.py us --checks ...`. Settings differ between
  projects — e.g. `us` writes `SentenceFinalPunctuation` space separated (`. ! ? : —`), has no
  `ValidPunctuation_NonText` (default `DEFAULT_WORD_MEDIAL_PUNCTUATION` = hyphens + apostrophes),
  has only ~1k SpellingStatus entries and a mostly unreviewed hyphenation list (no `*`).
  Never assume a list format from one project only.
- Third test project: `indonesian/` (`id:::`, idFAYH20). Specifics: clitics with
  divine capitals (`kuasa-Mu`, `Anak-Nya`), suffix after a closing quote (`‘apel’mu`),
  `ValidSentenceFinalPunctCapitalization` allows lowercase after `. ! ?` (so `capitalization` = 0),
  `\nd Tuhan\nd*` approved as `TUHAN`, USFM optional breaks `//`.
- Fourth test project: `tir/` (Tigrinya, `ti:::`). Specifics: Ethiopic script has no capitals
  (`capitalization`, `mixed-capitalization`, `name-case` = 0; book names `1ዜና` cannot be told from ordinals by
  case, so `ordinals` uses `\toc1-3`), and references use `፥ ፣ ፤`, `-|‑`, `–` — never `:`, except in link
  attributes (`12|GEN 4:12`), which are USFM and always use `:`.
- Do not add project folder names or language names to the repo (code, comments, this file): user rule, 2026-11-02.
- Report folder of a project: `<project folder>_report` (user decision, 2026-11-02).
- Known limit: words are split by Unicode letter categories, so scripts written without
  spaces (Thai, Chinese, ...) are not segmented into words.

## AI models for this repository

Claude Code models (Claude 5 family), by kind of work:

| Work | Model | Model ID |
|---|---|---|
| Writing and changing code, reviews | Opus 5.5 | `claude-opus-5-5` |
| Reading and analysis: reports, findings, source data, comparing projects | Sonnet 5.5 | `claude-sonnet-5-5` |
| Simple bulk reading: file search, finding where a word occurs | Haiku 5.5 | `claude-haiku-5-5` |

Use Fable 5.1 (`claude-fable-5-1`) only when the user asks for it: it is the most capable and costs more.
The checker itself uses no AI (standard library only).

Work is split into three slash commands (`.claude/commands/`), each with its own model:
`/chat` (Sonnet: questions about reports and data, read only), `/planning` (Opus: questions, measuring on the data,
agreeing a plan; no repo changes), `/do` (Opus: make the agreed changes, tests, re-run the projects).
A mode stays on until the user gives another mode command: a message without a command follows the rules of the
last mode used (user decision, 2026-11-02). Before the first mode command of a session, the normal rules apply.

## Project goal

Build a **validation (checker) script** for the Ukrainian Bible translation stored in `urk/`.

All check rules come from the project's own files: `Settings.xml` (characters,
punctuation, capitalization, abbreviations, numbers) and `SpellingStatus.xml` (word list).
New checks are agreed with the user first — see "Ideas / not implemented".

## Usage

The user runs `main.py` from PyCharm **without arguments**: the settings block at the top of
`main.py` (`PROJECT`, `CHECKS` — comment out unwanted lines, `BOOKS`, `LANGUAGE`, `REPORT_DIR`,
`UNIQUE`, `ERRORS_ONLY`) is turned into CLI arguments. Default: all checks, one report per check in a new run folder `<project>_report/YYYY-MM-DD_HH-MM/`,
a one-line-per-check summary in the console. When adding a check, add it to
`CHECKS` in `main.py` too. Command line arguments, if given, replace the settings block:

```
.venv/Scripts/python.exe main.py                      # settings block of main.py (with any argument, give PROJECT too)
.venv/Scripts/python.exe main.py PROJECT --books GEN MAT      # selected books (codes from \id)
.venv/Scripts/python.exe main.py PROJECT --checks punctuation spelling
.venv/Scripts/python.exe main.py PROJECT --unique     # each distinct problem once: count, one context, all locations ("MAT 27:46, 28:1 (2×); MRK 15:34")
.venv/Scripts/python.exe main.py PROJECT --errors-only --output report.txt
.venv/Scripts/python.exe main.py PROJECT --checks unused --output unused.txt   # list entries absent from text
.venv/Scripts/python.exe main.py PROJECT --checks all --report-dir PROJECT_report  # index.html + html/ + txt/ (one file per check)
.venv/Scripts/python.exe main.py PROJECT --stage 1 2 --report-dir PROJECT_report  # all checks of stages 1 and 2 (also with --checks)
.venv/Scripts/python.exe main.py PROJECT --checks hyphenation --language xx    # force generic (no language profile)
.venv/Scripts/python.exe main.py D:/Projects/OtherProject              # a Paratext project folder anywhere
.venv/Scripts/python.exe -m unittest                  # tests
```

Exit code: `1` if any `error` finding, else `0`.

**Window and exe** (user decision, 2026-11-02): `checker_app.py` opens a tkinter window (`checker/gui.py`): choose a
project (listed from the Paratext projects folder, found in the registry `Settings_Directory` or
`C:/My Paratext 9 Projects`; or Browse), choose books (like the Paratext Books dialog, added 2026-11-03: all books
of the folder at the start; a click on a book selects/clears it; a group button — Old/New Testament, Deuterocanon,
Extra material, groups in `checker/books.py` — selects only its group when all books are selected, adds it otherwise,
clears it when it is already selected; all selected = no `--books`), tick checks, Run (background thread, progress bar), the HTML report opens
in the browser.
Checks are shown by **stage**, titled "Unit N" in the window and reports (user decisions, 2026-11-05 and 2026-11-06; `checker/stages.py`, the order to fix problems: an earlier
stage causes false problems in later ones): 1 Project settings and lists, 2 File structure, 3 Characters and
punctuation, 4 Words, 5 References and terms, 6 Review lists. **Groups inside a unit** (user decision 2026-11-12, `stages.GROUPS`: unit, title, checks in the order to fix them; the checks are also in `STAGES`): in the window a group is a folded list inside its unit, at the place of its first check, its checks numbered `1.` `2.`; `index.html` has a heading `Poetry: fix in this order` and the numbers. Planned groups (2026-11-12, from the guide *Translation Checks for Technical Managers*; each measured before it is added; messages only say what to change, the text is never changed): Unit 3 "More characters" (digits of another system, `’` -> `ʼ`, `1/2` -> `1⁄2`, quote closed before a continuer of the same speaker), Unit 5 "More references" (`\x` to its own verse, `Jude 1:3` / `Jude 3`, very long term renderings), Unit 6 "Poetry" in this order: digits, lead-in punctuation, missing full stop at a line end (`,` + a capital that is not a name), two sentences in a long line, very long line, verse number inside a line, `\q2` after a full stop, `\b` at a chapter end. **Folded units** (user decision 2026-11-12): every unit and every group is a folded list `▸ Unit 3. Characters and
punctuation  (2 of 8)` (`gui._Fold`); a click on the title opens it, the box on the right selects or clears all its
checks and shows a dash when only some are selected. Units 1-3 stand in the left column, 4-6 in the right one. Select
all / Clear all (under the units, above Run; user wish); the progress bar is in the Run row, so the window stays low
while the units are folded (user wish: fit small screens). Nothing is
selected when the window opens and Run is disabled until a check is ticked; the choice stays while the window is open
(not saved). Reports always list checks in stage order; `index.html` has a heading per stage and, when stage 1-2 has
errors and later stages were checked, a line "Fix them first". Measured on 9 projects to place the checks:
`lists` -> `spelling` (W/R contradictions), `spelling` -> `hyphenation` (3.6k missing words are also unapproved),
`spelling` -> `variants`/`parallel-changes`. Reports of a project inside the Paratext folder go to `Documents/Scripture checker reports/
<project>_report` (never write into the Paratext folder); other projects keep `<project folder>_report`.
**Version and update notice** (user decision, 2026-11-05): `checker/version.py` `VERSION` is shown in the window title; at start the window asks the GitHub API in the background for the latest release (`checker/updates.py`, public data only, 5 s timeout, any error = no notice) and, if its tag is newer, shows "A new version is ready" with a button. Nothing is downloaded by itself. **Update** (exe only, user decision 2026-11-12): downloads `checker.exe` of the release next to the exe as `checker.exe.new`, checks size and sha256 (GitHub asset `digest`), renames the running exe to `checker.old.exe` (Windows allows renaming a running exe, not overwriting it), puts the new file in its place, starts it and closes; the next start deletes `checker.old.exe`. Any error (no rights to write, network, damaged file): the exe is not changed, a message, and the release page opens. Started from Python the button is **Download** (opens the release page). Changes go to `CHANGELOG.md` under "Unreleased" as they are made (user decision, 2026-11-05); release steps: raise `VERSION`, rename "Unreleased" to the version, commit, rebuild the exe, `gh release create v<VERSION> dist/checker.exe --target main` with English notes.
**No AI attribution** (user rule, 2026-11-12): commit messages, pushes, release notes and PR texts never name Claude
or Claude Code — no `Co-Authored-By: Claude …` trailer, no "Generated with Claude Code" line. Commits are only in the
user's name.
`build_exe.bat` builds `dist/checker.exe` with PyInstaller (build-only dependency, approved 2026-11-02; `build/` and
`dist/` are build output).

## Repository layout

```
wordlist/
├── CLAUDE.md            # this file — rules and project context
├── CHANGELOG.md         # What's new / Fixed per release; "Unreleased" = not released yet
├── main.py              # entry point -> checker.cli.main
├── checker_app.py       # window entry point -> checker.gui.main (also of checker.exe)
├── build_exe.bat        # PyInstaller build of dist/checker.exe
├── checker/
│   ├── settings.py      # Settings.xml -> ProjectSettings
│   ├── spelling.py      # SpellingStatus.xml -> SpellingList
│   ├── hyphenation.py   # hyphenatedWords.txt -> HyphenationList + hyphenation rules
│   ├── languages.py     # LanguageProfile per ISO code — the ONLY language-specific data
│   ├── usfm.py          # *.SFM -> text Segments (markers stripped, refs as anchors)
│   ├── books.py         # Paratext book numbers; book code from a file name (Settings.xml Naming)
│   ├── tokens.py        # word runs / punctuation runs / joined words / graphemes
│   ├── model.py         # Finding, Analysis, CheckContext, ERROR/WARNING
│   ├── stages.py        # STAGES: the checks in the order to fix their problems (window, reports, --stage)
│   ├── checks.py        # the checks; registries CHECKS / BOOK_CHECKS / SOURCE_CHECKS / PROJECT_CHECKS
│   ├── quotes.py        # quotation mark check (book level)
│   ├── pairs.py         # matched pairs ( ) [ ] check (book level)
│   ├── references.py    # reads Scripture references with the marks from Settings.xml
│   ├── parallels.py     # ParallelPassageStatus.xml: parallel-changes, parallel-differences
│   ├── terms.py         # Biblical Terms (terms list + TermRenderings.xml): terms, term-lists
│   ├── versification.py # .vrs mappings: Original verse numbers -> English (eng.vrs + custom.vrs of the project)
│   ├── eng.vrs          # Paratext English versification (data; Paratext keeps it inside the program)
│   ├── lxx/vul/rsc/rso.vrs # the other standard versifications (report links convert verses to English)
│   ├── eng.vrs.LICENSE  # MIT license of eng.vrs (UBS ICAP)
│   ├── structure.py     # USFM structure: markers, notes, chapter/verse numbers (raw file)
│   ├── places.py        # names of Paratext windows/menus used in report texts
│   ├── approvals.py     # approvals check: approved list entries that look wrong
│   ├── footnotes.py     # footnotes check: notes built differently from similar ones (raw \f … \f*)
│   ├── poetry.py        # poetry-numbers, poetry-two-sentences (Unit 6 group Poetry)
│   ├── divine_name.py   # divine-name check: the divine name without \nd in verses of nd_verses.txt
│   ├── nd_verses.txt    # verses (Original numbers) where a base translation has LORD in \nd; numbers only
│   ├── spaces.py        # special-spaces check: U+202F, \fv … \fv*, abbreviations with ~ (raw file)
│   ├── html_report.py   # HTML report: index.html + one page per check (static, inline CSS/JS)
│   ├── gui.py           # tkinter window: choose project and checks, run, open the report
│   ├── version.py       # VERSION (window title, compared with the newest GitHub release)
│   ├── updates.py       # is there a newer release on GitHub? (notice in the window; Update button swaps the exe)
│   ├── paratext_link.py # report links (scripturechecker:...) -> Paratext shows the verse; URL protocol registration
│   ├── icon.ico         # window and exe icon (16-256 px, transparent corners), made from `Open Book Icon.png` in the root
│   └── cli.py           # argparse, report writer, summary
├── tests/test_checker.py
├── .venv/               # local virtualenv (Python 3.14), not part of the source
├── .idea/               # PyCharm settings, do not edit
└── urk/                 # Paratext project "ukrNPUv1" — SOURCE DATA, READ-ONLY
    ├── NNBBBukrNPUv1.SFM   # 66 books in USFM (e.g. 01GENukrNPUv1.SFM, 41MATukrNPUv1.SFM)
    ├── Settings.xml        # Paratext project settings
    ├── SpellingStatus.xml  # Paratext spelling list (approved / wrong words)
    └── hyphenatedWords.txt # Publishing Assistant hyphenation list
```

**Never modify files in `urk/`.** The checker only reads them and reports findings.

## Source data facts

### Paratext project (`urk/Settings.xml`)
- Name `ukrNPUv1`, "New Ukrainian Translation ver.1", © 2022 Biblica, Inc.
- Language: Ukrainian (`uk`), encoding UTF-8 (65001), normalization **NFC**.
- Stylesheet `usfm.sty`, versification 4 (English), chapter:verse separator `:`.
- File names: `<2-digit number><3-letter book code>ukrNPUv1.SFM`. Note that numbered
  books shorten the code in the file name (e.g. `091SA` = 1SA, `471CO` = 1CO), so
  read the book code from the `\id` line, not from the file name. Numbering skips 40.

### USFM files (`urk/*.SFM`)
- UTF-8 (may start with a BOM — open with `encoding="utf-8-sig"`), CRLF line endings,
  very long lines.
- First lines: `\id <BOOK> - New Ukrainian Translation ver.1`, `\rem`, `\h`,
  `\toc1-3`, `\mt1`, then an introduction (`\iot`, `\ip`, `\ie`), then chapters.
- Most frequent markers: `\v \c \p \q1 \q2 \b \s1 \s2 \li1-3 \m \d \pm`;
  character markers (paired with `*`): `\nd \add \wj \xt \qs \tl`;
  footnotes: `\f ... \fr \ft \fq \fqa \fl ... \f*`.
- Text uses typographic punctuation: `«»`, en dash `–`, em dash `—`, apostrophe `ʼ` (U+02BC).

### Spelling list (`urk/SpellingStatus.xml`)
- ~53.8k entries: `<Status Word="..." State="R|W">`.
  - `R` = approved (right), `W` = wrong (~59 entries).
  - Optional children: `<SpecificCase>` (required capitalization, e.g. `Аарона`),
    `<Correction>` (suggested replacement for a `W` word).
- `Word` is usually lowercase; some entries contain spaces/punctuation (e.g. `"- аж"`).

### Settings.xml list format (important parsing details)
- Lists are separated by ASCII whitespace only; items may themselves be Unicode spaces
  (U+2009, U+202F, U+2006) or invisible chars (ZWNJ U+200C, ZWJ U+200D) — never `str.split()`.
- `\XXXX` inside an item is an escaped code point (`!\0020–` = `! –`).
- `ValidCharacters` items are grapheme clusters (base + combining marks, e.g. `а́`);
  multi-letter items like `дж` are irrelevant to the character check.
- Punctuation patterns describe the *whole* non-word run between two words; `_` means
  whitespace or the paragraph edge: `»,_–_`, `_«`, `-` (word-medial).
- `ValidPunctuation_NonText` (`- ʼ ZWNJ ZWJ`) = word-medial punctuation; used to join
  words like `Кірʼят-Арбу`. `ʼ` (U+02BC) is a letter in Unicode but punctuation here.
- `NumberThousandsSeparator` is U+202F; `NumberMedialPunctuation` is `/`-separated.

### Hyphenation list (`urk/hyphenatedWords.txt`)
- UTF-8 with BOM, CRLF. "#" comments, header lines `Name = "value"` (`SoftHyphen = "="`,
  `HardHyphen = "-"`, `HyphenatedMarkers = "p m q1 ..."`), then one entry per line.
- Entry = lowercase word with `=` at allowed break points (`хо=ди=ти=муть`); a leading `*`
  means reviewed/locked by hand. ~53.5k entries, 14 without `*` (new, unreviewed), 19 phrases
  with spaces (skipped by checks), some with stress marks (`ада́м`).
- Letters are compared after NFC + dropping leftover combining marks (stress accents);
  NFC first so precomposed letters (`й`, `ї`, `é`) survive.
- Script detection uses only categories Lu/Ll/Lt/Lo: `ʼ` (U+02BC) is Lm "MODIFIER LETTER".
- Vowel rules are skipped for words with mixed scripts or none of the profile's vowels
  (the Ukrainian list also contains English words).

## Implemented checks

| check-id | source | error | warning |
|---|---|---|---|
| `characters` | ValidCharacters / InvalidCharacters | char (or its base) is invalid | not in valid list |
| `punctuation` | ValidPunctuation / InvalidPunctuation | pattern is invalid | pattern not listed |
| `mixed-capitalization` | SpellingStatus.xml + InvalidMixedCapitalization | word in InvalidMixedCapitalization | mixed-case form not approved in SpellingStatus (R entry with this exact key or `SpecificCase`) |
| `capitalization` | SentenceFinalPunctuation, ValidSentenceFinalPunctCapitalization, Abbreviations, InvalidUncapitalizedStyles | — | lowercase after sentence end (unless the sequence is allowed or the previous word is an abbreviation); `\p` starting lowercase |
| `spelling` | SpellingStatus.xml | word has `State="W"` (shows `<Correction>`) | word not in list (with up to 3 approved words one edit away: `(similar approved words: слово)`); case differs from `<SpecificCase>`; capitalized words of `\toc1-3` book names are skipped (named in the report note) |
| `quotes` | Quotes / InnerQuotes / InnerInnerQuotes, ContinueQuotes, Continuer…, ContinueAt, QuoteClosesAllQuoteLevels | new quote opened while the same mark is open (forgot to close); mark of the wrong level; closing mark that closes an outer quote while an inner one is open; closing mark without opening; quote never closed | paragraph that should continue an open quote (ContinueAt) lacks the continuer; any of the error cases inside a note |
| `pairs` | Pairs (`(/) [/] {/}`), UnmatchedPairingCharacters | closing without opening; inner pair not closed before the outer closer; never closed (book-level stack like `quotes`) | the same for characters listed in UnmatchedPairingCharacters |
| `repeated-words` | RepeatableWords / NonRepeatableWords | repeated word listed in NonRepeatableWords | same word twice separated by whitespace only (case-insensitive), not in RepeatableWords |
| `spacing` | NumberThousandsSeparator, HindiUrduNumberGrouping, NumberMedialPunctuation | — | double whitespace; number with ≥5 digits without separator; groups after the separator ≠ 3 digits (HindiUrduNumberGrouping `T`: `1,44,000`, groups of 2 before the last 3); `10 000` with another space than the separator; space after the separator (`1, 44,000`, `45, 000`, `53, 400`; added 2026-11-10: a second part of only 3 digits needs 1-2 digits before it and no note, and no list or range mark (Pd dash, chapter-verse mark, NumberMedialPunctuation, the separator) on either side, because `605, 597, 586` and `119:9–21, 103–105` are lists; measured on 45 projects: 3 findings, all real) |
| `numbers` (opt-in) | text + NumberThousandsSeparator | — | 4-digit number written the rare way of the project: `4000` where ≥10 others and ≥90% have the separator (`4.000`), or the reverse; introductions (`0:…`, years) and numbers joined to letters (`H1234`) are not counted (added 2026-11-05, user decision; measured on 10 projects: 3 findings, one of them a year in a note) |
| `scripts` | Unicode script names | word mixes scripts (`cлово`, `VІ` with Cyrillic `І`) | — |
| `normalization` | NormalizationForm | text run not in NFC/NFD/... | — |
| `paragraph-final` | Valid/InvalidParagraphFinalPunctuationItems, MarkersRequiringSentenceFinalPunctuation | item (`<style>_<punct>` or `<style>` = ends with a word) is invalid | required marker without sentence-final punct; item not listed although the style has listed items (poetry/list styles `q* li* lh lf lim*` excepted); heading `\s#`/`\ms#` ending with a full stop / comma / colon (by Unicode name; `?` `!` allowed) unless listed |
| `usfm` | raw *.SFM + Naming | second `\id` in a file; file name of another book than `\id`; book in two files; closing marker without opening; marker / note not closed; chapter out of order or missing; verse out of order or duplicated; `\fr`/`\xo` reference (`14:5–6`, `11:12,13`) does not include the verse the note is in | verse numbers missing (versification may omit verses); verse without text (only a note / `\vp`; headings do not count, `\d` does) |
| `book-titles` | `\toc1`, `\toc2`, `\h`, `\mt#` before `\c 1` | — | `\toc1` is not all `\mt#` lines joined in file order (`\mt2 Друга книга` + `\mt1 Самуїла`; some projects put `\mt1` first); main title empty; `\toc2` is not `\h`; book number written with another space than in the other books (`1Kings` vs 16× `1 Kings`; per marker `\h` `\toc1-3`, because `\toc3` is often `1Ki`; the rare form ≤10% and the usual one ≥5 books; all books are counted, also outside `--books`; added 2026-11-09, measured on 50 projects: 2 findings, both real) |
| `special-spaces` | raw *.SFM + Quotes, NumberThousandsSeparator, SequenceIndicator (and other reference marks), Abbreviations | `\fv` not written `\fv 13<U+202F>\fv*Text` (narrow no-break space before `\fv*`, nothing after it); U+202F anywhere else except between two quotation marks (markers and notes between them do not count), between digits when it is the thousands separator, in a reference mark before a number; abbreviation listed with `~` (`н.~э.`) written with an ordinary space (or with U+202F: the message gives the `~` form); list of numbers after an abbreviation (`ст.~8, 9`) with a mark that is not in SequenceIndicator (outside `\xt`) | — |
| `lists` (opt-in) | SpellingStatus.xml, Settings.xml, hyphenatedWords.txt | correction of a W word is itself W | `Дивіться` W vs `дивіться` R; SpecificCase with other letters; R entry with a correction; InvalidMixedCapitalization word approved in SpellingStatus; hyphenated word marked W (entries without letters, such as `-` that Publishing Assistant puts into every list, are skipped); W word that is a word of a book name (`\toc1-3`) |
| `approvals` (opt-in) | Settings.xml, SpellingStatus.xml, hyphenatedWords.txt, ParallelPassageStatus.xml + text counts | — | approved character that is private use / control / not Unicode; approved punctuation with a space before `, . ; : ? !` (by Unicode name) or one mark written twice (`,,`), only if used; rejected paragraph ending used ≥20× and in ≥10% of the paragraphs of its marker (`q2_,` 1742 of 12433); rejected punctuation or character used ≥20×; bare marks in ValidSentenceFinalPunctCapitalization (text with capitals only); no NormalizationForm; R word mixing scripts or with a special character; one line per character marked wrong but in R words; hyphenation entry with `*` breaking a rule; ≥99% of ≥100 parallel passages approved |
| `variants` (opt-in) | text frequencies | — | name (never lowercase in text, ≥5 letters; in scripts without capitals every word) occurring ≤3× one edit (substitution, insertion, transposition) away from one ≥10× more frequent; edits in the last 2 letters are skipped (inflection), without capitals also edits in the first letter (prefixes) |
| `ordinals` | NumberOrdinals, NumberOrdinalType, `\toc1-3` | — | number + affix not in NumberOrdinals (`8-ого`); uppercase affixes (`1Sa`), words of book names (`1ዜና`) and verse parts after a reference (`22:43б`) are skipped |
| `name-case` (opt-in) | text frequencies | — | word capitalized mid-sentence in ≤5% of ≥10 occurrences (or lowercase in ≤5%); sentence starts, words after quotes/brackets, headings and all-caps words are not counted |
| `styled-words` (opt-in) | text + `\nd` spans | — | word in `\nd` in ≤5% of ≥10 occurrences, or without `\nd` in ≤5%; notes are not counted |
| `divine-name` (opt-in) | `checker/nd_verses.txt` + text `\nd` spans + versification | — | a word the project puts in `\nd` ≥20× and in ≥80% of its places is without `\nd` (and not written small) in a verse that has fewer `\nd` (also none) than an English base translation has LORD in `\nd` there (the map) |
| `poetry-numbers` (opt-in, Unit 6 > Poetry 1) | text of `\q`, `\q#`, `\qm#`, `\qc` (not `\qr \qa \qd`, not front/back matter or `XXA…`) | — | number written with digits (any script) in a poetry line; references (`40:8`), verse ranges (`7–8`) and `\xt` are skipped (added 2026-11-12, user request; measured on 50 projects: 0 in most, real ones like `40,000` in JDG 5:8, `77 veces`; a project that writes all numbers in digits gets ~30) |
| `poetry-two-sentences` (opt-in, Unit 6 > Poetry 2) | the same lines + SentenceFinalPunctuation | — | poetry line longer than 95% of the project's poetry lines (≥100 lines, at least 40 characters) with a sentence end inside (only marks named FULL STOP / EXCLAMATION / QUESTION / DANDA), ≥20 characters on each side; not when a dash or a small letter follows (speaker words: `…Меня? — возвещает`), not after an abbreviation (added 2026-11-12, from a regex of a checking guide; measured on 50 projects: 0-17, a simplified-English project 66) |
| `references` (opt-in) | `\xt`, `\fr`, `\xo` + `\toc1-3` of all books + ChapterVerseSeparator, RangeIndicator, SequenceIndicator, ChapterRangeSeparator, ChapterNumberSeparator, BookSequenceSeparator | `\xt` points to a chapter/verse that does not exist (every part, verses after the sequence mark, range ends, link targets); wrong mark in `\xt`/`\fr`/`\xo`; range that goes backwards | book name not found in any `\toc1-3`; link target book not in the project; text and link show different numbers (`8|JER 22:28`); non-ASCII letter in a link; number with no chapter after the chapter mark (`13፥2፤ 12`: verse or chapter? a person decides) |
| `terms` (opt-in) | terms list (BiblicalTermsListSetting: project folder or Paratext program folder; ProjectBiblicalTerms.xml) + TermRenderings.xml + eng.vrs/custom.vrs | — | clear cases only: none of the renderings of a term is in a verse of the term, while the term is rendered in all other verses (missing in ≤2 verses and ≤5%); rendering found nowhere in the text (`cлов` with Latin `c`). The hidden rest is counted in the report note |
| `term-lists` (opt-in) | the same files | — | verse marked OK without a rendering (Denial) where the rendering is there now, or which is not a verse of the term; rendering guessed by Paratext (only terms of the project list) |
| `footnotes` (opt-in) | raw `\f … \f*` + SentenceFinalPunctuation + verse texts | formula (fixed text before the first marker, numbers as `N`, + that marker: `Букв.: \fqa`) one character or only punctuation away from one used ≥20× and ≥10× more with the same marker (`Outros dizem \fqa` vs 49× `Outros dizem: \fqa`); for a note without a marker only punctuation inside counts; note without an end mark when ≥99% of ≥100 notes have one | `\fq`/`\fqa` swapped or missing in ≤10% of ≥12 notes with the formula; `\fqa` of ≥3 words word for word in the verse where the formula usually has `\fq`; formula with one other word than one used ≥5× and ≥3× more, same first word and marker (only formulas with a marker; a changed word of ≤2 letters = unit, skipped) |
| `unused` (opt-in) | all of the above lists + hyphenatedWords.txt | — | list entry occurs 0 times in the checked text |
| `parallel-changes` (opt-in) | ParallelPassageStatus.xml | — | words of an approved verse are different now (`'a' was changed to 'b'`); verse changed very much |
| `parallel-differences` (opt-in) | ParallelPassageStatus.xml | — | two verses (or verse ranges) of one parallel group, from different books, differ in 1–3 words |
| `hyphenation` (opt-in) | hyphenatedWords.txt (+ language profile) | generic: word mixes scripts (`cлово` with Latin `c`); single letter at line edge; break before word-medial punctuation (`ʼ`, from ValidPunctuation_NonText). Profile only: part without vowel; break before `no_break_before` (`ь`); glide torn from its vowel before a consonant (`вві=йти`) | suffix inconsistency; long word in text without break points; entry without `*`; text word missing from the list |

Hyphenation consistency (`inconsistent_affixes`): entries are grouped by their first 6 letters
(prefix) and, separately, by their last 6 letters (suffix); inside that part the break pattern
used by ≤20% of the group (majority ≥3 words) is reported with the majority form, e.g.
`авто=рите=том` vs 8× `ав=то=ри`, `спо=куша=тимуть` vs 227× `ти=муть`. For prefixes the
last position is ignored (a break there depends on the next letters: `свя=ще=ник` / `свя=щен=на`). "No break
points" = a part between hard hyphens has ≥7 letters and ≥3 vowels, and the word occurs in text.
Tunables are constants at the top of `checker/hyphenation.py`.

`quotes` is a book-level check (`BOOK_CHECKS`, `checker/quotes.py`): it gets all segments of a
book in order, because a quote may span paragraphs and chapters. Design:
- One stack of open marks for the scripture flow of a book; headings, titles, intro (`i*`)
  and notes are checked one segment at a time.
- Level of depth d = Quotes, InnerQuotes, InnerInnerQuotes, then the last two alternate.
- Opening mark equal to the open top mark (`«…«`) = "forgot to close": reported once and the
  top is replaced, so one missing mark does not cascade. Closing mark matching a deeper level
  pops to it (one error).
- A mark between two letters is an apostrophe, not a quote (`Don’t`). If one mark both opens
  and closes, direction is decided by surrounding spaces.
- Continuers (`ContinueQuotes=Yes`, e.g. English `“ ‘` at a new paragraph) are accepted at any
  paragraph start, also after `(`; ContinueAt (`p`, `b/m` = previous/current style, via
  `Segment.previous_style`) only says where a missing continuer is reported — once per open quote.
  If only some levels are repeated and the last mark can open the next level, it is an opener.
- Notes quote fragments of the text (`Or “I have been given … to`): no level check, all findings
  are warnings marked "(in a footnote)".

`unused`, `hyphenation`, `lists`, `approvals`, `variants`, `name-case`, `styled-words`, `divine-name`, `numbers`, `footnotes`, `references`, `poetry-numbers`, `poetry-two-sentences`, `parallel-changes`,
`parallel-differences`, `terms` and `term-lists` are project-level checks (`PROJECT_CHECKS`): they run once after
all books, using `UsageCounter`. They are not in the default run (`unused` ≈22k findings,
mostly SpellingStatus `R` words and hyphenation entries) and must be requested with
`--checks unused hyphenation` or `--checks all`. Its findings have no verse: the
location is `<window> <status>` (e.g. `Characters inventory (marked correct)`, `Wordlist (right, R)`).
With `--books` it counts only those books. Skipped text (`\rem`, `\id`, `\fr`, ...) is not counted;
multi-grapheme ValidCharacters items (`дж`) are ignored.

Design decisions:
- Separators between two digits (`6,8`, `1⁄16`, `12:5`) are skipped by `punctuation`
  (from NumberDecimalPoint / NumberMedialPunctuation / NumberThousandsSeparator / ChapterVerseSeparator).
- A mark of Reference Format (RangeIndicator, ChapterRangeSeparator, ...) is not punctuation **in a reference** only
  (added 2026-11-05, user request: a project rejects `–` as punctuation but uses it for verse ranges): after
  `chapter:verse` (`5:1‒3`, `5:1, 7‒9`, `12:31б‒13:2`) or after a book name of `	oc1-3` and a number (`Пар. 22‒26; 28‒29`,
  `Psalms 1–41`). Elsewhere (`слово‒слово`, `10‒12 лет`) the punctuation lists decide. Measured on 40 projects: e.g.
  541 -> 86 and 1174 -> 17 warnings; what stays is mostly `гл. 1‒9`, `vv. 28‑29` (no chapter, no book name).
- USFM attributes (`\xt 8-му|GEN 2:8\xt*`) are removed before checking (`usfm.remove_attributes`), also named
  attributes after any marker (`\periph Title|id="title"`, `\w Bible|lemma="b"`, `\zrule |cat="x"`; values may hold
  `\`) and milestones (`\qt-s |sid="q1"\*`, `\ts\*`). For `references` a `link-href="GEN 2:9"` is kept as `|GEN 2:9`.
  The title after `\periph` is a name for the software, not printed text: not checked.
- Not checked as text: `\id`, `\rem`, `\c`/`\v` numbers, note callers, `\fr`, `\xo`, `\fv`, `\fig`,
  `\cat ...\cat*` (USFM 3 category, e.g. `dup`).
- Words containing digits (`1Sa`, `2Ki`) are skipped by `spelling` and `mixed-capitalization`.
- `spelling` skips words of book names (added 2026-11-03): `ctx.book_title_words` = capitalized words of all
  `\toc1-3` (`structure.book_name_words(names_only=True)`; `Roma`, not `di`; scripts without capitals: every word;
  `~` is a space). The project sets them itself; a W mark on one is reported once by `lists`. The skipped words are
  named in `ctx.notes["spelling"]`.
- `spelling` leaves a word that `mixed-capitalization` reports to that check when both run (`ctx.checks`, added
  2026-11-05, user decision): 80% of the mixed-capitalization findings were the same word in the same verse in
  spelling. A W word stays a spelling error (it has a correction). The count is named in `ctx.notes["spelling"]`.
- `special-spaces` (`checker/spaces.py`, `SOURCE_CHECKS`, added 2026-11-03) works on the raw file, because `\fv` and
  the markers between two quotes are needed. The `\fv` form comes from the updated typesetting documentation (user
  decision). All findings are errors. `\id`/`\rem` lines are skipped; lists inside `\xt` are left to `references`.
- Messages put what was found in single quotes (`'слово'`, renderings `'a' || 'b'`): the HTML report shows each
  quoted part as a chip (dark background, copied on click) and marks `Problem.item` (= `Finding.item`) in the
  text. Invisible spaces (no-break, narrow, zero width) are highlighted, with their code point as a tooltip.
  `CONTEXT_WIDTH` (`checker/model.py`) = 50 characters on each side.
- `//` (USFM optional line break) is removed before parsing; ` // ` leaves one space. Removed text (`\fv 6\fv*`, `\fig`)
  does not join the spaces around it, so `spacing` reports only double spaces that are really in the file.
- Quote marks listed in `Pairs` (`“/”`) are left to the `quotes` check: `pairs` knows no continuers or apostrophes.
- A note in a heading (`\s1`, `\sp`) may name the next verse in `\fr`: the heading stands before that verse.
- A reference mark made of letters (a word in SequenceIndicator or ChapterNumberSeparator) is not a book name.
- Regexes that match letters use `tokens.LETTER` (letters + combining marks), not `[^\W\d_]`: Python's `\w` has no
  marks, so a book name with a vowel sign (`यशा` ends with U+093E) was cut and not found.
- An all-caps `SpecificCase` (`TUHAN`) also accepts the word in any case whose uppercase matches
  (small-caps styles like `\nd` render it in capitals; markers are stripped from segments).
- Quote mark between letters = apostrophe, unless it is the closer of the open top quote
  (Indonesian `‘apel’mu`): then it closes the quote.
- Unreviewed hyphenation entries are listed one by one only up to `MAX_LISTED_UNREVIEWED` (100);
  above that one summary line is reported.
- Footnotes/cross references are separate segments, reported after their paragraph.
- `SpecificCase` is only the approved spelling form (often just a sentence-initial
  capital, e.g. `Невдовзі`), so a case mismatch is a warning, not an error.
- Spelling lookup: exact word first, then lowercase. Words with digits are skipped.
- The list has 12 capitalized keys, all `W`; 6 of them contradict an approved lowercase key
  (`Дивіться` W vs `дивіться` R, also `Лицеміри`, `Населені`, `Вифлеєма`, `Істино`, `Воаза`).
  Their corrections look wrong too (`Дивіться` -> `дивиться`). Such a hit is a **warning**
  "the spelling list disagrees with itself", not an error (user decision, 2026-10-29).
- Mixed case = uppercase letter after the first character and the word is not all caps.
- `ValidMixedCapitalization` in Settings.xml is **ignored** (user decision, 2026-10-29):
  it is outdated (e.g. still has `Ейн-Мішпату` while the text has `Ен-Мішпату`), and all
  mixed-case words in the text are approved in SpellingStatus.xml. Not reported by `unused` either.

Notes on the checks added 2026-10-29 (all eight proposed ideas were accepted):
- `Segment.spans` holds character style spans `(start, end, marker)`; `styles_at(offset)`.
- `UsageCounter.add(analysis, ctx)` also collects case and `\nd` statistics (needs ctx);
  `add_source(book, content, ctx)` indexes every book (verses, `\toc1-3` names, `\xt`), also books outside
  `--books`, so references into them resolve; `\xt` references are collected only for checked books.
- `references` (`checker/references.py`): all marks come from `ProjectSettings.reference_format`; a setting may
  list choices with `|` and they keep their spaces (`, |,`, `–|—| and `). A wrong mark is reported but the reference
  is still read: a dash (Unicode category Pd) as a range, anything else as a list. Any colon or full stop between
  numbers (by Unicode name) counts as a wrong chapter-verse mark. `usfm` uses the same reader for `\fr`/`\xo`.
  A part without a book name keeps the previous book (start: the current book, but nothing in front/back matter and
  notes books `PERIPHERAL_BOOKS`: their introductions cite many books without names); after an unknown name it is
  skipped. Leading words are dropped one by one until the rest is a book name (`див. Мт.`, `см. также Пс.`,
  `lihat Ibrani`; `Євр.` and `См. Исх.` are book names and also in Abbreviations); only Abbreviations words = no
  name. `~` (USFM no-break space) is U+00A0 in references, in the reference marks of Settings.xml (`;~`, `~и~`)
  and in `\toc` names (`1~Цар.`) — added 2026-11-03 for a project with `~` there. A name stays over whole chapters
  (`Быт. 37; 39; 41:37`, `Нав. 2; 6:22`): warning (question) "whole chapters, or is ':' missing?", because the same
  form is a typo elsewhere (`Mwa 19; 22; 32:25` = 19:22) and the settings cannot tell them apart. A link attribute (`8-му|GEN 2:8`) is used instead of the text for the target, and always uses `:`.
  Verse 0 (psalm title, introduction) is valid. Parts without `chapter:verse` (`9—9`, `30-й вірш`) are skipped.
- `approvals` (`checker/approvals.py`, added 2026-11-02): signs that lists were approved without looking. The files have no dates or users (`<History>` is empty), so only entries that are wrong by themselves are reported. Punctuation counts skip separators between two digits (`12:5`), like `punctuation`.
- `name-case` / `styled-words` mostly list deliberate distinctions (divine pronouns `Той`, pagan `бог`,
  NT `Господь` without `\nd`, Indonesian `Engkau`/`engkau`), so they are review lists, opt-in.
- The book of a file is its **first** `\id`, as in Paratext (added 2026-11-03: a draft file had `\id XXB … \id LUK …` on one
  line and replaced the real book in the reference index). The file name is read with Settings.xml `Naming` /
  `FileNamePrePart`, `FileNamePostPart`, `FileNameBookNameForm` (`41MAT`, `MAT`, `41`; `checker/books.py`, numbers
  `01`-`39`, `41`-`99`, then `A0` = FRT); an unknown form or a name that does not fit = no comparison.
- `usfm` (`checker/structure.py`, `SOURCE_CHECKS`) gets the raw file content. Any marker closed
  somewhere in the file (`\litl*`) counts as a character marker, so unknown USFM 3 markers work.
  Inside notes a new character marker closes the previous one (`\fr … \ft … \fq`). Peripheral
  books (`FRT BAK INT XXA…`) have no chapter/verse numbering check. Verse parts `5a 5b` and ranges `6-7` are allowed.
- `paragraph-final`: closing quotes and pair closers are skipped before taking the last character.
  `us` lists `q2_,` as invalid → ~1.7k errors there; that is the project setting, not a bug.
- `NumberMedialPunctuation` is a **character set** (`-/–—:‑⁄`), not a `/`-separated list. SequenceIndicator marks
  are added to it, so `3፥35፣36` is not a `punctuation` finding.
- Space before `, . ; :` is already reported by `punctuation` (`_,` is an unknown pattern).
- `NumberSpacing` (`bothRequired`) is not used: its meaning is unclear.

Notes on `terms` / `term-lists` (`checker/terms.py`, added 2026-11-03):
- Which list (`terms._find_list`): the one chosen in Settings.xml `BiblicalTermsListSetting` — in the project folder,
  or for `Major::BiblicalTerms.xml` / `All::AllBiblicalTerms.xml` in the Paratext program folder (registry
  `Paratext9_Full_Release_AppPath`, else `C:/Program Files/Paratext 9`, `Terms/Lists/`); else `ProjectBiblicalTerms.xml`
  of the project folder (in most projects only a few own terms). The report note names the list used. Without
  TermRenderings.xml or a list: "not checked". So in the exe the Major list needs Paratext on that computer.
- Verse numbers (`checker/versification.py`, added 2026-11-03): program lists have no `<Versification>` and count
  verses as Original; a project list says it (`English-…`, `Original-…`). Original -> English uses `checker/eng.vrs`
  (Paratext's English versification; the same file is published by UBS ICAP, github.com/ubsicap/versification_json,
  MIT, license in `checker/eng.vrs.LICENSE`, also bundled; kept in the package because Paratext has it inside the
  program, bundled into the exe by build_exe.bat) plus the project's `custom.vrs`, whose lines replace eng.vrs lines
  about the same verse on either side. Other pairs of versifications: "not checked". Denials are in the project
  numbering (measured: hindi 40 vs 4, ptm 110 vs 4). Verse 1 is searched together with the `\d` title (verse 0):
  in Hebrew a title is often part of verse 1 and eng.vrs does not always move it (PSA 90:1).
  Verse = `BBBCCCVVV` + 2 (project list) or 5 (program list) digits.
- More than `MAX_LISTED_GUESSES` (100) guessed renderings: one line (one project had 732).
- A rendering is the start of a word (Paratext 9.5; old `*` at the end were removed by the team in 2026); `*` = any
  letters, `**` = any words, `(…)` = comment; words of a phrase may be joined by any non-letter (`Наамана-сирійця`).
- Measured on the first project (user decision 2026-11-03: list clear cases only, say what is hidden): 168 604
  term verses, 4 273 without a rendering. Listed: 220 (term rendered in all other verses, missing in ≤2 and ≤5%:
  `осуду` vs `суд`, `проголошував` vs `голошув`, `звичайною` vs the typo `вичайн`). Hidden and counted in
  `ctx.notes` (shown under the counts): 4 053 verses of 663 terms — common words translated in many ways
  (`עוֹלָם` 202, `πιστεύω` 106). All 851 names (PN / domain 9.7) were rendered everywhere.
- TermRenderings.xml also keeps terms of other lists (24k entries vs 8.9k terms, 291 guesses): only terms of the
  project list are checked, as Paratext shows only those.
- `ctx.notes` (check -> text) is a general way to say what a check did not list; txt and HTML show it.

Notes on `divine-name` (`checker/divine_name.py`, added 2026-11-05, user request: keep the map in the program so no
base project is needed):
- `nd_verses.txt` = 5 861 verses (784 chapter lines `GEN 3:1,8*2,9`; `*2` = two `\nd` in the verse; 6 842 `\nd` in
  all) where an English base translation has `\nd` (scripture text and psalm titles `\d`, which are verse 0 there and
  verse 1 in Original; no notes, no headings; a verse range counts in its first verse), made once from that project;
  it holds verse numbers and counts only, no text. `/1` = the verse also has one "Lord" without `\nd` (Adonai, 49
  verses: `EXO 4:10/1` "said to the LORD, Pardon your servant, Lord"): that many `\nd` may be missing, because a
  translation may write both with one word (`Ya Tuhan`, `Señor Todopoderoso`). Measured: all 12 findings in such verses
  were noise; none of the real ones were lost.
  Numbers are **Original** (the base translation's versification + its custom.vrs: `NEH 7:68`, `ISA 64:1` are numbered
  differently there). Bundled into the exe by build_exe.bat.
- A project verse goes to Original with `versification.project_to_original` (its versification + its custom.vrs, whose
  lines replace the standard lines about the same verse; `ctx.to_original`, set in `cli.run_checks`). A daughter
  project (`<TranslationInfo>Daughter:<parent>:…`) has no `<Versification>`: like Paratext, `settings.project_versification`
  takes the parent's from the projects folder (found 2026-11-05: a daughter of a Russian-numbered project was read as
  English, psalm verses were one off, 5 false findings); parent not on the computer = English; another value =
  "not checked". Not English: going
  English -> Original -> English is not exact (eng.vrs `PSA 13:0-5 = PSA 13:1-6` turns 13:6 into 13:5). custom.vrs
  matters: one project says Original in Settings.xml but numbers like English through custom.vrs (2 false findings
  without it). `to_english` (report links) still has no custom.vrs: a link knows only the project name.
- The plain comparison "map has `\nd`, project verse has none" is mostly noise: the base translation writes "the LORD"
  where others write "he" (45 of 45 in one project, >1000 in a paraphrase). So only a word the project itself keeps in
  `\nd` (≥20×, ≥80%; from `UsageCounter.style_refs`) and writes not small (`tu señor` = a man) is reported. The share
  counts the Old Testament only: the New Testament uses the same word for Jesus without `\nd` (`Господи` was 400 of
  401 in the OT but below 80% in the whole Bible; +10 findings on 11 projects, all real: `Господи, подивись`, PSA 9:13).
- Counts (added 2026-11-05, user request): a verse is reported when it has **fewer** `\nd` than the map (also 0) and such
  a word stands without `\nd` (`\nd Herren\nd* … ’Så säger Herren.’`, map 2). `UsageCounter.nd_places`: per verse of
  scripture text (no notes, no headings) the `\nd` count and the words without `\nd` that are not written small.
  **More** `\nd` than the map is not reported: translations repeat the name where the base translation has "he"
  (`Abram believed the LORD, and he credited` vs `\nd Господь\nd* зарахував`): 33-323 verses per project, noise.
- Measured on 10 projects with `\nd`: 270 findings (280 with the OT share below), mostly real (`Herren sa`, `እግዚኣብሄር` without `\nd`; 216 before
  counts, +64 with counts, -10 with the Adonai rule, +titles). Known noise left:
  a paraphrase that says the verse differently (`Tuhan Allah` for "the Sovereign LORD" twice), a word for Adonai that
  the base translation renders otherwise. Projects without `\nd` give 0.

Notes on `parallel-changes` / `parallel-differences` (`checker/parallels.py`, added 2026-11-02):
- Source: the project's **own** `ParallelPassageStatus.xml` (Paratext parallel passages tool), never a shared list or
  another project's file (user decision). Without the file both checks are "not checked": `ctx.skipped` -> the report
  and the console summary say so, instead of showing 0 findings.
- Entry = `passageKey` "<verse>;<all verses of the group>", `status` (F = approved), `<Content>` = verse text when it
  was approved. The file has no dates; `<History>` is empty in every project seen.
- Verse text comes from `UsageCounter.verse_texts` (scripture paragraphs and `\d`, no notes or headings; `6-7` fills
  both verses). Words use the normal word rules; punctuation is ignored. A range key (`MRK 1:7-8`) is compared as the
  text of all its verses (its `<Content>` is the whole range); lists (`LUK 6:27-28,35`, 1-2 per project) are skipped.
- `parallel-changes`: one verse may have several entries (Paratext changed the groups later; old entries keep old
  text). Only the approved text most like the verse now is used. Below 60% equal words the nearby verses (shifted by ±3, the key
  may use another versification) are tried; if none fits, one finding "changed very much". Each changed place is its
  own finding with the message "'a' was changed to 'b'", so `--unique` groups one replacement over many verses.
- `parallel-differences`: pairs of verses or verse ranges of one group from **different books** only (same-book pairs are mostly
  formulas, laws and their fulfilment, refrains), at least 70% equal words and at most 3 words different.
  The original texts differ too (Kings / Chronicles), so it is a review list.
- Findings are sorted in book order (order of the files), then chapter and verse.

## Ideas / not implemented

- Indonesian `ValidSentenceFinalPunctCapitalization` contains bare `. ! ?`, which disables the
  `capitalization` check completely (0 findings); without them it finds 13 real cases
  (`umum. dan`, `negerinya. kemudian`). Decided 2026-11-05 (user): keep it, the project chose this setting;
  `approvals` warns that bare marks turn the check off.
- References inside normal sentences (not `\xt`/`\fr`/`\xo`; 444 in `tir`) are not checked. Tried and removed
  (2026-10-31): nearly all findings were false. Notes use Hebrew verse numbers (`32፥1`), and common words equal book
  abbreviations (Ukrainian `як` = James, Tigrinya `ኣብ` = Obadiah).
- **Links to Paratext** (done 2026-11-05, `checker/paratext_link.py`): each `chapter:verse` in `Where:` of the HTML
  pages is a link `scripturechecker:<Settings.xml Name>/MAT%205:3?vrs=<Versification>` (built in the page script;
  places without a book stay text; `0:0`, the introduction, opens `1:0`: Paratext keeps the introduction there and
  ignores chapter 0). Windows runs `checker.exe "<link>"` (or `pythonw checker_app.py`):
  no window; it writes the reference to `HKCU\Software\SantaFe\Focus\ScriptureReference` (default value), posts
  `RegisterWindowMessage("SantaFeFocus")` with wParam 1 to HWND_BROADCAST (Paratext moves the windows of scroll group
  A), brings Paratext to the front and reads the child window titles (`<project>: MAT 5:3 (Standard Translation)`) to
  see that a window of the project moved; else a message box: Paratext not open / project not open / window in
  another scroll group. The URL protocol is registered under `HKCU\Software\Classes\scripturechecker` (no admin
  rights) every time the window starts, so a moved exe keeps working. Measured 2026-11-05: Paratext reads the sent
  reference in the **English** versification and shows it in each project's own (English PSA 51:1 -> PSA 50:3 in a
  Russian Protestant project). So the verse is first converted to English (`versification.to_english`: project
  versification -> Original -> English, with `lxx/vul/rsc/rso.vrs` from the same UBS repository as eng.vrs, MIT,
  bundled; a text verse maps to verse 1, not to a title `:0`); custom.vrs is not known in the link, so if the window
  does not land, up to 4 tries add the difference between wanted and shown verse (`next_try`). Tested on a Russian
  Protestant project: PSA 113:9 (= English 115:1), NUM 30:1 (= 29:40), PSA 9:22 and others land at once.
  The exe sets `PYINSTALLER_RESET_ENVIRONMENT=1` at start: a browser opened by "Open report" inherits the variables
  of the onefile exe (`_PYI_APPLICATION_HOME_DIR` = its temporary `_MEI…` folder), and a link opened later started
  checker.exe as a part of that old run, whose folder was gone: "Failed to load Python DLL" (found 2026-11-05).

## Coding conventions

- Python 3 standard library only unless the user approves a dependency. Approved: PyInstaller, only to build the exe.
- Use `pathlib`, type hints, small pure functions; the CLI entry point uses `argparse`.
- A new check = a function `(Analysis, CheckContext) -> Iterator[Finding]` registered in
  `CHECKS`, plus a test in `tests/test_checker.py`, plus a row in the table above, plus a place in one stage of
  `checker/stages.py` (a test fails otherwise).
- The project folder is a required CLI argument, with no default; `main.py` gives it from its `PROJECT` setting.
- Report format: `CHECK: <id>`, a simple description of the check (`CHECK_DESCRIPTIONS` in `checker/cli.py`,
  add one for a new check) and the counts. With `--unique` then numbered blocks, errors first, most frequent
  first (`N. <message>`, `Found:`, `Text:`, `Where:`); without it one finding per line as
  `BOOK C:V  <severity>  <check-id>  <message>  [context]`. Several checks in one file end with a total.
- Report texts name the **Paratext place** where a setting is changed, not the file or XML key (user decision,
  2026-11-02; readers work in Paratext 9.5): constants in `checker/places.py`, e.g. `Settings.xml
  InvalidParagraphFinalPunctuationItems` -> `Tools > Checking inventories > Markers missing final punctuation
  inventory`, `SpellingStatus.xml` -> `Wordlist`, `NumberOrdinals` -> Ordinal list in `Project settings > Number
  settings`, reference marks -> `Project settings > Scripture reference settings > Reference Format`. Descriptions
  give the full menu path, messages and `Where:` the short window name with the status (`(marked correct)`,
  `(right, R)`). No place known yet (keep the Settings.xml key): `Pairs`, `NormalizationForm`,
  `SentenceFinalPunctuation`, `Abbreviations`. `hyphenatedWords.txt` keeps its file name (line numbers point into it).
- Always read text as UTF-8 (`utf-8-sig`) and write output as UTF-8.
- `--report-dir` writes `index.html` (one row per check, links to the `txt/` and `html/` folders), `html/<check>.html`
  (the grouped problems as embedded JSON, 200 blocks per page, search, errors-only filter, link to its txt) and
  `txt/<check>.txt` (user decision, 2026-11-03: html and txt in separate folders), all inside a new run folder
  `<report dir>/YYYY-MM-DD_HH-MM/` (`cli.new_run_folder`; `_2`, `_3` for two runs in one minute), so earlier runs are
  kept. Reports of the earlier layouts lying directly in the report dir (`<check>.txt/.html`, `index.html`, `txt/`,
  `html/`) are deleted; other files there are kept. The pages need no server and no internet; `</` in the JSON is
  escaped so problem text cannot end the script. The window has "Open report" and "Open txt folder" buttons for the
  newest run in the Reports folder (`cli.latest_run`, also a run made earlier).

## Environment notes (Windows)

- Interpreter: `.venv/Scripts/python.exe`.
- The Windows console defaults to cp1252. `checker.cli` reconfigures stdout to UTF-8;
  for ad-hoc scripts run Python with `-X utf8` (`PYTHONIOENCODING` is ignored in
  isolated `-I` mode), otherwise printing Ukrainian text raises `UnicodeEncodeError`.
