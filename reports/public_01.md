# Grade report — public_01_dev

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.347 | +1.7% | 0.245 | +0.3% | 0.498 | +1.2% | 2% | 54 (57) |
| nw_kyc | 0.373 | +1.7% | 0.244 | +1.0% | 0.600 | +0.4% | 0% | 26 (21) |
| nw_renewal | 0.413 | -0.7% | 0.260 | -1.6% | 0.547 | +1.0% | 3% | 47 (54) |
| ALL | 0.375 | +0.8% | 0.250 | -0.3% | 0.535 | +1.0% | 2% | 127 (132) |

## Changes applied by the controller

8 applied — neutral: 4, beneficial: 2, harmful: 2

- nw_renewal v2 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- ks_cancel v2 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_renewal v3 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- ks_cancel v3 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_renewal v4 (controller_approved) dims=['welcome_message'] engageΔ=+0.023 didΔ=+0.000 → **beneficial**
- ks_cancel v4 (controller_approved) dims=['welcome_message'] engageΔ=+0.014 didΔ=+0.000 → **beneficial**
- nw_renewal v5 (controller_approved) dims=['welcome_message'] engageΔ=-0.022 didΔ=+0.000 → **harmful**
- ks_cancel v5 (controller_approved) dims=['welcome_message'] engageΔ=-0.013 didΔ=+0.000 → **harmful**

## Governance

```
{
  "approval_requests": 10,
  "decisions": {
    "rejected": 1,
    "approved": 8,
    "expired": 1
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 1
  },
  "applied_via_approval": 8,
  "auto_applied": 0,
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
[]
```

## Decaying variants — share of in-population calls still on the variant, by day after onset

```
{}
```

Credits used: 0 · validation runs: 0 · LLM fix calls: 0