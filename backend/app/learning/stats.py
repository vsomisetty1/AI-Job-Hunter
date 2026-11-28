"""Small-sample statistics for personal job-search data (pure, no numpy).

A personal search has tens or hundreds of applications, not millions, so:
* rates come with a Wilson score interval (sane at 0/5 or 5/5);
* two groups are compared with Fisher's exact test (exact at any size);
* several comparisons in one family are corrected with Holm's method;
* score accuracy is the ROC AUC (Mann-Whitney), with ties counted half.
"""

import math
from dataclasses import dataclass

Z95 = 1.959963984540054


@dataclass(frozen=True)
class Rate:
    k: int  # successes
    n: int  # trials

    @property
    def value(self) -> float | None:
        return self.k / self.n if self.n else None

    @property
    def interval(self) -> tuple[float, float] | None:
        return wilson(self.k, self.n)

    def as_dict(self) -> dict[str, object]:
        lo_hi = self.interval
        return {
            "k": self.k,
            "n": self.n,
            "rate": round(self.value, 4) if self.value is not None else None,
            "low": round(lo_hi[0], 4) if lo_hi else None,
            "high": round(lo_hi[1], 4) if lo_hi else None,
        }


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float] | None:
    """95 % Wilson score interval for k successes in n trials."""
    if n <= 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def fisher_exact(a: int, b: int, c: int, d: int) -> float:
    """Two-sided p-value of Fisher's exact test for the table [[a, b], [c, d]]
    (rows: groups; columns: success, failure)."""
    row1, row2, col1 = a + b, c + d, a + c
    n = row1 + row2
    if n == 0 or row1 == 0 or row2 == 0 or col1 == 0 or col1 == n:
        return 1.0

    def prob(x: int) -> float:
        return math.comb(row1, x) * math.comb(row2, col1 - x) / math.comb(n, col1)

    observed = prob(a)
    lo, hi = max(0, col1 - row2), min(row1, col1)
    total = sum(p for x in range(lo, hi + 1) if (p := prob(x)) <= observed * (1 + 1e-7))
    return min(1.0, total)


def holm(p_values: list[float]) -> list[float]:
    """Holm-adjusted p-values, in the input order."""
    m = len(p_values)
    order = sorted(range(m), key=lambda i: p_values[i])
    adjusted = [1.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * p_values[i]))
        adjusted[i] = running
    return adjusted


def auc(positives: list[float], negatives: list[float]) -> float | None:
    """Probability that a random positive scores higher than a random negative."""
    if not positives or not negatives:
        return None
    wins = 0.0
    for p in positives:
        for q in negatives:
            wins += 1.0 if p > q else 0.5 if p == q else 0.0
    return wins / (len(positives) * len(negatives))


def auc_p_value(positives: list[float], negatives: list[float]) -> float | None:
    """Two-sided p-value that the AUC differs from 0.5 (Mann-Whitney U, normal
    approximation with tie correction). None when either group is empty."""
    n1, n2 = len(positives), len(negatives)
    if not n1 or not n2:
        return None
    u = (auc(positives, negatives) or 0.0) * n1 * n2
    pooled = sorted(positives + negatives)
    n = n1 + n2
    ties = 0.0
    i = 0
    while i < n:
        j = i
        while j < n and pooled[j] == pooled[i]:
            j += 1
        t = j - i
        ties += t**3 - t
        i = j
    variance = n1 * n2 / 12 * ((n + 1) - ties / (n * (n - 1))) if n > 1 else 0.0
    if variance <= 0:
        return 1.0
    z = (u - n1 * n2 / 2) / math.sqrt(variance)
    return math.erfc(abs(z) / math.sqrt(2))


def median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def confidence(p_adjusted: float) -> str:
    """Plain-language strength of evidence for an adjusted p-value."""
    if p_adjusted < 0.01:
        return "high"
    if p_adjusted < 0.05:
        return "medium"
    return "low"
