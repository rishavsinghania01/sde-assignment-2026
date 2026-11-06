# Grade report — public_01_dev

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.342 | +0.2% | 0.246 | +0.6% | 0.490 | -0.4% | 4% | 69 (57) |
| nw_kyc | 0.367 | +0.0% | 0.243 | +0.6% | 0.594 | -0.6% | 0% | 16 (21) |
| nw_renewal | 0.413 | -0.7% | 0.261 | -1.1% | 0.544 | +0.5% | 0% | 49 (54) |
| ALL | 0.371 | -0.2% | 0.251 | -0.0% | 0.529 | -0.1% | 2% | 134 (132) |

## Changes applied by the controller

6 applied — neutral: 4, beneficial: 2

- ks_cancel v2 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_renewal v2 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- ks_cancel v3 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- ks_cancel v4 (controller_approved) dims=['welcome_message'] engageΔ=+0.014 didΔ=+0.000 → **beneficial**
- nw_renewal v3 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- ks_cancel v5 (controller_approved) dims=['welcome_message'] engageΔ=+0.011 didΔ=+0.000 → **beneficial**

## Governance

```
{
  "approval_requests": 7,
  "decisions": {
    "approved": 6,
    "rejected": 1,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 1
  },
  "applied_via_approval": 6,
  "auto_applied": 0,
  "auto_apply_rejected": 0,
  "apply_conflicts": 0,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "nw_renewal": 2,
    "ks_cancel": 1
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