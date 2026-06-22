from pyvpn.auth import certificate_fingerprint, normalize_fingerprint, token_matches


def test_token_matches_constant_result() -> None:
    assert token_matches("secret", "secret")
    assert not token_matches("secret", "wrong")


def test_fingerprint_normalization() -> None:
    fp = certificate_fingerprint(b"cert")
    assert normalize_fingerprint(fp.upper()) == fp
    assert normalize_fingerprint("sha256:" + ":".join(["ab", "cd"])) == "sha256:abcd"
