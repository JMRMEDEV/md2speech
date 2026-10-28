"""Built-in, tech-friendly default pronunciation dictionary.

These replacements are applied automatically so common software/engineering
acronyms are spoken the way an English-speaking engineer says them (e.g. "UX"
-> "you ex", not read as a word). Kokoro's text frontend otherwise tries to
pronounce all-caps tokens as words, which produces the wrong (often
Spanish-sounding) vowels for initialisms.

Guidelines for entries:
  * Only spell out initialisms that are normally said letter-by-letter.
  * Leave true acronyms that are said as words out of here (NASA, JSON->"jason",
    SQL->"sequel", SaaS) unless they are commonly mispronounced - a few such
    "said-as-a-word" fixes are included where TTS gets them wrong.
  * Spoken letters use spaced capitals ("U X"); Kokoro reads each as its
    English letter name. Where a letter name alone is ambiguous, a phonetic
    spelling is used instead (e.g. "W" -> "double you" is handled naturally).
  * User YAML entries override and extend these defaults.
"""

from __future__ import annotations


#: Term -> spoken form. Matched whole-word, case-insensitively, longest-first.
DEFAULT_PRONUNCIATIONS: dict[str, str] = {
    # --- roles / process ------------------------------------------------- #
    "UX": "you ex",
    "UI": "you eye",
    "UX/UI": "you ex, you eye",
    "UI/UX": "you eye, you ex",
    "QA": "Q A",
    "PM": "P M",
    "SWE": "software engineer",
    "CX": "C X",
    "JD": "job description",
    "CV": "C V",
    "STAR": "star",
    "MFA": "M F A",
    "SSO": "single sign on",

    # --- web / frontend -------------------------------------------------- #
    "HTML": "H T M L",
    "HTML5": "H T M L five",
    "CSS": "C S S",
    "CSS3": "C S S three",
    "DOM": "dom",
    "SEO": "S E O",
    "a11y": "accessibility",
    "i18n": "internationalization",
    "l10n": "localization",
    "WCAG": "W C A G",
    "ARIA": "aria",
    "SPA": "S P A",
    "SSR": "server side rendering",
    "SSG": "static site generation",
    "BFF": "backend for frontend",
    "PWA": "P W A",
    "CDN": "C D N",
    "URL": "U R L",
    "URI": "U R I",

    # --- languages / platforms ------------------------------------------- #
    "JS": "JavaScript",
    "TS": "TypeScript",
    "RN": "React Native",
    "ES6": "E S six",
    "ESNext": "E S next",
    ".NET": "dot net",
    "C#": "C sharp",

    # --- api / data ------------------------------------------------------ #
    "API": "A P I",
    "REST": "rest",
    "CRUD": "crud",
    "JSON": "jason",
    "XML": "X M L",
    "YAML": "yamel",
    "SQL": "sequel",
    "NoSQL": "no sequel",
    "GraphQL": "graph Q L",
    "JWT": "J W T",
    "JWKS": "J W K S",
    "OIDC": "O I D C",
    "OAuth": "oh auth",
    "SAML": "sammal",
    "PKCE": "pixy",
    "IdP": "identity provider",

    # --- infra / devops -------------------------------------------------- #
    "CI/CD": "C I C D",
    "CI": "C I",
    "CD": "C D",
    "AWS": "A W S",
    "GCP": "G C P",
    "S3": "S three",
    "EC2": "E C two",
    "K8s": "kubernetes",
    "CMS": "C M S",
    "CRM": "C R M",
    "SDK": "S D K",
    "IDE": "I D E",
    "CLI": "C L I",
    "GPU": "G P U",
    "CPU": "C P U",
    "RAM": "ram",
    "OS": "O S",

    # --- ai -------------------------------------------------------------- #
    "AI": "A I",
    "ML": "M L",
    "LLM": "L L M",
    "NLP": "N L P",
    "Gen AI": "gen A I",
    "GenAI": "gen A I",

    # --- testing / quality ----------------------------------------------- #
    "E2E": "end to end",
    "TDD": "T D D",
    "BDD": "B D D",
    "SR": "screen reader",

    # --- common abbreviations -------------------------------------------- #
    "e.g.": "for example",
    "i.e.": "that is",
    "etc.": "etcetera",
    "vs.": "versus",
    "vs": "versus",
    "aka": "also known as",
    "a.k.a.": "also known as",
    "a.k.a": "also known as",
    "FAQ": "F A Q",
    "WIP": "work in progress",
    "TBD": "to be determined",
    "N/A": "not applicable",
    "J&J": "J and J",
    "SVB": "S V B",
    "A/B": "A B",
}


def _phoneticize_letter_spellings(
    table: dict[str, str],
) -> dict[str, str]:
    """Rewrite dict values that are pure spaced single-capitals into phonetic
    letter names (e.g. "A P I" -> "eigh pee eye").

    This routes the whole acronym dictionary through the ear-tuned phonetic
    speller so initialisms never fall back to Spanish-style vowels, while
    leaving word-style values (``"rest"``, ``"jason"``, ``"J and J"``) untouched.
    """
    import re as _re

    from .normalize import spell_letters

    pure = _re.compile(r"([A-Z] )*[A-Z]")
    out: dict[str, str] = {}
    for key, value in table.items():
        if pure.fullmatch(value):
            out[key] = spell_letters(value.replace(" ", ""))
        else:
            out[key] = value
    return out


# Public table: letter-spellings converted to ear-tuned phonetics on import.
DEFAULT_PRONUNCIATIONS = _phoneticize_letter_spellings(DEFAULT_PRONUNCIATIONS)
