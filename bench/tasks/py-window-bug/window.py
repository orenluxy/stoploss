def window_sums(xs, k):
    """Sums of every contiguous window of size k."""
    if k <= 0 or k > len(xs):
        return []
    return [sum(xs[i:i + k]) for i in range(len(xs) - k)]  # BUG: misses last window
