"""Book codes in Paratext file names (Settings.xml Naming: PrePart, BookNameForm, PostPart).

The book numbers are the Paratext standard, the same for every language.
"""
from __future__ import annotations



# Book codes in Paratext order; the book number is the position + 1 (GEN = 1, MAT = 40, XXA = 93, FRT = 100).
BOOK_CODES = (
    "GEN EXO LEV NUM DEU JOS JDG RUT 1SA 2SA 1KI 2KI 1CH 2CH EZR NEH EST JOB PSA PRO ECC SNG ISA JER LAM "
    "EZK DAN HOS JOL AMO OBA JON MIC NAM HAB ZEP HAG ZEC MAL "
    "MAT MRK LUK JHN ACT ROM 1CO 2CO GAL EPH PHP COL 1TH 2TH 1TI 2TI TIT PHM HEB JAS 1PE 2PE 1JN 2JN 3JN JUD REV "
    "TOB JDT ESG WIS SIR BAR LJE S3Y SUS BEL 1MA 2MA 3MA 4MA 1ES 2ES MAN PS2 ODA PSS JSA JDB TBS SST DNT BLT "
    "XXA XXB XXC XXD XXE XXF XXG FRT BAK OTH 3ES EZA 5EZ 6EZ INT CNC GLO TDX NDX DAG PS3 2BA LBA JUB ENO "
    "1MQ 2MQ 3MQ REP 4BA LAO"
).split()



def file_number(code: str) -> str | None:
    """Number of a book in file names: "01" GEN, "41" MAT (40 is not used), "94" XXA, "100" XXG, "A0" FRT, "B0" TDX."""
    if code not in BOOK_CODES:
        return None
    number = BOOK_CODES.index(code) + 1
    if number >= 100:  # FRT = "A0", INT = "A7", TDX = "B0"
        tens, ones = divmod(number - 100, 10)
        return f"{chr(ord('A') + tens)}{ones}"
    if number >= 40:
        number += 1  # numbers below 100 skip 40: MAT is "41"
    return f"{number:02d}"


OLD_TESTAMENT = frozenset(BOOK_CODES[:39])
NEW_TESTAMENT = frozenset(BOOK_CODES[39:66])
# Not Scripture text: notes, front/back matter, introductions, glossary, index.
EXTRA_MATERIAL = frozenset("XXA XXB XXC XXD XXE XXF XXG FRT BAK OTH INT CNC GLO TDX NDX".split())
DEUTEROCANON = frozenset(BOOK_CODES[66:]) - EXTRA_MATERIAL


def book_order(code: str) -> int:
    """Position in the Paratext book order; unknown codes last."""
    return BOOK_CODES.index(code) if code in BOOK_CODES else len(BOOK_CODES)


_CODE_BY_NUMBER ={file_number(code): code for code in BOOK_CODES if file_number(code)}


def book_from_file_name(name: str, pre_part: str, post_part: str, form: str) -> str | None:
    """Book code that a file name stands for, or None if the name does not fit the naming of the project.

    form (BookNameForm): "41MAT" = number + code ("091SAxxx.SFM"), "MAT" = code ("GEN.SFM"), "41" = number.
    """
    if not (name.upper().startswith(pre_part.upper()) and name.upper().endswith(post_part.upper())):
        return None
    middle = name[len(pre_part):len(name) - len(post_part)].upper()
    form = form.strip().upper()
    if form == "41MAT":
        code = middle[-3:]  # after the number: "41MAT", "100XXG"
        return code if code in BOOK_CODES else None
    if form == "MAT":
        return middle if middle in BOOK_CODES else None
    if form == "41":
        return _CODE_BY_NUMBER.get(middle)
    return None
