from pyvpn.replay import ReplayWindow


def test_replay_window_accepts_new_and_rejects_duplicates() -> None:
    window = ReplayWindow(size=8)
    assert window.accept(1)
    assert not window.accept(1)
    assert window.accept(2)
    assert window.accept(9)
    assert not window.accept(1)
    assert window.accept(8)


def test_replay_window_rejects_zero() -> None:
    assert not ReplayWindow().accept(0)
