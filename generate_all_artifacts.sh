#!/bin/bash

# Ensure we use the virtual environment
source .venv/bin/activate
export PYTHONPATH=.

TENANTS=("lending_club" "synthetic_tenant" "freddie_mac" "prosper")

for TENANT in "${TENANTS[@]}"; do
    echo "====================================="
    echo "Processing Tenant: $TENANT"
    echo "====================================="

    # 1. Train PD Model
    python models/credit_risk/train_pd_model.py --tenant_id $TENANT

    # 2. Train EAD Model
    python models/credit_risk/train_ead_model.py --tenant_id $TENANT

    # 3. Train LGD Model
    python models/lgd/train_lgd_model.py --tenant_id $TENANT

    # 4. Generate Pricing Table
    python models/pricing/pricing_optimizer.py --tenant_id $TENANT

    # 5. Generate Dashboard Assets
    python scripts/generate_tenant_dashboard.py --tenant_id $TENANT

    echo "Finished processing $TENANT."
    echo ""
done

echo "All tenant pipelines executed successfully."
