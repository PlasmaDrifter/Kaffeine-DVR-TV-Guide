from kaffeine_dvr.updater import parse_version_tuple


def test_parse_version_tuple():
    assert parse_version_tuple("0.8.5") == (0, 8, 5)
    assert parse_version_tuple("v0.8.5") == (0, 8, 5)
    assert parse_version_tuple("v0.8.10") == (0, 8, 10)
    assert parse_version_tuple("v0.9.0") == (0, 9, 0)
    assert parse_version_tuple("v1.0.0") == (1, 0, 0)

    # Comparison tests
    assert parse_version_tuple("v0.8.6") > parse_version_tuple("v0.8.5")
    assert parse_version_tuple("v0.8.7") > parse_version_tuple("v0.8.6")
    assert parse_version_tuple("v0.9.0") > parse_version_tuple("v0.8.15")
    assert parse_version_tuple("v0.8.5") == parse_version_tuple("0.8.5")
