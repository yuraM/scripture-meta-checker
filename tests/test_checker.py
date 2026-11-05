import tempfile
from dataclasses import replace
import unittest
from pathlib import Path

from checker.checks import (
    BOOK_CHECKS, CHECKS, ERROR, PROJECT_CHECKS, SOURCE_CHECKS, WARNING, CheckContext, UsageCounter,
    check_hyphenation, check_lists, check_name_case, check_references, check_styled_words, check_unused,
    check_variants,
)
from checker.books import book_from_file_name, file_number
from checker.hyphenation import inconsistent_affixes, is_unhyphenated, load_hyphenation, rule_violations
from checker.languages import GENERIC, PROFILES, profile_for
from checker.parallels import PassageStatus
from checker.quotes import check_quotes
from checker.references import parse_reference
from checker.settings import ReferenceFormat, load_settings, split_list
from checker.spelling import SpellingEntry, SpellingList, load_spelling_status
from checker.tokens import Run, join_words, punctuation_pattern, split_runs
from checker.structure import index_book
from checker.usfm import parse_usfm

SETTINGS_XML = """﻿<ScriptureText>
  <Name>test</Name>
  <FileNamePostPart>test.SFM</FileNamePostPart>
  <ValidCharacters>  \n а б в г д е є і ї к л м н о п р с т у ш я А Б В Г Д К Л М Н О П Р С Т Ш Я . , ! ? : - « » ʼ   0 1 2 3 4 5 6 7 8 9</ValidCharacters>
  <InvalidCharacters>’ "</InvalidCharacters>
  <ValidPunctuation>._ ,_ !_ ?_ :_ - ʼ _« »_ »._ :_«</ValidPunctuation>
  <InvalidPunctuation>, _,_</InvalidPunctuation>
  <ValidPunctuation_NonText>- ʼ</ValidPunctuation_NonText>
  <Abbreviations>св. див.</Abbreviations>
  <ValidMixedCapitalization>Бет-Ель</ValidMixedCapitalization>
  <InvalidMixedCapitalization>аджеТи</InvalidMixedCapitalization>
  <SentenceFinalPunctuation>.?!:</SentenceFinalPunctuation>
  <ValidSentenceFinalPunctCapitalization>? : !\\0020–</ValidSentenceFinalPunctCapitalization>
  <ValidUncapitalizedStyles>q1</ValidUncapitalizedStyles>
  <InvalidUncapitalizedStyles>p</InvalidUncapitalizedStyles>
  <NumberDecimalPoint>,</NumberDecimalPoint>
  <NumberMedialPunctuation>-/–</NumberMedialPunctuation>
  <ChapterVerseSeparator>:</ChapterVerseSeparator>
  <NumberThousandsSeparator> </NumberThousandsSeparator>
  <Pairs>(/) [/]</Pairs>
  <RepeatableWords>так</RepeatableWords>
  <NonRepeatableWords>і</NonRepeatableWords>
  <ValidParagraphFinalPunctuationItems>p_. p_! q1_, q1 s1</ValidParagraphFinalPunctuationItems>
  <InvalidParagraphFinalPunctuationItems>q1_:</InvalidParagraphFinalPunctuationItems>
  <MarkersRequiringSentenceFinalPunctuation>p</MarkersRequiringSentenceFinalPunctuation>
  <NormalizationForm>NFC</NormalizationForm>
</ScriptureText>"""

SPELLING_XML = """<?xml version="1.0" encoding="utf-8"?>
<SpellingStatus>
  <Status Word="слово" State="R" />
  <Status Word="аарона" State="R"><SpecificCase>Аарона</SpecificCase></Status>
  <Status Word="господь" State="R"><SpecificCase>ГОСПОДЬ</SpecificCase></Status>
  <Status Word="ен-мішпату" State="R"><SpecificCase>Ен-Мішпату</SpecificCase></Status>
  <Status Word="помилка" State="W"><Correction>правильно</Correction></Status>
  <Status Word="дивіться" State="R" />
  <Status Word="Дивіться" State="W"><Correction>дивиться</Correction></Status>
</SpellingStatus>"""


class TempProjectMixin:
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "Settings.xml").write_text(SETTINGS_XML, encoding="utf-8")
        (self.root / "SpellingStatus.xml").write_text(SPELLING_XML, encoding="utf-8")
        self.settings = load_settings(self.root / "Settings.xml")
        self.spelling = load_spelling_status(self.root / "SpellingStatus.xml")
        self.ctx = CheckContext(self.settings, self.spelling)

    def tearDown(self):
        self._tmp.cleanup()

    def run_check(self, name, usfm):
        return [f for segment in parse_usfm(usfm, "TST") for f in CHECKS[name](self.ctx.analyse(segment), self.ctx)]


class SettingsTest(TempProjectMixin, unittest.TestCase):
    def test_split_list_keeps_unicode_spaces_and_decodes_escapes(self):
        self.assertEqual(split_list(" a \n  !\\0020– "), ("a", " ", "! –"))

    def test_load_settings(self):
        self.assertIn(" ", self.settings.valid_characters)
        self.assertIn("»._", self.settings.valid_punctuation)
        self.assertIn("! –", self.settings.valid_sentence_final_capitalization)
        self.assertEqual(self.settings.sentence_final_punctuation, frozenset(".?!:"))
        # NumberMedialPunctuation "-/–" is a set of characters, "/" included.
        self.assertEqual(self.settings.number_medial_punctuation, frozenset({",", "-", "/", "–", ":", " "}))
        self.assertEqual(self.settings.pairs, (("(", ")"), ("[", "]")))
        self.assertIn("ʼ", self.settings.punctuation_characters)
        self.assertNotIn("_", self.settings.punctuation_characters)

    def test_settings_written_differently_in_other_projects(self):
        # e.g. the English project: space separated SentenceFinalPunctuation, no ValidPunctuation_NonText.
        path = self.root / "Other.xml"
        path.write_text("<ScriptureText><SentenceFinalPunctuation>. ! ? : —</SentenceFinalPunctuation>"
                        "</ScriptureText>", encoding="utf-8")
        other = load_settings(path)
        self.assertEqual(other.sentence_final_punctuation, frozenset(".!?:—"))
        self.assertIn("ʼ", other.word_medial_punctuation)
        self.assertIn("-", other.word_medial_punctuation)

    def test_load_spelling_status(self):
        self.assertEqual(self.spelling.lookup("Слово").state, "R")
        self.assertEqual(self.spelling.lookup("аарона").specific_cases, ("Аарона",))
        self.assertEqual(self.spelling.lookup("помилка").corrections, ("правильно",))
        self.assertIsNone(self.spelling.lookup("інше"))


class UsfmTest(unittest.TestCase):
    def test_segments_refs_and_notes(self):
        usfm = ("\\id TST - Test\r\n\\c 1\r\n\\p\r\n\\v 1 Перше\\f + \\fr 1:1 \\ft Примітка.\\f* слово.\r\n"
                "\\v 2 \\nd Господь\\nd* сказав.\r\n\\q1 Вірш \\xt 8-му|TST 1:8\\xt*.")
        main, note, poem = parse_usfm(usfm)
        self.assertEqual(main.text, "Перше слово. Господь сказав.")
        self.assertEqual(main.book, "TST")
        self.assertEqual(main.ref_at(0), "1:1")
        self.assertEqual(main.ref_at(main.text.index("Господь")), "1:2")
        self.assertEqual((note.text, note.in_note, note.ref_at(0)), ("Примітка.", True, "1:1"))
        self.assertEqual((poem.style, poem.text), ("q1", "Вірш 8-му."))

    def test_category_marker_is_skipped(self):
        (note,) = [s for s in parse_usfm("\\p Text\\f + \\cat dup\\cat*\\fr 1:1 \\ft Or sea\\f*") if s.in_note]
        self.assertEqual(note.text, "Or sea")


class TokensTest(unittest.TestCase):
    def test_runs_words_and_patterns(self):
        text = "«Кірʼят-Арбу», слово"
        runs = split_runs(text, lambda ch: ch.isalpha() and ch != "ʼ")
        words = join_words(runs, frozenset("-ʼ"))
        self.assertEqual([w.text for w in words], ["Кірʼят-Арбу", "слово"])
        self.assertEqual(punctuation_pattern(runs[0], len(text)), "_«")
        self.assertEqual(punctuation_pattern(Run("», ", 12, False), len(text)), "»,_")


class ChecksTest(TempProjectMixin, unittest.TestCase):
    def test_characters(self):
        findings = self.run_check("characters", "\\p Слово’ й")
        self.assertEqual([(f.severity, f.item) for f in findings], [(ERROR, "’"), (WARNING, "й")])

    def test_punctuation(self):
        findings = self.run_check("punctuation", "\\p Слово , слово; слово 6,8.")
        self.assertEqual([(f.severity, f.item) for f in findings], [(ERROR, "_,_"), (WARNING, ";_")])

    def test_mixed_capitalization(self):
        # Бет-Ель is in ValidMixedCapitalization only, which is ignored; Ен-Мішпату is approved in SpellingStatus.
        findings = self.run_check("mixed-capitalization", "\\p Ен-Мішпату Бет-Ель аджеТи ен-Мішпату США.")
        self.assertEqual([(f.severity, f.item) for f in findings],
                         [(WARNING, "Бет-Ель"), (ERROR, "аджеТи"), (WARNING, "ен-Мішпату")])

    def test_capitalization(self):
        findings = self.run_check("capitalization", "\\p слово. слово св. слово? слово! – слово")
        self.assertEqual([f.item for f in findings], ["p", "."])
        self.assertEqual(self.run_check("capitalization", "\\q1 слово"), [])

    def test_spelling(self):
        findings = self.run_check("spelling", "\\p Слово помилка аарона інше 12 «Дивіться, дивіться \\nd Господь\\nd*")
        self.assertEqual([(f.severity, f.item) for f in findings],
                         [(ERROR, "помилка"), (WARNING, "аарона"), (WARNING, "інше"), (WARNING, "Дивіться")])
        self.assertIn("Wordlist disagrees with itself", findings[-1].message)

    def test_numbers(self):
        from checker.checks import UsageCounter, check_numbers
        self.ctx.settings = replace(self.settings, number_thousands_separator=".")
        usfm = ("\\id TST\n\\ip У 1446 році.\n\\c 1\n\\p "
                + " ".join(f"\\v {n} Було 4.000 воїнів." for n in range(1, 13))
                + " \\v 13 Було 4000 воїнів і 12.000 коней, H1234.")
        usage = UsageCounter()
        for segment in parse_usfm(usfm, "TST"):
            usage.add(self.ctx.analyse(segment), self.ctx)
        findings = list(check_numbers(usage, self.ctx))
        self.assertEqual([(f.ref, f.item) for f in findings], [("1:13", "4000")])
        self.assertIn("12 of 13", findings[0].message)
        self.assertIn("4000", findings[0].context)

    def test_spelling_leaves_mixed_case_to_its_check(self):
        text = "\\p Бет-Ель ен-Мішпату слово"
        self.assertEqual([f.item for f in self.run_check("spelling", text)], ["Бет-Ель", "ен-Мішпату"])
        # Both checks in one run: the word is shown once, by mixed-capitalization; the note says so.
        self.ctx.checks = frozenset({"spelling", "mixed-capitalization"})
        self.assertEqual(self.run_check("spelling", text), [])
        self.assertIn("mixed-capitalization", self.ctx.notes["spelling"])
        # A word marked wrong (W) stays a spelling error: it has a correction.
        self.ctx.spelling.entries["бет-ель"] = SpellingEntry("бет-ель", "W", (), ("Бет-Эль",))
        self.assertEqual([(f.severity, f.item) for f in self.run_check("spelling", text)], [(ERROR, "Бет-Ель")])

    def test_repeated_words(self):
        findings = self.run_check("repeated-words", "\\p слово слово, так так і і Слово слово. слово")
        self.assertEqual([(f.severity, f.item) for f in findings],
                         [(WARNING, "слово"), (ERROR, "і"), (WARNING, "слово")])

    def test_spacing(self):
        findings = self.run_check("spacing", "\\p Слово  слово 12000 і 10 000 і 10 000 і 1 00 і 3:12345")
        self.assertEqual([f.item for f in findings],
                         ["double space", "no thousands separator", "wrong thousands separator", "digit groups"])

    def test_scripts(self):
        findings = self.run_check("scripts", "\\p cлово слово Word VІ")
        self.assertEqual([(f.severity, f.item) for f in findings], [(ERROR, "cлово"), (ERROR, "VІ")])
        self.assertIn("LATIN SMALL LETTER C", findings[0].message)
        self.assertIn("in a LATIN word", findings[1].message)

    def test_normalization(self):
        # "е́" has no precomposed form, so it is NFC; a decomposed "й" is not.
        findings = self.run_check("normalization", "\\p е́ й")
        self.assertEqual([f.item for f in findings], ["й"])

    def test_paragraph_final(self):
        findings = self.run_check("paragraph-final",
                                  "\\p Слово.\n\\p Слово,\n\\p (Слово!)\n\\q1 слово:\n\\q1 слово;\n\\s1 Слово")
        self.assertEqual([(f.severity, f.item) for f in findings], [(WARNING, "p_,"), (ERROR, "q1_:")])

    def test_pairs(self):
        usfm = "\\p (слово [слово) слово] слово)\n\\s1 (Заголовок\n\\p слово (далі\n\\p кінець)"
        analyses = [self.ctx.analyse(s) for s in parse_usfm(usfm, "TST")]
        findings = list(BOOK_CHECKS["pairs"](analyses, self.ctx))
        self.assertEqual([(f.severity, f.item) for f in findings],
                         [(ERROR, "["), (ERROR, "]"), (ERROR, ")"), (ERROR, "(")])

    def test_quote_marks_in_pairs_are_left_to_quotes_check(self):
        settings = replace(self.settings, pairs=(("(", ")"), ("“", "”")), quote_levels=(("“", "”"),))
        ctx = CheckContext(settings, self.spelling)
        analyses = [ctx.analyse(s) for s in parse_usfm("\\p “слово (далі", "TST")]
        self.assertEqual([f.item for f in BOOK_CHECKS["pairs"](analyses, ctx)], ["("])

    def test_removed_text_does_not_make_two_spaces(self):
        usfm = ("\\d один // два//три\n\\p а\\f + \\fr 1:1 \\ft б. \\+fv 2\\+fv* в \\fv 3\\fv*  г\\f* д "
                "\\fig x\\fig* е")
        # The two spaces after \fv* are really in the source, so they stay.
        self.assertEqual([s.text for s in parse_usfm(usfm, "TST")], ["один дватри", "а д е", "б. в  г"])

    def test_note_in_heading_may_name_next_verse(self):
        content = ("\\id TST\n\\c 1\n\\p \\v 1 а\n\\s1 б\\f + \\fr 1:2 \\ft в\\f*\n\\p \\v 2 г\n"
                   "\\s1 д\\f + \\fr 1:4 \\ft е\\f*\n\\p \\v 3 ж")
        findings = list(SOURCE_CHECKS["usfm"]("TST", content, self.ctx))
        self.assertEqual([(f.ref, f.item) for f in findings], [("1:2", "\\fr")])

    def test_letter_mark_is_not_a_book_name(self):
        fmt = ReferenceFormat(chapter_verse=":", verse_ranges=("-",), verse_sequences=(",", " x "),
                              chapter_sequences=("; ", " x "), book_sequences=("; ",))
        parts, issues = parse_reference("36:1,9 x 37:2", fmt)
        self.assertEqual(issues, [])
        self.assertEqual([(p.name, p.chapter, p.verses) for p in parts],
                         [("", 36, [(1, 1), (9, 9)]), ("", 37, [(2, 2)])])

    def test_usfm_structure(self):
        content = ("\\id TST\n\\c 1\n\\p \\v 1 Слово \\nd Бог\\nd* \\add слово\n\\p \\v 2 \\f + \\fr 1:2 \\ft нота\n"
                   "\\p \\v 4 слово\\wj*\n\\v 3 слово \\v 5a слово \\v 5b слово \\v 6-7 \\v 8\n\\c 3\n\\p \\v 1 слово")
        findings = list(SOURCE_CHECKS["usfm"]("TST", content, self.ctx))
        self.assertEqual([(f.ref, f.severity, f.message) for f in findings], [
            ("1:1", ERROR, "\\add is not closed at the end of the paragraph"),
            ("1:2", ERROR, "note \\f has no closing \\f*"),
            ("1:2", WARNING, "verse 2 has no text"),  # only a note
            ("1:4", WARNING, "verse 3 is missing"),
            ("1:4", ERROR, "\\wj* has no opening \\wj"),
            ("1:3", ERROR, "wrong order: verse 3 comes after verse 4"),
            ("1:6-7", WARNING, "verse 6-7 has no text"),
            ("1:8", WARNING, "verse 8 has no text"),
            ("3:0", ERROR, "chapter 2 is missing"),
        ])

    def test_book_from_file_name(self):
        self.assertEqual([file_number(code) for code in ("GEN", "MAL", "MAT", "XXA", "FRT", "INT")],
                         ["01", "39", "41", "94", "A0", "A7"])
        self.assertEqual(book_from_file_name("091SAtest.SFM", "", "test.SFM", "41MAT"), "1SA")
        self.assertEqual(book_from_file_name("100XXGtest.SFM", "", "test.SFM", "41MAT"), "XXG")
        self.assertEqual(file_number("XXG"), "100")
        self.assertEqual(book_from_file_name("GEN.SFM", "", ".SFM", "MAT"), "GEN")
        self.assertEqual(book_from_file_name("pre41.sfm", "pre", ".SFM", "41"), "MAT")
        self.assertIsNone(book_from_file_name("notes.SFM", "", ".SFM", "41MAT"))
        self.assertIsNone(book_from_file_name("GEN.SFM", "", ".SFM", "unknown"))

    def test_usfm3_attributes_and_milestones_are_not_text(self):
        content = ('\\id FRT\n\\periph Title Page Full Bible |id="title"\n'
                   '\\mt1 Holy \\w Bible|lemma="b" strong="H1"\\w* and \\w grace|grace\\w*.\n'
                   '\\p \\qt-s |sid="q1" who="Me"\\*Text\\qt-e |eid="q1"\\*\\zgetperiph |id="intbible"\\*.\n'
                   '\\p \\fig |src="C: \\Users \\a.jpg" size="col"\\fig* end \\jmp Who|link-href="XXF 10:0"\\jmp*.\n'
                   '\\c 1\n\\p \\v 1 Word \\xt 8|GEN 2:8\\xt* and \\xt 9|link-href="GEN 2:9"\\xt*.')
        self.assertEqual([s.text for s in parse_usfm(content, "FRT")],
                         ["Holy Bible and grace.", "Text.", "end Who.", "Word 8 and 9."])
        self.assertEqual(list(SOURCE_CHECKS["usfm"]("FRT", content, self.ctx)), [])
        self.assertEqual([r.text for r in index_book("FRT", content).references], ["8|GEN 2:8", "9|GEN 2:9"])

    def test_book_titles(self):
        def messages(content):
            return [f.message for f in SOURCE_CHECKS["book-titles"]("TST", content, self.ctx)]

        good = ("\\id TST\n\\h Друге Самуїла\n\\toc1 Друга книга Самуїла\n\\toc2 Друге Самуїла\n"
                "\\mt2 Друга книга\n\\mt1 Самуїла\\f + \\ft нота\\f*\n\\c 1\n\\mt1 не заголовок")
        self.assertEqual(messages(good), [])
        # \mt1 before \mt2: the title is read in file order; the intro title \imt on the same line is not part of it.
        self.assertEqual(messages("\\toc1 Книга Самуїла перша\n\\mt1 Книга Самуїла \\mt2 перша \\imt Вступ\n"), [])
        # Three title lines: \mt2 + \mt1 + \mt3.
        self.assertEqual(messages("\\toc1 Друга книга Самуїла пророка\n\\mt2 Друга книга\n\\mt1 Самуїла\n"
                                  "\\mt3 пророка\n\\c 1\n"), [])
        self.assertEqual(messages("\\h Буття\n\\toc1 Книга Буття\n\\toc2 Бут.\n\\mt1 Буття\n"), [
            "the long book name \\toc1 'Книга Буття' is not the same as the main title 'Буття' (\\mt1)",
            "the short book name \\toc2 'Бут.' is not the same as the running header \\h 'Буття'",
        ])
        self.assertEqual(messages("\\toc1 Рут\n\\mt1\n"), ["the main title (\\mt1) is empty; the long book name "
                                                          "\\toc1 is 'Рут'"])

    def test_rendering_pattern(self):
        from checker.terms import rendering_pattern

        def found(rendering, text):
            return bool(rendering_pattern(rendering).search(text.lower() + " "))

        self.assertTrue(found("Варавв", "відпустив Варавву."))         # the start of a word
        self.assertFalse(found("голошув", "проголошував"))             # not inside a word
        self.assertTrue(found("Єгип*т*", "до Єгипету"))                  # * = any letters
        self.assertTrue(found("тонк льон", "у тонкому льоні"))          # each word of a phrase is a start
        self.assertTrue(found("місц ** судді", "на місці для судді"))   # ** = any words
        self.assertTrue(found("Нааман", "крім Наамана-сирійця."))      # a hyphen ends the word
        self.assertIsNone(rendering_pattern("(a comment only)"))

    def test_terms_checks(self):
        from checker.terms import load_terms
        project = self.root / "terms"
        project.mkdir()
        (project / "ProjectBiblicalTerms.xml").write_text(
            "<BiblicalTermsList><Term Id=\"γῆ\"><Gloss>earth</Gloss><References>"
            + "".join(f"<Verse>040001{verse:03d}00</Verse>" for verse in range(1, 22))
            + "</References></Term></BiblicalTermsList>", encoding="utf-8")
        (project / "TermRenderings.xml").write_text(
            "<TermRenderingsList><TermRendering Id=\"γῆ\" Guess=\"false\"><Renderings>земл||cуш</Renderings>"
            "<Denials><Denial>40001021</Denial><Denial>40002001</Denial></Denials></TermRendering>"
            "<TermRendering Id=\"other list\" Guess=\"true\"><Renderings>x</Renderings></TermRendering>"
            "</TermRenderingsList>", encoding="utf-8")
        ctx = CheckContext(self.settings, self.spelling)
        ctx.terms, _ = load_terms(project, "Project:test:ProjectBiblicalTerms.xml")
        usage = UsageCounter()
        verses = {verse: "на землі" for verse in range(1, 21)}
        verses[7] = "у краю"        # missing in 1 of 20 verses: a clear case
        verses[21] = "на землі"     # marked OK without a rendering, but the rendering is there
        for verse, text in verses.items():
            usage.verse_texts[("MAT", 1, verse)] = text
        usage.words.update(["на", "землі", "у", "краю"])
        terms = list(PROJECT_CHECKS["terms"](usage, ctx))
        self.assertEqual([(f.ref, f.item) for f in terms], [("1:7", "γῆ"), ("(renderings)", "cуш")])
        self.assertIn("19 of its 20 verses", terms[0].message)
        lists = list(PROJECT_CHECKS["term-lists"](usage, ctx))
        # The guessed term is not in the project list: Paratext does not show it, so it is not reported.
        self.assertEqual([(f.ref, "is here now" in f.message) for f in lists], [("1:21", True), ("2:1", False)])
        ctx.terms = None
        self.assertEqual(list(PROJECT_CHECKS["terms"](usage, ctx)), [])
        self.assertIn("terms", ctx.skipped)

    def test_versification(self):
        from checker.versification import original_to_project, read_mappings
        self.assertEqual(read_mappings("PSA 51:0 = PSA 51:1-2  # title\nJOL 2:28-29 = JOL 3:1-2\n#X 1:1 = X 1:2"),
                         [(("PSA", 51, 0), ("PSA", 51, 1)), (("PSA", 51, 0), ("PSA", 51, 2)),
                          (("JOL", 2, 28), ("JOL", 3, 1)), (("JOL", 2, 29), ("JOL", 3, 2))])
        project = self.root / "vrs"
        project.mkdir()
        mapping = original_to_project(project)  # the English versification kept in the package
        self.assertEqual(mapping[("PSA", 51, 3)], ("PSA", 51, 1))
        self.assertEqual(mapping[("MAL", 3, 19)], ("MAL", 4, 1))
        (project / "custom.vrs").write_text("1SA 20:43 = 1SA 21:1\n", encoding="utf-8")
        self.assertEqual(original_to_project(project)[("1SA", 21, 1)], ("1SA", 20, 43))

    def test_reference_names_and_no_break_space(self):
        fmt = ReferenceFormat(chapter_verse=":", verse_ranges=("–",), verse_sequences=(", ",),
                              chapter_sequences=("; ", "; "), book_sequences=("; ",))
        parts, issues = parse_reference("см. 3~Цар. 7:23–26; 2~Пар. 4:6", fmt)  # ~ = no-break space
        self.assertEqual([(p.name, p.chapter) for p in parts], [("3 Цар.", 7), ("2 Пар.", 4)])
        self.assertEqual(issues, [])
        # The name stays over whole chapters, and a person is asked: chapters, or a ':' missing?
        parts, issues = parse_reference("Быт. 37; 39; 41:37–57", fmt)
        self.assertEqual([(p.name, p.chapter) for p in parts], [("Быт.", 41)])
        self.assertEqual([(i.item, i.is_question) for i in issues], [("Быт. 37; 39;", True)])
        # Book names: words before the name are dropped, also words that are no abbreviations.
        usage = UsageCounter()
        usage.book_names.update({"исх": "EXO", "пс": "PSA", "1 цар": "1SA"})
        ctx = CheckContext(replace(self.settings, abbreviations=frozenset({"См.", "Исх."})), self.spelling)
        from checker.checks import _name_to_book
        self.assertEqual([_name_to_book(n, usage, ctx) for n in ("См. Исх.", "см. также Пс.", "1~Цар.", "См.",
                                                                 "см. сноску к")], ["EXO", "PSA", "1SA", "", None])

    def test_special_spaces(self):
        n = " "
        fmt = ReferenceFormat(chapter_verse=":", verse_sequences=(f",{n}", " и "), chapter_sequences=("; ",))
        settings = replace(self.settings, reference_format=fmt, number_thousands_separator=n,
                           quote_levels=(("«", "»"), ("„", "“")), abbreviations=frozenset({"н.~э.", "ст."}))
        ctx = CheckContext(settings, self.spelling)
        content = (f"\\id TST\n\\rem до н. э. «{n}x\n\\c 1\n\\p \\v 1 «Він сказав: „Так“{n}» і 50{n}000 людей "
                   f"\\wj „слово“\\wj*{n}»\\f + \\fr 1:1 \\ft \\fv 1{n}\\fv*\\fqa а \\fv 2\\fv* б ст.~8,{n}9 і ст.~7, 11 "
                   f"\\xt ст.~1, 2\\xt*\\f*\n\\v 2 до н.{n}э. і до н. э. та То{n}есть")
        found = [(f.ref, f.item) for f in SOURCE_CHECKS["special-spaces"]("TST", content, ctx)]
        self.assertEqual(found, [
            ("1:1", "\\fv"),            # "\fv 2\fv* б": no U+202F before \fv*, a space after it
            ("1:2", "н.~э."),           # a narrow no-break space in an abbreviation written with ~
            ("1:2", f"То{n}есть"),      # a narrow no-break space between two words
            ("1:2", "н.~э."),           # the abbreviation with a normal space
            ("1:1", "ст.~7, 11"),       # ", " is not a SequenceIndicator mark (the \xt is left to `references`)
        ])

    def test_naming_settings(self):
        path = self.root / "Naming.xml"
        path.write_text('<ScriptureText><Naming PrePart="x" PostPart="y.SFM" BookNameForm="MAT" /></ScriptureText>',
                        encoding="utf-8")
        settings = load_settings(path)
        self.assertEqual((settings.file_name_pre_part, settings.file_name_post_part, settings.file_name_book_form),
                         ("x", "y.SFM", "MAT"))

    def test_book_of_a_file(self):
        # A second \id (a draft of another book pasted into the file) does not change the book.
        content = "\\id XXB - notes \\id LUK - draft\n\\c 1\n\\p \\v 1 слово"
        self.assertEqual({s.book for s in parse_usfm(content, "95XXB")}, {"XXB"})
        ctx = CheckContext(replace(self.settings, file_name_book_form="41MAT"), self.spelling)
        findings = list(SOURCE_CHECKS["usfm"]("XXB", content, ctx, "95XXBtest.SFM"))
        self.assertEqual([f.item for f in findings], ["\\id LUK"])
        findings = list(SOURCE_CHECKS["usfm"]("XXB", content, ctx, "43LUKtest.SFM"))
        self.assertEqual([f.item for f in findings], ["\\id LUK", "LUK \\id XXB"])

    def test_note_reference_must_match_verse(self):
        content = ("\\id TST\n\\c 1\n\\p \\v 1 Слово\\f + \\fr 1:1 \\ft а\\f* \\v 2 слово\\f + \\fr 1:1–2 \\ft б\\f*"
                   " \\v 3 слово\\f + \\fr 1:4 \\ft в\\f*")
        findings = list(SOURCE_CHECKS["usfm"]("TST", content, self.ctx))
        self.assertEqual([(f.ref, f.message) for f in findings], [("1:3", "footnote reference \\fr 1:4 does not name this verse (chapter 1, verse 3)")])

    def test_ordinals(self):
        settings = replace(self.settings, number_ordinals=frozenset({"-й", "-го"}), number_ordinal_type="suffix")
        ctx = CheckContext(settings, self.spelling)
        segment = parse_usfm("\\p 5-й і 7-го, 8-ого, 1Sa 22:43б", "TST")[0]
        findings = list(CHECKS["ordinals"](ctx.analyse(segment), ctx))
        self.assertEqual([f.item for f in findings], ["-ого"])

    def test_heading_final_punctuation(self):
        findings = self.run_check("paragraph-final", "\\s1 Заголовок.\n\\s1 Чому?\n\\s1 Слово")
        self.assertEqual([f.message for f in findings], ["heading \\s1 ends with '.'"])

    def test_spelling_suggestion(self):
        findings = self.run_check("spelling", "\\p слвоо сліво")
        self.assertEqual([f.message for f in findings],
                         ["word is not approved in Wordlist: 'слвоо' (similar approved words: 'слово')",
                          "word is not approved in Wordlist: 'сліво' (similar approved words: 'слово')"])

    def test_name_case_and_styled_words(self):
        usage = UsageCounter()
        text = "\\p " + "і \\nd Господь\\nd* сказав, " * 40 + "і господь сказав, і Господь сказав."
        for segment in parse_usfm(text, "TST"):
            usage.add(self.ctx.analyse(segment), self.ctx)
        case = list(check_name_case(usage, self.ctx))
        self.assertEqual([f.message for f in case], ["'господь' in the middle of a sentence, usually written 'Господь' (41 of 42)"])
        styled = list(check_styled_words(usage, self.ctx))
        self.assertEqual([f.message for f in styled],
                         ["'господь' without \\nd, usually in \\nd (40 of 42)"] * 2)

    def test_references(self):
        usage = UsageCounter()
        usage.add_source("GEN", "\\id GEN\n\\toc3 Бут.\n\\c 1\n\\p \\v 1 а \\v 2 б\n\\c 2\n\\p \\v 1 в", self.ctx)
        usage.add_source("EXO", "\\id EXO\n\\toc3 Вих.\n\\c 1\n\\p \\v 1 а\\f + \\fr 1:1 \\ft \\xt Бут. 1:2; 2:1; "
                                "2:5; Вих. 3:1; Лев. 1:1; див. 1:1\\xt* \\xt тут|GEN 1:3\\xt*\\f*", self.ctx)
        findings = list(check_references(usage, self.ctx))
        self.assertEqual([(f.severity, f.item) for f in findings],
                         [(ERROR, "GEN 2:5"), (ERROR, "EXO 3:1"), (WARNING, "Лев."), (ERROR, "GEN 1:3")])

    def test_reference_book_names_with_vowel_signs(self):
        # Devanagari writes vowels with combining marks (U+093E in "यशा"); they belong to the book name.
        usage = UsageCounter()
        usage.add_source("ISA", "\\id ISA\n\\toc3 यशा\n\\c 1\n\\p \\v 1 а \\v 2 б", self.ctx)
        usage.add_source("REV", "\\id REV\n\\toc3 प्रका\n\\c 1\n\\p \\v 1 а\\x - \\xt यशा 1:2; यशा 1:5\\xt*\\x*", self.ctx)
        findings = list(check_references(usage, self.ctx))
        self.assertEqual([(f.severity, f.item) for f in findings], [(ERROR, "ISA 1:5")])

    def _reference_findings(self, *sources, **marks):
        fmt = ReferenceFormat(**marks)
        ctx = CheckContext(replace(self.settings, reference_format=fmt, chapter_verse_separator=fmt.chapter_verse),
                           self.spelling)
        usage = UsageCounter()
        for book, content in sources:
            usage.add_source(book, content, ctx)
        return [(f.severity, f.item) for f in check_references(usage, ctx)]

    TIGRINYA_MARKS = {"chapter_verse": "፥", "verse_ranges": ("-", "‑"), "verse_sequences": ("፣",),
                      "chapter_ranges": ("–",), "chapter_sequences": ("፤ ",), "book_sequences": ("፤ ",)}

    def test_references_use_marks_from_settings(self):
        books = ("GEN", "\\id GEN\n\\toc3 ዘፍ\n\\c 1\n\\p \\v 1 а \\v 2 б \\v 3 в\n\\c 2\n\\p \\v 1 г")
        findings = self._reference_findings(books, ("EXO", (
            "\\id EXO\n\\toc3 ዘፀ\n\\c 1\n\\p \\v 1 а\\x - \\xt ዘፍ 1፥1‑2፣3፤ 2፥1\\xt*\\x*"  # correct
            "\\x - \\xt ዘፍ 1፥1፤ ዘፍ 2፥9\\xt*\\x*"       # second book part does not exist
            "\\x - \\xt ዘፍ 1፥1፣9\\xt*\\x*"              # verse after the sequence mark does not exist
            "\\x - \\xt ዘፍ 1፥1–9፥1\\xt*\\x*"            # end of a chapter range does not exist
            "\\x - \\xt 6|GEN 9:6\\xt*\\x*"              # a link always uses ":"
            "\\x - \\xt ዘፍ 1:1\\xt*\\x*"                 # wrong chapter-verse mark
            "\\x - \\xt ዘፍ 1፥1,2\\xt*\\x*"               # wrong sequence mark
            "\\x - \\xt ዘፍ 1፥1;2፥1\\xt*\\x*"             # wrong mark between references
            "\\x - \\xt ዘፍ 1፥1፤ 2\\xt*\\x*"))            # number without a chapter: a person decides
            , **self.TIGRINYA_MARKS)
        self.assertEqual(findings, [
            (ERROR, "GEN 2፥9"), (ERROR, "GEN 1፥9"), (ERROR, "GEN 9፥1"), (ERROR, "GEN 9፥6"),
            (ERROR, ":"), (ERROR, ","), (ERROR, ";"), (WARNING, "2"),
        ])

    def test_reference_text_and_link_must_agree(self):
        books = ("GEN", "\\id GEN\n\\toc3 Бут.\n\\c 1\n\\p \\v 1 а \\v 2 б\\x - \\xt 2|GEN 1:2\\xt*"
                        "\\xt 1 Сам. 1:2|GEN 1:2\\xt*\\xt 8|GEN 1:2\\xt*\\xt 2|GEN 1:2ን\\xt*\\x*")
        self.assertEqual(self._reference_findings(books), [(WARNING, "GEN 1:2"), (WARNING, "ን")])

    def test_note_reference_with_marks_from_settings(self):
        fmt = ReferenceFormat(**self.TIGRINYA_MARKS)
        ctx = CheckContext(replace(self.settings, reference_format=fmt), self.spelling)
        content = ("\\id TST\n\\c 11\n\\p \\v 12 а \\v 13 б\\f + \\fr 11፥12፣13 \\ft в\\f*"
                   " \\v 14 г\\f + \\fr 11፥12፣13 \\ft д\\f*")
        findings = list(SOURCE_CHECKS["usfm"]("TST", content, ctx))
        self.assertEqual([f.ref for f in findings if f.item == "\\fr"], ["11:14"])

    def test_sequence_mark_between_digits_is_not_punctuation(self):
        xml = SETTINGS_XML.replace("</ScriptureText>", "<SequenceIndicator>, |፣</SequenceIndicator></ScriptureText>")
        (self.root / "Settings.xml").write_text(xml, encoding="utf-8")
        self.assertLessEqual({",", "፣"}, load_settings(self.root / "Settings.xml").number_medial_punctuation)

    def test_reference_range_mark_only_in_references(self):
        # "‒" is a rejected mark but the range mark of Reference Format: allowed in references only.
        fmt = ReferenceFormat(chapter_verse=":", verse_ranges=("‒",), chapter_ranges=("‒",),
                              verse_sequences=(", ",), chapter_sequences=("; ",))
        settings = replace(self.settings, reference_format=fmt, invalid_punctuation=frozenset({"‒"}),
                           number_medial_punctuation=frozenset({":", ","}))
        ctx = CheckContext(settings, self.spelling)
        ctx.book_title_words = frozenset({"1 пар"})
        segment = parse_usfm("\\p (5:1‒3, 7‒9; 12:31б‒13:2; 1~Пар. 22‒26; 28‒29) слово‒слово 10‒12", "TST")[0]
        findings = [f for f in CHECKS["punctuation"](ctx.analyse(segment), ctx) if f.item == "‒"]
        self.assertEqual(len(findings), 2)  # "слово‒слово" and "10‒12": not references

    def test_ordinals_skip_book_names(self):
        settings = replace(self.settings, number_ordinals=frozenset({"ን"}), number_ordinal_type="suffix")
        ctx = CheckContext(settings, self.spelling)
        ctx.book_name_words = frozenset({"1ዜና"})
        segment = parse_usfm("\\p 1ዜና 5ን 7ይ", "TST")[0]
        self.assertEqual([f.item for f in CHECKS["ordinals"](ctx.analyse(segment), ctx)], ["ይ"])

    def test_approvals(self):
        from checker.approvals import suspicious_punctuation
        self.assertEqual(suspicious_punctuation("_,"), "it has a space before ','")
        self.assertEqual(suspicious_punctuation(",,_"), "',' is written two times")
        self.assertEqual(suspicious_punctuation("_..._"), "")  # an ellipsis is a deliberate run
        self.assertEqual(suspicious_punctuation("»._"), "")

        settings = replace(self.settings, valid_characters=self.settings.valid_characters | {""},
                           valid_punctuation=self.settings.valid_punctuation | {",,_"},
                           valid_paragraph_final=frozenset({"q1"}), invalid_paragraph_final=frozenset({"q1_,"}),
                           normalization_form="")
        spelling = SpellingList({
            "cлово": SpellingEntry("cлово", "R"),        # Latin "c"
            "ім’я": SpellingEntry("ім’я", "R"),           # "’" is marked wrong in the characters
            "слово": SpellingEntry("слово", "R"),
        })
        ctx = CheckContext(settings, spelling)
        usage = UsageCounter()
        text = "\\p Слово,, слово.\n" + "\\q1 Слово,\n" * 20 + "\\q1 Слово\n"
        for segment in parse_usfm(text, "TST"):
            usage.add(ctx.analyse(segment), ctx)
        findings = {f.item: f.message for f in PROJECT_CHECKS["approvals"](usage, ctx)}
        self.assertIn("private use character", findings[""])
        self.assertIn("',' is written two times (used once)", findings[",,_"])
        self.assertIn("20 of 21 \\q1 paragraphs end like this", findings["q1_,"])
        self.assertIn("CYRILLIC + LATIN", findings["cлово"])
        self.assertIn("1 word with it is marked right in Wordlist", findings["’"])
        self.assertIn("NormalizationForm", findings)
        self.assertIn("': ?' alone are marked correct", findings[": ?"])  # "! –" is a sequence, not alone
        self.assertNotIn("слово", findings)

    def test_reports_name_paratext_places(self):
        from checker.cli import CHECK_DESCRIPTIONS
        keys = ("ValidCharacters", "ValidPunctuation", "SpellingStatus", "NumberOrdinals", "NonRepeatableWords",
                "RangeIndicator", "ParallelPassageStatus", "InvalidMixedCapitalization")
        for check, text in CHECK_DESCRIPTIONS.items():
            self.assertFalse([key for key in keys if key in text], check)
        self.assertIn("Tools > Checking inventories > Markers missing final punctuation inventory",
                      CHECK_DESCRIPTIONS["paragraph-final"])
        findings = self.run_check("repeated-words", "\\p і і")
        self.assertEqual([f.message for f in findings],
                         ["word is written twice: 'і і' (marked wrong in Repeated words inventory)"])

    def test_lists(self):
        findings = list(check_lists(UsageCounter(), self.ctx))
        self.assertIn("'Дивіться' is W but 'дивіться' is R", {f.message for f in findings})

    def test_lists_hyphenated_wrong_word(self):
        # "-" is in every hyphenation list: not a word, even when the Wordlist marks it wrong.
        self.ctx.spelling.entries["-"] = SpellingEntry("-", "W")
        path = self.root / "hyphenatedWords.txt"
        path.write_text('HardHyphen = "-"\nSoftHyphen = "="\n*-\n*по=мил=ка\n*сло=во\n', encoding="utf-8")
        self.ctx.hyphenation = load_hyphenation(path)
        findings = [f for f in check_lists(UsageCounter(), self.ctx) if "is hyphenated" in f.message]
        self.assertEqual([f.item for f in findings], ["по=мил=ка"])

    def _parallel_usage(self) -> UsageCounter:
        usage = UsageCounter()
        for content in ("\\id GEN\n\\c 1\n\\p \\v 1 alpha beta gamma delta \\v 2 one two three four five.\n"
                        "\\s1 Heading\n\\p \\v 3 eps zeta eta theta \\v 4 p q r s t \\v 5 k l m n o",
                        "\\id EXO\n\\c 1\n\\p \\v 1 one two, three four five six"):
            for segment in parse_usfm(content, "TST"):
                usage.add(self.ctx.analyse(segment), self.ctx)
        return usage

    def test_parallel_changes(self):
        group = ("GEN 1:1", "GEN 1:2")
        self.ctx.parallel_passages = [
            PassageStatus("GEN 1:1", group, "F", "alpha beta, gamma delta"),   # only punctuation differs
            PassageStatus("GEN 1:1", ("GEN 1:1",), "F", "omega beta gamma delta"),  # older entry of an old group
            PassageStatus("GEN 1:2", group, "F", "one two six four five"),     # changed
            PassageStatus("GEN 1:2", ("GEN 1:2",), "F", "one two six four five"),  # same entry in another group
            PassageStatus("GEN 1:2", group, "U", "zzz"),                       # not approved
            PassageStatus("GEN 1:5", group, "F", "eps zeta eta theta"),        # other verse numbers: found in 1:3
            PassageStatus("GEN 1:4", group, "F", "u v w x y"),                 # very different
            PassageStatus("GEN 1:1-2", group, "F", "alpha beta gamma delta one two three four nine"),  # a range
            PassageStatus("GEN 1:6-8,9", group, "F", "x"),                     # a list: not compared
        ]
        findings = list(PROJECT_CHECKS["parallel-changes"](self._parallel_usage(), self.ctx))
        self.assertEqual([(f.ref, f.message) for f in findings], [
            ("1:1-2", "'nine' was changed to 'five' after the parallel passage was approved"),
            ("1:2", "'six' was changed to 'three' after the parallel passage was approved"),
            ("1:4", "this verse was changed very much after the parallel passage was approved "
                    "(or its verse number is different there)"),
        ])

    def test_parallel_differences(self):
        group = ("GEN 1:2", "EXO 1:1", "GEN 1:1", "LEV 1:1-2", "EXO 1:1-2")  # LEV is not checked, EXO 1:2 is missing
        self.ctx.parallel_passages = [PassageStatus("GEN 1:2", group, "F", ""), PassageStatus("EXO 1:1", group, "F", "")]
        findings = list(PROJECT_CHECKS["parallel-differences"](self._parallel_usage(), self.ctx))
        self.assertEqual([(f.ref, f.message) for f in findings],
                         [("1:2", "the parallel verse EXO 1:1 is a little different: here nothing, there 'six'")])

    def test_parallel_checks_without_file(self):
        self.assertEqual(list(PROJECT_CHECKS["parallel-changes"](UsageCounter(), self.ctx)), [])
        self.assertIn("ParallelPassageStatus.xml", self.ctx.skipped["parallel-changes"])
        self.assertIn("Parallel Passages", self.ctx.skipped["parallel-changes"])

    def test_variants(self):
        usage = UsageCounter()
        text = "\\p " + "Петро Ізраїля " * 10 + "Петор Ізраїле"
        for segment in parse_usfm(text, "TST"):
            usage.add(self.ctx.analyse(segment))
        findings = list(check_variants(usage, self.ctx))
        self.assertEqual([(f.item, f.ref) for f in findings], [("петор", "0:0")])
        self.assertIn("two letters are swapped", findings[0].message)

    def test_variants_in_script_without_capitals(self):
        usage = UsageCounter()
        for segment in parse_usfm("\\p " + "ኣብራሃም " * 10 + "ኣብርሃም ብኣብራሃም", "TST"):
            usage.add(self.ctx.analyse(segment))
        self.assertEqual([f.item for f in check_variants(usage, self.ctx)], ["ኣብርሃም"])

    def test_unused(self):
        usage = UsageCounter()
        for segment in parse_usfm("\\p Слово помилка, Бет-Ель!", "TST"):
            usage.add(self.ctx.analyse(segment))
        # Locations name the Paratext window and the status there, not Settings.xml keys.
        unused = {(f.book, f.ref, f.item) for f in check_unused(usage, self.ctx)}
        self.assertNotIn("ValidMixedCapitalization", {ref for _, ref, _ in unused})
        self.assertIn(("Mixed capitalization inventory", "(marked wrong)", "аджеТи"), unused)
        self.assertIn(("Settings.xml", "Abbreviations", "св."), unused)
        self.assertIn(("Punctuation inventory", "(marked correct)", "»._"), unused)
        self.assertNotIn(("Punctuation inventory", "(marked correct)", ",_"), unused)
        self.assertIn(("Wordlist", "(right, R)", "аарона"), unused)
        self.assertNotIn(("Wordlist", "(right, R)", "слово"), unused)
        self.assertNotIn(("Wordlist", "(wrong, W)", "помилка"), unused)


def quote_settings(xml_body):
    """Settings with only the quote tags (the rest default)."""
    tmp = tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-8")
    with tmp:
        tmp.write(f"<ScriptureText>{xml_body}</ScriptureText>")
    try:
        return load_settings(Path(tmp.name))
    finally:
        Path(tmp.name).unlink()


UK_QUOTES = ("<Quotes>« »</Quotes><InnerQuotes>„ “</InnerQuotes><InnerInnerQuotes>« »</InnerInnerQuotes>"
             "<ContinueQuotes>No</ContinueQuotes>")
EN_QUOTES = ("<Quotes>“ ”</Quotes><InnerQuotes>‘ ’</InnerQuotes><InnerInnerQuotes>“ ”</InnerInnerQuotes>"
             "<ContinueQuotes>Yes</ContinueQuotes><Continuer>“</Continuer><InnerContinuer>‘</InnerContinuer>"
             "<ContinueAt>p</ContinueAt>")


class QuotesTest(unittest.TestCase):
    def run_quotes(self, settings_xml, usfm):
        settings = quote_settings(settings_xml)
        ctx = CheckContext(settings, SpellingList({}))
        return [(f.severity, f.message) for f in check_quotes([ctx.analyse(s) for s in parse_usfm(usfm, "TST")], ctx)]

    def test_correct_nesting_across_paragraphs(self):
        usfm = "\\c 1\\p\\v 1 Він сказав: «Слово „інше «третє» ще“ кінець\\p\\v 2 далі».\\s1 Заголовок «так»"
        self.assertEqual(self.run_quotes(UK_QUOTES, usfm), [])

    def test_missing_close_then_new_open(self):
        findings = self.run_quotes(UK_QUOTES, "\\c 1\\p\\v 1 «Перше. \\v 2 «Друге».")
        self.assertEqual(len(findings), 1)
        self.assertIn("'«' opens a new quote, but '«' from TST 1:1 is still open", findings[0][1])

    def test_wrong_level_and_mismatch(self):
        findings = self.run_quotes(UK_QUOTES, "\\c 1\\p\\v 1 „Слово“ і «слово „ще» кінець“")
        messages = [message for _, message in findings]
        self.assertIn("wrong mark for quote level 1: '„', it should be '«'", messages[0])
        self.assertIn("'»' closes '«' from TST 1:1 but '„' from TST 1:1 is still open", messages[1])
        self.assertIn("'“' closes a quote, but no quote is open", messages[2])

    def test_never_closed_and_notes_are_lenient(self):
        findings = self.run_quotes(UK_QUOTES, "\\c 1\\p\\v 1 «Слово\\f + \\fr 1:1 \\ft Або: …його».\\f*")
        self.assertEqual(findings, [
            (WARNING, "'»' closes a quote, but no quote is open (in a footnote)"),
            (ERROR, "quote mark '«' is opened but never closed"),
        ])

    def test_continuers(self):
        ok = "\\c 1\\p\\v 1 “First ‘inner\\p\\v 2 “ ‘still inner’ end.”\\q1 “Poem line,”"
        self.assertEqual(self.run_quotes(EN_QUOTES, ok), [])
        missing = self.run_quotes(EN_QUOTES, "\\c 1\\p\\v 1 “First\\p\\v 2 Second\\p\\v 3 Third.”")
        self.assertEqual(len(missing), 1)  # reported once per open quote
        self.assertIn("must start with '“'", missing[0][1])

    def test_apostrophe_is_not_a_quote(self):
        self.assertEqual(self.run_quotes(EN_QUOTES, "\\c 1\\p\\v 1 “Don’t go,” he said."), [])

    def test_closing_mark_followed_by_suffix(self):
        # Indonesian: a suffix may follow the closing mark ("‘apel’mu").
        self.assertEqual(self.run_quotes(EN_QUOTES, "\\c 1\\p\\v 1 “Makan ‘kismis’mu dan ‘apel’mu.”"), [])

    def test_optional_line_break_is_removed(self):
        (segment,) = parse_usfm("\\c 1\\p\\v 1 Libni //Simei")
        self.assertEqual(segment.text, "Libni Simei")


HYPHENATION_TXT ="""﻿#Hyphenated Word List v2.0
SoftHyphen = "="
*ба=чи=ти=муть
*би=ти=муть
*хо=ди=ти=муть
*жи=ти=муть
*пи=ти=муть
*спо=куша=тимуть
*ав=то=ри=тет=них
*ав=то=ри=тету
*ав=то=ри=те=там
*ав=то=ри=те=тів
*ав=то=ри=тети
*авто=рите=том
*вві=йти
*кл=ючи
*а=мінь
*двад=цят=ьох
*бо=йо=вий
*розповідати
*авель-бет-мааха
*слово
*плем=ʼя
*ac=cu=racy
*а́=дам
*вiд=ведіть
нові=слово
"""


class HyphenationTest(TempProjectMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        (self.root / "hyphenatedWords.txt").write_text(HYPHENATION_TXT, encoding="utf-8")
        self.hyphenation = load_hyphenation(self.root / "hyphenatedWords.txt")

    def test_load(self):
        entry = self.hyphenation.by_word["бачитимуть"]
        self.assertEqual((entry.breaks, entry.locked, entry.segments), ((2, 4, 6), True, ["ба", "чи", "ти", "муть"]))
        self.assertFalse(self.hyphenation.by_word["новіслово"].locked)

    def problems(self, profile):
        return {e.word: list(rule_violations(e, profile, frozenset("ʼ"))) for e in self.hyphenation.words}

    def test_rules_with_language_profile(self):
        problems = self.problems(PROFILES["uk"])
        self.assertEqual(problems["ввійти"], ["'й' must stay with the vowel before it"])
        self.assertEqual(problems["ключи"], ["part 'кл' has no vowel"])
        self.assertEqual(problems["амінь"], ["one letter stays alone at the end or start of a line"])
        self.assertEqual(problems["двадцятьох"], ["a line must not break before 'ь'"])
        self.assertEqual(problems["племʼя"], ["a line must not break before 'ʼ'"])
        self.assertEqual(problems["бойовий"], [])
        self.assertEqual(problems["accuracy"], [])  # other script: vowel rules are skipped
        self.assertEqual(problems["а́дам"], ["one letter stays alone at the end or start of a line"])  # stress mark ignored
        self.assertEqual(problems["вiдведіть"], ["has letters from different alphabets: CYRILLIC + LATIN (letters that look the same?)"])

    def test_generic_rules_only_without_profile(self):
        problems = self.problems(GENERIC)
        self.assertEqual(problems["ввійти"], [])
        self.assertEqual(problems["ключи"], [])
        self.assertEqual(problems["двадцятьох"], [])
        self.assertEqual(problems["амінь"], ["one letter stays alone at the end or start of a line"])
        self.assertEqual(problems["племʼя"], ["a line must not break before 'ʼ'"])

    def test_language_profile_from_settings_code(self):
        self.assertIs(profile_for("uk:::"), PROFILES["uk"])
        self.assertIs(profile_for("xyz"), GENERIC)
        self.assertIs(CheckContext(self.settings, self.spelling).language, GENERIC)  # no LanguageIsoCode

    def test_unhyphenated(self):
        flagged = {e.word for e in self.hyphenation.words if is_unhyphenated(e, PROFILES["uk"])}
        self.assertEqual(flagged, {"розповідати"})

    def test_affix_consistency(self):
        issues = list(inconsistent_affixes(self.hyphenation.words))
        self.assertEqual([(i.side, i.entry.text, i.actual, i.expected) for i in issues],
                         [("prefix", "авто=рите=том", "авто=ри", "ав=то=ри"),
                          ("suffix", "спо=куша=тимуть", "тимуть", "ти=муть")])

    def test_check_reports_missing_and_unused(self):
        ctx = CheckContext(self.settings, self.spelling, self.hyphenation)
        usage = UsageCounter()
        for segment in parse_usfm("\\p Слово розповідати інше", "TST"):
            usage.add(ctx.analyse(segment))
        findings = list(check_hyphenation(usage, ctx))
        self.assertIn(("missing", "інше"), {(f.ref, f.item) for f in findings})
        self.assertIn("'розповідати' is a long word with no places to break it", {f.message for f in findings})
        unused = {f.item for f in check_unused(usage, ctx) if f.book == "hyphenatedWords.txt"}
        self.assertIn("бачитимуть", unused)
        self.assertNotIn("слово", unused)


class ReportTest(unittest.TestCase):
    def report(self, findings, checks, unique):
        import io
        from checker.cli import write_report
        out = io.StringIO()
        write_report(findings, checks, unique, out)
        return out.getvalue()

    def test_unique_report_lists_all_locations(self):
        from checker.model import Finding
        findings = [Finding(book, ref, WARNING, "spelling", "x", "word 'x'", "ctx")
                    for book, ref in [("MAT", "27:46"), ("MAT", "28:1"), ("MAT", "28:1"), ("MRK", "15:34")]]
        self.assertIn("1. word 'x'\n   Found: 4 times\n   Text:  ctx\n   Where: MAT 27:46, 28:1 (2×); MRK 15:34",
                      self.report(findings, ["spelling"], unique=True))

    def test_unique_report_shows_errors_first(self):
        from checker.model import Finding
        findings = [Finding("MAT", "1:1", WARNING, "spelling", "x", "warning text", ""),
                    Finding("MAT", "1:2", ERROR, "spelling", "y", "error text", "")]
        text = self.report(findings, ["spelling"], unique=True)
        self.assertIn("CHECK: spelling", text)
        self.assertLess(text.index("1. error text"), text.index("2. warning text"))

    def test_line_report_and_empty_check(self):
        from checker.model import Finding
        findings = [Finding("MAT", "1:1", ERROR, "spelling", "x", "word 'x'", "ctx")]
        text = self.report(findings, ["spelling", "pairs"], unique=False)
        self.assertIn("MAT 1:1  error  spelling  word 'x'  [ctx]", text)
        self.assertIn("CHECK: pairs", text)
        self.assertIn("all checks", text)

    def test_every_check_has_a_description(self):
        from checker.checks import PROJECT_CHECKS
        from checker.cli import CHECK_DESCRIPTIONS
        self.assertEqual(set(CHECK_DESCRIPTIONS), {*CHECKS, *BOOK_CHECKS, *SOURCE_CHECKS, *PROJECT_CHECKS})

    def test_every_check_is_in_one_stage(self):
        from checker.checks import PROJECT_CHECKS
        from checker.stages import STAGES, in_stage_order, stage_checks
        staged = [name for _, names in STAGES for name in names]
        self.assertEqual(sorted(staged), sorted({*CHECKS, *BOOK_CHECKS, *SOURCE_CHECKS, *PROJECT_CHECKS}))
        self.assertEqual(in_stage_order(["unused", "spelling", "lists", "spelling"]), ["lists", "spelling", "unused"])
        self.assertEqual(stage_checks([2]), list(STAGES[1][1]))

    def test_stage_option(self):
        from checker.cli import build_parser
        args = build_parser().parse_args(["X", "--stage", "1", "--checks", "pairs"])
        self.assertEqual((args.stage, args.checks), ([1], ["pairs"]))

    def test_index_by_stage(self):
        from checker.html_report import CheckResult, write_index
        results = [CheckResult("usfm", "", errors=3), CheckResult("spelling", "", warnings=1)]
        with tempfile.TemporaryDirectory() as folder:
            index = write_index(Path(folder), "TST", results, "").read_text(encoding="utf-8")
            self.assertLess(index.index("Stage 2. File structure"), index.index("Stage 4. Words"))
            self.assertIn("Fix them first", index)
            # Only early stages checked: nothing later to warn about.
            index = write_index(Path(folder), "TST", results[:1], "").read_text(encoding="utf-8")
            self.assertNotIn("Fix them first", index)

    def test_html_report(self):
        import json
        import re
        from checker.cli import write_reports
        from checker.model import Finding
        findings = [Finding("MAT", "1:1", ERROR, "spelling", "x", "word '<x>'", "a </script> b"),
                    Finding("MAT", "1:2", ERROR, "spelling", "x", "word '<x>'", "")]
        with tempfile.TemporaryDirectory() as folder:
            from checker.cli import latest_run, new_run_folder
            report_dir = Path(folder) / "TST_report"
            (report_dir / "txt").mkdir(parents=True)
            (report_dir / "spelling.txt").write_text("old report", encoding="utf-8")  # layouts of older versions
            (report_dir / "txt" / "spelling.txt").write_text("old report", encoding="utf-8")
            (report_dir / "notes.txt").write_text("a file of the user", encoding="utf-8")
            first = new_run_folder(report_dir)
            write_reports(Path(folder) / "TST", findings, ["spelling"], first, True, {})
            run = new_run_folder(report_dir)  # the same minute: "<date>_<time>_2"
            results = write_reports(Path(folder) / "TST", findings, ["spelling", "pairs"], run, True,
                                    {"pairs": "Not checked: test."})
            self.assertEqual(latest_run(report_dir), run)
            self.assertTrue(run.name.startswith(first.name) and run.name.endswith("_2"))
            index = (run / "index.html").read_text(encoding="utf-8")
            page = (run / "html" / "spelling.html").read_text(encoding="utf-8")
            self.assertTrue((run / "txt" / "spelling.txt").exists())
            self.assertEqual(sorted(p.name for p in report_dir.iterdir()), sorted([first.name, run.name, "notes.txt"]))
            self.assertEqual(sorted(p.name for p in run.iterdir()), ["html", "index.html", "txt"])
        self.assertEqual([(r.name, r.errors, len(r.problems)) for r in results], [("spelling", 2, 1), ("pairs", 0, 0)])
        self.assertIn('href="html/spelling.html"', index)
        self.assertIn('href="txt/spelling.txt"', index)
        self.assertIn('href="txt/"', index)
        self.assertIn('href="../index.html"', page)
        self.assertIn('href="../txt/spelling.txt"', page)
        self.assertIn("not checked", index)
        # The text of the problems is data: "</script>" inside it must not end the script element.
        data = re.search(r'id="data">(.*?)</script>', page, re.S).group(1)
        self.assertEqual(json.loads(data)[0]["where"], "MAT 1:1, 1:2")
        self.assertEqual(json.loads(data)[0]["context"], "a </script> b")


class FootnotesTest(unittest.TestCase):
    FINAL = frozenset(".!?")

    def run_notes(self, bodies, verse_texts=None):
        from checker.footnotes import check_footnotes, read_notes
        usfm = "\\id TST\n\\c 1\n" + "\n".join(f"\\v {n} Текст.\\f + \\fr 1:{n} \\ft {body}\\f*"
                                             for n, body in enumerate(bodies, start=1))
        notes = read_notes("TST", usfm)
        return [(f.ref, f.severity, f.message) for f in check_footnotes(notes, self.FINAL, verse_texts or {})]

    def test_read_notes(self):
        from checker.footnotes import read_notes
        note, = read_notes("TST", "\\c 3\n\\v 5 Слово\\f + \\fr 3:5 \\ft Букв.: \\fqa сини\\fqa* Бога.\\f*")
        self.assertEqual((note.ref, note.formula, note.text), ("3:5", ("Букв.:", "fqa"), "Букв.: сини Бога."))

    def test_typo_in_formula(self):
        bodies = ["Букв.: \\fqa слово."] * 20 + ["Букв: \\fqa слово."]
        self.assertEqual(self.run_notes(bodies), [("1:21", "error", "note starts 'Букв: \\fqa', but 20 notes start "
                                                                       "'Букв.: \\fqa': a typing mistake?")])

    def test_quote_marker(self):
        bodies = ["Букв.: \\fqa слово."] * 12 + ["Букв.: \\fq слово."] + ["Букв.: слово."]
        found = self.run_notes(bodies)
        self.assertEqual([(ref, "has no \\fqa" in message, "has \\fq," in message) for ref, _, message in found],
                         [("1:14", True, False), ("1:13", False, True)])

    def test_end_mark(self):
        bodies = [f"Пояснення {n}." for n in range(120)] + ["Близько 2,9 кг"]
        self.assertEqual([ref for ref, _, _ in self.run_notes(bodies)], ["1:121"])

    def test_alternative_reading_in_the_verse(self):
        bodies = ["Деякі рукописи не містять слів \\fq інше слово."] * 12 + ["Деякі рукописи не містять слів \\fqa "
                                                                            "та у вашому дусі."]
        found = self.run_notes(bodies, {("TST", 1, 13): "Прославте Бога в тілі та у вашому дусі."})
        self.assertEqual([ref for ref, _, _ in found], ["1:13"])
        self.assertIn("should it be \\fq?", found[0][2])


class ParatextLinkTest(unittest.TestCase):
    def test_link_round_trip(self):
        from checker.paratext_link import make_link, parse_link
        link = make_link("ab c", "1JN 5:8", "4")
        self.assertEqual(link, "scripturechecker:ab%20c/1JN%205:8?vrs=4")
        self.assertEqual(parse_link(link), ("ab c", "1JN 5:8", "4"))
        # Browsers may add a slash; the JavaScript of the page encodes the same way.
        self.assertEqual(parse_link("scripturechecker://P/MAT%205:3/"), ("P", "MAT 5:3", ""))
        self.assertIsNone(parse_link("scripturechecker:P/hyphenatedWords.txt"))
        self.assertIsNone(parse_link("https://example.org"))

    def test_window_title(self):
        from checker.paratext_link import shows, window_reference
        self.assertEqual(window_reference("abc: 1JN 5:8 (Standard Translation)"), ("abc", "1JN 5:8"))
        self.assertIsNone(window_reference("Paratext 9.5"))
        self.assertTrue(shows("MAT 5:1", "MAT 5:0"))
        self.assertFalse(shows("MAT 5:2", "MAT 5:3"))

    def test_to_english(self):
        from checker.versification import to_english
        self.assertEqual(to_english(("PSA", 50, 3), "5"), ("PSA", 51, 1))  # Septuagint psalm numbers
        self.assertEqual(to_english(("PSA", 113, 9), "5"), ("PSA", 115, 1))  # a verse of text, not the title
        self.assertEqual(to_english(("NUM", 30, 1), "5"), ("NUM", 29, 40))
        self.assertEqual(to_english(("PSA", 51, 3), "1"), ("PSA", 51, 1))
        self.assertEqual(to_english(("MAT", 5, 3), "4"), ("MAT", 5, 3))
        self.assertIsNone(to_english(("MAT", 5, 3), "9"))

    def test_next_try_for_another_versification(self):
        from checker.paratext_link import next_try
        # Wanted PSA 50:3 of the project; sending it showed PSA 49:3, so the next try is one chapter on.
        self.assertEqual(next_try("PSA 50:3", "PSA 50:3", "PSA 49:3"), "PSA 51:3")
        self.assertEqual(next_try("PSA 51:3", "PSA 50:3", "PSA 50:5"), "PSA 51:1")
        self.assertIsNone(next_try("PSA 51:1", "PSA 50:3", "MAT 1:1"))  # another book: no guess
        self.assertIsNone(next_try("PSA 1:1", "PSA 1:1", "PSA 2:1"))  # chapter 0

    def test_links_in_the_page(self):
        from checker.html_report import CheckResult, Problem, write_check_page
        result = CheckResult("spelling", "", 1, 0, "", [Problem("error", "m", 1, "", "MAT 5:3", "x")])
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "html").mkdir()
            page = write_check_page(Path(folder), "P", result, "", {"project": "Abc", "vrs": "4"})
            text = page.read_text(encoding="utf-8")
        self.assertIn('const LINK = {"protocol": "scripturechecker", "project": "Abc", "vrs": "4"}', text)


class DivineNameTest(unittest.TestCase):
    def test_map_is_bundled(self):
        from checker.divine_name import nd_verses
        verses = nd_verses()
        self.assertEqual(verses[("GEN", 2, 4)].nd, 1)  # "the LORD God made the earth"
        self.assertEqual(verses[("GEN", 3, 8)].nd, 2)  # "the LORD God … the LORD God"
        self.assertEqual(verses[("EXO", 4, 10)].lord, 1)  # "said to the LORD, Pardon your servant, Lord"
        self.assertEqual(verses[("PSA", 18, 1)].nd, 3)  # the psalm title is verse 1 in Original numbers
        self.assertNotIn(("GEN", 1, 1), verses)  # "God created"
        self.assertGreater(len(verses), 5000)

    def test_fewer_nd_than_the_map(self):
        from checker.divine_name import VerseNd, check_divine_name
        inside = [("GEN", f"{chapter}:1") for chapter in range(30, 55)]
        style_refs = {("nd", "господь"): (inside, [("GEN", "2:4")])}
        places = {
            ("GEN", "2:4"): VerseNd(0, ["Господь"]),  # map 1, here 0
            ("GEN", "1:1"): VerseNd(0, ["Господь"]),  # not in the map
            ("GEN", "3:8"): VerseNd(1, ["Господь"]),  # map 2, here 1
            ("GEN", "3:9"): VerseNd(1, ["Господь"]),  # map 1, here 1
            ("GEN", "3:13"): VerseNd(0, ["Він"]),     # "he" where the base translation says "the LORD"
            ("EXO", "4:10"): VerseNd(0, ["Господи"]),  # map 1 \nd + 1 "Lord": one word for both is fine
        }
        found = list(check_divine_name(style_refs | {("nd", "господи"): (inside, [])}, places, {},
                                       lambda verse: verse))
        self.assertEqual([f.ref for f in found], ["2:4", "3:8"])

    def test_project_versification_with_custom_vrs(self):
        from checker.versification import project_to_original
        with tempfile.TemporaryDirectory() as folder:
            convert = project_to_original(Path(folder), "4")
            self.assertEqual(convert(("PSA", 13, 6)), ("PSA", 13, 6))  # not 13:5, as English -> Original -> English
            self.assertEqual(convert(("PSA", 3, 1)), ("PSA", 3, 2))    # eng.vrs: PSA 3:0-8 = PSA 3:1-9
            (Path(folder) / "custom.vrs").write_text("ISA 64:1 = ISA 63:19\n", encoding="utf-8")
            self.assertEqual(project_to_original(Path(folder), "")(("ISA", 64, 1)), ("ISA", 63, 19))
            self.assertIsNone(project_to_original(Path(folder), "9"))


class UpdateTest(unittest.TestCase):
    def test_versions(self):
        from checker.updates import is_newer
        self.assertTrue(is_newer("v1.10", "1.9"))
        self.assertTrue(is_newer("v2.0", "1.12"))
        self.assertFalse(is_newer("v1.1", "1.1"))
        self.assertFalse(is_newer("v1.0", "1.1"))
        self.assertFalse(is_newer("", "1.1"))  # no answer from GitHub

    def test_no_internet_is_no_update(self):
        from unittest import mock
        from checker import updates
        with mock.patch("urllib.request.urlopen", side_effect=OSError("offline")):
            self.assertIsNone(updates.newer_release("1.0"))


class WindowTest(unittest.TestCase):
    def test_report_folder_is_not_inside_the_paratext_folder(self):
        from checker.gui import default_report_dir, find_projects
        with tempfile.TemporaryDirectory() as folder:
            paratext = Path(folder) / "Paratext"
            (paratext / "ABC").mkdir(parents=True)
            (paratext / "ABC" / "Settings.xml").write_text("<ScriptureText/>", encoding="utf-8")
            (paratext / "_Backups").mkdir()
            self.assertEqual(list(find_projects(paratext)), ["ABC"])
            self.assertNotIn(paratext.resolve(), default_report_dir(paratext / "ABC", paratext).resolve().parents)
            other = Path(folder) / "copy" / "ABC"
            self.assertEqual(default_report_dir(other, paratext), Path(folder) / "copy" / "ABC_report")

    def test_nothing_selected_at_start(self):
        from tkinter import TclError, Tk
        from checker.gui import CheckerWindow
        try:
            root = Tk()
        except TclError:
            self.skipTest("no display")
        try:
            root.withdraw()
            window = CheckerWindow(root)
            self.assertFalse(any(var.get() for var in window.selected.values()))
            self.assertEqual(str(window.run_button.cget("state")), "disabled")
            window.selected["spelling"].set(True)
            self.assertEqual(str(window.run_button.cget("state")), "normal")
            window.selected["spelling"].set(False)
            self.assertEqual(str(window.run_button.cget("state")), "disabled")
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
