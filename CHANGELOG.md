# Changelog

Changes of the Scripture checker by release. Releases: https://github.com/yuraM/scripture-meta-checker/releases

## Unreleased

### What's new

- **Update button:** when a new version is ready, the button **Update** downloads it and starts it; you do not
  need to download it in the browser. The file is checked before it is used. If the update is not possible (for
  example, no rights to write into the folder of the program), the program stays as it was and the release page
  opens.

## 1.0.2 (2026-11-12)

### What's new

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
