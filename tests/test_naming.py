import pytest

from einvoice import sdi_filename, to_base36


def test_to_base36_padding():
    assert to_base36(0) == "00000"
    assert to_base36(7) == "00007"
    assert to_base36(35) == "0000Z"
    assert to_base36(36) == "00010"


def test_sdi_filename_from_int():
    assert sdi_filename("IT", "01234567897", 7) == "IT01234567897_00007.xml"


def test_sdi_filename_from_string():
    assert sdi_filename("it", "01234567897", "abc12") == "IT01234567897_ABC12.xml"


def test_sdi_filename_rejects_bad_progressive():
    with pytest.raises(ValueError):
        sdi_filename("IT", "01234567897", "TOOLONG6")
    with pytest.raises(ValueError):
        sdi_filename("IT", "01234567897", "ab-1")
