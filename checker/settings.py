"""Parse the Paratext project settings file (Settings.xml)."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

# In punctuation patterns "_" stands for whitespace (or the start/end of a paragraph).
SPACE_PLACEHOLDER = "_"

# List items are separated by ASCII whitespace only, so items such as U+2009 THIN SPACE survive.
_SEPARATOR_RE = re.compile(r"[ \t\r\n]+")
# Used when Settings.xml has no ValidPunctuation_NonText: hyphens and apostrophes join words
# ("Baal-Hanan", "Godʼs", "donʼt"). Language independent: these are Unicode hyphen/apostrophe characters.
DEFAULT_WORD_MEDIAL_PUNCTUATION = frozenset("-‐‑'’ʼ")
# Paratext escapes characters inside list items as \XXXX (e.g. \0020 for a space).
_ESCAPE_RE = re.compile(r"\\([0-9A-Fa-f]{4})")


def split_list(text: str | None) -> tuple[str, ...]:
    """Split a whitespace-separated settings value into its items, decoding \\XXXX escapes."""
    if not text:
        return ()
    return tuple(
        _ESCAPE_RE.sub(lambda m: chr(int(m.group(1), 16)), item)
        for item in _SEPARATOR_RE.split(text)
        if item
    )


@dataclass(frozen=True)
class ReferenceFormat:
    """Marks of Scripture references. Each list holds the allowed choices, kept with their spaces (", ")."""
    chapter_verse: str = ":"           # ChapterVerseSeparator "1:5"
    verse_ranges: tuple[str, ...] = ()       # RangeIndicator "1:1–3"
    verse_sequences: tuple[str, ...] = ()    # SequenceIndicator "1:1, 3"
    chapter_ranges: tuple[str, ...] = ()     # ChapterRangeSeparator "1:7—6:15"
    chapter_sequences: tuple[str, ...] = ()  # ChapterNumberSeparator "1:5; 3:2"
    book_sequences: tuple[str, ...] = ()     # BookSequenceSeparator "Мт. 1:1; Лк. 2:2"


@dataclass(frozen=True)
class ProjectSettings:
    name: str
    language_iso_code: str  # e.g. "uk:::"
    file_name_post_part: str
    valid_characters: frozenset[str]
    invalid_characters: frozenset[str]
    valid_punctuation: frozenset[str]
    invalid_punctuation: frozenset[str]
    # Punctuation that may appear inside a word (ValidPunctuation_NonText), e.g. "-" and "ʼ".
    word_medial_punctuation: frozenset[str]
    abbreviations: frozenset[str]
    valid_mixed_capitalization: frozenset[str]
    invalid_mixed_capitalization: frozenset[str]
    sentence_final_punctuation: frozenset[str]
    # Punctuation sequences after which a lowercase word is allowed.
    valid_sentence_final_capitalization: frozenset[str]
    valid_uncapitalized_styles: frozenset[str]
    invalid_uncapitalized_styles: frozenset[str]
    # Separators allowed between two digits: "6,8", "1⁄16", "12:5", "10 000".
    number_medial_punctuation: frozenset[str]
    # Quotation marks per nesting level (Quotes, InnerQuotes, InnerInnerQuotes): (("«", "»"), ("„", "“"), ...).
    quote_levels: tuple[tuple[str, str], ...] = ()
    # Continuer per level, repeated at the start of a paragraph that continues an open quote.
    quote_continuers: tuple[str, ...] = ()
    continue_quotes: bool = False
    # Where continuers are expected: "p" (paragraph style) or "b/m" (previous style / style).
    continue_at: frozenset[str] = frozenset()
    quote_closes_all_levels: bool = False
    # Matched pairs (Pairs "(/) [/] {/}"): (("(", ")"), ("[", "]"), ...).
    pairs: tuple[tuple[str, str], ...] = ()
    # Pairing characters approved to occur unmatched (UnmatchedPairingCharacters).
    unmatched_pairing_characters: frozenset[str] = frozenset()
    # Words that may / must not occur twice in a row (RepeatableWords / NonRepeatableWords).
    repeatable_words: frozenset[str] = frozenset()
    non_repeatable_words: frozenset[str] = frozenset()
    # Paragraph-final items "<style>_<punctuation>" or "<style>" (paragraph ends with a word).
    valid_paragraph_final: frozenset[str] = frozenset()
    invalid_paragraph_final: frozenset[str] = frozenset()
    markers_requiring_sentence_final: frozenset[str] = frozenset()
    normalization_form: str = ""  # "NFC", "NFD" or "" (not set)
    number_thousands_separator: str = ""
    chapter_verse_separator: str = ":"
    reference_format: ReferenceFormat = ReferenceFormat()
    # NumberOrdinals ("-й -го", "st nd rd th", "ke-") and NumberOrdinalType ("suffix" / "prefix").
    number_ordinals: frozenset[str] = frozenset()
    number_ordinal_type: str = ""
    # File names (Naming): PrePart + book ("41MAT" = number and code, "MAT", "41") + PostPart.
    file_name_pre_part: str = ""
    file_name_book_form: str = ""
    # BiblicalTermsListSetting: "Project:<name>:ProjectBiblicalTerms.xml", "Major::BiblicalTerms.xml".
    biblical_terms_list: str = ""
    versification: str = ""  # Settings.xml <Versification>: "4" = English, "1" = Original, ...

    @property
    def punctuation_characters(self) -> frozenset[str]:
        """Every character used in a punctuation pattern; these never form words."""
        chars = {
            ch
            for pattern in self.valid_punctuation | self.invalid_punctuation | self.word_medial_punctuation
            for ch in pattern
        }
        return frozenset(ch for ch in chars if ch != SPACE_PLACEHOLDER and not ch.isspace())


def project_versification(path: Path, root: ET.Element | None = None) -> str:
    """<Versification> of Settings.xml. A daughter project (<TranslationInfo>Daughter:<parent>:…) has none: Paratext
    uses the one of its parent project, found next to it in the projects folder. "" = not known (Paratext: English)."""
    for _ in range(5):  # a parent may be a daughter too
        if root is None:
            try:
                root = ET.parse(path).getroot()
            except (OSError, ET.ParseError):
                return ""
        versification = (root.findtext("Versification") or "").strip()
        parts = (root.findtext("TranslationInfo") or "").split(":")
        if versification or parts[0] != "Daughter" or len(parts) < 2 or not parts[1]:
            return versification
        path = path.parent.parent / parts[1] / path.name
        root = None
    return ""


def load_settings(path: Path) -> ProjectSettings:
    root = ET.parse(path).getroot()

    def items(tag: str) -> frozenset[str]:
        return frozenset(split_list(root.findtext(tag)))

    # NumberMedialPunctuation is a set of characters: "-/–/⁄" = "-", "/", "–", "⁄"; "-/–—:‑⁄" in another project.
    number_medial = set(root.findtext("NumberMedialPunctuation") or "")
    for tag in ("NumberDecimalPoint", "NumberThousandsSeparator", "ChapterVerseSeparator"):
        number_medial.add(root.findtext(tag) or "")
    def choices(tag: str) -> tuple[str, ...]:
        # Choices are separated by "|" and keep their spaces: ", |,", "–|—| and ".
        # "~" is the USFM no-break space (";~", "~и~"); references read it as U+00A0 too.
        return tuple(item.replace("~", " ") for item in (root.findtext(tag) or "").split("|") if item)

    # "3:35,36": a list of verses is also a separator between two digits ("3፥35፣36" in Tigrinya).
    for mark in choices("SequenceIndicator"):
        if not any(ch.isalnum() for ch in mark):
            number_medial.add(mark.strip())
    number_medial.discard("")

    def flag(tag: str) -> bool:
        return (root.findtext(tag) or "").strip().lower() in ("yes", "true", "t")

    chapter_verse_separator = (root.findtext("ChapterVerseSeparator") or ":").strip() or ":"

    def naming(tag: str, attribute: str) -> str:
        # Older files have <FileNamePostPart>, newer ones also <Naming PostPart="...">.
        value = root.findtext(tag)
        if value is None and (element := root.find("Naming")) is not None:
            value = element.get(attribute)
        return (value or "").strip()

    quote_levels = []
    for tag in ("Quotes", "InnerQuotes", "InnerInnerQuotes"):
        pair = split_list(root.findtext(tag))
        if len(pair) != 2:
            break
        quote_levels.append((pair[0], pair[1]))
    quote_continuers = tuple(
        (root.findtext(tag) or "").strip() for tag in ("Continuer", "InnerContinuer", "InnerInnerContinuer")
    )

    return ProjectSettings(
        name=root.findtext("Name") or "",
        language_iso_code=root.findtext("LanguageIsoCode") or "",
        file_name_post_part=naming("FileNamePostPart", "PostPart") or ".SFM",
        file_name_pre_part=naming("FileNamePrePart", "PrePart"),
        biblical_terms_list=(root.findtext("BiblicalTermsListSetting") or "").strip(),
        versification=project_versification(path, root),
        file_name_book_form=naming("FileNameBookNameForm", "BookNameForm") or naming("FileNameForm", "BookNameForm"),
        valid_characters=items("ValidCharacters"),
        invalid_characters=items("InvalidCharacters"),
        valid_punctuation=items("ValidPunctuation"),
        invalid_punctuation=items("InvalidPunctuation"),
        word_medial_punctuation=items("ValidPunctuation_NonText") or DEFAULT_WORD_MEDIAL_PUNCTUATION,
        abbreviations=items("Abbreviations"),
        valid_mixed_capitalization=items("ValidMixedCapitalization"),
        invalid_mixed_capitalization=items("InvalidMixedCapitalization"),
        # Written either run together (".?!:") or space separated (". ! ? : —").
        sentence_final_punctuation=frozenset("".join(split_list(root.findtext("SentenceFinalPunctuation")))),
        valid_sentence_final_capitalization=items("ValidSentenceFinalPunctCapitalization"),
        valid_uncapitalized_styles=items("ValidUncapitalizedStyles"),
        invalid_uncapitalized_styles=items("InvalidUncapitalizedStyles"),
        number_medial_punctuation=frozenset(number_medial),
        quote_levels=tuple(quote_levels),
        quote_continuers=quote_continuers,
        continue_quotes=flag("ContinueQuotes"),
        continue_at=items("ContinueAt"),
        quote_closes_all_levels=flag("QuoteClosesAllQuoteLevels"),
        pairs=tuple(
            (pair[0], pair[1]) for item in split_list(root.findtext("Pairs"))
            if len(pair := item.split("/")) == 2 and pair[0] and pair[1]
        ),
        unmatched_pairing_characters=items("UnmatchedPairingCharacters"),
        repeatable_words=items("RepeatableWords"),
        non_repeatable_words=items("NonRepeatableWords"),
        valid_paragraph_final=items("ValidParagraphFinalPunctuationItems"),
        invalid_paragraph_final=items("InvalidParagraphFinalPunctuationItems"),
        markers_requiring_sentence_final=items("MarkersRequiringSentenceFinalPunctuation"),
        normalization_form=(root.findtext("NormalizationForm") or "").strip().upper(),
        # Kept unstripped: the separator may be a space character (U+202F).
        number_thousands_separator=root.findtext("NumberThousandsSeparator") or "",
        chapter_verse_separator=chapter_verse_separator,
        reference_format=ReferenceFormat(
            chapter_verse=chapter_verse_separator,
            verse_ranges=choices("RangeIndicator"),
            verse_sequences=choices("SequenceIndicator"),
            chapter_ranges=choices("ChapterRangeSeparator"),
            chapter_sequences=choices("ChapterNumberSeparator"),
            book_sequences=choices("BookSequenceSeparator"),
        ),
        number_ordinals=items("NumberOrdinals"),
        number_ordinal_type=(root.findtext("NumberOrdinalType") or "").strip().lower(),
    )
