# Changelog

Changes of the Scripture checker by release. Releases: https://github.com/yuraM/scripture-meta-checker/releases

## Unreleased

### What's new

- **marker-capitals** also checks the signature of a letter (\sig ... \sig*): its first word starts with a capital letter.
- **New checks m-after-heading and duplicate-footnotes:** \m right after a heading (change it to \p); a
  footnote with the same text as a note shortly before it, without \cat dup\cat* (typesetting removes the second
  note when both are on one page).
- **Six new checks for typesetting** (all opt-in, each says what to change):
  quote-spaces (the space between two quotation marks, usually U+202F), digit-hyphens (10-12 where the project
  writes 10‑12), marker-spaces ('\nd Lord \nd*': the space goes after the end marker), chapter-end-headings
  (a heading as the last line of a chapter), footnote-spaces (spaces at the end of, before and after a note) and
  outline-references (a reference in \io without \ior).
- **New check sentence-numbers** (Unit 3, Numbers and spaces): a sentence or the words of a speaker start with a
  number in digits ("… there. 430 years …"). A paragraph that starts with a number may have a verse number without
  \v. Lists, tables and numbers after a dash are not counted.
- **New since the last run:** the report shows how many problems are new and how many were fixed since the
  last run of the project (columns New and Fixed). New problems have a NEW mark, and the check page has a box
  "Only new". Only checks and books that both runs checked are compared.
- **Accept a problem:** each problem in the report has an **Accept** button (not a problem). The next reports
  hide the problem in those places. **Undo** takes it back. The **Accepted** button in the window lists the
  accepted problems by check: **Clear** shows the problems of one check again, **Clear all** shows all of them.
  The first page of the report (index.html) has the button **Undo all Accept** too.
- **"!" instead of 0:** when a check has nothing to check with (a file of the project is missing or empty, or the
  list in Paratext is empty, for example the Ordinal list or the quotation marks), the report shows a red **!** and
  the reason, not 0 problems.
- **Every check in a group:** repeated-words, ordinals, terms and unused are now folded groups too (Repeated words, Ordinal numbers, Biblical terms, Unused list entries), so all units look the same.
- **Groups of checks:** in the window, checks that belong together are a folded group inside their unit, for
  example Characters, Punctuation, Numbers and spaces, References, Poetry. Click the name of a
  group to see its checks; they are numbered in the order to fix the problems. The box on the right of the group
  selects all its checks (a dash = only some are selected). The report shows each group with its own heading.
- **usfm** now also finds the last verses of a chapter, or the last chapters of a book, that are missing: the
  versification of the project (with its custom.vrs) says how many verses each chapter has. Verses that English Bibles
  do not have (Greek parts of Daniel, Psalm 151) are not shown.
- **untranslated-verses** (Unit 2): a verse that may be untranslated or in another language (another alphabet, or
  words that occur nowhere else in the project).
- **repeated-text** (Unit 2): a verse with the same words as the verse before it, or words written twice in a row
  ("he went to the city he went to the city").
- **verse-lengths** (Unit 2): a verse 3 times shorter or longer than usual, compared with an English translation
  (the program keeps only the lengths). A part may be missing, or the verse is numbered another way.
- **glossary-words** (Unit 2): a glossary word `\w` without an entry in the glossary book GLO.
- **figures** (Unit 2): a picture `\fig` without a file, placed in another verse than its reference, or whose file
  is not in the figures folder.
- **dashes**, **ellipses** (Unit 3): `-` among `–` between spaces, `...` among `…`.
- **heading-case** (Unit 4): a heading with a capital on each word among headings with a capital only on the first
  word, or the other way.
- **all-caps** (Unit 4): a word typed all in capitals (`SENHOR`, `МЕНЕ, МЕНЕ, ТЕКЕЛ`, a heading in
  capitals). Capitals are made only by markers (`\nd`, `\sc`); Roman numerals are not shown.
- **marker-capitals** (Unit 4): the first word of a `\pc` paragraph (every line of an inscription) must
  start with a capital letter (`mene, mene, tekel` -> `Mene, mene, tekel`).
- **note-callers** (Unit 5): a note with another caller (`\f +`, `\x -`) than the other notes.
- **book-name-forms** (Unit 5): one book named two ways in references (`Lk` and `Luk`).
- **apostrophes** (Unit 3): a sign between two letters that is not the one the project nearly always uses
  (`ng'ombe` where the project writes `ʼ`).
- **digit-systems** (Unit 3): digits of another system than most numbers of the project (`۲۷` among `27`).
- **fractions** (Unit 3): `1/2` where the project writes most fractions with the fraction slash: `1⁄2`.
- **footnote-quotes** (Unit 5, Footnotes): a footnote quotes the verse (`\fq`), but a word of the quote is not
  in the verse. Words with another ending count as found.
- **references** now also checks the references in `\r` (parallel passages under a heading), `\sr`, `\mr`,
  `\ior` (outline of a book introduction) and `\rq`.
- **self-references** (Unit 5): a cross reference `\x` that points to the verse it stands in.
- **one-chapter-books** (Unit 5): references to books with one chapter written two ways (`Jude 1:3` and `Jude 3`).
- **term-renderings** (Unit 1): a rendering in Biblical Terms with more than 5 words.
- **poetry-numbers** (Unit 6, Poetry 1): a number written with digits in a poetry line `\q1`, `\q2`, for example
  `40,000` in a song. Poetry usually writes numbers in words. References (`40:8`) are not shown.
- **line-ends** (Unit 6, Poetry and lists 2): a poetry line or a list item (`\li`) ends with a comma, and the next
  line starts with a
  capital letter of a word that is written small everywhere else. Maybe a full stop is missing.
- **poetry-two-sentences** (Unit 6, Poetry 3): a long poetry line with a full stop, `!` or `?` inside it, for example
  "…from the ground. You will eat plants…". Maybe the line should be two lines. "Long" is decided by the project:
  longer than 95% of its poetry lines.
- **poetry-long-lines** (Unit 6, Poetry 4): a very long poetry line, maybe two lines.
- **poetry-verse-inside** (Unit 6, Poetry 5): a verse number inside a poetry line.
- **poetry-chapter-break** (Unit 6, Poetry 6): poetry goes on into the next chapter with no `\b` (stanza
  break) at the end of the chapter and no heading.

## 1.0.2 (2026-11-12)

### What's new

- **Update button:** when a new version is ready, the button **Update** downloads it and starts it; you do not
  need to download it in the browser. The file is checked before it is used. If the update is not possible (for
  example, no rights to write into the folder of the program), the program stays as it was and the release page
  opens.
- **divine-name** (unit 6, Review lists): finds the name of God (LORD) without `\nd` in verses where other
  translations have it in `\nd`, for example `Herren sa` in a verse where every other `Herren` is in `\nd`. It also
  compares how many times: a verse with two LORD in `\nd` elsewhere but only one `\nd` here is shown. Psalm titles are
  checked too. Verses with "the Lord, the LORD" (Adonai) allow one word for both. The list of
  these verses is part of the program, so no other project is needed. Verse numbers are converted with the
  versification of the project and its own `custom.vrs`. Only words that the project itself nearly always
  puts in `\nd` are checked.
- **book-titles**: a book number written differently from the other books is shown, for example `\h 1Kings` when
  all other books have `\h 1 Kings`. `\h`, `\toc1`, `\toc2` and `\toc3` are compared each on their own, because many
  projects write the short `\toc3` without a space (`1Ki`).
- The groups of checks in the window and the reports are now called **Unit 1 … Unit 6** (before: Stage).
- **spacing**: a number with a space after the thousands separator is shown, for example `1, 44,000`, `45, 000`
  or `53, 400`. Lists of numbers (`605, 597, 586`) and verse lists (`119:9–21, 103–105`) are not shown.

### Fixed

- **spacing:** projects with Hindi/Urdu number grouping (Project settings > Number settings) write `1,44,000`
  (groups of 2 digits, the last group 3 digits). Such numbers were shown as wrong; now they are right, and a
  number written `144,000` in these projects is shown.
- **Daughter projects** (made from another project in Paratext) have no versification of their own: the checker now
  takes the versification of the parent project, as Paratext does. Before it used English, so report links and verse
  numbers of Biblical Terms could be one verse off in such projects (for example in Psalms).
- **punctuation:** a mark of Scripture references (for example the range mark `–` in Project settings >
  Scripture reference settings > Reference Format) is not reported inside a reference (`5:1–3`, `12:31b–13:2`,
  `Psalms 1–41`), also when the punctuation lists reject it. In other places (`word–word`) it is still checked.
- **Report links:** `0:0` (the introduction of a book) is now a link too; it opens the start of the book
  in Paratext (`1:0`, where Paratext keeps the introduction).
- **book-titles:** the text of the check now says that the long book name `\toc1` is all title lines `\mt1`,
  `\mt2`, `\mt3` … joined in the order of the file (for example `\mt2 + \mt1 + \mt3`); before it gave only
  `\mt2 + \mt1` as the example. The check itself already joined every `\mt` line.

## 1.0.1 (2026-11-05)

### What's new

- The version is shown in the window title.
- At start the window asks GitHub for the newest release; when there is a newer one, a line with a **Download**
  button appears. Nothing is downloaded by itself.

## 1.0 (2026-11-05)

First release: the window, checks in 6 stages, HTML and txt reports, links from the report to Paratext.
