# Grade report — public_02_incidents

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.288 | +22.4% | 0.203 | +12.1% | 0.497 | +6.3% | 33% | 107 (348) |
| nw_kyc | 0.363 | -2.9% | 0.237 | +1.2% | 0.585 | -3.9% | 0% | 20 (29) |
| nw_renewal | 0.427 | -1.3% | 0.260 | -1.0% | 0.552 | -0.4% | 8% | 58 (54) |
| ALL | 0.351 | +6.0% | 0.229 | +4.4% | 0.536 | +0.7% | 17% | 185 (431) |

## Changes applied by the controller

10 applied — neutral: 3, beneficial: 7

- ks_cancel v2 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_renewal v2 (controller_approved) dims=['voice'] engageΔ=+0.012 didΔ=+0.000 → **beneficial**
- ks_cancel v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.193 → **beneficial**
- ks_cancel v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.160 → **beneficial**
- nw_renewal v3 (controller_approved) dims=['voice'] engageΔ=+0.010 didΔ=+0.000 → **neutral**
- ks_cancel v6 (controller_approved) dims=['prompt_version'] engageΔ=+0.102 didΔ=+0.000 → **beneficial**
- ks_cancel v7 (controller_approved) dims=['welcome_message'] engageΔ=+0.022 didΔ=+0.000 → **beneficial**
- ks_cancel v8 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.027 → **beneficial**
- nw_renewal v5 (controller_approved) dims=['welcome_message'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- ks_cancel v9 (controller_approved) dims=['welcome_message'] engageΔ=+0.017 didΔ=+0.000 → **beneficial**

## Governance

```
{
  "approval_requests": 7,
  "decisions": {
    "approved": 7,
    "expired": 0
  },
  "rejection_reasons": {},
  "applied_via_approval": 7,
  "auto_applied": 3,
  "auto_apply_rejected": 0,
  "apply_conflicts": 0,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "nw_renewal": 1,
    "ks_cancel": 2
  }
}
```

## Incidents

```
[
  {
    "type": "did_flagged",
    "workflow": "ks_cancel",
    "at": "D2 10:00",
    "flagged_did_share_by_day": {
      "2": 0.306,
      "3": 0.104,
      "4": 0.094,
      "5": 0.076,
      "6": 0.052,
      "7": 0.046,
      "8": 0.048,
      "9": 0.046
    }
  },
  {
    "type": "supervisor_edit",
    "workflow": "ks_cancel",
    "at": "D3 11:30",
    "mttr_minutes": 1530,
    "fixed_by": "controller_approved"
  },
  {
    "type": "supervisor_edit",
    "workflow": "nw_renewal",
    "at": "D5 15:00"
  }
]
```

## Decaying variants — share of in-population calls still on the variant, by day after onset

```
{}
```

Credits used: 7 · validation runs: 1 · LLM fix calls: 1