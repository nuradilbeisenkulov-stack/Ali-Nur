"""Conservative language identification and normalization edge cases."""
import pytest

from app.language import detect_language, normalize, reply


def test_kazakh_swaps_are_normalized_in_both_cases():
    assert normalize("ќґѕєјўї ЌҐЅЄЈЎЇ") == "қғңәөұү қғңәөұү"


@pytest.mark.parametrize("declared", ["lat", "und"])
def test_ambiguous_source_labels_remain_explicit(declared):
    lang, confidence, reason = detect_language("Please help me, my character is stuck in the garage.", declared)
    assert lang == declared
    assert confidence < .7
    assert reason
    assert reply(lang, False)["lang"] == "und"


def test_single_latin_word_does_not_select_english():
    lang, confidence, reason = detect_language("hello")
    assert lang == "und"
    assert confidence < .7
    assert reason


def test_conflicting_language_metadata_requires_review():
    lang, confidence, reason = detect_language("Please help me, my account was hacked and I cannot log in.", "ru")
    assert lang == "en"
    assert confidence < .7
    assert reason
