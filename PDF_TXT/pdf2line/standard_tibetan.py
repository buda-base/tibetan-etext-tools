"""
Standard Tibetan syllable detection and stack splitting.

These functions are used for advanced normalization (normalize_for_perplexity)
which is not needed for basic pdf2line text extraction.

Stub implementations are provided here to satisfy imports.
"""


def is_standard_tibetan(syllable: str) -> bool:
    """
    Check if a syllable follows standard Tibetan phonotactics.
    
    This is a stub implementation. Full implementation would check:
    - Valid consonant stacks
    - Proper vowel placement
    - Legal suffix/postfix combinations
    
    For basic normalization, this function is not needed.
    """
    raise NotImplementedError(
        "is_standard_tibetan is not implemented. "
        "This function is only needed for normalize_for_perplexity, "
        "not for basic text normalization with normalize_corpus."
    )


def split_into_stacks(syllable: str) -> list[str]:
    """
    Split a non-standard (Sanskrit) syllable into constituent consonant stacks.
    
    This is a stub implementation. Full implementation would:
    - Identify consonant clusters
    - Split them according to phonological boundaries
    - Return list of stack strings
    
    For basic normalization, this function is not needed.
    """
    raise NotImplementedError(
        "split_into_stacks is not implemented. "
        "This function is only needed for normalize_for_perplexity, "
        "not for basic text normalization with normalize_corpus."
    )
