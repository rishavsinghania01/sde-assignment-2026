from math import sqrt
from typing import NamedTuple


class Counts(NamedTuple):
    dials: int = 0
    connected: int = 0
    engaged: int = 0
    flags: int = 0

    def __add__(self, other):
        return Counts(*(a + b for a, b in zip(self, other)))

    def sample(self, metric):
        return {
            'pickup_rate': (self.connected, self.dials),
            'engagement_rate': (self.engaged, self.connected),
            'flag_rate': (self.flags, self.connected),
        }[metric]

    def rate(self, metric):
        successes, total = self.sample(metric)
        return successes / total if total else 0.0


def bounds(candidate, control, metric, z):
    # Half a success and half a failure keep the variance finite at the extremes.
    a, n = candidate.sample(metric)
    b, m = control.sample(metric)
    if not n or not m:
        return -1.0, 1.0
    p, q = (a + .5) / (n + 1), (b + .5) / (m + 1)
    width = z * sqrt(1.5 * (p * (1 - p) / n + q * (1 - q) / m))
    return p - q - width, p - q + width


def guardrail_ok(candidate, control, guardrail, z):
    return all(
        bounds(candidate, control, key.removesuffix('_max_drop'), z)[0] >= -limit
        for key, limit in guardrail.items()
    )


def normalized(weights):
    total = sum(weights.values())
    return {name: weight / total for name, weight in weights.items() if weight > 0}


def move_weight(weights, source, target, amount):
    result = normalized(weights)
    amount = min(result[source], amount)
    result[source] = round(result[source] - amount, 10)
    result[target] = round(result.get(target, 0) + amount, 10)
    return {name: weight for name, weight in result.items() if weight > 0}
