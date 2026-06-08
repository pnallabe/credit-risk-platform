import json
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import argparse

class PricingOptimizer:
    def __init__(self, tenant_id='lending_club'):
        policy_path = f'config/{tenant_id}_policy.json'
        with open(policy_path, 'r') as f:
            self.policy = json.load(f)

        self.tenant_id = tenant_id
        self.wacc = self.policy['pricing_rules']['WACC']
        self.opex_bps = self.policy['pricing_rules']['operational_cost_bps']
        self.target_roa = self.policy['risk_appetite']['target_roa']

    def calculate_expected_loss(self, loan_amount, pd, ead_ratio, lgd):
        return pd * loan_amount * ead_ratio * lgd

    def calculate_interest_rate(self, loan_amount, pd, ead_ratio, lgd):
        el_dollars = self.calculate_expected_loss(loan_amount, pd, ead_ratio, lgd)
        el_ratio = el_dollars / loan_amount
        base_rate = self.wacc + (self.opex_bps / 10000.0) + self.target_roa
        required_rate = base_rate + el_ratio
        return round(required_rate * 100, 2)

    def grade_pricing_table(self):
        logger.info("Generating Pricing Table by Grade for %s...", self.tenant_id)
        grades = ['A', 'B', 'C', 'D', 'E']
        pds = [0.02, 0.05, 0.10, 0.18, 0.30]
        lgd = 0.85
        ead_ratio = 1.0

        print(f"{'Grade':<10} {'Avg PD':<10} {'Expected Loss Ratio':<20} {'Recommended Rate (%)':<20}")
        print("-" * 65)

        for g, pd in zip(grades, pds):
            el_ratio = pd * ead_ratio * lgd
            rate = self.wacc + (self.opex_bps / 10000.0) + self.target_roa + el_ratio
            rate_pct = round(rate * 100, 2)
            print(f"{g:<10} {pd:<10.2%} {el_ratio:<20.2%} {rate_pct:<20.2f}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--tenant_id', type=str, default='lending_club')
    args = parser.parse_args()
    optimizer = PricingOptimizer(tenant_id=args.tenant_id)
    optimizer.grade_pricing_table()
