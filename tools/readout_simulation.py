"""Operating characteristics of the experiment readout on synthetic two-arm trials.

Arms are independent binomials, so repeat callers are absent here and the 1.5 variance
factor in controller.learning makes the real rule slightly more cautious than shown.
"""

import argparse
from collections import Counter

import numpy as np

from controller.learning import Counts, bounds, guardrail_ok, readout

GUARDRAIL = {'pickup_rate_max_drop': .02}


def legacy(new, base, hours):
    # The rule this replaced: one read at the first look with enough support.
    won = bounds(new, base, 'engagement_rate', 2.807)[0] >= .01 and guardrail_ok(new, base, GUARDRAIL, 1.645)
    return 'promote' if won else 'restore'


def trial(rng, rule, lift, pickup_shift, dials_per_hour, pickup, engagement, deadline):
    arms = {'control': [0, 0, 0], 'challenger': [0, 0, 0]}
    for hour in range(1, deadline + 1):
        if 9 <= hour % 24 < 21:
            for name, share, p, e in (('control', .55, pickup, engagement),
                                      ('challenger', .45, pickup + pickup_shift, engagement + lift)):
                dials = rng.poisson(dials_per_hour * share)
                connected = rng.binomial(dials, p)
                arms[name][0] += dials
                arms[name][1] += connected
                arms[name][2] += rng.binomial(connected, e)
        base, new = Counts(*arms['control']), Counts(*arms['challenger'])
        if hour < 24 or min(base.connected, new.connected) < 700 or min(base.dials, new.dials) < 3000:
            continue
        if rule == 'legacy':
            return legacy(new, base, hour), hour
        decision, _ = readout(new, base, 'engagement_rate', GUARDRAIL)
        if decision:
            return decision, hour
    return 'restore at deadline', deadline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trials', type=int, default=2000)
    parser.add_argument('--dials-per-hour', type=int, default=300)
    parser.add_argument('--pickup', type=float, default=.26)
    parser.add_argument('--engagement', type=float, default=.55)
    parser.add_argument('--seed', type=int, default=11)
    args = parser.parse_args()
    cases = [(lift, 0) for lift in (-.03, -.02, -.01, 0, .01, .02, .03)] + [(.02, -.03)]
    print(f'{args.trials} trials per row, {args.dials_per_hour} dials/hour 09:00-21:00, 55/45 split, '
          f'pickup {args.pickup}, engagement {args.engagement}, 96 h deadline')
    for rule in ('legacy', 'expected_loss'):
        rng = np.random.default_rng(args.seed)
        print(f'\n{rule}')
        print('engagement lift | pickup shift | promote | restore | restore at deadline | median hours')
        for lift, shift in cases:
            outcomes, hours = Counter(), []
            for _ in range(args.trials):
                outcome, hour = trial(rng, rule, lift, shift, args.dials_per_hour, args.pickup,
                                      args.engagement, 96)
                outcomes[outcome] += 1
                hours.append(hour)
            share = {key: outcomes[key] / args.trials for key in ('promote', 'restore', 'restore at deadline')}
            print(f'{lift:+.2f} | {shift:+.2f} | {share["promote"]:.1%} | {share["restore"]:.1%} | '
                  f'{share["restore at deadline"]:.1%} | {np.median(hours):.0f}')


if __name__ == '__main__':
    main()
