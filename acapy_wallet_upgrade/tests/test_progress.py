from acapy_wallet_upgrade.strategies import Progress


def test_progress(capsys):
    progress = Progress("test", interval=3)
    for _ in range(301):
        progress.update(1)
    progress.report()
    captured = capsys.readouterr()
    assert "test 301" in captured.out
    assert "test 300" in captured.out


def test_progress_small(capsys):
    progress = Progress("test", interval=50)
    progress.update()
    progress.update()
    progress.report()
    captured = capsys.readouterr()
    assert "test 2" in captured.out
