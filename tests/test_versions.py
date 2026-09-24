from quiver.util.versions import compare, is_newer, normalize


def test_normalize_strips_v():
    assert normalize("v1.2.3") == "1.2.3"
    assert normalize("V10") == "10"
    assert normalize("") == ""
    assert normalize(None) == ""


def test_equal():
    assert compare("1.2.3", "v1.2.3") == 0
    assert compare("1.2.3", "1.2.3") == 0


def test_patch_upgrade():
    assert is_newer("1.2.4", "1.2.3")
    assert not is_newer("1.2.3", "1.2.4")


def test_numeric_not_lexicographic():
    assert is_newer("0.59.10", "0.59.2")
    assert is_newer("1.10", "1.9")


def test_prerelease_lower_than_release():
    assert compare("1.2.3-rc1", "1.2.3") < 0
    assert is_newer("1.2.3", "1.2.3-rc1")
    assert is_newer("1.2.3-rc2", "1.2.3-rc1")


def test_build_metadata_ignored():
    assert compare("1.2.3+build5", "1.2.3") == 0


def test_date_versions():
    assert is_newer("2024.09.01", "2024.08.31")
    assert not is_newer("2024.08.31", "2024.9.1")


def test_longer_version_wins_when_equal_prefix():
    assert is_newer("2.0.0", "2.0")
    assert is_newer("2.0.1", "2.0")


def test_mixed_segments():
    assert is_newer("1.2.3b", "1.2.3a")
    assert is_newer("1.3", "1.2.99")


def test_big_jump():
    assert is_newer("10", "9.9.9")
    assert not is_newer("9.9.9", "10")
