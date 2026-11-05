# Changelog

Changes of the Scripture checker by release. Releases: https://github.com/yuraM/scripture-meta-checker/releases

## Unreleased

### What's new

- **divine-name** (stage 6, Review lists): finds the name of God (LORD) without `\nd` in verses where other
  translations have it in `\nd`, for example `Herren sa` in a verse where every other `Herren` is in `\nd`. The list of
  these verses is part of the program, so no other project is needed. Only words that the project itself nearly always
  puts in `\nd` are checked.

### Fixed

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
