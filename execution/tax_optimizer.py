#!/usr/bin/env python3
"""
Israel Self-Employed Tax Optimizer — 2026
Generates optimization recommendations by diffing baseline vs. improved scenarios.

Usage:
    python tax_optimizer.py --annual-revenue 360000 --expenses expenses.json
    python tax_optimizer.py --annual-revenue 200000 --keren-hishtalmut 5000 --report
"""

import argparse
import json
import sys
import os
from copy import deepcopy
from datetime import date

# Import calculator from the same directory
sys.path.insert(0, os.path.dirname(__file__))
from tax_calculator import (
    run_calculation,
    load_expenses,
    VALID_CATEGORIES,
    KH_CGT_EXEMPT_CEILING,
    KH_DEDUCTION_RATE,
    KH_INCOME_CEILING_FOR_DED,
    PENSION_INCOME_CEILING,
    PENSION_DEDUCTION_RATE,
    PENSION_CREDIT_RATE,
    OSEK_PATUR_CEILING,
)


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _total_tax(result: dict) -> float:
    """Total income tax + NI (excludes VAT as it's a pass-through)."""
    return result["summary"]["total_tax_burden_excl_vat"]


def _net_saving(baseline: dict, improved: dict) -> float:
    """How much less tax is paid in the improved scenario."""
    return round(_total_tax(baseline) - _total_tax(improved), 2)


def _calc_marginal_rate(taxable_income: float) -> float:
    """Return the marginal income tax rate at a given taxable income level."""
    from tax_calculator import INCOME_TAX_BRACKETS
    for lower, upper, rate in reversed(INCOME_TAX_BRACKETS):
        if taxable_income > lower:
            return rate
    return 0.10


def _has_category(expenses: list, *categories) -> bool:
    cats = {e.get("category") for e in expenses}
    return any(c in cats for c in categories)


def _run(inputs: dict, **overrides) -> dict:
    """Run calculation with optional overrides."""
    inp = deepcopy(inputs)
    inp.update(overrides)
    return run_calculation(inp)


# ─────────────────────────────────────────────
# INDIVIDUAL OPTIMIZATION CHECKS
# ─────────────────────────────────────────────

def check_keren_hishtalmut(inputs: dict, baseline: dict) -> dict:
    """Recommend increasing Keren Hishtalmut deposit to optimal level."""
    current_dep = inputs.get("kh_deposit", 0.0)
    revenue = inputs["annual_revenue"]

    # Optimal: max of both benefits
    optimal_dep = min(KH_CGT_EXEMPT_CEILING, revenue)  # can't deposit more than revenue
    if current_dep >= optimal_dep - 1:
        return None

    improved = _run(inputs, kh_deposit=optimal_dep)
    saving = _net_saving(baseline, improved)

    if saving < 1:
        return None

    additional = optimal_dep - current_dep
    return {
        "id": "keren_hishtalmut_max",
        "priority": 1,
        "action": (
            f"הגדל הפקדה לקרן השתלמות מ-{current_dep:,.0f} ₪ ל-{optimal_dep:,.0f} ₪ "
            f"(תוספת: {additional:,.0f} ₪)"
        ),
        "annual_tax_saving": saving,
        "additional_deposit": round(additional, 2),
        "effort": "low",
        "deadline": "31 דצמבר",
        "notes": (
            f"ניכוי IT עד {min(13203, revenue * KH_DEDUCTION_RATE):,.0f} ₪. "
            f"הפקדה עד {KH_CGT_EXEMPT_CEILING:,.0f} ₪ פטורה ממס רווח הון בעת משיכה (לאחר 6 שנים). "
            f"ניתן להפקיד בכל חברת ביטוח/בית השקעות."
        ),
    }


def check_pension(inputs: dict, baseline: dict) -> dict:
    """Recommend increasing pension deposit to maximize tax benefit."""
    current_dep = inputs.get("pension_deposit", 0.0)
    revenue = inputs["annual_revenue"]

    eligible_income = min(revenue, PENSION_INCOME_CEILING)
    max_deduction = eligible_income * PENSION_DEDUCTION_RATE  # 11%
    max_credit_base = eligible_income * PENSION_CREDIT_RATE   # 5.5%
    optimal_dep = max_deduction + max_credit_base             # total for max benefit

    if current_dep >= optimal_dep - 1:
        return None

    improved = _run(inputs, pension_deposit=optimal_dep)
    saving = _net_saving(baseline, improved)

    if saving < 1:
        return None

    return {
        "id": "pension_max",
        "priority": 1,
        "action": (
            f"הגדל הפקדה לפנסיה מ-{current_dep:,.0f} ₪ ל-{optimal_dep:,.0f} ₪ "
            f"(מקסימום הטבה: ניכוי {max_deduction:,.0f} ₪ + זיכוי על {max_credit_base:,.0f} ₪)"
        ),
        "annual_tax_saving": saving,
        "additional_deposit": round(optimal_dep - current_dep, 2),
        "effort": "low",
        "deadline": "31 דצמבר",
        "notes": (
            f"ניכוי: 11% מהכנסה (עד {PENSION_INCOME_CEILING:,.0f} ₪). "
            f"זיכוי: 35% על 5.5% מהכנסה. "
            f"חשוב: הפנסיה לא מפחיתה את בסיס הביטוח הלאומי."
        ),
    }


def check_missing_car(inputs: dict, baseline: dict) -> dict:
    """If no car expenses — flag potential saving."""
    if _has_category(inputs.get("expenses", []), "car"):
        return None

    revenue = inputs["annual_revenue"]
    # Estimate: typical car costs ~1,500/month = 18,000/year
    est_monthly = 1_500
    est_annual = est_monthly * 12
    fake_expenses = deepcopy(inputs.get("expenses", []))
    fake_expenses.append({"category": "car", "gross_amount": est_annual, "has_vat_invoice": True,
                          "description": "הוצאות רכב משוערות"})

    improved = _run(inputs, expenses=fake_expenses)
    saving = _net_saving(baseline, improved)

    if saving < 500:
        return None

    return {
        "id": "missing_car",
        "priority": 2,
        "action": "תעד הוצאות רכב — לא הזנת הוצאות רכב",
        "annual_tax_saving": saving,
        "notes": (
            f"הוצאות רכב פרטי מוכרות ב-45% למס הכנסה ו-66% מע\"מ. "
            f"הערכה: {est_annual:,} ₪/שנה (דלק, ביטוח, טיפולים, פחת) → חיסכון משוער {saving:,.0f} ₪. "
            f"שמור קבלות — כולל מילוי דו\"ח נסיעות לחיזוק הניכוי."
        ),
        "effort": "medium",
        "estimated_annual_expense": est_annual,
    }


def check_missing_phone(inputs: dict, baseline: dict) -> dict:
    """If no phone expenses — flag."""
    if _has_category(inputs.get("expenses", []), "mobile_phone"):
        return None

    est_annual = 2_400  # ~200/month, 50% deductible = 1,200
    fake_expenses = deepcopy(inputs.get("expenses", []))
    fake_expenses.append({"category": "mobile_phone", "gross_amount": est_annual,
                          "has_vat_invoice": True, "description": "טלפון נייד משוער"})

    improved = _run(inputs, expenses=fake_expenses)
    saving = _net_saving(baseline, improved)

    if saving < 100:
        return None

    return {
        "id": "missing_phone",
        "priority": 3,
        "action": "תעד הוצאות טלפון נייד — לא הזנת",
        "annual_tax_saving": saving,
        "notes": (
            f"50% ממנוי/חשבון טלפון מוכרים למס הכנסה (מקסימום 1,200 ₪ ניכוי שנתי כולל פחת מכשיר). "
            f"66% מע\"מ ניתן לקיזוז (עוסק מורשה). חיסכון משוער: {saving:,.0f} ₪."
        ),
        "effort": "low",
    }


def check_missing_professional_dev(inputs: dict, baseline: dict) -> dict:
    """Suggest courses/professional development."""
    if _has_category(inputs.get("expenses", []), "courses"):
        return None

    est_annual = 5_000
    fake_expenses = deepcopy(inputs.get("expenses", []))
    fake_expenses.append({"category": "courses", "gross_amount": est_annual,
                          "has_vat_invoice": True, "description": "קורסים/השתלמויות"})

    improved = _run(inputs, expenses=fake_expenses)
    saving = _net_saving(baseline, improved)

    if saving < 200:
        return None

    return {
        "id": "professional_dev",
        "priority": 3,
        "action": "השקע בקורסים/השתלמות — 100% מוכר ומפחית מס",
        "annual_tax_saving": saving,
        "notes": (
            "קורסים מקצועיים, ספרות מקצועית, כנסים — 100% מוכר למס הכנסה ומע\"מ. "
            f"השקעה של {est_annual:,} ₪ בהשתלמות תחסוך ~{saving:,.0f} ₪ במס."
        ),
        "effort": "low",
        "estimated_annual_expense": est_annual,
    }


def check_home_office(inputs: dict, baseline: dict) -> dict:
    """Check if home office expenses could be improved."""
    home_cats = {"home_office_rent", "home_electricity", "home_arnona", "home_internet"}
    if _has_category(inputs.get("expenses", []), *home_cats):
        return None  # Already claiming home office

    revenue = inputs["annual_revenue"]
    ratio = inputs.get("home_office_ratio", 0.25)

    # Estimate typical rent 6,000/month + electricity 300/month + arnona 400/month
    est_rent = 72_000
    est_electricity = 3_600
    est_arnona = 4_800
    fake_expenses = deepcopy(inputs.get("expenses", []))
    fake_expenses.extend([
        {"category": "home_office_rent", "gross_amount": est_rent, "description": "שכירות"},
        {"category": "home_electricity", "gross_amount": est_electricity, "description": "חשמל"},
        {"category": "home_arnona", "gross_amount": est_arnona, "description": "ארנונה"},
    ])

    improved = _run(inputs, expenses=fake_expenses)
    saving = _net_saving(baseline, improved)

    if saving < 500:
        return None

    deductible_rent = est_rent * ratio
    return {
        "id": "home_office",
        "priority": 2,
        "action": f"תבע הוצאות משרד בבית — לא הזנת (יחס {ratio:.0%})",
        "annual_tax_saving": saving,
        "notes": (
            f"אם אתה עובד מהבית, ניתן לנכות {ratio:.0%} משכירות/ארנונה/חשמל/אינטרנט. "
            f"עבור חדר עבודה בדירת 4 חדרים = 25% מ-{est_rent:,} ₪ שכירות = "
            f"{deductible_rent:,.0f} ₪ ניכוי שנתי. "
            f"יש לתעד את שטח חדר העבודה ביחס לדירה."
        ),
        "effort": "medium",
    }


def check_hardware_timing(inputs: dict, baseline: dict) -> dict:
    """Q4 reminder: buy hardware before year-end for immediate VAT recovery."""
    today = date.today()
    if today.month < 10:  # Only relevant in Q4
        return None

    if _has_category(inputs.get("expenses", []), "computer_hardware"):
        return None

    vat_status = baseline["inputs"]["vat_status"]
    if vat_status != "murshe":
        return None

    return {
        "id": "hardware_timing",
        "priority": 2,
        "action": "Q4: רכוש ציוד מחשוב לפני 31 דצמבר לקבלת מע\"מ מלא השנה",
        "annual_tax_saving": None,  # depends on purchase amount
        "notes": (
            "ציוד מחשוב (מחשב, מסך, עכבר, מדפסת) — 100% מע\"מ מוחזר בשנת הרכישה. "
            "ניכוי IT: 33.33% לשנה (על פני 3 שנים). "
            "רכישה לפני 31.12 מספקת את החזר המע\"מ של 18% מהמחיר השנה."
        ),
        "effort": "low",
    }


def check_vat_threshold(inputs: dict, baseline: dict) -> dict:
    """Warn if approaching or exceeding Osek Patur ceiling."""
    revenue = inputs["annual_revenue"]

    if revenue >= OSEK_PATUR_CEILING:
        return None  # Already murshe

    if revenue < OSEK_PATUR_CEILING * 0.73:  # Not near threshold
        return None

    proximity_pct = (revenue / OSEK_PATUR_CEILING) * 100

    return {
        "id": "vat_threshold_warning",
        "priority": 1,
        "action": f"⚠️  קרוב לתקרת עוסק פטור — {revenue:,.0f} ₪ ({proximity_pct:.0f}% מ-{OSEK_PATUR_CEILING:,.0f} ₪)",
        "annual_tax_saving": None,
        "notes": (
            f"תקרת עוסק פטור היא {OSEK_PATUR_CEILING:,.0f} ₪. "
            "חצייה של התקרה חייבת ברישום כעוסק מורשה תוך 30 יום. "
            "מעבר לעוסק מורשה: מוסיף 18% למחיר ללקוחות פרטיים, "
            "אך מאפשר קיזוז מע\"מ תשומות. "
            "תכנן מראש עם רואה חשבון."
        ),
        "effort": "high",
    }


def check_business_gifts(inputs: dict, baseline: dict) -> dict:
    """Year-end: business gifts up to 230 NIS per recipient are deductible."""
    today = date.today()
    if today.month < 11:
        return None

    if _has_category(inputs.get("expenses", []), "business_gifts"):
        return None

    return {
        "id": "business_gifts",
        "priority": 3,
        "action": "סוף שנה: מתנות עסקיות — עד 230 ₪ לנמען מוכרות",
        "annual_tax_saving": None,
        "notes": (
            "מתנות עסקיות עד 230 ₪ לנמען לשנה מוכרות למס הכנסה. "
            "אין החזר מע\"מ על מתנות עסקיות. "
            "תעד: שם הנמען, תאריך, קשר עסקי."
        ),
        "effort": "low",
    }


# ─────────────────────────────────────────────
# MAIN OPTIMIZER
# ─────────────────────────────────────────────

def generate_recommendations(inputs: dict) -> dict:
    baseline = run_calculation(inputs)

    checks = [
        check_vat_threshold,
        check_keren_hishtalmut,
        check_pension,
        check_missing_car,
        check_home_office,
        check_missing_phone,
        check_hardware_timing,
        check_missing_professional_dev,
        check_business_gifts,
    ]

    recommendations = []
    for check_fn in checks:
        rec = check_fn(inputs, baseline)
        if rec:
            recommendations.append(rec)

    # Sort: priority asc, then by saving desc
    def sort_key(r):
        saving = r.get("annual_tax_saving") or 0
        return (r.get("priority", 9), -saving)

    recommendations.sort(key=sort_key)

    # Build optimized scenario: apply all quantified recommendations
    optimized_inputs = deepcopy(inputs)
    for rec in recommendations:
        rid = rec["id"]
        if rid == "keren_hishtalmut_max":
            optimized_inputs["kh_deposit"] = float(rec["additional_deposit"]) + inputs.get("kh_deposit", 0)
        elif rid == "pension_max":
            optimized_inputs["pension_deposit"] = float(rec["additional_deposit"]) + inputs.get("pension_deposit", 0)
        elif rid in ("missing_car", "missing_phone", "professional_dev", "home_office"):
            # Already added fake expenses to get saving estimate — replicate here
            pass  # The saving estimate used fake_expenses; for optimized_scenario we skip re-adding

    optimized = run_calculation(optimized_inputs)
    total_saving = sum(r["annual_tax_saving"] for r in recommendations if r.get("annual_tax_saving"))

    return {
        "baseline": baseline,
        "recommendations": recommendations,
        "optimized_scenario": optimized,
        "total_quantified_saving": round(total_saving, 2),
    }


# ─────────────────────────────────────────────
# HUMAN-READABLE REPORT
# ─────────────────────────────────────────────

def print_report(result: dict) -> None:
    baseline = result["baseline"]
    recs = result["recommendations"]
    total_saving = result["total_quantified_saving"]

    print(f"\n{'═' * 60}")
    print(f"  🎯 דוח המלצות אופטימיזציה מס — {baseline['tax_year']}")
    print(f"{'═' * 60}")

    s = baseline["summary"]
    print(f"\n📊 מצב נוכחי (baseline):")
    print(f"  הכנסה ברוטו:       {s['gross_revenue']:,.0f} ₪")
    print(f"  מס הכנסה:          {s['net_income_tax']:,.0f} ₪")
    print(f"  ביטוח לאומי:       {s['total_ni_health']:,.0f} ₪")
    print(f"  סה\"כ מס:           {s['total_tax_burden_excl_vat']:,.0f} ₪  ({s['effective_total_rate_pct']:.1f}%)")

    if not recs:
        print("\n✅ לא נמצאו הזדמנויות אופטימיזציה משמעותיות. כל הכבוד!")
        return

    print(f"\n💡 המלצות ({len(recs)}):")
    print(f"{'─' * 60}")

    for i, rec in enumerate(recs, 1):
        saving_str = f"חיסכון: {rec['annual_tax_saving']:,.0f} ₪/שנה" if rec.get("annual_tax_saving") else "חיסכון: לפי סכום"
        priority_icon = {1: "🔴", 2: "🟡", 3: "🟢"}.get(rec["priority"], "⚪")
        print(f"\n{i}. {priority_icon} {rec['action']}")
        print(f"   📈 {saving_str}")
        print(f"   💬 {rec['notes']}")
        if rec.get("deadline"):
            print(f"   ⏰ דד-ליין: {rec['deadline']}")

    print(f"\n{'─' * 60}")
    if total_saving > 0:
        optimized_s = result["optimized_scenario"]["summary"]
        print(f"💰 פוטנציאל חיסכון מוסכם: {total_saving:,.0f} ₪/שנה")
        print(f"   לאחר אופטימיזציה — מס אפקטיבי: {optimized_s['effective_total_rate_pct']:.1f}%")
    print(f"{'═' * 60}\n")


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Israel Self-Employed Tax Optimizer 2026 — Generates recommendations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tax_optimizer.py --annual-revenue 200000 --report
  python tax_optimizer.py --annual-revenue 360000 --expenses expenses.json --keren-hishtalmut 5000 --report
        """,
    )
    p.add_argument("--annual-revenue", type=float, required=True)
    p.add_argument("--expenses", type=str, default="[]")
    p.add_argument("--credit-points", type=float, default=2.25)
    p.add_argument("--pension", type=float, default=0.0)
    p.add_argument("--keren-hishtalmut", type=float, default=0.0)
    p.add_argument("--vat-status", choices=["auto", "patur", "murshe"], default="auto")
    p.add_argument("--home-office-ratio", type=float, default=0.25)
    p.add_argument("--report", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()

    try:
        expenses = load_expenses(args.expenses)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"Error loading expenses: {e}", file=sys.stderr)
        sys.exit(1)

    inputs = {
        "annual_revenue":       args.annual_revenue,
        "expenses":             expenses,
        "credit_points":        args.credit_points,
        "pension_deposit":      args.pension,
        "kh_deposit":           args.keren_hishtalmut,
        "vat_status_override":  args.vat_status,
        "home_office_ratio":    args.home_office_ratio,
    }

    result = generate_recommendations(inputs)

    if args.report:
        print_report(result)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
