"""Where a setting is changed in Paratext (9.5): reports name these places instead of file and XML key names.

Report readers work in Paratext and do not know the project files. Settings without a known place
(Pairs, NormalizationForm, SentenceFinalPunctuation, Abbreviations) are still named by their Settings.xml key.
"""

INVENTORIES = "Tools > Checking inventories > "

# Short window names: used in messages and in "Where:" lines.
CHARACTERS = "Characters inventory"
PUNCTUATION = "Punctuation inventory"
MIXED_CAPITALIZATION = "Mixed capitalization inventory"
REPEATED_WORDS = "Repeated words inventory"
UNMATCHED_PAIRS = "Unmatched pairs of punctuation inventory"
FINAL_PUNCTUATION = "Markers missing final punctuation inventory"
PUNCTUATION_LOWERCASE = "Punctuation followed by lowercase inventory"
MARKERS_LOWERCASE = "Markers followed by lowercase inventory"
WORDLIST = "Wordlist"
PARALLEL_PASSAGES = "Parallel Passages"
NUMBER_SETTINGS = "Project settings > Number settings"
QUOTATION_RULES = "Project settings > Quotation rules"
REFERENCE_FORMAT = "Project settings > Scripture reference settings > Reference Format"
BOOK_NAMES = "Project settings > Scripture reference settings > Book Names"

# Status marks of inventories and Wordlist (green check / red cross).
CORRECT = "(marked correct)"
WRONG = "(marked wrong)"


def inventory(name: str) -> str:
    """Full menu path of a checking inventory: "Tools > Checking inventories > Characters inventory"."""
    return INVENTORIES + name
