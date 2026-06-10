from window import window_sums


def test_counts():
    assert len(window_sums([1, 2, 3, 4], 2)) == 3


def test_values():
    assert window_sums([1, 2, 3, 4], 2) == [3, 5, 7]


def test_full_window():
    assert window_sums([1, 2, 3], 3) == [6]
