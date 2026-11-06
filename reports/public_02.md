# Grade report — public_02_incidents

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.285 | +21.1% | 0.200 | +10.5% | 0.500 | +6.8% | 32% | 93 (348) |
| nw_kyc | 0.372 | -0.6% | 0.236 | +0.7% | 0.601 | -1.3% | 0% | 21 (29) |
| nw_renewal | 0.434 | +0.3% | 0.262 | -0.2% | 0.555 | +0.2% | 5% | 54 (54) |
| ALL | 0.353 | +6.8% | 0.228 | +4.1% | 0.542 | +1.7% | 15% | 168 (431) |

## Changes applied by the controller

13 applied — neutral: 3, beneficial: 7, harmful: 3

- ks_cancel v2 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_renewal v2 (controller_approved) dims=['voice'] engageΔ=+0.012 didΔ=+0.000 → **beneficial**
- ks_cancel v3 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- ks_cancel v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.193 → **beneficial**
- nw_renewal v3 (controller_approved) dims=['voice'] engageΔ=-0.012 didΔ=+0.000 → **harmful**
- ks_cancel v5 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.159 → **beneficial**
- ks_cancel v7 (controller_approved) dims=['prompt_version'] engageΔ=+0.102 didΔ=+0.000 → **beneficial**
- nw_renewal v4 (controller_approved) dims=['welcome_message'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- ks_cancel v8 (controller_approved) dims=['welcome_message'] engageΔ=+0.021 didΔ=+0.000 → **beneficial**
- ks_cancel v9 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.025 → **beneficial**
- nw_renewal v6 (controller_approved) dims=['voice'] engageΔ=-0.012 didΔ=+0.000 → **harmful**
- ks_cancel v10 (controller_approved) dims=['welcome_message'] engageΔ=-0.021 didΔ=+0.000 → **harmful**
- nw_renewal v7 (controller_approved) dims=['voice'] engageΔ=+0.012 didΔ=+0.000 → **beneficial**

## Governance

```
{
  "approval_requests": 12,
  "decisions": {
    "approved": 10,
    "rejected": 1,
    "expired": 1
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 1
  },
  "applied_via_approval": 10,
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
      "2": 0.359,
      "3": 0.108,
      "4": 0.091,
      "5": 0.098,
      "6": 0.084,
      "7": 0.05,
      "8": 0.044,
      "9": 0.047
    }
  },
  {
    "type": "supervisor_edit",
    "workflow": "ks_cancel",
    "at": "D3 11:30",
    "mttr_minutes": 315,
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