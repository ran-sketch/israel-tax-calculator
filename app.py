import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "execution"))

import streamlit as st
import pandas as pd
import altair as alt
from tax_calculator import run_calculation, EXPENSE_RULES, VALID_CATEGORIES
from tax_optimizer import generate_recommendations

# ── Page config ────────────────────────────────────────────────
st.set_page_config(
    page_title="Israel Self-Employed Tax Calculator 2026",
    page_icon="🇮🇱",
    layout="wide",
)

st.markdown("""
<style>
    .block-container { padding-top: 1.5rem; }
    div[data-testid="metric-container"] {
        background: #f8f9fa; border-radius: 10px; padding: 10px 16px;
    }
    .stTabs [data-baseweb="tab"] { font-size: 15px; font-weight: 500; }
</style>
""", unsafe_allow_html=True)

# ── Header ─────────────────────────────────────────────────────
st.title("🇮🇱 Israel Self-Employed Tax Calculator — 2026")
st.caption("Income tax · National Insurance · VAT · Recognized expenses — updated for Israeli tax law 2026")

# ── Session state ──────────────────────────────────────────────
if "expenses" not in st.session_state:
    st.session_state.expenses = []

# ── Category labels (English) ──────────────────────────────────
CATEGORY_LABELS = {
    "car":                   "Car (private ≤3.5t)",
    "mobile_phone":          "Mobile phone",
    "home_office_rent":      "Home office — rent",
    "home_electricity":      "Home office — electricity",
    "home_arnona":           "Home office — municipal tax",
    "home_internet":         "Home office — internet",
    "office_internet":       "Dedicated office — internet",
    "office_rent":           "Dedicated office — rent",
    "meals_entertainment":   "Meals / business entertainment",
    "professional_services": "Professional services (accountant, lawyer)",
    "computer_hardware":     "Computer hardware",
    "software":              "Software / subscriptions",
    "advertising":           "Advertising / marketing",
    "courses":               "Courses / professional development",
    "business_insurance":    "Business insurance",
    "business_gifts":        "Business gifts",
    "other_fully_deductible":"Other (100% deductible)",
}

# ── Sidebar ────────────────────────────────────────────────────
with st.sidebar:
    st.header("Inputs")

    annual_revenue = st.number_input(
        "Annual revenue (₪)",
        min_value=0, max_value=5_000_000, value=240_000, step=10_000,
        help="Gross revenue before VAT (if Osek Murshe, enter ex-VAT amount)"
    )

    st.divider()
    st.subheader("Settings")

    credit_points = st.number_input(
        "Tax credit points",
        min_value=0.0, max_value=20.0, value=2.25, step=0.25,
        help="Single adult = 2.25 | Working mother + child ≈ 4.25 | New immigrant = +3 pts"
    )

    vat_override = st.selectbox(
        "VAT status",
        options=["auto", "patur", "murshe"],
        index=0,
        format_func=lambda x: {"auto": "Auto (by revenue)", "patur": "Osek Patur (exempt)", "murshe": "Osek Murshe (registered)"}[x],
        help="Auto: exempt below ₪122,833/yr, registered above"
    )

    home_office_ratio = st.slider(
        "Home office room ratio",
        min_value=0.0, max_value=1.0, value=0.25, step=0.05,
        format="%.0f%%",
        help="Office room area ÷ total apartment rooms. 1 room in a 4-room apt = 25%"
    )

    st.divider()
    st.subheader("Savings accounts")

    pension = st.number_input(
        "Annual pension deposit (₪)",
        min_value=0, max_value=500_000, value=0, step=1_000,
        help="Max tax benefit: ₪38,412/yr (11% deduction + 5.5%×35% credit)"
    )

    kh = st.number_input(
        "Keren Hishtalmut deposit (₪)",
        min_value=0, max_value=100_000, value=0, step=1_000,
        help="Optimal: ₪20,566/yr — maximizes income tax deduction + CGT exemption"
    )

# ── Expense entry ──────────────────────────────────────────────
st.subheader("Business Expenses")

col1, col2, col3, col4, col5 = st.columns([2.5, 2, 1.5, 1, 0.8])
with col1:
    new_cat = st.selectbox(
        "Category", options=list(VALID_CATEGORIES),
        format_func=lambda k: CATEGORY_LABELS.get(k, k),
        label_visibility="collapsed"
    )
with col2:
    new_desc = st.text_input("Description", placeholder="Description (optional)", label_visibility="collapsed")
with col3:
    new_amount = st.number_input("Amount (₪)", min_value=0, value=0, step=500, label_visibility="collapsed")
with col4:
    new_has_vat = st.checkbox("VAT invoice", value=True, label_visibility="collapsed",
                               help="Do you have a valid VAT invoice for this expense?")
with col5:
    if st.button("Add ➕", use_container_width=True):
        if new_amount > 0:
            st.session_state.expenses.append({
                "category": new_cat,
                "description": new_desc or CATEGORY_LABELS.get(new_cat, new_cat),
                "gross_amount": float(new_amount),
                "has_vat_invoice": new_has_vat,
            })
            st.rerun()

if st.session_state.expenses:
    hdrs = st.columns([0.4, 2.5, 2, 1.5, 1, 0.5])
    for h, t in zip(hdrs, ["#", "Category", "Description", "Amount", "VAT inv.", "Del"]):
        h.caption(t)

    to_delete = None
    for i, exp in enumerate(st.session_state.expenses):
        c0, c1, c2, c3, c4, c5 = st.columns([0.4, 2.5, 2, 1.5, 1, 0.5])
        c0.write(f"{i+1}")
        c1.write(CATEGORY_LABELS.get(exp["category"], exp["category"]))
        c2.write(exp.get("description", ""))
        c3.write(f"₪{exp['gross_amount']:,.0f}")
        c4.write("✅" if exp.get("has_vat_invoice") else "❌")
        if c5.button("🗑", key=f"del_{i}"):
            to_delete = i

    if to_delete is not None:
        st.session_state.expenses.pop(to_delete)
        st.rerun()

    if st.button("Clear all expenses", type="secondary"):
        st.session_state.expenses = []
        st.rerun()
else:
    st.info("No expenses added yet. Expenses reduce both income tax and VAT liability.")

st.divider()

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

s      = result["summary"]
it     = result["income_tax"]
ni     = result["ni"]
vat    = result["vat"]
exp_r  = result["expenses"]

# ── Tabs ───────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs(["📊 Tax Calculation", "📅 Monthly Breakdown", "💡 Optimization Tips", "📚 Tax Reference"])


# ══════════════════════════════════════════
# TAB 1 — Calculation results
# ══════════════════════════════════════════
with tab1:

    # KPI row
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Gross Revenue", f"₪{annual_revenue:,.0f}")
    m2.metric("Income Tax", f"₪{s['net_income_tax']:,.0f}",
              delta=f"{it['effective_it_rate_pct']:.1f}% effective", delta_color="inverse")
    m3.metric("National Insurance", f"₪{s['total_ni_health']:,.0f}")
    if vat["status"] == "murshe":
        m4.metric("VAT payable (net)", f"₪{vat['vat_payable']:,.0f}",
                  delta="pass-through", help="Collected from clients, remitted to tax authority. Not your cost.")
    else:
        m4.metric("VAT", "Osek Patur", help="Exempt — no VAT charged or reclaimed")
    m5.metric("Net Take-Home", f"₪{s['net_cash_after_taxes']:,.0f}",
              delta=f"{100 - s['effective_total_rate_pct']:.1f}% kept")
    m6.metric("Total Tax Rate", f"{s['effective_total_rate_pct']:.1f}%", delta_color="inverse")

    st.divider()
    col_l, col_r = st.columns(2)

    # Income tax detail
    with col_l:
        st.subheader("Income Tax Breakdown")
        rows = {
            "Gross revenue":                f"₪{it['gross_revenue']:,.0f}",
            "− Recognized expenses":        f"(₪{it['it_deductible_expenses']:,.0f})",
        }
        if it["pension_deduction"] > 0:
            rows["− Pension deduction"]     = f"(₪{it['pension_deduction']:,.0f})"
        if it["kh_deduction"] > 0:
            rows["− Keren Hishtalmut deduction"] = f"(₪{it['kh_deduction']:,.0f})"
        rows["− 52% of NI (deductible)"]   = f"(₪{it['ni_deduction_52pct']:,.0f})"
        rows["**= Taxable income**"]        = f"**₪{it['taxable_income']:,.0f}**"
        rows["Tax on brackets"]             = f"₪{it['gross_tax_before_credits']:,.0f}"
        rows["− Credit points"]             = f"(₪{it['credit_points_reduction']:,.0f})"
        if it["pension_tax_credit"] > 0:
            rows["− Pension tax credit"]    = f"(₪{it['pension_tax_credit']:,.0f})"
        rows["**= Income tax payable**"]    = f"**₪{it['net_income_tax']:,.0f}**"

        for label, val in rows.items():
            lc, rc = st.columns([2, 1])
            lc.markdown(label)
            rc.markdown(val)

    # NI + VAT
    with col_r:
        st.subheader("National Insurance + Health")
        ni_rows = {"Calculation base": f"₪{ni['ni_base_applied']:,.0f}"}
        if ni["floored_to_minimum"]:
            ni_rows["⚠️ Floored to minimum"] = "₪41,304/yr"
        ni_rows["Tier 1 (up to ₪92,436/yr)"] = f"₪{ni['tier1_total']:,.0f}"
        if ni["tier2_income"] > 0:
            ni_rows["Tier 2 (above ₪92,436/yr)"] = f"₪{ni['tier2_total']:,.0f}"
        ni_rows["**National Insurance**"] = f"**₪{ni['total_ni']:,.0f}**"
        ni_rows["**Health Insurance**"]   = f"**₪{ni['total_health']:,.0f}**"

        for label, val in ni_rows.items():
            lc, rc = st.columns([2, 1])
            lc.markdown(label)
            rc.markdown(val)

        st.divider()
        st.subheader("VAT")
        if vat["status"] == "murshe":
            st.write(f"Output VAT (charged to clients): ₪{vat['output_vat']:,.0f}")
            st.write(f"Input VAT (recovered on expenses): (₪{vat['input_vat_recoverable']:,.0f})")
            st.markdown(f"**VAT payable to authority: ₪{vat['vat_payable']:,.0f}** *(pass-through)*")
        else:
            st.success("Osek Patur — no VAT charged or reclaimed")
            pct = (annual_revenue / 122_833) * 100
            if pct > 70:
                st.warning(f"⚠️ You are at {pct:.0f}% of the Osek Patur ceiling (₪122,833)")

    # Expenses table
    if exp_r["breakdown"]:
        st.divider()
        st.subheader("Expense Deduction Detail")

        rows_df = []
        for e in exp_r["breakdown"]:
            row = {
                "Category":         CATEGORY_LABELS.get(e["category"], e["category"]),
                "Description":      e.get("description", ""),
                "Paid (₪)":         f"₪{e['gross_amount']:,.0f}",
                "IT Deductible":    f"₪{e['it_deductible_amount']:,.0f}",
            }
            if vat["status"] == "murshe":
                row["VAT Recovered"] = f"₪{e.get('input_vat_recoverable', 0):,.0f}"
            if e.get("warning"):
                row["⚠️ Warning"] = e["warning"]
            rows_df.append(row)

        st.dataframe(pd.DataFrame(rows_df), use_container_width=True, hide_index=True)

        mc1, mc2, mc3 = st.columns(3)
        mc1.metric("Total expenses paid", f"₪{exp_r['total_actual_cash']:,.0f}")
        mc2.metric("Total IT deduction", f"₪{exp_r['total_it_deductible']:,.0f}")
        if vat["status"] == "murshe":
            mc3.metric("Total VAT recovered", f"₪{exp_r['total_input_vat_recoverable']:,.0f}")

    # Bar chart
    st.divider()
    st.subheader("Where Does the Money Go?")

    chart_rows = {
        "Net Take-Home":       (max(0, s["net_cash_after_taxes"]), "#38a169"),
        "Income Tax":          (s["net_income_tax"],               "#e53e3e"),
        "National Insurance":  (s["total_ni_health"],              "#dd6b20"),
        "Business Expenses":   (s["total_expenses_cash_out"],      "#718096"),
    }
    if vat["status"] == "murshe":
        chart_rows["VAT payable (net)"] = (vat["vat_payable"], "#805ad5")
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
            y=alt.Y("Amount:Q", axis=alt.Axis(format=",.0f", title="₪")),
            color=alt.Color("Color:N", scale=None, legend=None),
            tooltip=["Category", alt.Tooltip("Amount:Q", format=",.0f")],
        )
        .properties(height=280)
    )
    st.altair_chart(chart, use_container_width=True)


# ══════════════════════════════════════════
# TAB 2 — Monthly Breakdown
# ══════════════════════════════════════════
with tab2:
    st.subheader("Monthly Breakdown")
    st.caption("Enter a monthly revenue figure to see how that month's money distributes. Uses annual ×12 for bracket calculations.")

    col_mi, col_minfo = st.columns([1, 2])
    with col_mi:
        monthly_rev = st.number_input(
            "Monthly revenue (₪)",
            min_value=0, max_value=500_000,
            value=int(annual_revenue / 12),
            step=1_000,
            key="monthly_rev",
            help="Revenue for a single month (ex-VAT if Osek Murshe). Annualized ×12 for tax bracket calculation."
        )
    with col_minfo:
        projected_annual = monthly_rev * 12
        st.info(
            f"Projected annual: **₪{projected_annual:,.0f}** (₪{monthly_rev:,.0f} × 12). "
            f"Income tax brackets are annual — monthly figures are the annual tax ÷ 12."
        )

    # Run calculation annualizing the monthly revenue
    monthly_inputs = {**inputs, "annual_revenue": projected_annual}
    mr = run_calculation(monthly_inputs)
    ms = mr["summary"]
    mit = mr["income_tax"]
    mni = mr["ni"]
    mvat = mr["vat"]

    st.divider()

    mm1, mm2, mm3, mm4, mm5 = st.columns(5)
    mm1.metric("Revenue", f"₪{monthly_rev:,.0f}")
    mm2.metric("Income Tax", f"₪{ms['net_income_tax']/12:,.0f}",
               delta=f"{mit['effective_it_rate_pct']:.1f}% rate", delta_color="inverse")
    mm3.metric("NI + Health", f"₪{ms['total_ni_health']/12:,.0f}")
    if mvat["status"] == "murshe":
        mm4.metric("VAT to remit", f"₪{mvat['vat_payable']/12:,.0f}",
                   help="Avg monthly VAT payable — remitted bi-monthly to tax authority")
    else:
        mm4.metric("VAT", "Patur")
    mm5.metric("Net Take-Home", f"₪{ms['net_cash_after_taxes']/12:,.0f}",
               delta=f"{100 - ms['effective_total_rate_pct']:.1f}% kept")

    st.divider()

    # Monthly vs annual comparison table
    monthly_table_rows = [
        ("Gross Revenue",        monthly_rev,                          projected_annual),
        ("Business Expenses",    ms["total_expenses_cash_out"] / 12,   ms["total_expenses_cash_out"]),
        ("Income Tax",           ms["net_income_tax"] / 12,            ms["net_income_tax"]),
        ("NI + Health",          ms["total_ni_health"] / 12,           ms["total_ni_health"]),
        ("Net Take-Home",        ms["net_cash_after_taxes"] / 12,      ms["net_cash_after_taxes"]),
    ]
    if mvat["status"] == "murshe":
        monthly_table_rows.insert(3, ("VAT payable (net)", mvat["vat_payable"] / 12, mvat["vat_payable"]))

    st.subheader("Monthly vs Annual")
    mdf = pd.DataFrame(
        [{"Category": r, "Monthly (₪)": f"₪{m:,.0f}", "Annual (₪)": f"₪{a:,.0f}"}
         for r, m, a in monthly_table_rows]
    )
    st.dataframe(mdf, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Where Does This Month's Money Go?")

    m_chart_rows = {
        "Net Take-Home":      (max(0, ms["net_cash_after_taxes"] / 12), "#38a169"),
        "Income Tax":         (ms["net_income_tax"] / 12,               "#e53e3e"),
        "NI + Health":        (ms["total_ni_health"] / 12,              "#dd6b20"),
        "Business Expenses":  (ms["total_expenses_cash_out"] / 12,      "#718096"),
    }
    if mvat["status"] == "murshe":
        m_chart_rows["VAT payable (net)"] = (mvat["vat_payable"] / 12, "#805ad5")

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
            y=alt.Y("Amount:Q", axis=alt.Axis(format=",.0f", title="₪/month")),
            color=alt.Color("Color:N", scale=None, legend=None),
            tooltip=["Category", alt.Tooltip("Amount:Q", format=",.0f")],
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
        st.success(f"💰 **Potential savings: ₪{total_saving:,.0f}/year** — implementing all recommendations below")

    if not recs:
        st.balloons()
        st.success("✅ No significant optimization opportunities found. You're well-optimized!")
    else:
        PRIORITY_ICON = {1: "🔴", 2: "🟡", 3: "🟢"}
        EFFORT_LABEL  = {"low": "🟢 Easy", "medium": "🟡 Some work", "high": "🔴 Complex"}

        for rec in recs:
            icon = PRIORITY_ICON.get(rec["priority"], "⚪")
            saving_str = (
                f"**Save ₪{rec['annual_tax_saving']:,.0f}/yr**"
                if rec.get("annual_tax_saving")
                else "**Savings depend on amount**"
            )
            with st.expander(f"{icon} {rec['action']} — {saving_str}", expanded=rec["priority"] == 1):
                st.write(rec["notes"])
                if rec.get("deadline"):
                    st.info(f"⏰ Deadline: {rec['deadline']}")
                if rec.get("effort"):
                    st.caption(EFFORT_LABEL.get(rec["effort"], rec["effort"]))

    if total_saving > 0:
        st.divider()
        opt_s = opt_result["optimized_scenario"]["summary"]
        c1, c2, c3 = st.columns(3)
        c1.metric(
            "Tax rate after optimization",
            f"{opt_s['effective_total_rate_pct']:.1f}%",
            delta=f"−{s['effective_total_rate_pct'] - opt_s['effective_total_rate_pct']:.1f}%",
        )
        c2.metric(
            "Net take-home after optimization",
            f"₪{opt_s['net_cash_after_taxes']:,.0f}",
            delta=f"+₪{opt_s['net_cash_after_taxes'] - s['net_cash_after_taxes']:,.0f}",
        )
        c3.metric("Total annual savings", f"₪{total_saving:,.0f}")


# ══════════════════════════════════════════
# TAB 4 — Reference
# ══════════════════════════════════════════
with tab4:

    st.subheader("Income Tax Brackets — 2026")
    st.info("⚠️ 2026 change: the 20% bracket was expanded to ₪19,000/month (was ₪16,150 in 2025). Temporary for 2026–2027.")

    brackets_df = pd.DataFrame([
        {"Annual from": "₪0",       "Annual to": "₪84,120",    "Monthly (approx)": "₪0 – ₪7,010",    "Rate": "10%"},
        {"Annual from": "₪84,120",  "Annual to": "₪120,720",   "Monthly (approx)": "₪7,010 – ₪10,060","Rate": "14%"},
        {"Annual from": "₪120,720", "Annual to": "₪228,000 ✨","Monthly (approx)": "₪10,060 – ₪19,000","Rate": "20%"},
        {"Annual from": "₪228,000", "Annual to": "₪301,200",   "Monthly (approx)": "₪19,000 – ₪25,100","Rate": "31%"},
        {"Annual from": "₪301,200", "Annual to": "₪560,280",   "Monthly (approx)": "₪25,100 – ₪46,690","Rate": "35%"},
        {"Annual from": "₪560,280", "Annual to": "₪721,560",   "Monthly (approx)": "₪46,690 – ₪60,130","Rate": "47%"},
        {"Annual from": "₪721,560", "Annual to": "No limit",   "Monthly (approx)": "Above ₪60,130",    "Rate": "50% (47% + 3% surtax)"},
    ])
    st.dataframe(brackets_df, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("National Insurance + Health (Self-Employed, 2026)")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("""
| Income range | NI | Health | **Total** |
|---|---|---|---|
| ₪0 – ₪7,703/month | 4.47% | 3.23% | **7.70%** |
| ₪7,703 – ₪51,910/month | 12.83% | 5.17% | **18.00%** |
        """)
    with c2:
        st.markdown("""
- **Minimum base:** ₪3,442/month — NI charged on this floor even if income is lower
- **Maximum base:** ₪51,910/month — no NI on income above this
- **52%** of your NI+health payment is deductible for income tax
        """)

    st.divider()
    st.subheader("Recognized Expenses — Quick Reference")

    exp_table = pd.DataFrame([
        {"Expense":              "Car (private)",
         "Income Tax %":         "45%",
         "VAT Recovery %":       "66%",
         "Notes":                "Fuel, insurance, servicing, depreciation"},
        {"Expense":              "Mobile phone",
         "Income Tax %":         "50%",
         "VAT Recovery %":       "66%",
         "Notes":                "Max IT deduction ₪1,200/yr incl. device depreciation"},
        {"Expense":              "Home office",
         "Income Tax %":         "Room ratio",
         "VAT Recovery %":       "Room ratio",
         "Notes":                "Rent / electricity / municipal tax / internet"},
        {"Expense":              "Meals & entertainment",
         "Income Tax %":         "80%",
         "VAT Recovery %":       "0% ⚠️",
         "Notes":                "No VAT recovery on meals"},
        {"Expense":              "Computer hardware",
         "Income Tax %":         "33.33%/yr",
         "VAT Recovery %":       "100% in purchase year",
         "Notes":                "Depreciated over 3 years for IT; full VAT in year 1"},
        {"Expense":              "Software / subscriptions",
         "Income Tax %":         "100%",
         "VAT Recovery %":       "100%",
         "Notes":                ""},
        {"Expense":              "Courses / training",
         "Income Tax %":         "100%",
         "VAT Recovery %":       "100%",
         "Notes":                "Not for career change studies"},
        {"Expense":              "Advertising / marketing",
         "Income Tax %":         "100%",
         "VAT Recovery %":       "100%",
         "Notes":                ""},
        {"Expense":              "Accountant / lawyer",
         "Income Tax %":         "100%",
         "VAT Recovery %":       "100%",
         "Notes":                ""},
        {"Expense":              "Business gifts",
         "Income Tax %":         "Up to ₪230/recipient/yr",
         "VAT Recovery %":       "0%",
         "Notes":                "Document recipient name"},
    ])
    st.dataframe(exp_table, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Keren Hishtalmut (Education Fund) — Self-Employed")
    st.markdown("""
| Benefit | Cap | How it works |
|---|---|---|
| Income tax deduction | **₪13,203/yr** | Reduces taxable income directly |
| Capital gains tax exemption | **₪20,566/yr** | Withdrawal is CGT-free after 6 years |

**Optimal deposit: ₪20,566/yr** — covers both benefits.
    """)

    st.divider()
    st.subheader("Pension — Self-Employed")
    st.markdown("""
| Component | Rate | Income ceiling | Max benefit |
|---|---|---|---|
| Expense deduction | 11% of income | ₪232,800/yr | ₪25,608/yr deduction |
| Tax credit | 5.5% × 35% | ₪232,800/yr | ₪4,476/yr direct credit |

Pension deposit does **not** reduce National Insurance — only income tax.
    """)

    st.divider()
    st.caption("⚖️ For planning purposes only. Not a substitute for professional advice from a licensed CPA.")
