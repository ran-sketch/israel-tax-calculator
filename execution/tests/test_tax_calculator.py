#!/usr/bin/env python3
"""
Validation tests for Israel Self-Employed Tax Calculator 2026.

Run:  python execution/tests/test_tax_calculator.py
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tax_calculator import run_calculation, CREDIT_POINT_ANNUAL, NI_MIN_ANNUAL


def _run(annual_revenue, pension=0, kh=0, expenses=None, vat="auto", credit_points=2.25,
         home_office_ratio=0.0):
    return run_calculation({
        "annual_revenue":      annual_revenue,
        "pension_deposit":     pension,
        "kh_deposit":          kh,
        "expenses":            expenses or [],
        "vat_status_override": vat,
        "credit_points":       credit_points,
        "home_office_ratio":   home_office_ratio,
    })


# ─────────────────────────────────────────────
# CASE 1 — 25,000/month, pension 2,000/month, keren 1,700/month, patur, low expenses
# ─────────────────────────────────────────────
def test_case_1_25k_monthly():
    r = _run(
        annual_revenue=300_000,
        pension=24_000,
        kh=20_400,
        expenses=[{"category": "mobile_phone", "gross_amount": 2_400, "has_vat_invoice": True}],
        vat="patur",
    )
    s, it = r["summary"], r["income_tax"]

    # Full pension deposit (24k) < max deduction (11% of 232,800 = 25,608) — should be fully deducted
    assert it["pension_deduction"] == 24_000, \
        f"Expected full pension deduction 24,000, got {it['pension_deduction']}"

    # KH deposit (20,400) > IT deduction ceiling (13,203) — should be capped
    assert it["kh_deduction"] <= 13_203 + 1, \
        f"KH deduction {it['kh_deduction']} exceeds 13,203 cap"

    # Taxable income should be less than revenue (deductions applied)
    assert it["taxable_income"] < 300_000, "Taxable income should be less than gross revenue"

    # Effective rate: at 300k with savings, expect 15–35%
    assert 10 < s["effective_total_rate_pct"] < 40, \
        f"Effective rate {s['effective_total_rate_pct']:.1f}% outside expected 10–40% range"

    # spendable_cash_net should be less than net_cash_after_taxes (pension+KH not free cash)
    assert s["spendable_cash_net"] < s["net_cash_after_taxes"], \
        "spendable_cash must be less than economic net when savings deposits > 0"

    print(f"  PASS  rate={s['effective_total_rate_pct']:.1f}%  "
          f"IT=₪{s['net_income_tax']:,.0f}  NI=₪{s['total_ni_health']:,.0f}  "
          f"spendable=₪{s['spendable_cash_net']:,.0f}")


# ─────────────────────────────────────────────
# CASE 2 — 20,000/month, no deductions at all
# ─────────────────────────────────────────────
def test_case_2_20k_clean():
    r = _run(annual_revenue=240_000)
    s, it = r["summary"], r["income_tax"]

    # With no expenses/pension/KH: taxable = revenue - 52%*NI deduction only
    expected_taxable = 240_000 - it["ni_deduction_52pct"]
    assert abs(it["taxable_income"] - expected_taxable) < 1, \
        f"Taxable income {it['taxable_income']:,.0f} != expected {expected_taxable:,.0f}"

    # spendable == economic net (no savings deposits)
    assert abs(s["spendable_cash_net"] - s["net_cash_after_taxes"]) < 1, \
        "Without pension/KH, spendable == economic net"

    # Effective rate: ~18–30% for 240k
    assert 15 < s["effective_total_rate_pct"] < 35, \
        f"Effective rate {s['effective_total_rate_pct']:.1f}% off for 240k clean income"

    print(f"  PASS  rate={s['effective_total_rate_pct']:.1f}%  "
          f"IT=₪{s['net_income_tax']:,.0f}  NI=₪{s['total_ni_health']:,.0f}")


# ─────────────────────────────────────────────
# CASE 3 — 300,000 annual revenue, murshe, verify bracket and VAT
# ─────────────────────────────────────────────
def test_case_3_300k_murshe():
    r = _run(annual_revenue=300_000, vat="murshe")
    s, it, vat = r["summary"], r["income_tax"], r["vat"]

    # VAT should be active
    assert vat["status"] == "murshe"
    assert vat["output_vat"] == round(300_000 * 0.18, 2), "Output VAT = revenue × 18%"
    assert vat["vat_payable"] > 0

    # Credits reduce gross tax
    assert it["net_income_tax"] < it["gross_tax_before_credits"]

    # Income/NI tax should total to meaningful effective rate (>20% at 300k)
    assert s["effective_total_rate_pct"] > 18, \
        f"Rate {s['effective_total_rate_pct']:.1f}% seems too low for 300k"

    print(f"  PASS  rate={s['effective_total_rate_pct']:.1f}%  "
          f"VAT_payable=₪{vat['vat_payable']:,.0f}  IT=₪{s['net_income_tax']:,.0f}")


# ─────────────────────────────────────────────
# CASE 4 — High expenses: should not produce suspiciously low income tax
# ─────────────────────────────────────────────
def test_case_4_high_expenses_sanity():
    # 300k revenue, 200k in fully-deductible expenses
    # Net income for NI = 100k. NI = ~7.7k on tier1 + ~1.4k tier2 ≈ 9.1k
    # 52% deduction ≈ 4.7k. Taxable ≈ 95.3k.
    # IT on 95k ≈ 8.4k (10%) + 1.6k (14%) - 6.5k credits ≈ 3.5k
    r = _run(
        annual_revenue=300_000,
        expenses=[{"category": "other_fully_deductible", "gross_amount": 200_000,
                   "has_vat_invoice": False}],
        vat="patur",
    )
    s, it = r["summary"], r["income_tax"]

    # Taxable income must be positive (deductions can't go negative)
    assert it["taxable_income"] > 0, "Taxable income should be positive (100k net income)"

    assert s["net_income_tax"] >= 0

    # Effective total rate should be < 30% (high expense, low net)
    assert s["effective_total_rate_pct"] < 30, \
        f"Effective rate {s['effective_total_rate_pct']:.1f}% too high for 100k net"

    print(f"  PASS  taxable=₪{it['taxable_income']:,.0f}  "
          f"IT=₪{s['net_income_tax']:,.0f}  "
          f"rate={s['effective_total_rate_pct']:.1f}%")


# ─────────────────────────────────────────────
# CASE 5 — NI ordering sanity: effective rate at 500k should be substantial
# ─────────────────────────────────────────────
def test_case_5_ni_deduction_ordering():
    r = _run(annual_revenue=500_000)
    s, it, ni = r["summary"], r["income_tax"], r["ni"]

    # NI deduction must not exceed total NI paid (52% can't exceed 100%)
    assert it["ni_deduction_52pct"] <= ni["total_ni_health"] + 1, \
        f"52% NI deduction {it['ni_deduction_52pct']:,.0f} exceeds total NI {ni['total_ni_health']:,.0f}"

    # At 500k, effective rate should be well above 25%
    assert s["effective_total_rate_pct"] > 25, \
        f"Effective rate {s['effective_total_rate_pct']:.1f}% too low for 500k revenue"

    # Taxable income should be > 0
    assert it["taxable_income"] > 0

    # Gross tax should exceed credits (500k income, credits only ~6.5k)
    assert it["gross_tax_before_credits"] > it["credit_points_reduction"]

    print(f"  PASS  rate={s['effective_total_rate_pct']:.1f}%  "
          f"IT=₪{s['net_income_tax']:,.0f}  NI=₪{s['total_ni_health']:,.0f}  "
          f"NI_deduction=₪{it['ni_deduction_52pct']:,.0f}")


# ─────────────────────────────────────────────
# CASE 6 — VAT status must not affect IT or NI
# ─────────────────────────────────────────────
def test_case_6_vat_isolation():
    r_patur  = _run(annual_revenue=100_000, vat="patur")
    r_murshe = _run(annual_revenue=100_000, vat="murshe")

    it_diff = abs(r_patur["summary"]["net_income_tax"] - r_murshe["summary"]["net_income_tax"])
    ni_diff = abs(r_patur["summary"]["total_ni_health"] - r_murshe["summary"]["total_ni_health"])

    assert it_diff < 1, f"IT differs by {it_diff:.0f} between patur/murshe with no expenses"
    assert ni_diff < 1, f"NI differs by {ni_diff:.0f} between patur/murshe"

    assert r_patur["vat"]["vat_payable"] == 0
    assert r_murshe["vat"]["vat_payable"] > 0

    print(f"  PASS  IT_patur=₪{r_patur['summary']['net_income_tax']:,.0f}  "
          f"IT_murshe=₪{r_murshe['summary']['net_income_tax']:,.0f}  (match)")


# ─────────────────────────────────────────────
# CASE 7 — Credit points reduce tax by exact expected amount
# ─────────────────────────────────────────────
def test_case_7_credit_points_exact():
    r_std  = _run(annual_revenue=200_000, credit_points=2.25)
    r_high = _run(annual_revenue=200_000, credit_points=4.25)

    it_std  = r_std["summary"]["net_income_tax"]
    it_high = r_high["summary"]["net_income_tax"]
    expected_diff = (4.25 - 2.25) * CREDIT_POINT_ANNUAL  # 2 points × annual value

    actual_diff = it_std - it_high
    assert actual_diff > 0, "More credit points must reduce tax"
    assert abs(actual_diff - expected_diff) < 1, \
        f"Credit reduction {actual_diff:.0f} != expected {expected_diff:.0f}"

    print(f"  PASS  IT_std=₪{it_std:,.0f}  IT_high=₪{it_high:,.0f}  "
          f"diff=₪{actual_diff:,.0f}  expected=₪{expected_diff:,.0f}")


# ─────────────────────────────────────────────
# RUNNER
# ─────────────────────────────────────────────
TESTS = [
    ("25k/month with pension+KH",         test_case_1_25k_monthly),
    ("20k/month clean no deductions",      test_case_2_20k_clean),
    ("300k murshe VAT mechanics",          test_case_3_300k_murshe),
    ("High expenses sanity check",         test_case_4_high_expenses_sanity),
    ("NI deduction ordering at 500k",      test_case_5_ni_deduction_ordering),
    ("VAT isolation from IT/NI",           test_case_6_vat_isolation),
    ("Credit points exact reduction",      test_case_7_credit_points_exact),
]

if __name__ == "__main__":
    print(f"\nIsrael Tax Calculator — Validation Suite ({len(TESTS)} tests)\n{'─'*60}")
    passed, failed = 0, []
    for name, fn in TESTS:
        print(f"[{name}]")
        try:
            fn()
            passed += 1
        except (AssertionError, Exception) as e:
            print(f"  FAIL  {e}")
            failed.append(name)
    print(f"\n{'─'*60}")
    if failed:
        print(f"FAILED {len(failed)}/{len(TESTS)}: {failed}")
        sys.exit(1)
    else:
        print(f"All {passed}/{len(TESTS)} tests passed ✓")
