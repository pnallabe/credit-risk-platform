# Risk Modeling, CNPV Pricing & Champion-Challenger Engine Manual

Welcome to the **HelixDecision Risk Modeling & Pricing Optimization Guide**. This technical manual details the mathematical algorithms, continuous risk-based pricing models, Double Machine Learning (DML) price elasticity estimation, and champion/challenger policy experimentation built into HelixDecision.

---

## 1. Risk & Pricing Architecture Overview

```mermaid
graph TD
    Data[Applicant Features & Credit Score] --> RiskModel[PD / LGD Scoring Models]
    RiskModel -->|PD & LGD| PricingOpt[SLSQP Pricing Optimizer]

    subgraph Pricing Subsystem
        PricingOpt --> DMLEstimator[DML Price Elasticity Estimator]
        PricingOpt --> FTPEngine[Funds Transfer Pricing Engine]
        PricingOpt --> CapitalEngine[Economic Capital & RAROC Engine]
    end

    PricingOpt -->|Optimal APR & Line| PolicyEngine[Policy Challenger A/B Router]

    subgraph Deployment & Monitoring
        PolicyEngine -->|Champion (80%)| ChampionExec[Champion Policy Execution]
        PolicyEngine -->|Challenger (20%)| ChallengerExec[Challenger Policy Execution]
        ChampionExec --> DriftMonitor[PSI & Performance Monitoring]
        ChallengerExec --> DriftMonitor
    end
```

---

## 2. SLSQP Continuous Pricing & Line Optimizer (`models/pricing/pricing_optimizer.py`)

 HelixDecision utilizes SciPy's Sequential Least Squares Programming (`SLSQP`) continuous optimizer to maximize **Commercial Net Present Value (CNPV)** across credit limit and APR dimensions.

### 2.1 Mathematical CNPV Objective Formulation

The optimizer solves for the optimal vector $ \mathbf{x}^* = [\text{APR}^*, \text{Limit}^*] $ that maximizes Expected CNPV:

$$\max_{\text{APR}, \text{Limit}} \text{CNPV}(\text{APR}, \text{Limit}) = \text{Limit} \cdot \delta(\text{APR}) \cdot \left[ \text{APR} + \gamma_{\text{interchange}} - \text{FTP} - \text{OpEx} - (\text{PD} \cdot \text{LGD}) \right]$$

Where:
* $ \delta(\text{APR}) = \max\left(0.1, 1.0 + \epsilon \cdot (\text{APR} - \text{APR}_0)\right) $ is the demand response multiplier.
* $ \epsilon = \frac{d\text{Volume}}{d\text{APR}} $ is the causal price elasticity estimated via Double Machine Learning.
* $ \gamma_{\text{interchange}} $ is interchange revenue (default: `1.8%`).
* $ \text{FTP} $ is Funds Transfer Pricing cost of funds (default: `5.0%`).
* $ \text{OpEx} $ is operating expense rate (default: `1.5%`).
* $ \text{PD} \cdot \text{LGD} $ is expected annual credit loss rate.

### 2.2 Optimizer Constraints & Bounds

1. **Minimum APR Hurdle Rate**:
   $$\text{APR} \ge \text{WACC} + \text{OpEx} + 0.5 \cdot (\text{PD} \cdot \text{LGD})$$
2. **Usury Cap Limit**:
   $$\text{APR} \le 36.0\%$$
3. **Credit Line Cap**:
   $$\$500 \le \text{Limit} \le \$25,000$$
4. **Maximum Loss Budget Constraint**:
   $$\text{Limit} \cdot (\text{PD} \cdot \text{LGD}) \le \text{Max Loss Budget } (\$1,500)$$

---

## 3. Double Machine Learning (DML) Price Elasticity Estimator

`DMLPriceElasticityEstimator` isolates unconfounded price sensitivity from observational application data by orthogonalizing against borrower risk covariates $ \mathbf{X} $.

### DML Two-Stage Residualization Algorithm
1. **Stage 1**: Train Ridge regression models on borrower risk covariates $ \mathbf{X} $:
   $$\hat{Y} = \mathcal{M}_Y(\mathbf{X}), \quad \hat{T} = \mathcal{M}_T(\mathbf{X})$$
2. **Residual Calculation**:
   $$\tilde{Y} = Y - \hat{Y}, \quad \tilde{T} = T - \hat{T}$$
3. **Stage 2 OLS**: Regress outcome volume residuals on treatment APR residuals:
   $$\hat{\epsilon} = \frac{\sum \tilde{T} \cdot \tilde{Y}}{\sum \tilde{T}^2}$$

### Python Code Example
```python
import numpy as np
from models.pricing.pricing_optimizer import SLSQPPricingOptimizer, DMLPriceElasticityEstimator

# 1. Instantiate DML Estimator & Optimizer
dml_estimator = DMLPriceElasticityEstimator(alpha=1.0)
optimizer = SLSQPPricingOptimizer(
    wacc=0.08,
    opex_rate=0.015,
    ftp_rate=0.05,
    usury_cap=0.36,
    dml_estimator=dml_estimator
)

# 2. Optimize offer for applicant with PD=2.5%, LGD=85%
result = optimizer.optimize_offer(
    annual_pd=0.025,
    lgd=0.85,
    initial_apr=0.18,
    initial_limit=5000.0,
    causal_elasticity=-1.65
)

print(f"Optimal APR: {result.optimal_apr * 100:.2f}%")
print(f"Optimal Credit Limit: ${result.optimal_credit_limit:,.2f}")
print(f"Expected CNPV: ${result.expected_cnpv:,.2f}")
print(f"Expected Loss: ${result.expected_loss:,.2f}")
print(f"Status: {result.status_message}")
```

---

## 4. Funds Transfer Pricing & Economic Capital (`models/pricing/ftp_engine.py`)

Funds Transfer Pricing (FTP) assigns an institutional cost of funds to each credit extension based on term duration and interest rate curves.

### Risk-Adjusted Return on Capital (RAROC) Equation
$$\text{RAROC} = \frac{\text{Net Income}}{\text{Economic Capital}} = \frac{\text{Limit} \cdot (\text{APR} + \gamma - \text{FTP} - \text{OpEx} - \text{PD} \cdot \text{LGD})}{\text{UL}_{99.9\%}}$$

Where $ \text{UL}_{99.9\%} $ is the Unexpected Loss at the 99.9% confidence interval under Basel II/III capital frameworks.

---

## 5. Champion/Challenger Policy System (`decision_engine/policy_challenger.py`)

HelixDecision supports policy-level champion/challenger experimentation.

### Policy Split Configuration Schema
```python
from decision_engine.policy_challenger import PolicyChallengerConfig

champion_cfg = PolicyChallengerConfig(
    role="CHAMPION",
    version_id=101,
    version_tag="v2.4.0-stable",
    traffic_pct=0.80,
    tenant_id="lending_club",
    active=True
)

challenger_cfg = PolicyChallengerConfig(
    role="CHALLENGER",
    version_id=102,
    version_tag="v2.5.0-experimental",
    traffic_pct=0.20,
    tenant_id="lending_club",
    active=True
)
```

### Deterministic Traffic Routing Algorithm
Traffic is routed deterministically using MD5/SHA256 hashing of the `application_id`:
```python
def route_application(application_id: str, challenger_pct: float = 0.20) -> str:
    hash_val = int(hashlib.sha256(application_id.encode()).hexdigest(), 16)
    normalized_bucket = (hash_val % 10000) / 10000.0
    return "CHALLENGER" if normalized_bucket < challenger_pct else "CHAMPION"
```

### A/B Evaluation & Auto-Promotion Thresholds
* **Sample Size Requirement**: Minimum 1,000 decisions per arm.
* **Kolmogorov-Smirnov p-value**: $ p < 0.05 $ for approval rate divergence.
* **Auto-Promotion Rule**: If Challenger exhibits higher CNPV with equal or lower bad rate (default rate) over a 14-day window, `PolicyComparisonReport` issues a `PROMOTE` recommendation.
