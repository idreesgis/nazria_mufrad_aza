import pytest

from nazria_api.dburl import database_from_url


def test_url_with_ssl_and_special_password():
    d = database_from_url("postgis://app:p%40ss%word@db.example.com:5433/nazria?sslmode=require", "nazria_api")
    assert (d["NAME"], d["USER"], d["PASSWORD"], d["HOST"], d["PORT"]) == ("nazria", "app", "p@ss%word", "db.example.com", "5433")
    assert d["OPTIONS"] == {"sslmode": "require", "options": "-c search_path=nazria_api"}


def test_unix_socket_and_bad_input():
    d = database_from_url("postgresql://postgres@/nazria_local?host=/var/tmp&port=55432", "api")
    assert (d["HOST"], d["PORT"]) == ("/var/tmp", "55432")
    with pytest.raises(ValueError, match="unsupported"):
        database_from_url("postgresql://u@h/db?search_path=public", "api")
    with pytest.raises(ValueError, match="postgresql"):
        database_from_url("mysql://u@h/db", "api")
