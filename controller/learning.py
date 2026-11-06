from math import erf, exp, pi, sqrt
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


def difference(candidate, control, metric):
    # Half a success and half a failure keep the variance finite at the extremes.
    a, n = candidate.sample(metric)
    b, m = control.sample(metric)
    if not n or not m:
        return 0.0, 1.0
    p, q = (a + .5) / (n + 1), (b + .5) / (m + 1)
    return p - q, sqrt(1.5 * (p * (1 - p) / n + q * (1 - q) / m))


def bounds(candidate, control, metric, z):
    if not candidate.sample(metric)[1] or not control.sample(metric)[1]:
        return -1.0, 1.0
    mean, error = difference(candidate, control, metric)
    return mean - z * error, mean + z * error


def normal_cdf(x):
    return .5 * (1 + erf(x / sqrt(2)))


def expected_loss(mean, error):
    """Expected shortfall from choosing the candidate when its lift is N(mean, error**2)."""
    x = mean / error
    return error * exp(-x * x / 2) / sqrt(2 * pi) - mean * normal_cdf(-x)


def readout(candidate, control, primary, guardrail, tolerance=.0025, breach_limit=.10):
    """Pick an arm once the expected cost of being wrong is below tolerance.

    Returns 'promote', 'restore' or None (keep collecting), plus the numbers behind it.
    tolerance is in rate units: .0025 accepts an expected 0.25-point shortfall on the
    primary KPI. Promotion also needs the posterior chance of a guardrail breach to stay
    under breach_limit. tools/readout_simulation.py reports what these defaults cost.
    """
    mean, error = difference(candidate, control, primary)
    breach = 0.0
    for name, limit in guardrail.items():
        drop, spread = difference(candidate, control, name.removesuffix('_max_drop'))
        breach = max(breach, normal_cdf((-limit - drop) / spread))
    risk = {'lift': mean, 'lift_error': error, 'candidate_loss': expected_loss(mean, error),
            'control_loss': expected_loss(-mean, error), 'guardrail_breach': breach}
    if mean > 0 and risk['candidate_loss'] <= tolerance and breach <= breach_limit:
        return 'promote', risk
    if mean <= 0 and risk['control_loss'] <= tolerance:
        return 'restore', risk
    return None, risk


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
