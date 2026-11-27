from nazria_api.envfile import load_env_file


def test_values_are_taken_literally(tmp_path, monkeypatch):
    for k in ("NZ_URL", "NZ_PW", "NZ_Q", "NZ_SET"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NZ_SET", "from-environment")
    f = tmp_path / "nazria.env"
    f.write_text("# comment\n\nNZ_URL=postgresql://u:p@h/db?sslmode=require&connect_timeout=10\n"
                 "export NZ_PW=a$b;c&d e\nNZ_Q=\"quoted value\"\nNZ_SET=from-file\nnot a line\n", encoding="utf-8")
    assert load_env_file(f) == 3
    import os
    assert os.environ["NZ_URL"] == "postgresql://u:p@h/db?sslmode=require&connect_timeout=10"
    assert os.environ["NZ_PW"] == "a$b;c&d e" and os.environ["NZ_Q"] == "quoted value"
    assert os.environ["NZ_SET"] == "from-environment"
