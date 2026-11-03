"""Language-specific knowledge that cannot be read from the project files.

Everything else in the checker is driven by Settings.xml, SpellingStatus.xml and
hyphenatedWords.txt, so it works for any language. A profile only enables extra
hyphenation rules. Projects whose language has no profile get GENERIC: rules that need
linguistic knowledge (vowels, letters that cannot start a line) are skipped.

To add a language, add a LanguageProfile to PROFILES keyed by its ISO 639 code, as
found in Settings.xml <LanguageIsoCode> (e.g. "uk:::" -> "uk").
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LanguageProfile:
    code: str
    # Lowercase vowels; empty disables the vowel-based rules.
    vowels: frozenset[str] = frozenset()
    # Lowercase letters that must not start the part after a break (e.g. Ukrainian "ь").
    no_break_before: frozenset[str] = frozenset()
    # Lowercase letters that stay with a preceding vowel when a consonant follows (Ukrainian "й": "вій=на").
    glides: frozenset[str] = frozenset()


GENERIC = LanguageProfile(code="")

PROFILES: dict[str, LanguageProfile] = {
    "uk": LanguageProfile(
        code="uk",
        vowels=frozenset("аеєиіїоуюя"),
        no_break_before=frozenset("ь"),
        glides=frozenset("й"),
    ),
}


def language_code(iso_code: str) -> str:
    """Normalize Paratext's LanguageIsoCode ("uk:::", "en-US") to a bare code ("uk", "en")."""
    return iso_code.split(":")[0].split("-")[0].strip().lower()


def profile_for(iso_code: str) -> LanguageProfile:
    return PROFILES.get(language_code(iso_code), GENERIC)
