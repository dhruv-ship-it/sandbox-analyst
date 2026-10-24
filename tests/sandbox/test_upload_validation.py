import pytest

from sandbox_analyst.sandbox.base import validate_upload_name, validate_upload_size


def test_plain_name_is_accepted():
    validate_upload_name("data.csv")


def test_empty_name_is_rejected():
    with pytest.raises(ValueError, match="empty"):
        validate_upload_name("")


@pytest.mark.parametrize("name", ["dir/data.csv", "dir\\data.csv", "/etc/passwd"])
def test_names_with_separators_are_rejected(name):
    with pytest.raises(ValueError, match="plain file name"):
        validate_upload_name(name)


@pytest.mark.parametrize("name", ["../secret.csv", "a/../../b.csv", ".."])
def test_names_with_parent_references_are_rejected(name):
    with pytest.raises(ValueError):
        validate_upload_name(name)


def test_size_within_limit_is_accepted():
    validate_upload_size(1024, max_upload_mb=25)


def test_size_over_limit_is_rejected():
    too_big = 26 * 1024 * 1024
    with pytest.raises(ValueError, match="too large"):
        validate_upload_size(too_big, max_upload_mb=25)


def test_size_exactly_at_limit_is_accepted():
    exactly = 25 * 1024 * 1024
    validate_upload_size(exactly, max_upload_mb=25)
