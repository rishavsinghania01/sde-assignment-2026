import copy
import json
from datetime import datetime, timedelta

from .learning import Counts, bounds, guardrail_ok, move_weight, normalized, readout


def time_before(ts, hours):
    return (datetime.fromisoformat(ts) - timedelta(hours=hours)).isoformat()


def isolated_default(config, dimension):
    return all(dimension in config['allocations'].get(cohort['id'], {})
               for cohort in config['cohorts'])


def prompt_signal(recent, reference, hours):
    minimum, rate, excess = (180, .045, .005) if hours == 6 else (500, .04, .007)
    if recent.connected < minimum or recent.rate('flag_rate') < rate:
        return None
    lower, _ = bounds(recent, reference, 'flag_rate', 3.09)
    return lower if lower >= excess else None


class Strategy:
    def __init__(self, store, api, governance):
        self.store = store
        self.api = api
        self.governance = governance

    def assess(self, workflow, current, state, ts, allow_changes):
        wid, version = workflow['workflow_id'], current['version']
        cfg = current['config']
        previous = self.store.get(wid, 'observed_version')
        if previous != version:
            with self.store.db:
                self.store.set(wid, 'observed_version', version)
                self.store.audit(wid, ts, 'config_observed', current)
                if current['actor'] == 'supervisor':
                    self.store.set(wid, 'experiment', None)
                    self.store.set(wid, 'supervisor_hold', ts)
                    for dim in ('caller_id', 'prompt_version'):
                        self.store.set(wid, 'verify_' + dim, None)
                    self.store.audit(wid, ts, 'supervisor_edit_preserved', {
                        'version': version, 'experiment_invalidated': True,
                    })
        self.verify(workflow, current, ts)
        if not allow_changes:
            return
        hold = self.store.get(wid, 'supervisor_hold')
        # Safety incidents still get evaluated after a supervisor edit.
        if self.prompt_incident(workflow, current, state, ts):
            return
        plan = self.caller_plan(workflow, current, ts)
        if plan is None and (hold is None or hold <= time_before(ts, 24)):
            plan = self.experiment_plan(workflow, current, state, ts)
        if plan is not None:
            self.governance.propose(workflow, current, ts, plan)

    def plan(self, workflow, cfg, ts, action, dimension, after, summary, reason, evidence, impact):
        wid = workflow['workflow_id']
        updated = copy.deepcopy(cfg)
        if dimension == 'prompt_version':
            before = cfg[dimension]
            updated[dimension] = after
            path = dimension
        else:
            before = cfg['allocations']['default'][dimension]
            updated['allocations']['default'][dimension] = after
            path = 'allocations.default.' + dimension
        # Leads uploaded over the remaining cadence are an upper bound on active
        # reach. The historical dial share approximates the default cohort's share.
        start = time_before(ts, 24 * len(workflow['cadence']))
        uploads = self.store.db.execute(
            'SELECT COUNT(*), COALESCE(SUM(leads),0) FROM uploads WHERE workflow=? AND ts>? AND ts<=?',
            (wid, start, ts)
        ).fetchone()
        daily = workflow['daily_batch']['size']
        affected = uploads[1] + daily
        if dimension != 'prompt_version' and cfg['cohorts']:
            total = self.store.total(wid, time_before(ts, 72), ts).dials
            default = self.store.total(wid, time_before(ts, 72), ts, cohort='default').dials
            affected = round(affected * (default / total if total else 1))
        evidence = {
            **evidence, 'scope': 'workflow' if dimension == 'prompt_version' else 'default',
            'reach': {'recent_campaigns': uploads[0], 'recent_uploads': uploads[1],
                      'next_batch': daily, 'method': 'cadence horizon plus next batch, before exclusions'},
        }
        return {
            'action': action, 'dimension': dimension, 'config': updated,
            'summary': summary, 'rationale': reason, 'evidence': evidence,
            'impact': min(1, max(0, impact)), 'affected': affected,
            'diff': {path: {'before': before, 'after': after}},
        }

    def caller_plan(self, workflow, current, ts):
        wid, cfg = workflow['workflow_id'], current['config']
        if not isolated_default(cfg, 'caller_id'):
            return None
        weights = normalized(cfg['allocations']['default']['caller_id'])
        if len(weights) < 2:
            return None
        recent = self.store.counts(wid, time_before(ts, 8), ts, 'caller',
                                   cohort='default', version=current['version'])
        eligible = {v: recent[v] for v in weights if v in recent and recent[v].dials >= 180}
        if len(eligible) < 2:
            return None
        ranked = sorted(eligible, key=lambda v: (eligible[v].rate('pickup_rate'), v))
        weak, strong = ranked[0], ranked[-1]
        weaker, stronger = eligible[weak], eligible[strong]
        lower, _ = bounds(stronger, weaker, 'pickup_rate', 3.6)
        if lower < .025 or weights[weak] <= .05:
            return None
        history = self.store.counts(wid, time_before(ts, 168), time_before(ts, 8),
                                    'caller', cohort='default')
        previous = history.get(weak, Counts())
        pickup_drop = previous.rate('pickup_rate') - weaker.rate('pickup_rate')
        incident = previous.dials >= 250 and pickup_drop >= .045
        # Randomised caller ID changes who picks up. Compare engagement among
        # those who connected before sending their traffic to a different ID.
        guardrail = {'engagement_rate_max_drop': workflow['objective']['guardrail'].get(
            'engagement_rate_max_drop', .025
        )}
        engagement_lower, _ = bounds(stronger, weaker, 'engagement_rate', 1.645)
        auto = workflow['governance']['auto_apply']
        shift = weights[weak] - .05
        if auto['enabled'] and 'caller_id' in auto['allowed_dims'] and auto['max_shift'] > 0:
            shift = min(shift, auto['max_shift'])
        if (not incident and workflow['objective']['primary'] == 'engagement_rate'
                and engagement_lower <= 0):
            return None
        if not guardrail_ok(stronger, weaker, guardrail, 1.645):
            if not incident or weaker.connected < 25 or stronger.connected < 60:
                return None
            # A flagged ID can leave too few pickups for arm-level noninferiority.
            # Bound the observed mix and reduce the move while uncertainty remains.
            shift = min(shift, .20)
            new_connected = sum(weights[v] * c.rate('pickup_rate') for v, c in eligible.items())
            if set(eligible) != set(weights) or new_connected <= 0:
                return None
            shifted_fraction = shift * stronger.rate('pickup_rate') / new_connected
            if shifted_fraction * max(0, -engagement_lower) > next(iter(guardrail.values())):
                return None
        if shift < .03:
            return None
        after = move_weight(weights, weak, strong, shift)
        return self.plan(
            workflow, cfg, ts, 'caller_incident' if incident else 'caller_shift', 'caller_id',
            after, f'Move {shift:.0%} of default calls from {weak} to {strong}',
            'Contemporaneous callers share the same default cohort and config version. '
            'The lower pickup lift bound clears 2.5 points. Keep a small probe on the weaker ID.',
            {'method': 'reweight observed caller rates under the current config',
             'window_hours': 8, 'from': weak, 'to': strong, 'from_counts': weaker,
             'to_counts': stronger, 'prior_from_counts': previous,
             'pickup_delta_lower': lower, 'engagement_delta_lower': engagement_lower,
             'projected_pickup_delta': shift * (stronger.rate('pickup_rate') - weaker.rate('pickup_rate')),
             'pre_mix': self.store.total(wid, time_before(ts, 8), ts, cohort='default',
                                         version=current['version'])},
            shift * lower,
        )

    def charged_call(self, wid, ts, key, path, payload):
        cached = self.store.get(wid, key)
        if cached is not None:
            return cached.get('result')
        # These endpoints have no idempotency key or lookup. After an ambiguous
        # result, keep the spent intent and do not retry the same paid operation.
        with self.store.db:
            self.store.set(wid, key, {'intent': payload})
            self.store.audit(wid, ts, 'credit_intent', {'key': key, 'path': path, **payload})
        status, result = self.api.mutate('POST', path, payload)
        with self.store.db:
            self.store.set(wid, key, {'result': result if status == 200 else None})
            self.store.audit(wid, ts, 'credit_result', {'key': key, 'status': status, **result})
        return result if status == 200 else None

    def detect_prompt(self, wid, live, ts):
        for hours in (6, 24):
            boundary = time_before(ts, hours)
            recent = self.store.total(wid, boundary, ts, prompt=live)
            past = self.store.counts(wid, time_before(ts, 168), boundary, 'prompt')
            reference = min((p for p in past.values() if p.connected >= 500),
                            key=lambda p: p.rate('flag_rate'), default=Counts(0, 1000, 0, 20))
            lower = prompt_signal(recent, reference, hours)
            if lower is not None:
                return hours, recent, past, reference, lower
        return None

    def prompt_incident(self, workflow, current, state, ts):
        wid, cfg = workflow['workflow_id'], current['config']
        live = cfg['prompt_version']
        signal = self.detect_prompt(wid, live, ts)
        if signal is None:
            return False
        hours, recent, past, reference, lower = signal
        version = current['version']
        if self.store.get(wid, 'prompt_alert') != version:
            with self.store.db:
                self.store.set(wid, 'prompt_alert', version)
                self.store.audit(wid, ts, 'prompt_incident', {
                    'version': version, 'prompt': live, 'recent': recent,
                    'reference': reference, 'flag_delta_lower': lower, 'window_hours': hours,
                })
        if not self.governance.available(workflow, ts):
            return True
        credits = self.api.get('/sim/state')['credits_remaining']
        reserve = max(4, min(16, self.store.meta('initial_credits') * .12))
        key = f'suggest:{live}:{self.store.get(wid, "supervisor_hold", "")}'
        if self.store.get(wid, key) is None and credits - 3 < reserve + 4:
            return True
        suggested = self.charged_call(wid, ts, key, '/llm/suggest-fixes', {
            'workflow_id': wid, 'problem': f'{live} flag rate {recent.rate("flag_rate"):.1%}; '
            'suggest grounded alternatives that preserve conversational engagement',
        }) or {}
        allowed = set(workflow['options']['prompt_version']) - {live}
        suggestions = {item['prompt_version'] for item in suggested.get('suggestions', [])}
        catalog = workflow.get('prompt_catalog', {})

        def preference(prompt):
            prior = past.get(prompt, Counts())
            known = prior.connected >= 500 and prior.rate('flag_rate') <= .03
            description = catalog.get(prompt, '').lower()
            strict = any(word in description for word in ('verbatim', 'strict'))
            return (not known, strict, -prior.rate('engagement_rate') if known else 0,
                    'ground' not in description, prompt)

        candidates = sorted(allowed & (suggestions | set(past)), key=preference)[:3]
        minimum = workflow['governance'].get('min_validation_pass_rate', .97)
        for prompt in candidates:
            validation_key = f'validate:{key}:{prompt}'
            credits = self.api.get('/sim/state')['credits_remaining']
            if self.store.get(wid, validation_key) is None and credits - 4 < reserve:
                break
            validation = self.charged_call(wid, ts, validation_key, '/validation/runs',
                                           {'workflow_id': wid, 'prompt_version': prompt, 'n': 400})
            if not validation or validation['pass_rate'] < minimum:
                continue
            prior = past.get(prompt, Counts())
            guardrail = workflow['objective']['guardrail']
            if prior.connected >= 500 and any(
                bounds(prior, recent, name.removesuffix('_max_drop'), 1.645)[1] < -limit
                for name, limit in guardrail.items()
            ):
                continue
            plan = self.plan(
                workflow, cfg, ts, 'prompt_fix', 'prompt_version', prompt,
                f'Replace {live} with validated prompt {prompt}',
                'Automated hallucination flags crossed the incident threshold. The candidate passed '
                'the workflow safety floor. Live pickup and engagement need separate verification.',
                {'method': 'synthetic safety validation plus observed prior prompt performance',
                 'window_hours': hours, 'live_counts': recent, 'historical_candidate_counts': prior,
                 'flag_delta_lower': lower, 'validation_pass_rate': validation['pass_rate'],
                 'validation_n': validation['n'], 'validation_run_id': validation['validation_run_id']},
                lower,
            )
            self.governance.propose(workflow, current, ts, plan)
            return True
        return True

    def experiment_plan(self, workflow, current, state, ts):
        wid, cfg = workflow['workflow_id'], current['config']
        primary = workflow['objective']['primary']
        guardrail = workflow['objective']['guardrail']
        trial = self.store.get(wid, 'experiment')
        if trial is None:
            if primary != 'engagement_rate' or state['end_minute'] - state['sim_minute'] < 3 * 1440:
                return None
            # A new trial bumps the config version, which would end the live check on a prompt fix.
            if self.store.get(wid, 'verify_prompt_version') is not None:
                return None
            previous = self.store.db.execute(
                """SELECT plan FROM proposals WHERE workflow=? AND state='applied'
                   AND json_extract(plan, '$.action')='experiment' ORDER BY rowid DESC LIMIT 1""",
                (wid,)
            ).fetchone()
            done = self.store.db.execute(
                """SELECT MAX(updated) FROM proposals WHERE workflow=? AND state='applied'
                   AND json_extract(plan, '$.action') IN ('end_experiment','rollback')""",
                (wid,)
            ).fetchone()[0]
            if done and done > time_before(ts, 24):
                return None
            dims = [('voice', 'voice'), ('welcome_message', 'welcome')]
            if previous and json.loads(previous[0])['dimension'] == 'voice':
                dims.reverse()
            # One contrast per trial. Existing split allocations belong to the business.
            for dimension, group in dims:
                baseline = normalized(cfg['allocations']['default'][dimension])
                options = sorted(set(workflow['options'][dimension]) - baseline.keys())
                if not isolated_default(cfg, dimension) or len(baseline) != 1 or not options:
                    continue
                prior = self.store.counts(wid, time_before(ts, 168), ts, group, cohort='default')
                control = next(iter(baseline))
                if prior.get(control, Counts()).connected < 500:
                    continue
                tested = {r[0] for r in self.store.db.execute(
                    """SELECT json_extract(plan,'$.experiment.challenger') FROM proposals
                       WHERE workflow=? AND state='applied' AND json_extract(plan,'$.action')='experiment'
                         AND json_extract(plan,'$.dimension')=?""", (wid, dimension)
                )}
                fresh = [v for v in options if v not in tested]
                if not fresh:
                    continue
                challenger = fresh[0]
                experiment = {'dimension': dimension, 'group': group, 'control': control,
                              'challenger': challenger, 'baseline': baseline}
                plan = self.plan(
                    workflow, cfg, ts, 'experiment', dimension, {control: .55, challenger: .45},
                    f'Test {challenger} against {control} on default calls',
                    'Run a two-arm randomised dial-level trial with one changed dimension. '
                    'The challenger has no live effect estimate. Keep the current option as control.',
                    {'method': 'historical support check', 'control_counts': prior[control],
                     'challenger_counts': prior.get(challenger, Counts()), 'projected_delta': None},
                    0,
                )
                return {**plan, 'experiment': experiment}
            return None

        dimension, group = trial['dimension'], trial['group']
        if current['version'] != trial['version']:
            return None
        control, challenger = trial['control'], trial['challenger']
        elapsed = datetime.fromisoformat(ts) - datetime.fromisoformat(trial['started'])
        if trial['phase'] == 'promote':
            start = max(trial['started'], time_before(ts, 48))
        else:
            start = trial['started']
        counts = self.store.counts(wid, start, ts, group, cohort='default', version=trial['version'])
        base, new = counts.get(control, Counts()), counts.get(challenger, Counts())
        minimum_dials = min(base.dials, new.dials)
        minimum_connected = min(base.connected, new.connected)
        lower, upper = bounds(new, base, primary, 1.96)
        guard_bounds = {metric: bounds(new, base, metric.removesuffix('_max_drop'), 1.645)
                        for metric in guardrail}
        early_loss = minimum_dials >= 350 and minimum_connected >= 120 and (
            bounds(new, base, primary, 4)[1] < -.015 or any(
                bounds(new, base, name.removesuffix('_max_drop'), 4)[1] < -limit
                for name, limit in guardrail.items()
            )
        )
        evidence = {'method': 'within-version randomised call comparison', 'start': start,
                    'control': control, 'challenger': challenger, 'control_counts': base,
                    'challenger_counts': new, 'primary': primary, 'primary_interval': [lower, upper],
                    'guardrail_intervals': guard_bounds, 'early_loss': early_loss}
        if trial['phase'] == 'promote':
            if not early_loss:
                return None
            action, weights = 'rollback', trial['baseline']
            summary = f'Restore {control} after measured deterioration of {challenger}'
            reason = 'The retained control provides a contemporaneous reference for a conservative harm stop.'
            impact = abs(new.rate(primary) - base.rate(primary))
        else:
            # Look every round once support is there, and stop at the first decision.
            # The decision is stored so a slow approval cannot reopen it; only a harm
            # stop overrides it.
            evaluation_key = f'evaluation:{trial["proposal_id"]}:{trial["version"]}'
            evaluation = self.store.get(wid, evaluation_key)
            if evaluation is None or early_loss:
                enough = minimum_dials >= 3000 and minimum_connected >= 700 and elapsed >= timedelta(hours=24)
                decision, risk = readout(new, base, primary, guardrail) if enough else (None, {})
                if early_loss or (decision is None and elapsed >= timedelta(hours=96)):
                    decision = 'restore'
                if decision is None:
                    return None
                evaluation = {'won': decision == 'promote', 'evidence': {**evidence, **risk},
                              'lift': risk.get('lift', 0.0)}
                with self.store.db:
                    self.store.set(wid, evaluation_key, evaluation)
                    self.store.audit(wid, ts, 'experiment_readout', evaluation)
            evidence = evaluation['evidence']
            if evaluation['won']:
                action, weights = 'promote', {control: .20, challenger: .80}
                summary = f'Raise {challenger} to 80% and retain {control} as a control'
                reason = ('Expected loss from choosing the challenger is under 0.25 points of the primary KPI '
                          'and the chance of a guardrail breach is under 10%.')
                impact = .8 * evaluation['lift']
            else:
                action, weights = 'end_experiment', trial['baseline']
                summary = f'End the trial and restore {control}'
                reason = ('The challenger triggered a harm stop, is at most marginally better than control, '
                          'or stayed undecided for 96 hours.')
                impact = abs(new.rate(primary) - base.rate(primary)) if early_loss else 0
        plan = self.plan(workflow, cfg, ts, action, dimension, weights, summary, reason, evidence, impact)
        return {**plan, 'experiment': trial}

    def verify(self, workflow, current, ts):
        wid = workflow['workflow_id']
        for dimension in ('caller_id', 'prompt_version'):
            key = 'verify_' + dimension
            watch = self.store.get(wid, key)
            if watch is None:
                continue
            plan = watch['plan']
            if watch['version'] != current['version']:
                with self.store.db:
                    self.store.set(wid, key, None)
                    self.store.audit(wid, ts, 'verification_superseded', {'id': watch['proposal_id']})
                continue
            filters = {'cohort': 'default'} if dimension == 'caller_id' else {}
            before = Counts(*plan['evidence'].get('pre_mix', plan['evidence'].get('live_counts')))
            after = self.store.total(wid, watch['started'], ts, version=watch['version'], **filters)
            if after.connected < 250:
                continue
            metric = 'pickup_rate' if dimension == 'caller_id' else 'flag_rate'
            interval = bounds(after, before, metric, 2.58)
            kpis = {name: bounds(after, before, name, 2.58) for name in ('pickup_rate', 'engagement_rate')}
            improved = interval[0] > 0 if metric == 'pickup_rate' else interval[1] < 0
            harms = {key: kpis[key.removesuffix('_max_drop')][1] < -value
                     for key, value in workflow['objective']['guardrail'].items()}
            elapsed = datetime.fromisoformat(ts) - datetime.fromisoformat(watch['started'])
            if not improved and not any(harms.values()) and elapsed < timedelta(hours=48):
                continue
            with self.store.db:
                self.store.set(wid, key, None)
                self.store.audit(wid, ts, 'change_verification', {
                    'id': watch['proposal_id'], 'metric': metric, 'improved': improved,
                    'before': before, 'after': after, 'interval': interval,
                    'kpi_intervals': kpis, 'guardrail_regressions': harms,
                    'comparison': 'observational before/after',
                })
