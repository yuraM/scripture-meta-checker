# Changelog

Changes of the Scripture checker by release. Releases: https://github.com/yuraM/scripture-meta-checker/releases

## Unreleased

### Fixed

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
