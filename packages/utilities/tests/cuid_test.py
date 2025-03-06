from utilities.cuid import create_cuid


def test_create_cuid_length():
    cuid = create_cuid()
    assert len(cuid) == 24, "CUID should be 25 characters long"


def test_create_cuid_uniqueness():
    cuid1 = create_cuid()
    cuid2 = create_cuid()
    assert cuid1 != cuid2, "CUIDs should be unique"


def test_create_cuid_type():
    cuid = create_cuid()
    assert isinstance(cuid, str), "CUID should be a string"
