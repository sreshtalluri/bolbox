"""Tal structure.

A tal is not a time signature. Tintal is 16 matras in four vibhags with sam on
matra 1 and khali on the third vibhag; 4/4 is only how it gets rendered into
MIDI. These tests hold that line, because collapsing the two is the mistake that
makes adding jhaptal (10 matras, uneven vibhags) a rewrite instead of a table
entry.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from bolbox.tal import TALS, TINTAL, Tal, UnknownTalError, get_tal


def test_tintal_shape() -> None:
    assert TINTAL.matras == 16
    assert TINTAL.vibhags == (4, 4, 4, 4)
    assert TINTAL.vibhag_starts == (0, 4, 8, 12)


def test_khali_is_the_third_vibhag() -> None:
    assert TINTAL.khali_matras == frozenset({8, 9, 10, 11})
    assert TINTAL.is_khali(8)
    assert TINTAL.is_khali(11)
    assert not TINTAL.is_khali(12)
    assert not TINTAL.is_khali(0)


def test_sam_recurs_every_cycle() -> None:
    assert TINTAL.is_sam(0)
    assert TINTAL.is_sam(16)
    assert TINTAL.is_sam(32)
    assert not TINTAL.is_sam(1)


def test_khali_recurs_every_cycle() -> None:
    assert TINTAL.is_khali(16 + 8), "matra 8 of the second avartan is still khali"


def test_midi_time_signature_is_a_rendering_choice() -> None:
    assert TINTAL.midi_time_signature == (16, 4)


def test_lookup_is_case_and_space_insensitive() -> None:
    assert get_tal(" Tintal ") is TINTAL


def test_unknown_tal_names_what_is_supported() -> None:
    with pytest.raises(UnknownTalError) as exc:
        get_tal("jhaptal")
    assert "jhaptal" in str(exc.value)
    assert "tintal" in str(exc.value)


def test_vibhags_must_sum_to_the_matra_count() -> None:
    """The check that makes a new tal entry safe to add by hand."""
    with pytest.raises(ValueError, match="sum to"):
        Tal(name="broken", matras=16, vibhags=(4, 4, 4), khali_vibhags=frozenset())


def test_khali_index_must_be_in_range() -> None:
    with pytest.raises(ValueError, match="out of range"):
        Tal(name="broken", matras=8, vibhags=(4, 4), khali_vibhags=frozenset({5}))


def test_every_registered_tal_is_internally_consistent() -> None:
    for tal in TALS.values():
        assert sum(tal.vibhags) == tal.matras
        assert tal.matra_to_quarter > 0
        assert tal.midi_time_signature[0] > 0


def test_a_hypothetical_uneven_tal_works() -> None:
    """Jhaptal is 2+3+2+3. Adding it must be data, not code -- prove the shape holds."""
    jhaptal = Tal(
        name="jhaptal",
        matras=10,
        vibhags=(2, 3, 2, 3),
        khali_vibhags=frozenset({2}),
        matra_to_quarter=Fraction(1),
    )
    assert jhaptal.vibhag_starts == (0, 2, 5, 7)
    assert jhaptal.khali_matras == frozenset({5, 6})
    assert jhaptal.midi_time_signature == (10, 4)
