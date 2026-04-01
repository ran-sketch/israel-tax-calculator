#!/usr/bin/env python3
"""
Israel Self-Employed Tax Calculator — 2026
Deterministic calculation engine. No external dependencies.

Usage:
    python tax_calculator.py --annual-revenue 360000 --expenses expenses.json --report
    python tax_calculator.py --annual-revenue 80000 --expenses '[{"category":"mobile_phone","gross_amount":3600}]'

All monetary amounts in NIS. Revenue should be ex-VAT if you are Osek Murshe.
"""

import argparse
import json
import sys
from copy import deepcopy

# ─────────────────────────────────────────────
# CONSTANTS — 2026 Tax Year
# ─────────────────────────────────────────────

TAX_YEAR = 2026

# Income Tax Brackets (annual thresholds, NIS)
# Key 2026 change: 20% bracket expanded to 228,000 (19,000/month)
# compared to 193,800 (16,150/month) in 2025.
INCOME_TAX_BRACKETS = [
    (0,       84_120,  0.10),
    (84_120,  120_720, 0.14),
    (120_720, 228_000, 0.20),   # EXPANDED in 2026
    (228_000, 301_200, 0.31),
    (301_200, 560_280, 0.35),
    (560_280, 721_560, 0.47),
    (721_560, float("inf"), 0.50),  # 47% + 3% mas yasaf
]

# Credit points
CREDIT_POINT_MONTHLY = 242.0        # NIS per point per month
CREDIT_POINT_ANNUAL = CREDIT_POINT_MONTHLY * 12  # 2,904 NIS

# Bituach Leumi + Health Insurance (self-employed, ages 18–retirement)
NI_TIER1_MONTHLY_CAP = 7_703.0      # threshold between tier 1 and tier 2 (monthly)
NI_TIER1_ANNUAL_CAP  = NI_TIER1_MONTHLY_CAP * 12   # 92,436

NI_MIN_MONTHLY  = 3_442.0           # minimum income base for NI
NI_MAX_MONTHLY  = 51_910.0          # maximum income base for NI
NI_MIN_ANNUAL   = NI_MIN_MONTHLY * 12   # 41,304
NI_MAX_ANNUAL   = NI_MAX_MONTHLY * 12   # 622,920

# Rates: (ni_rate, health_rate) per tier
NI_TIER1_NI_RATE     = 0.0447
NI_TIER1_HEALTH_RATE = 0.0323
NI_TIER1_TOTAL       = NI_TIER1_NI_RATE + NI_TIER1_HEALTH_RATE  # 0.077

NI_TIER2_NI_RATE     = 0.1283
NI_TIER2_HEALTH_RATE = 0.0517
NI_TIER2_TOTAL       = NI_TIER2_NI_RATE + NI_TIER2_HEALTH_RATE  # 0.18

# 52% of total NI+health is deductible for income tax (Section 47, Income Tax Ordinance)
NI_DEDUCTIBLE_FRACTION = 0.52

# VAT
VAT_RATE = 0.18
OSEK_PATUR_CEILING = 122_833.0      # annual revenue threshold — verify annually with ITA

# Pension (self-employed)
PENSION_INCOME_CEILING = 232_800.0  # verify for 2026 — adjusted annually
PENSION_DEDUCTION_RATE = 0.11       # 11% of eligible income is deductible
PENSION_CREDIT_RATE    = 0.055      # 5.5% → 35% credit
PENSION_CREDIT_TAX_RATE = 0.35

# Keren Hishtalmut (self-employed)
KH_DEDUCTION_CEILING      = 13_203.0    # max annual IT deduction — verify for 2026
KH_DEDUCTION_RATE         = 0.045       # 4.5% of income
KH_INCOME_CEILING_FOR_DED = KH_DEDUCTION_CEILING / KH_DEDUCTION_RATE  # 293,400
KH_CGT_EXEMPT_CEILING     = 20_566.0    # max annual deposit qualifying for CGT exemption

# ─────────────────────────────────────────────
# ENGINE AUDIT — what is deterministic vs estimated
# ─────────────────────────────────────────────
# DETERMINISTIC (exact per current constants):
#   income tax progressive brackets, credit point reduction,
#   VAT pass-through, KH cap logic, expense partial-deduction rules
#
# SIMPLIFIED APPROXIMATION (labeled in assumptions output):
#   NI base: uses revenue minus IT-deductible expenses as proxy for
#            "net business income" per NI law — close but not exact
#   Pension/KH eligible income: uses gross revenue; may overstate by ~expenses*rate
#            for high-expense businesses (usually bounded by ceiling anyway)
#
# CONDITIONAL ON MISSING PROFILE DATA (not implemented, flagged):
#   Exact pension benefit if other income sources exist
#   NI exemptions (disability, age, maternity)
#   Municipal tax (arnona) exact deduction if multiple business uses
#   Partnership / multiple businesses
#
# CONSTANTS TO VERIFY ANNUALLY WITH OFFICIAL ITA:
#   CREDIT_POINT_MONTHLY, NI thresholds, OSEK_PATUR_CEILING,
#   PENSION_INCOME_CEILING, KH_DEDUCTION_CEILING

# ─────────────────────────────────────────────
# EXPENSE RULES
# ─────────────────────────────────────────────
# it_pct: fraction of expense deductible for income tax
# vat_pct: fraction of input VAT recoverable
# room_ratio: if True, use home_office_ratio instead of it_pct/vat_pct
# depreciation: if True, it_pct is applied per-year (33.33% over 3 years),
#               but full VAT is recovered in year of purchase
# gift_cap_per_recipient: per-recipient annual cap in NIS

EXPENSE_RULES = {
    "car": {
        "it_pct": 0.45,
        "vat_pct": 0.66,
        "label": "רכב פרטי (≤3.5t)",
    },
    "mobile_phone": {
        "it_pct": 0.50,
        "vat_pct": 0.66,
        "label": "טלפון נייד",
        # Note: max 1,200 NIS/year IT deduction incl. depreciation.
        # We apply the 50% rule; caller should cap total phone expense input at 2,400/yr if using this cap.
    },
    "home_office_rent": {
        "it_pct": None,  # set to home_office_ratio at runtime
        "vat_pct": None,
        "room_ratio": True,
        "label": "שכירות משרד בבית",
    },
    "home_electricity": {
        "it_pct": None,
        "vat_pct": None,
        "room_ratio": True,
        "label": "חשמל (בית)",
    },
    "home_arnona": {
        "it_pct": None,
        "vat_pct": None,
        "room_ratio": True,
        "label": "ארנונה (בית)",
    },
    "home_internet": {
        "it_pct": None,
        "vat_pct": None,
        "room_ratio": True,
        "label": "אינטרנט (בית)",
    },
    "office_internet": {
        "it_pct": 1.00,
        "vat_pct": 1.00,
        "label": "אינטרנט (משרד)",
    },
    "meals_entertainment": {
        "it_pct": 0.80,
        "vat_pct": 0.00,  # No VAT recovery on meals
        "label": "כיבוד / אירוח עסקי",
    },
    "professional_services": {
        "it_pct": 1.00,
        "vat_pct": 1.00,
        "label": "שירותים מקצועיים (רו\"ח, עו\"ד, יועץ)",
    },
    "computer_hardware": {
        "it_pct": 1.0 / 3.0,  # 33.33% per year depreciation
        "vat_pct": 1.00,       # 100% VAT recovery in purchase year
        "depreciation": True,
        "label": "ציוד מחשוב / חומרה",
    },
    "software": {
        "it_pct": 1.00,
        "vat_pct": 1.00,
        "label": "תוכנות / מנויים",
    },
    "advertising": {
        "it_pct": 1.00,
        "vat_pct": 1.00,
        "label": "פרסום / שיווק",
    },
    "courses": {
        "it_pct": 1.00,
        "vat_pct": 1.00,
        "label": "קורסים / השתלמויות",
    },
    "business_insurance": {
        "it_pct": 1.00,
        "vat_pct": 1.00,
        "label": "ביטוח עסקי",
    },
    "office_rent": {
        "it_pct": 1.00,
        "vat_pct": 1.00,
        "label": "שכירות משרד חיצוני",
    },
    "business_gifts": {
        "it_pct": None,  # special logic: up to 230 NIS per recipient
        "vat_pct": 0.00,
        "gift_cap": 230.0,
        "label": "מתנות עסקיות",
    },
    "other_fully_deductible": {
        "it_pct": 1.00,
        "vat_pct": 1.00,
        "label": "הוצאה עסקית אחרת (100%)",
    },
}

VALID_CATEGORIES = set(EXPENSE_RULES.keys())


# ─────────────────────────────────────────────
# PURE CALCULATION FUNCTIONS
# ─────────────────────────────────────────────

def determine_vat_status(annual_revenue: float, override: str = "auto") -> str:
    """
    Returns 'patur' or 'murshe'.
    override: 'auto' (decide by revenue), 'patur', or 'murshe'.
    """
    if override in ("patur", "murshe"):
        return override
    return "patur" if annual_revenue < OSEK_PATUR_CEILING else "murshe"


def calc_expense_deductions(
    expenses: list,
    home_office_ratio: float,
    vat_status: str,
) -> dict:
    """
    Process each expense and compute:
    - it_deductible_amount: amount deductible for income tax
    - input_vat_recoverable: input VAT that can be offset (only for murshe)

    For Osek Murshe: IT deduction is on ex-VAT amount (gross / 1.18 if has_vat_invoice).
    For Osek Patur: IT deduction is on gross amount (VAT embedded, can't reclaim).
    """
    breakdown = []
    total_it_deductible = 0.0
    total_input_vat = 0.0
    total_actual_cash = 0.0

    for exp in expenses:
        category = exp.get("category", "")
        gross = float(exp.get("gross_amount", 0))
        has_vat_invoice = bool(exp.get("has_vat_invoice", True))
        recipient_count = int(exp.get("recipient_count", 1))
        description = exp.get("description", category)

        if category not in EXPENSE_RULES:
            breakdown.append({
                "description": description,
                "category": category,
                "gross_amount": gross,
                "it_deductible_amount": 0.0,
                "input_vat_recoverable": 0.0,
                "warning": f"Unknown category '{category}' — not deducted. Use one of: {sorted(VALID_CATEGORIES)}",
            })
            total_actual_cash += gross
            continue

        rule = EXPENSE_RULES[category]

        # Determine ex-VAT base for IT deduction
        if vat_status == "murshe" and has_vat_invoice:
            ex_vat_base = gross / (1 + VAT_RATE)
            vat_amount = gross - ex_vat_base
        else:
            # Patur or no invoice: gross is the cost basis for IT
            ex_vat_base = gross
            vat_amount = 0.0

        # ── Determine IT deduction ──
        if rule.get("room_ratio"):
            it_pct = home_office_ratio
        elif category == "business_gifts":
            # capped at gift_cap per recipient
            cap = rule["gift_cap"] * recipient_count
            it_pct = min(gross, cap) / gross if gross > 0 else 0.0
        else:
            it_pct = rule["it_pct"]

        it_deductible = ex_vat_base * it_pct

        # ── Determine VAT recovery ──
        vat_recoverable = 0.0
        if vat_status == "murshe" and has_vat_invoice and vat_amount > 0:
            vat_pct = home_office_ratio if rule.get("room_ratio") else rule.get("vat_pct", 0.0)
            vat_recoverable = vat_amount * vat_pct

        total_it_deductible += it_deductible
        total_input_vat += vat_recoverable
        total_actual_cash += gross

        breakdown.append({
            "description": description,
            "category": category,
            "label": rule.get("label", category),
            "gross_amount": round(gross, 2),
            "ex_vat_base": round(ex_vat_base, 2),
            "it_pct_applied": round(it_pct, 4),
            "it_deductible_amount": round(it_deductible, 2),
            "vat_amount": round(vat_amount, 2),
            "input_vat_recoverable": round(vat_recoverable, 2),
        })

    return {
        "total_it_deductible": round(total_it_deductible, 2),
        "total_input_vat_recoverable": round(total_input_vat, 2),
        "total_actual_cash": round(total_actual_cash, 2),
        "breakdown": breakdown,
    }


def calc_income_tax_progressive(taxable_income: float) -> float:
    """Progressive income tax before credit points."""
    if taxable_income <= 0:
        return 0.0
    tax = 0.0
    for lower, upper, rate in INCOME_TAX_BRACKETS:
        if taxable_income <= lower:
            break
        slice_top = min(taxable_income, upper)
        tax += (slice_top - lower) * rate
    return tax


def calc_ni(ni_base_annual: float) -> dict:
    """
    Bituach Leumi + Health Insurance for self-employed.
    Returns breakdown of NI, health, and deductible portion.
    """
    # Clamp to min/max
    ni_base_clamped = max(min(ni_base_annual, NI_MAX_ANNUAL), NI_MIN_ANNUAL)
    floored_from_minimum = ni_base_annual < NI_MIN_ANNUAL

    # Tier 1
    tier1_income = min(ni_base_clamped, NI_TIER1_ANNUAL_CAP)
    tier1_ni     = tier1_income * NI_TIER1_NI_RATE
    tier1_health = tier1_income * NI_TIER1_HEALTH_RATE
    tier1_total  = tier1_ni + tier1_health

    # Tier 2
    tier2_income = max(0.0, ni_base_clamped - NI_TIER1_ANNUAL_CAP)
    tier2_ni     = tier2_income * NI_TIER2_NI_RATE
    tier2_health = tier2_income * NI_TIER2_HEALTH_RATE
    tier2_total  = tier2_ni + tier2_health

    total_ni     = tier1_ni + tier2_ni
    total_health = tier1_health + tier2_health
    total_ni_health = total_ni + total_health
    ni_deductible = total_ni_health * NI_DEDUCTIBLE_FRACTION  # 52%

    return {
        "ni_base_reported": round(ni_base_annual, 2),
        "ni_base_applied":  round(ni_base_clamped, 2),
        "floored_to_minimum": floored_from_minimum,
        "tier1_income":    round(tier1_income, 2),
        "tier1_ni":        round(tier1_ni, 2),
        "tier1_health":    round(tier1_health, 2),
        "tier1_total":     round(tier1_total, 2),
        "tier2_income":    round(tier2_income, 2),
        "tier2_ni":        round(tier2_ni, 2),
        "tier2_health":    round(tier2_health, 2),
        "tier2_total":     round(tier2_total, 2),
        "total_ni":        round(total_ni, 2),
        "total_health":    round(total_health, 2),
        "total_ni_health": round(total_ni_health, 2),
        "ni_deductible_52pct": round(ni_deductible, 2),
    }


def calc_vat(annual_revenue: float, total_input_vat: float, vat_status: str) -> dict:
    """VAT payable calculation."""
    if vat_status == "patur":
        return {
            "status": "patur",
            "output_vat": 0.0,
            "input_vat_recoverable": 0.0,
            "vat_payable": 0.0,
            "note": "עוסק פטור — אינך גובה מע\"מ ואינך מחזיר מע\"מ תשומות",
        }
    output_vat = annual_revenue * VAT_RATE
    vat_payable = max(0.0, output_vat - total_input_vat)
    return {
        "status": "murshe",
        "output_vat": round(output_vat, 2),
        "input_vat_recoverable": round(total_input_vat, 2),
        "vat_payable": round(vat_payable, 2),
    }


def calc_pension_benefit(pension_deposit: float, annual_revenue: float) -> dict:
    """
    Pension IT benefit for self-employed.
    Returns: deduction amount (reduces taxable income) + credit amount (direct tax reduction).
    """
    eligible_income = min(annual_revenue, PENSION_INCOME_CEILING)
    max_deduction = eligible_income * PENSION_DEDUCTION_RATE   # 11%
    max_credit_base = eligible_income * PENSION_CREDIT_RATE    # 5.5%

    # If total deposit <= max_deduction + max_credit_base, all is beneficial
    # Deduction portion = min(deposit, max_deduction)
    # Credit portion = min(deposit - deduction_portion, max_credit_base)
    deduction_amount = min(pension_deposit, max_deduction)
    remaining_deposit = pension_deposit - deduction_amount
    credit_base_amount = min(remaining_deposit, max_credit_base)
    tax_credit = credit_base_amount * PENSION_CREDIT_TAX_RATE  # 35%

    return {
        "pension_deposit": round(pension_deposit, 2),
        "eligible_income": round(eligible_income, 2),
        "deduction_amount": round(deduction_amount, 2),
        "credit_base": round(credit_base_amount, 2),
        "tax_credit": round(tax_credit, 2),
        "max_optimal_deposit": round(max_deduction + max_credit_base, 2),
    }


def calc_kh_benefit(kh_deposit: float, annual_revenue: float) -> dict:
    """
    Keren Hishtalmut IT benefit for self-employed.
    Returns: deductible amount (reduces taxable income).
    """
    max_deductible = min(KH_DEDUCTION_CEILING, annual_revenue * KH_DEDUCTION_RATE)
    it_deduction = min(kh_deposit, max_deductible)
    cgt_exempt = kh_deposit <= KH_CGT_EXEMPT_CEILING

    return {
        "kh_deposit": round(kh_deposit, 2),
        "it_deduction": round(it_deduction, 2),
        "cgt_exempt_if_held_6yr": cgt_exempt,
        "cgt_exempt_ceiling": KH_CGT_EXEMPT_CEILING,
        "optimal_deposit_for_max_benefit": round(KH_CGT_EXEMPT_CEILING, 2),
        "note": (
            f"ניכוי מס הכנסה מוגבל ל-{KH_DEDUCTION_CEILING:,.0f} ₪ לשנה. "
            f"פטור ממס רווח הון על הפקדה עד {KH_CGT_EXEMPT_CEILING:,.0f} ₪ לשנה."
        ),
    }


# ─────────────────────────────────────────────
# MAIN ORCHESTRATOR
# ─────────────────────────────────────────────

def run_calculation(inputs: dict) -> dict:
    """
    Full tax calculation pipeline (canonical order per directives/tax_engine.md).
    inputs keys:
        annual_revenue          float (ex-VAT for murshe)
        expenses                list of expense dicts
        credit_points           float (default 2.25)
        pension_deposit         float (default 0)
        kh_deposit              float (default 0)
        vat_status_override     str (auto|patur|murshe, default auto)
        home_office_ratio       float (default 0.25)

    Returns two net figures in summary:
        net_cash_after_taxes  — economic net (pension/KH deposits still counted as yours)
        spendable_cash_net    — true spendable cash (all outflows including savings deposits)
    """
    revenue         = float(inputs.get("annual_revenue", 0))
    expenses        = inputs.get("expenses", [])
    credit_points   = float(inputs.get("credit_points", 2.25))
    pension_dep     = float(inputs.get("pension_deposit", 0))
    kh_dep          = float(inputs.get("kh_deposit", 0))
    vat_override    = inputs.get("vat_status_override", "auto")
    home_ratio      = float(inputs.get("home_office_ratio", 0.25))

    warnings = []

    # Step 1: VAT status
    vat_status = determine_vat_status(revenue, vat_override)

    # Step 2: Expense deductions
    exp_result = calc_expense_deductions(expenses, home_ratio, vat_status)
    it_deductible_expenses = exp_result["total_it_deductible"]
    total_input_vat        = exp_result["total_input_vat_recoverable"]
    total_actual_cash      = exp_result["total_actual_cash"]

    # Step 3: NI base = net business income (revenue minus IT-deductible expenses).
    # WHY: Israeli National Insurance Law (Section 345) assesses self-employed NI on
    # "net income from business" (parnasa netonet) = revenue minus business expenses.
    # SIMPLIFICATION: we use IT-deductible expense amounts as proxy — the sets overlap
    # closely. Pension/KH deposits do NOT reduce the NI base (only income tax).
    ni_base = max(0.0, revenue - it_deductible_expenses)
    ni_result = calc_ni(ni_base)
    ni_deductible = ni_result["ni_deductible_52pct"]

    if ni_result["floored_to_minimum"]:
        warnings.append({
            "code": "NI_FLOORED_TO_MINIMUM",
            "message": (
                f"Income is below NI minimum base (₪{NI_MIN_ANNUAL:,.0f}/yr). "
                "NI is charged on the minimum floor regardless."
            ),
        })

    # Step 4: Pension benefit
    # NOTE: eligible_income uses gross revenue as base (standard simplification).
    # For high-expense businesses this may slightly overstate the max deduction
    # by at most: it_deductible_expenses × 11%. Flagged below if material.
    pension_result = calc_pension_benefit(pension_dep, revenue)
    pension_deduction = pension_result["deduction_amount"]
    pension_credit    = pension_result["tax_credit"]

    if it_deductible_expenses > 0 and pension_dep > 0:
        overstate_risk = it_deductible_expenses * PENSION_DEDUCTION_RATE
        if overstate_risk > 500:
            warnings.append({
                "code": "PENSION_BASE_APPROXIMATION",
                "message": (
                    f"Pension max-deduction ceiling uses gross revenue. "
                    f"With ₪{it_deductible_expenses:,.0f} in deductible expenses, "
                    f"the ceiling may be overstated by up to ₪{overstate_risk:,.0f}. "
                    "Consult your accountant for exact pension base."
                ),
            })

    # Step 5: Keren Hishtalmut benefit
    kh_result = calc_kh_benefit(kh_dep, revenue)
    kh_deduction = kh_result["it_deduction"]

    # Step 6: Taxable income for IT
    # Order: revenue → expenses → pension deduction → KH deduction → 52% NI deduction
    taxable_income = max(0.0, revenue
                         - it_deductible_expenses
                         - pension_deduction
                         - kh_deduction
                         - ni_deductible)

    # Step 7: Income tax
    gross_tax     = calc_income_tax_progressive(taxable_income)
    credits_total = credit_points * CREDIT_POINT_ANNUAL + pension_credit
    net_income_tax = max(0.0, gross_tax - credits_total)

    # Step 8: VAT
    vat_result = calc_vat(revenue, total_input_vat, vat_status)

    # Step 9: Summary — two net figures
    total_tax_burden = net_income_tax + ni_result["total_ni_health"]
    effective_rate   = (total_tax_burden / revenue * 100) if revenue > 0 else 0.0

    # economic_net: revenue minus expenses, taxes, NI — does NOT subtract pension/KH
    # because those deposits remain the taxpayer's assets (savings accounts).
    economic_net = revenue - total_actual_cash - net_income_tax - ni_result["total_ni_health"]

    # spendable_cash_net: true cash left after ALL outflows, including savings deposits.
    # This is what you can actually spend this year.
    spendable_cash_net = economic_net - pension_dep - kh_dep

    if pension_dep > 0 or kh_dep > 0:
        warnings.append({
            "code": "TWO_NET_FIGURES",
            "message": (
                f"Two 'net' figures are provided. "
                f"Spendable cash (₪{max(0, spendable_cash_net):,.0f}) subtracts pension "
                f"(₪{pension_dep:,.0f}) and KH (₪{kh_dep:,.0f}) deposits — actual cash "
                f"available to spend. Economic net (₪{economic_net:,.0f}) treats those "
                "deposits as still yours (long-term savings)."
            ),
        })

    return {
        "tax_year": TAX_YEAR,
        "inputs": {
            "annual_revenue": revenue,
            "vat_status": vat_status,
            "credit_points": credit_points,
            "pension_deposit": pension_dep,
            "kh_deposit": kh_dep,
            "home_office_ratio": home_ratio,
        },
        "expenses": exp_result,
        "ni": ni_result,
        "pension": pension_result,
        "keren_hishtalmut": kh_result,
        "income_tax": {
            "gross_revenue": round(revenue, 2),
            "it_deductible_expenses": round(it_deductible_expenses, 2),
            "pension_deduction": round(pension_deduction, 2),
            "kh_deduction": round(kh_deduction, 2),
            "ni_deduction_52pct": round(ni_deductible, 2),
            "taxable_income": round(taxable_income, 2),
            "gross_tax_before_credits": round(gross_tax, 2),
            "credit_points_reduction": round(credit_points * CREDIT_POINT_ANNUAL, 2),
            "pension_tax_credit": round(pension_credit, 2),
            "net_income_tax": round(net_income_tax, 2),
            "effective_it_rate_pct": round(net_income_tax / revenue * 100 if revenue > 0 else 0, 2),
        },
        "vat": vat_result,
        "summary": {
            "gross_revenue": round(revenue, 2),
            "total_expenses_cash_out": round(total_actual_cash, 2),
            "net_income_tax": round(net_income_tax, 2),
            "total_ni_health": round(ni_result["total_ni_health"], 2),
            "total_tax_burden_excl_vat": round(total_tax_burden, 2),
            "effective_total_rate_pct": round(effective_rate, 2),
            # economic_net: includes pension/KH as yours (they're savings, not expenses)
            "net_cash_after_taxes": round(economic_net, 2),
            # spendable_cash_net: actual cash left after every outflow this year
            "spendable_cash_net": round(max(0.0, spendable_cash_net), 2),
            "pension_kh_deposits": round(pension_dep + kh_dep, 2),
            "vat_payable_passthrough": round(vat_result["vat_payable"], 2),
        },
        "assumptions": {
            "ni_mode": "net_income_simplified",
            "ni_base_note": (
                "NI assessed on revenue minus IT-deductible expenses "
                "(proxy for Israeli NI law 'net business income')"
            ),
            "pension_base": "gross_revenue_approximation",
            "pension_base_note": (
                "Pension/KH ceilings use gross revenue; "
                "may overstate slightly for high-expense businesses"
            ),
            "credit_point_annual": CREDIT_POINT_ANNUAL,
            "credit_point_note": "Verify CREDIT_POINT_MONTHLY (242) against official 2026 ITA table",
            "revenue_mode": "annual",
            "vat_mode": vat_status,
            "constants_source": "2026 — verify NI thresholds, OSEK_PATUR_CEILING annually",
        },
        "warnings": warnings,
    }


# ─────────────────────────────────────────────
# HUMAN-READABLE REPORT
# ─────────────────────────────────────────────

def _fmt(n: float) -> str:
    return f"{n:,.0f} ₪"


def print_report(result: dict) -> None:
    r = result
    inp = r["inputs"]
    it  = r["income_tax"]
    ni  = r["ni"]
    kh  = r["keren_hishtalmut"]
    pen = r["pension"]
    vat = r["vat"]
    exp = r["expenses"]
    s   = r["summary"]

    SEP = "─" * 60

    print(f"\n{'═' * 60}")
    print(f"  🇮🇱 דוח מס עצמאי ישראל — שנת מס {r['tax_year']}")
    print(f"{'═' * 60}")

    print(f"\n📥 נתוני קלט")
    print(f"  הכנסה שנתית:       {_fmt(inp['annual_revenue'])}")
    print(f"  סטטוס מע\"מ:         {inp['vat_status'].upper()}")
    print(f"  נקודות זיכוי:       {inp['credit_points']}")
    print(f"  הפקדה לפנסיה:       {_fmt(inp['pension_deposit'])}")
    print(f"  הפקדה קרן השתלמות: {_fmt(inp['kh_deposit'])}")

    # Expenses breakdown
    if exp["breakdown"]:
        print(f"\n📋 הוצאות מוכרות")
        print(f"  {SEP}")
        for e in exp["breakdown"]:
            warn = e.get("warning", "")
            print(f"  {e.get('label', e['category']):<40} {_fmt(e['gross_amount'])} → IT ניכוי: {_fmt(e['it_deductible_amount'])}", end="")
            if e.get("input_vat_recoverable", 0) > 0:
                print(f" | VAT שב: {_fmt(e['input_vat_recoverable'])}", end="")
            if warn:
                print(f"\n    ⚠️  {warn}", end="")
            print()
        print(f"  {SEP}")
        print(f"  סה\"כ ניכויי IT:    {_fmt(exp['total_it_deductible'])}")
        if inp["vat_status"] == "murshe":
            print(f"  סה\"כ VAT תשומות:  {_fmt(exp['total_input_vat_recoverable'])}")

    # NI
    print(f"\n🏥 ביטוח לאומי + בריאות (עצמאי)")
    print(f"  בסיס הכנסה לחישוב: {_fmt(ni['ni_base_applied'])}", end="")
    if ni["floored_to_minimum"]:
        print(f" ⚠️  (הורם לרצפת מינימום {_fmt(NI_MIN_ANNUAL)})", end="")
    print()
    print(f"  מדרגה 1 ({_fmt(0)}–{_fmt(NI_TIER1_ANNUAL_CAP)}):  NI {_fmt(ni['tier1_ni'])} + בריאות {_fmt(ni['tier1_health'])}")
    if ni["tier2_income"] > 0:
        print(f"  מדרגה 2 (מעל {_fmt(NI_TIER1_ANNUAL_CAP)}):    NI {_fmt(ni['tier2_ni'])} + בריאות {_fmt(ni['tier2_health'])}")
    print(f"  סה\"כ ביטוח לאומי:  {_fmt(ni['total_ni'])}")
    print(f"  סה\"כ בריאות:       {_fmt(ni['total_health'])}")
    print(f"  סה\"כ ביטוח:        {_fmt(ni['total_ni_health'])}")
    print(f"  מוכר למס הכנסה:    {_fmt(ni['ni_deductible_52pct'])} (52%)")

    # Pension & KH
    if inp["pension_deposit"] > 0:
        print(f"\n🏦 פנסיה")
        print(f"  הפקדה:             {_fmt(pen['pension_deposit'])}")
        print(f"  ניכוי (11%):       {_fmt(pen['deduction_amount'])}")
        print(f"  זיכוי מס (35%×5.5%): {_fmt(pen['tax_credit'])}")
    if inp["kh_deposit"] > 0:
        print(f"\n📚 קרן השתלמות")
        print(f"  הפקדה:             {_fmt(kh['kh_deposit'])}")
        print(f"  ניכוי:             {_fmt(kh['it_deduction'])}")
        cgt_str = "✅ פטורה ממס רווח הון" if kh["cgt_exempt_if_held_6yr"] else f"⚠️  חלקית — מעל {_fmt(KH_CGT_EXEMPT_CEILING)}"
        print(f"  רווח הון:          {cgt_str}")

    # Income Tax
    print(f"\n💰 מס הכנסה")
    print(f"  הכנסה ברוטו:       {_fmt(it['gross_revenue'])}")
    print(f"  מינוס הוצאות:      ({_fmt(it['it_deductible_expenses'])})")
    print(f"  מינוס פנסיה:       ({_fmt(it['pension_deduction'])})")
    print(f"  מינוס קרן השתלמות: ({_fmt(it['kh_deduction'])})")
    print(f"  מינוס 52% ביטוח:   ({_fmt(it['ni_deduction_52pct'])})")
    print(f"  הכנסה חייבת:       {_fmt(it['taxable_income'])}")
    print(f"  מס לפני זיכויים:   {_fmt(it['gross_tax_before_credits'])}")
    print(f"  זיכוי נקודות:      ({_fmt(it['credit_points_reduction'])})")
    if it["pension_tax_credit"] > 0:
        print(f"  זיכוי פנסיה:       ({_fmt(it['pension_tax_credit'])})")
    print(f"  מס הכנסה נטו:      {_fmt(it['net_income_tax'])}")

    # VAT
    if vat["status"] == "murshe":
        print(f"\n🧾 מע\"מ (עוסק מורשה)")
        print(f"  מע\"מ עסקאות:       {_fmt(vat['output_vat'])}")
        print(f"  מע\"מ תשומות:       ({_fmt(vat['input_vat_recoverable'])})")
        print(f"  לתשלום לרשות:     {_fmt(vat['vat_payable'])}")
    else:
        print(f"\n🧾 מע\"מ: עוסק פטור — אין גבייה/תשלום")

    # Summary
    print(f"\n{'═' * 60}")
    print(f"  📊 סיכום")
    print(f"{'═' * 60}")
    print(f"  הכנסה ברוטו:        {_fmt(s['gross_revenue'])}")
    print(f"  הוצאות בפועל:       ({_fmt(s['total_expenses_cash_out'])})")
    print(f"  מס הכנסה:           ({_fmt(s['net_income_tax'])})")
    print(f"  ביטוח לאומי+בריאות: ({_fmt(s['total_ni_health'])})")
    print(f"  {'─' * 45}")
    print(f"  נטו לאחר מיסים:     {_fmt(s['net_cash_after_taxes'])}")
    print(f"  אחוז מס אפקטיבי:   {s['effective_total_rate_pct']:.1f}% (מס הכנסה + ביטוח לאומי)")
    if vat["status"] == "murshe":
        print(f"  מע\"מ לתשלום:        {_fmt(s['vat_payable_passthrough'])} (pass-through, לא עלות)")
    print(f"{'═' * 60}\n")


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Israel Self-Employed Tax Calculator 2026",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic calculation
  python tax_calculator.py --annual-revenue 200000

  # With expenses from JSON file
  python tax_calculator.py --annual-revenue 360000 --expenses expenses.json --report

  # With expenses inline
  python tax_calculator.py --annual-revenue 80000 \\
    --expenses '[{"category":"mobile_phone","gross_amount":3600}]' \\
    --report

  # With pension and keren hishtalmut
  python tax_calculator.py --annual-revenue 360000 \\
    --pension 25000 --keren-hishtalmut 20566 --report
        """,
    )
    p.add_argument("--annual-revenue", type=float, required=True,
                   help="Annual gross revenue in NIS (ex-VAT if Osek Murshe)")
    p.add_argument("--expenses", type=str, default="[]",
                   help="JSON array of expenses, or path to a .json file")
    p.add_argument("--credit-points", type=float, default=2.25,
                   help="Number of tax credit points (default 2.25 for single adult)")
    p.add_argument("--pension", type=float, default=0.0,
                   help="Annual pension fund deposit (NIS)")
    p.add_argument("--keren-hishtalmut", type=float, default=0.0,
                   help="Annual keren hishtalmut deposit (NIS)")
    p.add_argument("--vat-status", choices=["auto", "patur", "murshe"], default="auto",
                   help="VAT status override (default: auto-determined from revenue)")
    p.add_argument("--home-office-ratio", type=float, default=0.25,
                   help="Fraction of home used as office (default 0.25 = 1 room in 4-room apt)")
    p.add_argument("--report", action="store_true",
                   help="Print human-readable Hebrew report (default: JSON output)")
    return p.parse_args()


def load_expenses(raw: str) -> list:
    """Load expenses from JSON string or file path."""
    raw = raw.strip()
    if raw.startswith("[") or raw.startswith("{"):
        data = json.loads(raw)
    else:
        with open(raw, "r", encoding="utf-8") as f:
            data = json.load(f)
    if isinstance(data, dict):
        data = [data]
    return data


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

    result = run_calculation(inputs)

    if args.report:
        print_report(result)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
