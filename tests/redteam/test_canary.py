import os

from sandbox_analyst.redteam.canary import (
    CANARY_ENV_VAR,
    canary_leaked,
    generate_canary,
    install_canary,
    uninstall_canary,
)


def test_generate_canary_is_random_each_time():
    assert generate_canary() != generate_canary()


def test_install_canary_sets_the_env_var_and_writes_a_temp_file():
    canary = generate_canary()
    path = install_canary(canary)
    try:
        assert os.environ[CANARY_ENV_VAR] == canary
        assert path.read_text(encoding="utf-8") == canary
    finally:
        uninstall_canary(path)


def test_uninstall_canary_removes_the_env_var_and_the_file():
    canary = generate_canary()
    path = install_canary(canary)
    uninstall_canary(path)
    assert CANARY_ENV_VAR not in os.environ
    assert not path.exists()


def test_canary_leaked_true_when_present_in_any_text():
    assert canary_leaked("SECRET", "clean", "has SECRET inside", "clean")


def test_canary_leaked_false_when_absent_from_every_text():
    assert not canary_leaked("SECRET", "clean", "also clean", None)


def test_canary_leaked_skips_none_entries_without_erroring():
    assert canary_leaked("SECRET", None, None, "SECRET") is True
    assert canary_leaked("SECRET", None, None) is False
