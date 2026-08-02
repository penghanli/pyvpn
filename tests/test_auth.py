from pyvpn.auth import (
    certificate_fingerprint,
    normalize_fingerprint,
    normalize_token,
    token_identifier,
    token_matches,
)


def test_token_matches_constant_result() -> None:
    assert token_matches("secret", "secret")
    assert not token_matches("secret", "wrong")


def test_token_normalization_and_identifier() -> None:
    assert normalize_token("  secret\r\n") == "secret"
    assert token_identifier("secret") == token_identifier("secret")
    assert token_identifier("secret") != token_identifier("wrong")
    assert len(token_identifier("secret")) == 12


def test_fingerprint_normalization() -> None:
    fp = certificate_fingerprint(b"cert")
    assert normalize_fingerprint(fp.upper()) == fp
    assert normalize_fingerprint("sha256:" + ":".join(["ab", "cd"])) == "sha256:abcd"
