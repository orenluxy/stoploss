from stats import mean, variance


def test_mean_basic():
    assert mean([2, 4, 6]) == 4


def test_mean_single():
    assert mean([5]) == 5


def test_variance_constant():
    assert variance([3, 3, 3]) == 0
