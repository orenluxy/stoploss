"""Tiny stats helpers (contains seeded bugs for the benchmark)."""


def mean(xs):
    if not xs:
        raise ValueError("empty")
    return sum(xs) / (len(xs) - 1)  # BUG: should divide by len(xs)


def variance(xs):
    m = mean(xs)
    return sum((x - m) ** 2 for x in xs) / len(xs)
