import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "execution"))

import streamlit as st
import pandas as pd
import altair as alt
from tax_calculator import run_calculation, EXPENSE_RULES, VALID_CATEGORIES
from tax_optimizer import generate_recommendations


def _spendable_metric(col, summary: dict, divisor: int = 1) -> None:
    """Render the spendable-cash / net-take-home metric for annual or monthly views."""
    has_savings = summary["pension_kh_deposits"] > 0
    col.metric(
        "Spendable Cash" if has_savings else "Net Take-Home",
        f"₪{summary['spendable_cash_net'] / divisor:,.0f}",
        delta=(f"+₪{summary['pension_kh_deposits'] / divisor:,.0f} in savings"
               if has_savings else f"{100 - summary['effective_total_rate_pct']:.1f}% kept"),
        help=("Cash after taxes, expenses, AND pension/KH deposits. "
              f"Economic net (incl. savings): ₪{summary['net_cash_after_taxes'] / divisor:,.0f}"
              if has_savings else "Spendable cash after taxes and expenses."),
    )


# ── Page config ────────────────────────────────────────────────
st.set_page_config(
    page_title="Israel Self-Employed Tax Calculator 2026",
    page_icon="🇮🇱",
    layout="wide",
)

# ── CSS ────────────────────────────────────────────────────────
st.markdown("""
<style>
  /* Layout */
  .block-container { padding-top: 1rem; padding-bottom: 2rem; }

  /* Metric cards */
  div[data-testid="metric-container"] {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 12px 16px;
  }

  /* Section label (UPPERCASE tag above a group) */
  .section-tag {
    font-size: 10.5px;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #a0aec0;
    margin-bottom: 0.15rem;
  }

  /* Set-aside callout box */
  .set-aside {
    background: #fffbeb;
    border: 2px solid #f59e0b;
    border-radius: 12px;
    padding: 1rem 1.5rem;
    margin: 0.5rem 0 1.25rem 0;
  }
  .set-aside-top {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: #92400e;
    margin-bottom: 4px;
  }
  .set-aside-amount {
    font-size: 2rem;
    font-weight: 800;
    color: #78350f;
    line-height: 1.15;
  }
  .set-aside-sub {
    font-size: 13px;
    color: #b45309;
    margin-top: 6px;
  }

  /* Calculation flow rows */
  .flow-row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    padding: 7px 0;
    border-bottom: 1px solid #f1f5f9;
    font-size: 14px;
  }
  .flow-row:last-child { border-bottom: none; }

  /* Disclaimer footer */
  .disclaimer {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 0.6rem 1rem;
    font-size: 12px;
    color: #718096;
    margin-top: 1.5rem;
  }

  /* Tabs */
  .stTabs [data-baseweb="tab"] { font-size: 14px; font-weight: 500; }
</style>
""", unsafe_allow_html=True)


# ── Session state ──────────────────────────────────────────────
if "expenses" not in st.session_state:
    st.session_state.expenses = []

# ── Category labels ────────────────────────────────────────────
CATEGORY_LABELS = {
    "car":                    "Car (private ≤3.5t)",
    "mobile_phone":           "Mobile phone",
    "home_office_rent":       "Home office — rent",
    "home_electricity":       "Home office — electricity",
    "home_arnona":            "Home office — municipal tax",
    "home_internet":          "Home office — internet",
    "office_internet":        "Dedicated office — internet",
    "office_rent":            "Dedicated office — rent",
    "meals_entertainment":    "Meals / business entertainment",
    "professional_services":  "Professional services (accountant, lawyer)",
    "computer_hardware":      "Computer hardware",
    "software":               "Software / subscriptions",
    "advertising":            "Advertising / marketing",
    "courses":                "Courses / professional development",
    "business_insurance":     "Business insurance",
    "business_gifts":         "Business gifts",
    "other_fully_deductible": "Other (100% deductible)",
}


# ══════════════════════════════════════════
# SIDEBAR — Inputs
# ══════════════════════════════════════════
with st.sidebar:
    st.markdown("## Inputs")

    # ── INCOME ──────────────────────────────
    st.markdown('<p class="section-tag">Income</p>', unsafe_allow_html=True)

    annual_revenue = st.number_input(
        "Annual revenue (₪, ex-VAT)",
        min_value=0, max_value=5_000_000, value=240_000, step=10_000,
        help="Gross revenue for the year, before VAT. If Osek Murshe, enter the amount you charge clients before adding VAT."
    )
    vat_override = st.selectbox(
        "VAT status",
        options=["auto", "patur", "murshe"],
        index=0,
        format_func=lambda x: {
            "auto":   "Auto (by revenue)",
            "patur":  "Osek Patur — VAT exempt",
            "murshe": "Osek Murshe — VAT registered",
        }[x],
        help="Auto: exempt below ₪122,833/yr, registered above. Osek Patur cannot reclaim input VAT."
    )

    st.divider()

    # ── BUSINESS EXPENSES ────────────────────
    exp_count = len(st.session_state.expenses)
    exp_label = f"Business Expenses {'· ' + str(exp_count) + ' added' if exp_count else ''}"
    st.markdown('<p class="section-tag">Business Expenses</p>', unsafe_allow_html=True)

    with st.expander(exp_label, expanded=False):
        new_cat = st.selectbox(
            "Category",
            options=list(VALID_CATEGORIES),
            format_func=lambda k: CATEGORY_LABELS.get(k, k),
        )
        new_desc = st.text_input("Description (optional)", placeholder="e.g. MacBook Pro")
        new_amount = st.number_input("Amount (₪)", min_value=0, value=0, step=500, key="exp_amount")
        new_has_vat = st.checkbox(
            "VAT invoice available",
            value=True,
            help="Do you hold a valid VAT invoice? Required to reclaim input VAT as Osek Murshe."
        )
        if st.button("Add expense", type="primary", use_container_width=True):
            if new_amount > 0:
                st.session_state.expenses.append({
                    "category":       new_cat,
                    "description":    new_desc or CATEGORY_LABELS.get(new_cat, new_cat),
                    "gross_amount":   float(new_amount),
                    "has_vat_invoice": new_has_vat,
                })
                st.rerun()

    if st.session_state.expenses:
        to_delete = None
        for i, exp in enumerate(st.session_state.expenses):
            c1, c2 = st.columns([5, 1])
            c1.caption(
                f"{CATEGORY_LABELS.get(exp['category'], exp['category'])} · ₪{exp['gross_amount']:,.0f}"
            )
            if c2.button("✕", key=f"del_{i}", help="Remove"):
                to_delete = i
        if to_delete is not None:
            st.session_state.expenses.pop(to_delete)
            st.rerun()
        if st.button("Clear all expenses", type="secondary", use_container_width=True):
            st.session_state.expenses = []
            st.rerun()
    else:
        st.caption("No expenses added yet. Expenses reduce both income tax and VAT liability.")

    st.divider()

    # ── SAVINGS & DEDUCTIONS ────────────────
    st.markdown('<p class="section-tag">Savings & Deductions</p>', unsafe_allow_html=True)

    pension = st.number_input(
        "Annual pension deposit (₪)",
        min_value=0, max_value=500_000, value=0, step=1_000,
        help="Gives a tax expense deduction (11% of income) AND a direct tax credit (5.5% × 35%). "
             "Max combined benefit at ₪38,412/yr."
    )
    kh = st.number_input(
        "Keren Hishtalmut deposit (₪)",
        min_value=0, max_value=100_000, value=0, step=1_000,
        help="Study fund (קרן השתלמות). Deductible up to ₪13,203/yr. "
             "Optimal deposit ₪20,566/yr — CGT-exempt on withdrawal after 6 years."
    )

    st.divider()

    # ── TAX PROFILE ────────────────────────
    st.markdown('<p class="section-tag">Tax Profile</p>', unsafe_allow_html=True)

    credit_points = st.number_input(
        "Tax credit points",
        min_value=0.0, max_value=20.0, value=2.25, step=0.25,
        help="Each point = ₪2,904/yr tax credit. Single adult: 2.25 · Working parent: +1 per child · New immigrant: +3"
    )
    home_office_ratio = st.slider(
        "Home office room ratio",
        min_value=0.0, max_value=1.0, value=0.25, step=0.05,
        format="%.0f%%",
        help="Office room area ÷ total apartment rooms. 1 office in a 4-room flat = 25%."
    )


# ── Run calculations ───────────────────────────────────────────
inputs = {
    "annual_revenue":      annual_revenue,
    "expenses":            st.session_state.expenses,
    "credit_points":       credit_points,
    "pension_deposit":     float(pension),
    "kh_deposit":          float(kh),
    "vat_status_override": vat_override,
    "home_office_ratio":   home_office_ratio,
}

result     = run_calculation(inputs)
opt_result = generate_recommendations(inputs)

s     = result["summary"]
it    = result["income_tax"]
ni    = result["ni"]
vat   = result["vat"]
exp_r = result["expenses"]

# Derived set-aside figures
set_aside_tax   = s["net_income_tax"] + s["total_ni_health"]
set_aside_vat   = vat["vat_payable"] if vat["status"] == "murshe" else 0
set_aside_total = set_aside_tax + set_aside_vat
set_aside_pct   = (set_aside_total / annual_revenue * 100) if annual_revenue > 0 else 0


# ══════════════════════════════════════════
# MAIN AREA — Header
# ══════════════════════════════════════════
st.markdown("## Israel Self-Employed Tax Calculator")
st.caption("Income tax · National Insurance · VAT · Recognized expenses — 2026 tax year")


# ── KPI SUMMARY STRIP ──────────────────────────────────────────
m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric(
    "Gross Revenue",
    f"₪{annual_revenue:,.0f}",
    help="Annual revenue, ex-VAT"
)
m2.metric(
    "Income Tax",
    f"₪{s['net_income_tax']:,.0f}",
    delta=f"{it['effective_it_rate_pct']:.1f}% effective rate",
    delta_color="inverse",
    help="After credit points and applicable deductions"
)
m3.metric(
    "NI + Health",
    f"₪{s['total_ni_health']:,.0f}",
    help="National Insurance + Health Insurance (Bituach Leumi)"
)
if vat["status"] == "murshe":
    m4.metric(
        "VAT Payable",
        f"₪{vat['vat_payable']:,.0f}",
        delta="pass-through",
        help="Collected from clients, remitted to the tax authority. Not a cost to your business."
    )
else:
    m4.metric(
        "VAT",
        "Osek Patur",
        help="Exempt — no VAT charged or reclaimed"
    )
_spendable_metric(m5, s)
m6.metric(
    "Effective Total Rate",
    f"{s['effective_total_rate_pct']:.1f}%",
    delta_color="inverse",
    help="Income tax + NI+Health as a percentage of gross revenue"
)

st.divider()

# ── SET ASIDE CALLOUT ──────────────────────────────────────────
breakdown_parts = [
    f"₪{s['net_income_tax']:,.0f} income tax",
    f"₪{s['total_ni_health']:,.0f} NI+Health",
]
if set_aside_vat > 0:
    breakdown_parts.append(f"₪{set_aside_vat:,.0f} VAT")

st.markdown(f"""
<div class="set-aside">
  <div class="set-aside-top">Recommended: set aside each year</div>
  <div class="set-aside-amount">
    ₪{set_aside_total:,.0f}
    <span style="font-size:1rem; font-weight:500; color:#b45309;">
      &nbsp;({set_aside_pct:.0f}% of revenue)
    </span>
  </div>
  <div class="set-aside-sub">
    ≈ ₪{set_aside_total / 12:,.0f}/month &nbsp;·&nbsp; {' + '.join(breakdown_parts)}
  </div>
</div>
""", unsafe_allow_html=True)

# ── Engine warnings ────────────────────────────────────────────
for w in result.get("warnings", []):
    if w["code"] == "NI_FLOORED_TO_MINIMUM":
        st.warning(w["message"])
    elif w["code"] == "PENSION_BASE_APPROXIMATION":
        st.info(f"ℹ️ {w['message']}")


# ── Tabs ───────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    "📊 Calculation",
    "📅 Monthly View",
    "💡 Optimization",
    "📚 Reference",
])


# ══════════════════════════════════════════
# TAB 1 — Main calculation results
# ══════════════════════════════════════════
with tab1:

    col_left, col_right = st.columns(2, gap="large")

    # ── LEFT COLUMN ────────────────────────────────────────────
    with col_left:

        # Income Tax Calculation Flow
        st.markdown("#### Income Tax")

        def _flow_row(label, value, color="#4a5568", weight="400", indent=False):
            pad = "1.1rem" if indent else "0"
            st.markdown(
                f'<div class="flow-row">'
                f'<span style="color:#4a5568; padding-left:{pad}">{label}</span>'
                f'<span style="color:{color}; font-weight:{weight}">{value}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

        _flow_row("Gross revenue", f"₪{it['gross_revenue']:,.0f}")
        _flow_row("− Recognized business expenses",
                  f"(₪{it['it_deductible_expenses']:,.0f})", color="#e53e3e", indent=True)
        if it["pension_deduction"] > 0:
            _flow_row("− Pension deduction",
                      f"(₪{it['pension_deduction']:,.0f})", color="#e53e3e", indent=True)
        if it["kh_deduction"] > 0:
            _flow_row("− Keren Hishtalmut deduction",
                      f"(₪{it['kh_deduction']:,.0f})", color="#e53e3e", indent=True)
        _flow_row("− 52% of NI+Health (deductible)",
                  f"(₪{it['ni_deduction_52pct']:,.0f})", color="#e53e3e", indent=True)
        _flow_row("= Taxable income",
                  f"₪{it['taxable_income']:,.0f}", color="#2b6cb0", weight="700")
        _flow_row("Tax on brackets", f"₪{it['gross_tax_before_credits']:,.0f}")
        _flow_row("− Credit points",
                  f"(₪{it['credit_points_reduction']:,.0f})", color="#e53e3e", indent=True)
        if it["pension_tax_credit"] > 0:
            _flow_row("− Pension tax credit",
                      f"(₪{it['pension_tax_credit']:,.0f})", color="#e53e3e", indent=True)
        _flow_row("= Income tax payable",
                  f"₪{it['net_income_tax']:,.0f}", color="#22543d", weight="700")

        st.markdown("<br>", unsafe_allow_html=True)

        # National Insurance
        st.markdown("#### National Insurance + Health")

        _flow_row("Calculation base", f"₪{ni['ni_base_applied']:,.0f}")
        if ni["floored_to_minimum"]:
            _flow_row("⚠ Floored to minimum base", "₪41,304/yr", color="#c05621")
        _flow_row("Tier 1 — up to ₪92,436/yr", f"₪{ni['tier1_total']:,.0f}")
        if ni["tier2_income"] > 0:
            _flow_row("Tier 2 — above ₪92,436/yr", f"₪{ni['tier2_total']:,.0f}")
        _flow_row("= National Insurance", f"₪{ni['total_ni']:,.0f}", color="#2b6cb0", weight="700")
        _flow_row("= Health Insurance",   f"₪{ni['total_health']:,.0f}", color="#2b6cb0", weight="700")

        st.markdown("<br>", unsafe_allow_html=True)

        # Net Summary
        st.markdown("#### Net Summary")

        _flow_row("Gross revenue", f"₪{annual_revenue:,.0f}")
        _flow_row("− Total taxes (IT + NI+Health)",
                  f"(₪{s['net_income_tax'] + s['total_ni_health']:,.0f})", color="#e53e3e", indent=True)
        _flow_row("− Business expenses",
                  f"(₪{s['total_expenses_cash_out']:,.0f})", color="#e53e3e", indent=True)
        if s["pension_kh_deposits"] > 0:
            _flow_row("− Savings (pension / KH)",
                      f"(₪{s['pension_kh_deposits']:,.0f})", color="#e53e3e", indent=True)
        _flow_row("= Spendable cash net",
                  f"₪{s['spendable_cash_net']:,.0f}", color="#22543d", weight="700")
        if s["pension_kh_deposits"] > 0:
            _flow_row("  + Savings deposits (yours, long-term)",
                      f"+₪{s['pension_kh_deposits']:,.0f}", color="#2b6cb0", indent=True)
            _flow_row("= Economic net (incl. savings)",
                      f"₪{s['net_cash_after_taxes']:,.0f}", color="#22543d", weight="700")

    # ── RIGHT COLUMN ───────────────────────────────────────────
    with col_right:

        # VAT
        st.markdown("#### VAT")
        if vat["status"] == "murshe":
            _flow_row("Output VAT charged to clients", f"₪{vat['output_vat']:,.0f}")
            _flow_row("− Input VAT recovered on expenses",
                      f"(₪{vat['input_vat_recoverable']:,.0f})", color="#e53e3e", indent=True)
            _flow_row("= VAT payable to authority",
                      f"₪{vat['vat_payable']:,.0f}", color="#553c9a", weight="700")
            st.caption(
                "VAT is a pass-through — collected from clients, remitted to the tax authority. "
                "It is not a cost to your business."
            )
        else:
            st.success("Osek Patur — no VAT charged or reclaimed")
            if annual_revenue > 0:
                pct = (annual_revenue / 122_833) * 100
                if pct > 70:
                    st.warning(
                        f"⚠ You are at {pct:.0f}% of the Osek Patur ceiling (₪122,833/yr). "
                        "Consider planning for transition to Osek Murshe."
                    )

        st.markdown("<br>", unsafe_allow_html=True)

        # Business Expenses Detail
        st.markdown("#### Business Expenses")

        if exp_r["breakdown"]:
            ec1, ec2, ec3 = st.columns(3)
            ec1.metric("Total paid", f"₪{exp_r['total_actual_cash']:,.0f}")
            ec2.metric("Tax deductible", f"₪{exp_r['total_it_deductible']:,.0f}")
            if vat["status"] == "murshe":
                ec3.metric("VAT recovered", f"₪{exp_r['total_input_vat_recoverable']:,.0f}")

            rows_df = []
            for e in exp_r["breakdown"]:
                row = {
                    "Category":      CATEGORY_LABELS.get(e["category"], e["category"]),
                    "Description":   e.get("description", ""),
                    "Paid (₪)":      f"₪{e['gross_amount']:,.0f}",
                    "IT Deductible": f"₪{e['it_deductible_amount']:,.0f}",
                }
                if vat["status"] == "murshe":
                    row["VAT Recovered"] = f"₪{e.get('input_vat_recoverable', 0):,.0f}"
                if e.get("warning"):
                    row["Note"] = e["warning"]
                rows_df.append(row)

            with st.expander("Expense breakdown detail"):
                st.dataframe(
                    pd.DataFrame(rows_df),
                    use_container_width=True,
                    hide_index=True,
                )
        else:
            st.caption(
                "No expenses added. Use the sidebar to add expenses — "
                "they reduce both your taxable income and VAT liability."
            )

    # ── CHART ─────────────────────────────────────────────────
    st.divider()
    st.markdown("#### Where Does the Revenue Go?")

    chart_rows = {
        "Spendable Cash":    (s["spendable_cash_net"],       "#38a169"),
        "Income Tax":        (s["net_income_tax"],           "#e53e3e"),
        "NI + Health":       (s["total_ni_health"],          "#ed8936"),
        "Business Expenses": (s["total_expenses_cash_out"],  "#a0aec0"),
    }
    if s["pension_kh_deposits"] > 0:
        chart_rows["Savings (pension/KH)"] = (s["pension_kh_deposits"], "#4299e1")
    if vat["status"] == "murshe":
        chart_rows["VAT payable (net)"] = (vat["vat_payable"], "#9f7aea")

    chart_data = pd.DataFrame({
        "Category": list(chart_rows.keys()),
        "Amount":   [v[0] for v in chart_rows.values()],
        "Color":    [v[1] for v in chart_rows.values()],
    })
    chart = (
        alt.Chart(chart_data)
        .mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6)
        .encode(
            x=alt.X("Category:N", axis=alt.Axis(labelAngle=0, labelFontSize=13), sort=None),
            y=alt.Y("Amount:Q", axis=alt.Axis(format=",.0f", title="₪ / year")),
            color=alt.Color("Color:N", scale=None, legend=None),
            tooltip=["Category", alt.Tooltip("Amount:Q", format=",.0f", title="₪")],
        )
        .properties(height=280)
    )
    st.altair_chart(chart, use_container_width=True)

    st.markdown(
        '<div class="disclaimer">'
        "⚖ For planning purposes only. Not a substitute for advice from a licensed CPA (רואה חשבון). "
        "All figures are estimates based on the information entered and 2026 Israeli tax rules."
        "</div>",
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════
# TAB 2 — Monthly Breakdown
# ══════════════════════════════════════════
with tab2:
    st.markdown("#### Monthly View")
    st.caption(
        "Enter monthly figures to see how a typical month distributes. "
        "Tax brackets are calculated on annualized amounts (monthly × 12)."
    )

    mc1, mc2, mc3 = st.columns(3)
    with mc1:
        monthly_rev = st.number_input(
            "Monthly revenue (₪, ex-VAT)",
            min_value=0, max_value=500_000,
            value=int(annual_revenue / 12),
            step=1_000,
            key="monthly_rev",
            help="Revenue for a typical month. Annualized ×12 for bracket calculations."
        )
    with mc2:
        monthly_pension = st.number_input(
            "Monthly pension deposit (₪)",
            min_value=0, max_value=50_000,
            value=int(pension / 12),
            step=500,
            key="monthly_pension",
        )
    with mc3:
        monthly_kh = st.number_input(
            "Monthly Keren Hishtalmut (₪)",
            min_value=0, max_value=10_000,
            value=int(kh / 12),
            step=200,
            key="monthly_kh",
        )

    projected_annual = monthly_rev * 12
    st.info(
        f"Annualized: revenue **₪{projected_annual:,.0f}** · "
        f"pension **₪{monthly_pension * 12:,.0f}** · "
        f"KH **₪{monthly_kh * 12:,.0f}**. "
        "Monthly figures = annual ÷ 12."
    )

    monthly_inputs = {
        **inputs,
        "annual_revenue":  projected_annual,
        "pension_deposit": float(monthly_pension * 12),
        "kh_deposit":      float(monthly_kh * 12),
    }
    mr   = run_calculation(monthly_inputs)
    ms   = mr["summary"]
    mit  = mr["income_tax"]
    mvat = mr["vat"]

    st.divider()

    mm1, mm2, mm3, mm4, mm5 = st.columns(5)
    mm1.metric("Revenue", f"₪{monthly_rev:,.0f}")
    mm2.metric(
        "Income Tax",
        f"₪{ms['net_income_tax'] / 12:,.0f}",
        delta=f"{mit['effective_it_rate_pct']:.1f}% rate",
        delta_color="inverse",
    )
    mm3.metric("NI + Health", f"₪{ms['total_ni_health'] / 12:,.0f}")
    if mvat["status"] == "murshe":
        mm4.metric(
            "VAT to remit",
            f"₪{mvat['vat_payable'] / 12:,.0f}",
            help="Average monthly VAT — remitted bi-monthly to the tax authority",
        )
    else:
        mm4.metric("VAT", "Patur")
    _spendable_metric(mm5, ms, divisor=12)

    st.divider()
    st.markdown("#### Monthly vs Annual")

    monthly_table_rows = [
        ("Gross Revenue",                  monthly_rev,                          projected_annual),
        ("Business Expenses",              ms["total_expenses_cash_out"] / 12,   ms["total_expenses_cash_out"]),
        ("Pension deposit",                monthly_pension,                      monthly_pension * 12),
        ("Keren Hishtalmut deposit",       monthly_kh,                           monthly_kh * 12),
        ("Income Tax",                     ms["net_income_tax"] / 12,            ms["net_income_tax"]),
        ("NI + Health",                    ms["total_ni_health"] / 12,           ms["total_ni_health"]),
        ("Spendable Cash",                 ms["spendable_cash_net"] / 12,        ms["spendable_cash_net"]),
        ("  Economic net (incl. savings)", ms["net_cash_after_taxes"] / 12,      ms["net_cash_after_taxes"]),
    ]
    if mvat["status"] == "murshe":
        monthly_table_rows.insert(5, (
            "VAT payable (net)",
            mvat["vat_payable"] / 12,
            mvat["vat_payable"],
        ))

    mdf = pd.DataFrame(
        [{"": r, "Monthly (₪)": f"₪{m:,.0f}", "Annual (₪)": f"₪{a:,.0f}"}
         for r, m, a in monthly_table_rows]
    )
    st.dataframe(mdf, use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("#### Where Does This Month's Revenue Go?")

    m_chart_rows = {
        "Spendable Cash":    (ms["spendable_cash_net"] / 12,       "#38a169"),
        "Income Tax":        (ms["net_income_tax"] / 12,           "#e53e3e"),
        "NI + Health":       (ms["total_ni_health"] / 12,          "#ed8936"),
        "Business Expenses": (ms["total_expenses_cash_out"] / 12,  "#a0aec0"),
    }
    if monthly_pension > 0:
        m_chart_rows["Pension"]          = (float(monthly_pension), "#4299e1")
    if monthly_kh > 0:
        m_chart_rows["Keren Hishtalmut"] = (float(monthly_kh),      "#63b3ed")
    if mvat["status"] == "murshe":
        m_chart_rows["VAT payable"] = (mvat["vat_payable"] / 12, "#9f7aea")

    m_chart_data = pd.DataFrame({
        "Category": list(m_chart_rows.keys()),
        "Amount":   [v[0] for v in m_chart_rows.values()],
        "Color":    [v[1] for v in m_chart_rows.values()],
    })
    m_chart = (
        alt.Chart(m_chart_data)
        .mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6)
        .encode(
            x=alt.X("Category:N", axis=alt.Axis(labelAngle=0, labelFontSize=13), sort=None),
            y=alt.Y("Amount:Q", axis=alt.Axis(format=",.0f", title="₪ / month")),
            color=alt.Color("Color:N", scale=None, legend=None),
            tooltip=["Category", alt.Tooltip("Amount:Q", format=",.0f", title="₪")],
        )
        .properties(height=280)
    )
    st.altair_chart(m_chart, use_container_width=True)


# ══════════════════════════════════════════
# TAB 3 — Optimizer
# ══════════════════════════════════════════
with tab3:
    recs         = opt_result["recommendations"]
    total_saving = opt_result["total_quantified_saving"]

    if total_saving > 0:
        st.success(
            f"**Potential tax savings: ₪{total_saving:,.0f}/year** — "
            "by implementing all recommendations below"
        )

    if not recs:
        st.success("No significant optimization opportunities found. Your setup is well-optimized.")
    else:
        PRIORITY_ICON = {1: "🔴", 2: "🟡", 3: "🟢"}
        EFFORT_LABEL  = {
            "low":    "Easy action",
            "medium": "Moderate effort",
            "high":   "Complex — consult a CPA",
        }

        for rec in recs:
            icon = PRIORITY_ICON.get(rec["priority"], "⚪")
            saving_str = (
                f"Save ₪{rec['annual_tax_saving']:,.0f}/yr"
                if rec.get("annual_tax_saving")
                else "Savings vary"
            )
            with st.expander(
                f"{icon} {rec['action']} — {saving_str}",
                expanded=rec["priority"] == 1,
            ):
                st.write(rec["notes"])
                if rec.get("deadline"):
                    st.info(f"Deadline: {rec['deadline']}")
                if rec.get("effort"):
                    st.caption(EFFORT_LABEL.get(rec["effort"], rec["effort"]))

    if total_saving > 0:
        st.divider()
        st.markdown("#### After Optimization — Projected Impact")
        opt_s = opt_result["optimized_scenario"]["summary"]
        c1, c2, c3 = st.columns(3)
        c1.metric(
            "Tax rate after optimization",
            f"{opt_s['effective_total_rate_pct']:.1f}%",
            delta=f"−{s['effective_total_rate_pct'] - opt_s['effective_total_rate_pct']:.1f}%",
        )
        c2.metric(
            "Economic net after optimization",
            f"₪{opt_s['net_cash_after_taxes']:,.0f}",
            delta=f"+₪{opt_s['net_cash_after_taxes'] - s['net_cash_after_taxes']:,.0f}",
        )
        c3.metric("Total annual savings", f"₪{total_saving:,.0f}")


# ══════════════════════════════════════════
# TAB 4 — Reference
# ══════════════════════════════════════════
with tab4:

    st.markdown("#### Income Tax Brackets — 2026")
    st.info(
        "2026 update: the 20% bracket expanded to ₪19,000/month (up from ₪16,150 in 2025). "
        "Temporary measure for 2026–2027."
    )
    brackets_df = pd.DataFrame([
        {"Annual from": "₪0",       "Annual to": "₪84,120",    "Monthly (approx)": "₪0 – ₪7,010",     "Rate": "10%"},
        {"Annual from": "₪84,120",  "Annual to": "₪120,720",   "Monthly (approx)": "₪7,010 – ₪10,060", "Rate": "14%"},
        {"Annual from": "₪120,720", "Annual to": "₪228,000 ✦", "Monthly (approx)": "₪10,060 – ₪19,000","Rate": "20%"},
        {"Annual from": "₪228,000", "Annual to": "₪301,200",   "Monthly (approx)": "₪19,000 – ₪25,100","Rate": "31%"},
        {"Annual from": "₪301,200", "Annual to": "₪560,280",   "Monthly (approx)": "₪25,100 – ₪46,690","Rate": "35%"},
        {"Annual from": "₪560,280", "Annual to": "₪721,560",   "Monthly (approx)": "₪46,690 – ₪60,130","Rate": "47%"},
        {"Annual from": "₪721,560", "Annual to": "No limit",   "Monthly (approx)": "Above ₪60,130",    "Rate": "50% (47% + 3% surtax)"},
    ])
    st.dataframe(brackets_df, use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("#### National Insurance + Health — Self-Employed (2026)")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("""
| Income range | NI | Health | Total |
|---|---|---|---|
| Up to ₪7,703/month | 4.47% | 3.23% | **7.70%** |
| ₪7,703 – ₪51,910/month | 12.83% | 5.17% | **18.00%** |
        """)
    with c2:
        st.markdown("""
- **Minimum base:** ₪3,442/month — charged even if income is lower
- **Maximum base:** ₪51,910/month — no NI above this ceiling
- **52%** of your NI+Health payment is deductible for income tax
        """)

    st.divider()
    st.markdown("#### Recognized Expense Deduction Rates")
    exp_table = pd.DataFrame([
        {"Expense": "Car (private)",        "Income Tax %": "45%",              "VAT Recovery %": "66%",              "Notes": "Fuel, insurance, servicing, depreciation"},
        {"Expense": "Mobile phone",         "Income Tax %": "50%",              "VAT Recovery %": "66%",              "Notes": "Max ₪1,200/yr incl. device depreciation"},
        {"Expense": "Home office",          "Income Tax %": "Room ratio",       "VAT Recovery %": "Room ratio",       "Notes": "Rent / electricity / arnona / internet"},
        {"Expense": "Meals & entertainment","Income Tax %": "80%",              "VAT Recovery %": "0% ⚠",            "Notes": "No VAT recovery on meals"},
        {"Expense": "Computer hardware",    "Income Tax %": "33.33%/yr",        "VAT Recovery %": "100% (year 1)",    "Notes": "Depreciated over 3 years for income tax"},
        {"Expense": "Software / subscriptions","Income Tax %": "100%",          "VAT Recovery %": "100%",             "Notes": ""},
        {"Expense": "Courses / training",   "Income Tax %": "100%",             "VAT Recovery %": "100%",             "Notes": "Not for career-change studies"},
        {"Expense": "Advertising / marketing","Income Tax %": "100%",           "VAT Recovery %": "100%",             "Notes": ""},
        {"Expense": "Accountant / lawyer",  "Income Tax %": "100%",             "VAT Recovery %": "100%",             "Notes": ""},
        {"Expense": "Business gifts",       "Income Tax %": "Up to ₪230/recipient/yr", "VAT Recovery %": "0%",       "Notes": "Document recipient name"},
    ])
    st.dataframe(exp_table, use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("#### Keren Hishtalmut (Study Fund) — Self-Employed")
    st.markdown("""
| Benefit | Annual cap | How it works |
|---|---|---|
| Income tax deduction | ₪13,203/yr | Reduces taxable income directly |
| CGT exemption on withdrawal | ₪20,566/yr | Withdrawal is tax-free after 6 years |

**Optimal deposit: ₪20,566/yr** — covers both benefits in full.
    """)

    st.divider()
    st.markdown("#### Pension — Self-Employed")
    st.markdown("""
| Component | Rate | Income ceiling | Max annual benefit |
|---|---|---|---|
| Expense deduction | 11% of income | ₪232,800/yr | ₪25,608 deduction |
| Tax credit | 5.5% × 35% | ₪232,800/yr | ₪4,476 direct credit |

Pension deposits reduce **income tax only** — they do not reduce National Insurance.
    """)

    st.divider()
    st.markdown("#### Concepts & Definitions")

    with st.expander("What is taxable income?"):
        st.write(
            "Taxable income = gross revenue minus recognized business expenses, minus pension deduction, "
            "minus Keren Hishtalmut deduction, minus 52% of NI+Health paid. "
            "Income tax brackets are applied to this figure."
        )
    with st.expander("What is the difference between Spendable Cash and Economic Net?"):
        st.write(
            "**Spendable Cash** is what you can actually spend — revenue minus all taxes, "
            "business expenses, and pension/KH deposits. "
            "**Economic Net** adds back pension and KH deposits, since that money is still yours "
            "(just locked up in long-term savings). "
            "Economic Net is the more complete measure of what you earned."
        )
    with st.expander("What is VAT input vs output?"):
        st.write(
            "**Output VAT** is what you charge your clients (17% on top of your price). "
            "**Input VAT** is what you paid on business expenses with valid VAT invoices. "
            "You remit only the difference to the tax authority. "
            "If input VAT exceeds output VAT, you receive a refund. "
            "VAT is not your money — you are a collection agent for the state."
        )
    with st.expander("Why is pension not the same as a tax?"):
        st.write(
            "Pension deposits are your own money going into a long-term savings account in your name. "
            "They are not a cost — they are deferred compensation. "
            "Depositing into pension reduces your income tax via deduction and tax credit, "
            "so the effective out-of-pocket cost is lower than the gross deposit amount."
        )
    with st.expander("What does 'deductible' mean?"):
        st.write(
            "A deductible expense reduces your taxable income. "
            "If you are in the 31% bracket, a ₪1,000 fully deductible expense saves you ₪310 in income tax. "
            "Not all expenses are 100% deductible — car, mobile phone, and home office have partial rates "
            "set by the Israeli Tax Authority."
        )

    st.divider()
    st.caption("⚖ For planning purposes only. Not a substitute for professional advice from a licensed CPA.")
