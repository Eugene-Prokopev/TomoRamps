"""Smoke-тесты: проверяют, что пакет на месте и окружение живо."""
import tomostage


def test_package_imports():
    assert tomostage.__version__ == "0.0.1"
