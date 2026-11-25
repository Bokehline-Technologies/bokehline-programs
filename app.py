"""Bokehline Programs: a program portfolio dashboard on a fictional manufacturing dataset.

Run it with:  streamlit run app.py

The app is read-only. It opens bokehline_programs.db in read-only mode, so nothing a
visitor does can change the data. All dates are measured against the dataset's
"as of" date (stored in the meta table), so the demo doesn't go stale.
"""
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

DB_PATH = Path(__file__).parent / "bokehline_programs.db"

PHASES = ["Phase 1 - Plan", "Phase 2 - Product Design", "Phase 3 - Process Design",
          "Phase 4 - Validation", "Phase 5 - Launch", "Closed"]
STATUS_ORDER = ["Green", "Yellow", "Red", "Closed"]
STATUS_SCALE = alt.Scale(domain=STATUS_ORDER, range=["#0ca30c", "#fab219", "#d03b3b", "#8a8984"])
BLUE = "#3987e5"
ORANGE = "#d95926"
GATE_SHORT = {"G1 Concept Approval": "G1", "G2 Design Freeze": "G2", "G3 Process Freeze": "G3",
              "G4 PPAP Approval": "G4", "G5 Launch Readiness": "G5"}

st.set_page_config(page_title="Bokehline Programs", page_icon="📈", layout="wide")


# ---------- data ----------
def connect():
    # mode=ro: the app can never write to the database
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


@st.cache_data
def load():
    with connect() as con:
        as_of = date.fromisoformat(con.execute("SELECT value FROM meta WHERE key='as_of_date'").fetchone()[0])
        programs = pd.read_sql_query("""
            SELECT p.program_id, p.program_code AS code, p.name, c.name AS customer, c.segment,
                   pl.plant_code AS plant, e.first_name || ' ' || e.last_name AS pm,
                   p.current_phase AS phase, p.status, p.kickoff_date, p.sop_baseline, p.sop_forecast,
                   p.sop_actual, p.annual_volume, p.status_note
            FROM programs p
            JOIN customers c ON c.customer_id = p.customer_id
            JOIN plants pl ON pl.plant_id = p.plant_id
            JOIN employees e ON e.employee_id = p.program_manager_id""", con)
        gates = pd.read_sql_query("SELECT * FROM gate_reviews", con)
        risks = pd.read_sql_query("""
            SELECT r.*, e.first_name || ' ' || e.last_name AS owner
            FROM risks r LEFT JOIN employees e ON e.employee_id = r.owner_id""", con)
        actions = pd.read_sql_query("""
            SELECT a.*, e.first_name || ' ' || e.last_name AS owner
            FROM actions a LEFT JOIN employees e ON e.employee_id = a.owner_id""", con)
        budget = pd.read_sql_query("SELECT * FROM budget_lines", con)

    for col in ["kickoff_date", "sop_baseline", "sop_forecast", "sop_actual"]:
        programs[col] = pd.to_datetime(programs[col])
    programs["sop_variance"] = (programs["sop_forecast"] - programs["sop_baseline"]).dt.days
    for col in ["planned_date", "forecast_date", "actual_date"]:
        gates[col] = pd.to_datetime(gates[col])
    gates["slip_days"] = (gates["forecast_date"] - gates["planned_date"]).dt.days
    gates["held"] = gates["actual_date"].notna()
    gates["gate_short"] = gates["gate"].map(GATE_SHORT)
    risks["score"] = risks["likelihood"] * risks["severity"]
    for col in ["raised_date", "target_date"]:
        risks[col] = pd.to_datetime(risks[col])
    for col in ["due_date", "completed_date"]:
        actions[col] = pd.to_datetime(actions[col])
    ts = pd.Timestamp(as_of)
    actions["state"] = "Open"
    actions.loc[actions["completed_date"].notna(), "state"] = "Done"
    actions.loc[actions["completed_date"].isna() & (actions["due_date"] < ts), "state"] = "Overdue"
    actions["days_overdue"] = (ts - actions["due_date"]).dt.days.where(actions["state"] == "Overdue")
    return as_of, programs, gates, risks, actions, budget


if not DB_PATH.exists():
    st.error(f"Can't find {DB_PATH.name}. Put it in the same folder as app.py, then refresh.")
    st.stop()

AS_OF, PROGRAMS, GATES, RISKS, ACTIONS, BUDGET = load()
TS = pd.Timestamp(AS_OF)


def fmt_date(x):
    return "" if pd.isna(x) else pd.Timestamp(x).strftime("%b %d, %Y")


# ---------- sidebar ----------
st.sidebar.title("Bokehline Programs")
page = st.sidebar.radio("Go to", ["Portfolio", "Timeline", "Program detail", "Risks & actions", "Gate performance"],
                        label_visibility="collapsed")
st.sidebar.divider()
st.sidebar.subheader("Filters")
seg = st.sidebar.multiselect("Segment", sorted(PROGRAMS["segment"].unique()))
plant = st.sidebar.multiselect("Plant", sorted(PROGRAMS["plant"].unique()))
pm = st.sidebar.multiselect("Program manager", sorted(PROGRAMS["pm"].unique()))
show_closed = st.sidebar.toggle("Include closed programs", value=False)
st.sidebar.divider()
st.sidebar.caption(f"Data as of {AS_OF:%B %d, %Y}.")
st.sidebar.caption("All data is fictional. Companies, people, programs, and figures are made up.")

P = PROGRAMS.copy()
if seg:
    P = P[P["segment"].isin(seg)]
if plant:
    P = P[P["plant"].isin(plant)]
if pm:
    P = P[P["pm"].isin(pm)]
if not show_closed:
    P = P[P["status"] != "Closed"]
ids = set(P["program_id"])
G = GATES[GATES["program_id"].isin(ids)].merge(P[["program_id", "code", "name", "pm"]], on="program_id")
R = RISKS[RISKS["program_id"].isin(ids)].merge(P[["program_id", "code", "name"]], on="program_id")
A = ACTIONS[ACTIONS["program_id"].isin(ids)].merge(P[["program_id", "code", "name"]], on="program_id")

if P.empty:
    st.title(page)
    st.info("No programs match these filters. Clear a filter in the sidebar to see results.")
    st.stop()


def next_gate(program_id):
    g = GATES[(GATES["program_id"] == program_id) & (~GATES["held"])].sort_values("gate_no")
    return (None, None) if g.empty else (g.iloc[0]["gate_short"], g.iloc[0]["forecast_date"])


# ---------- page: portfolio ----------
if page == "Portfolio":
    st.title("Program portfolio")
    active = P[P["status"] != "Closed"]
    upcoming = G[(~G["held"]) & (G["forecast_date"] <= TS + timedelta(days=30))]
    overdue = A[A["state"] == "Overdue"]

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Active programs", len(active))
    c2.metric("At Yellow or Red", int(active["status"].isin(["Yellow", "Red"]).sum()))
    c2.caption(f"{int((active['status'] == 'Red').sum())} at Red")
    c3.metric("Gates due in 30 days", len(upcoming))
    c4.metric("Avg SOP variance", f"{active['sop_variance'].mean():+.0f} days" if len(active) else "–")
    c4.caption("Forecast vs. baseline")
    c5.metric("Overdue actions", len(overdue))

    st.divider()
    left, right = st.columns(2)
    with left:
        st.subheader("Status by phase")
        sp = P.groupby(["phase", "status"]).size().reset_index(name="programs")
        chart = alt.Chart(sp).mark_bar(cornerRadiusEnd=4).encode(
            y=alt.Y("phase:N", sort=PHASES, title=None, axis=alt.Axis(labelLimit=220, labelOverlap=False)),
            x=alt.X("programs:Q", title="Programs", axis=alt.Axis(tickMinStep=1)),
            color=alt.Color("status:N", scale=STATUS_SCALE, sort=STATUS_ORDER, title="Status",
                            legend=alt.Legend(orient="top")),
            order=alt.Order("status_rank:Q"),
            tooltip=[alt.Tooltip("phase:N", title="Phase"), alt.Tooltip("status:N", title="Status"),
                     alt.Tooltip("programs:Q", title="Programs")],
        ).transform_calculate(status_rank="indexof(['Green','Yellow','Red','Closed'], datum.status)")
        st.altair_chart(chart.properties(height=260), width="stretch")

    with right:
        st.subheader("SOP variance by program")
        st.caption("Forecast start of production vs. baseline, in days. Right of zero is late.")
        v = active.sort_values("sop_variance", ascending=False)
        if v.empty:
            st.caption("No active programs in this view.")
        else:
            bars = alt.Chart(v).mark_bar(cornerRadiusEnd=4).encode(
                y=alt.Y("name:N", sort=v["name"].tolist(), title=None, axis=alt.Axis(labelLimit=200, labelOverlap=False)),
                x=alt.X("sop_variance:Q", title="Days vs. baseline"),
                color=alt.Color("status:N", scale=STATUS_SCALE, legend=None),
                tooltip=[alt.Tooltip("code:N", title="Program"), alt.Tooltip("name:N", title="Name"),
                         alt.Tooltip("status:N", title="Status"),
                         alt.Tooltip("sop_baseline:T", title="Baseline SOP", format="%b %d, %Y"),
                         alt.Tooltip("sop_forecast:T", title="Forecast SOP", format="%b %d, %Y"),
                         alt.Tooltip("sop_variance:Q", title="Variance (days)")])
            zero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color="gray").encode(x="x:Q")
            st.altair_chart((bars + zero).properties(height=max(220, 28 * len(v))), width="stretch")

    # ----- gates due soon: plan vs. forecast dumbbell -----
    st.subheader("Gates due in the next 45 days")
    horizon = TS + timedelta(days=45)
    soon = G[(~G["held"]) & (G["forecast_date"] <= horizon)].sort_values("forecast_date").copy()
    if soon.empty:
        st.caption("No gates due in the next 45 days.")
    else:
        st.caption("Dot = forecast date. Hollow circle = original plan. The line between them is the slip.")
        soon["row"] = soon["name"] + "  ·  " + soon["gate_short"]
        soon["vs_plan"] = soon["slip_days"].map(lambda d: "on plan" if d == 0 else f"{d:+d} days")
        soon["timing"] = soon["slip_days"].map(lambda d: "Behind plan" if d > 0 else "On or ahead of plan")
        soon["plan_shown"] = soon["planned_date"].clip(lower=TS - timedelta(days=21))
        soon["label_at"] = soon[["plan_shown", "forecast_date"]].max(axis=1)
        order = soon["row"].tolist()
        xs = alt.Scale(domain=[TS - timedelta(days=21), horizon + timedelta(days=10)])
        y = alt.Y("row:N", sort=order, title=None, axis=alt.Axis(labelLimit=320, labelOverlap=False))
        tip = [alt.Tooltip("code:N", title="Program"), alt.Tooltip("gate:N", title="Gate"),
               alt.Tooltip("planned_date:T", title="Planned", format="%b %d, %Y"),
               alt.Tooltip("forecast_date:T", title="Forecast", format="%b %d, %Y"),
               alt.Tooltip("vs_plan:N", title="Vs. plan"), alt.Tooltip("pm:N", title="Program manager")]
        base = alt.Chart(soon).encode(y=y, tooltip=tip)
        link = base.mark_rule(color="#8a8984", strokeWidth=2, clip=True).encode(
            x=alt.X("plan_shown:T", scale=xs, title=None, axis=alt.Axis(format="%b %d", tickCount=8)),
            x2="forecast_date:T")
        plan = base.mark_point(shape="circle", size=90, filled=False, color="#b8b7b2", strokeWidth=2, clip=True).encode(
            x=alt.X("plan_shown:T", scale=xs))
        fc = base.mark_circle(size=150, opacity=1, stroke="#1a1a19", strokeWidth=2).encode(
            x=alt.X("forecast_date:T", scale=xs),
            color=alt.Color("timing:N", title=None, legend=alt.Legend(orient="top"),
                            scale=alt.Scale(domain=["On or ahead of plan", "Behind plan"], range=[BLUE, ORANGE])))
        lbl = base.mark_text(align="left", dx=12, color="#b8b7b2", fontSize=12).encode(
            x=alt.X("label_at:T", scale=xs), text="vs_plan:N")
        today = alt.Chart(pd.DataFrame({"d": [TS], "t": ["As of " + TS.strftime("%b %d")]}))
        rule = today.mark_rule(color=BLUE, strokeDash=[4, 4]).encode(x=alt.X("d:T", scale=xs))
        rule_lbl = today.mark_text(color=BLUE, dy=-8, align="left", dx=4, fontSize=11).encode(
            x=alt.X("d:T", scale=xs), y=alt.value(0), text="t:N")
        st.altair_chart((rule + link + plan + fc + lbl + rule_lbl).properties(height=max(160, 34 * len(soon))),
                        width="stretch")

    # ----- gate tracker: one row per program -----
    st.subheader("Gate tracker")
    st.caption("Each row is a program, worst first. Cells show the date each gate was held, or its forecast date "
               "if it's still to come. The outlined cell is the program's next gate.")
    rank = {k: i for i, k in enumerate(["Red", "Yellow", "Green", "Closed"])}
    PP = P.assign(_r=P["status"].map(rank)).sort_values(["_r", "sop_variance"], ascending=[True, False])
    order = PP["name"].tolist()
    cols = ["Status", "G1", "G2", "G3", "G4", "G5", "SOP forecast"]
    col_titles = {"Status": "Status", "G1": "G1 Concept", "G2": "G2 Design", "G3": "G3 Process",
                  "G4": "G4 PPAP", "G5": "G5 Launch", "SOP forecast": "SOP forecast"}
    GG = G[G["program_id"].isin(PP["program_id"])].copy()
    nxt = GG[~GG["held"]].sort_values("gate_no").groupby("program_id").head(1)
    GG["is_next"] = GG.index.isin(nxt.index)
    GG["state"] = "Upcoming, on plan"
    GG.loc[~GG["held"] & (GG["slip_days"] > 0), "state"] = "Upcoming, forecast late"
    GG.loc[GG["held"] & (GG["actual_date"] <= GG["planned_date"]), "state"] = "Held on time"
    GG.loc[GG["held"] & (GG["actual_date"] > GG["planned_date"]), "state"] = "Held late"
    GG["when"] = GG["actual_date"].fillna(GG["forecast_date"])
    GG["cell"] = GG["when"].dt.strftime("%b %d '%y").str.replace(" 0", " ")
    GG["col"] = GG["gate_short"]
    GG["vs_plan"] = ((GG["when"] - GG["planned_date"]).dt.days).map(lambda d: "on plan" if d == 0 else f"{d:+d} days")
    cells = GG.drop(columns=[c for c in ["name", "code", "pm"] if c in GG.columns]) \
        .merge(PP[["program_id", "name", "code", "pm"]], on="program_id")

    st_cells = PP[["program_id", "name", "code", "pm", "status", "status_note"]].copy()
    st_cells["col"] = "Status"
    sop = PP[["program_id", "name", "code", "pm", "sop_forecast", "sop_variance", "sop_baseline"]].copy()
    sop["col"] = "SOP forecast"
    sop["cell"] = sop["sop_forecast"].dt.strftime("%b %d '%y").str.replace(" 0", " ") + "  (" + \
        sop["sop_variance"].map(lambda d: "±0" if d == 0 else f"{d:+d}") + ")"

    x = alt.X("col:N", sort=cols, title=None,
              axis=alt.Axis(orient="top", labelAngle=0, labelExpr=f"{col_titles}[datum.value]".replace("'", '"'),
                            labelFontSize=12, ticks=False, domain=False))
    y = alt.Y("name:N", sort=order, title=None, axis=alt.Axis(labelLimit=260, labelOverlap=False, ticks=False,
                                                                domain=False, labelPadding=8))
    status_layer = alt.Chart(st_cells).mark_rect(cornerRadius=4, stroke="#1a1a19", strokeWidth=3).encode(
        x=x, y=y, color=alt.Color("status:N", scale=STATUS_SCALE, title="Status", legend=alt.Legend(orient="top")),
        tooltip=[alt.Tooltip("code:N", title="Program"), alt.Tooltip("status:N", title="Status"),
                 alt.Tooltip("status_note:N", title="Note"), alt.Tooltip("pm:N", title="Program manager")])
    status_text = alt.Chart(st_cells).mark_text(fontSize=12, fontWeight="bold").encode(
        x=x, y=y, text="status:N",
        color=alt.condition(alt.datum.status == "Yellow", alt.value("#1a1a19"), alt.value("white")))
    gate_scale = alt.Scale(domain=["Held on time", "Held late", "Upcoming, on plan", "Upcoming, forecast late"],
                           range=[BLUE, ORANGE, "#3a3a37", "#6e3b26"])
    gate_layer = alt.Chart(cells).mark_rect(cornerRadius=4, stroke="#1a1a19", strokeWidth=3).encode(
        x=x, y=y, color=alt.Color("state:N", scale=gate_scale, title="Gate", legend=alt.Legend(orient="top")),
        tooltip=[alt.Tooltip("code:N", title="Program"), alt.Tooltip("gate:N", title="Gate"),
                 alt.Tooltip("state:N", title="State"),
                 alt.Tooltip("planned_date:T", title="Planned", format="%b %d, %Y"),
                 alt.Tooltip("when:T", title="Held / forecast", format="%b %d, %Y"),
                 alt.Tooltip("vs_plan:N", title="Vs. plan"), alt.Tooltip("result:N", title="Result")])
    next_ring = alt.Chart(cells[cells["is_next"]]).mark_rect(cornerRadius=4, filled=False, stroke="#e8e7e3",
                                                              strokeWidth=2).encode(x=x, y=y)
    gate_text = alt.Chart(cells).mark_text(fontSize=11, color="white").encode(x=x, y=y, text="cell:N")
    sop_text = alt.Chart(sop).mark_text(fontSize=12, color="#e8e7e3", align="center").encode(
        x=x, y=y, text="cell:N",
        tooltip=[alt.Tooltip("code:N", title="Program"),
                 alt.Tooltip("sop_baseline:T", title="Baseline SOP", format="%b %d, %Y"),
                 alt.Tooltip("sop_forecast:T", title="Forecast SOP", format="%b %d, %Y"),
                 alt.Tooltip("sop_variance:Q", title="Days vs. baseline")])
    tracker = alt.layer(status_layer, status_text, gate_layer, next_ring, gate_text, sop_text) \
        .resolve_scale(color="independent") \
        .properties(height=36 * len(PP) + 10) \
        .configure_view(strokeWidth=0).configure_axis(grid=False)
    st.altair_chart(tracker, width="stretch")
    st.caption("SOP forecast: date, then days vs. the baseline SOP (+ is late). Hover any cell for details.")


# ---------- page: timeline ----------
elif page == "Timeline":
    st.title("Program timeline")
    st.caption("Each bar runs from kickoff to forecast start of production, colored by status. "
               "Filled circles are gates held; open circles are gates still to come. "
               "The gray tick marks the baseline SOP.")
    T = P.sort_values("kickoff_date").copy()
    T["label"] = T["code"] + "  " + T["name"]
    order = T["label"].tolist()
    gt = G.merge(T[["program_id", "label"]], on="program_id")
    gt["date"] = gt["actual_date"].fillna(gt["forecast_date"])
    gt["state"] = gt["held"].map({True: "Held", False: "Upcoming"})

    y = alt.Y("label:N", sort=order, title=None, axis=alt.Axis(labelLimit=260, labelOverlap=False))
    bars = alt.Chart(T).mark_bar(height=12, cornerRadius=4, opacity=0.85).encode(
        y=y, x=alt.X("kickoff_date:T", title=None, axis=alt.Axis(format="%b %Y")),
        x2="sop_forecast:T", color=alt.Color("status:N", scale=STATUS_SCALE, title="Status",
                                              legend=alt.Legend(orient="top")),
        tooltip=[alt.Tooltip("code:N", title="Program"), alt.Tooltip("name:N", title="Name"),
                 alt.Tooltip("status:N", title="Status"), alt.Tooltip("phase:N", title="Phase"),
                 alt.Tooltip("kickoff_date:T", title="Kickoff", format="%b %d, %Y"),
                 alt.Tooltip("sop_forecast:T", title="Forecast SOP", format="%b %d, %Y"),
                 alt.Tooltip("sop_variance:Q", title="Variance (days)")])
    baseline = alt.Chart(T).mark_tick(color="#8a8984", thickness=2, size=18).encode(
        y=y, x="sop_baseline:T",
        tooltip=[alt.Tooltip("name:N", title="Name"),
                 alt.Tooltip("sop_baseline:T", title="Baseline SOP", format="%b %d, %Y")])
    pts = alt.Chart(gt).mark_point(size=60, strokeWidth=2).encode(
        y=y, x="date:T",
        shape=alt.value("circle"),
        fill=alt.condition("datum.held", alt.value("#1f2328"), alt.value("white")),
        color=alt.value("#1f2328"),
        tooltip=[alt.Tooltip("code:N", title="Program"), alt.Tooltip("gate:N", title="Gate"),
                 alt.Tooltip("state:N", title="State"), alt.Tooltip("date:T", title="Date", format="%b %d, %Y"),
                 alt.Tooltip("slip_days:Q", title="Vs. plan (days)"), alt.Tooltip("result:N", title="Result")])
    today = alt.Chart(pd.DataFrame({"d": [TS], "t": [f"As of {AS_OF:%b %d, %Y}"]}))
    rule = today.mark_rule(color=BLUE, strokeDash=[4, 4], strokeWidth=2).encode(x="d:T")
    label = today.mark_text(color=BLUE, align="left", dx=6, dy=-8, baseline="bottom").encode(
        x="d:T", y=alt.value(0), text="t:N")
    st.altair_chart((bars + baseline + pts + rule + label).properties(height=max(260, 30 * len(T))),
                    width="stretch")


# ---------- page: program detail ----------
elif page == "Program detail":
    st.title("Program detail")
    labels = (P["code"] + " – " + P["name"]).tolist()
    pick = st.selectbox("Program", labels)
    prog = P.iloc[labels.index(pick)]
    pid = int(prog["program_id"])

    st.subheader(prog["name"])
    st.caption(f"{prog['code']} · {prog['customer']} ({prog['segment']}) · {prog['plant']} · PM {prog['pm']}")
    box = {"Green": st.success, "Yellow": st.warning, "Red": st.error, "Closed": st.info}[prog["status"]]
    box(f"**{prog['status']}.** {prog['status_note']}")

    # ----- phase progress strip -----
    steps = [p.split(" - ") for p in PHASES[:5]]
    cur = 6 if prog["status"] == "Closed" else int(prog["phase"].split(" ")[1].split(" ")[0])
    strip = pd.DataFrame({
        "n": [int(n.split(" ")[1]) for n, _ in steps],
        "label": [("✓ " if int(n.split(" ")[1]) < cur else "") + f"{n.split(' ')[1]}  {name}" for n, name in steps]})
    strip["state"] = strip["n"].map(lambda n: "Complete" if n < cur else ("Current phase" if n == cur else "Not started"))
    strip["row"] = "phase"
    sx = alt.X("n:O", title=None, axis=None)
    sy = alt.Y("row:N", title=None, axis=None, scale=alt.Scale(paddingInner=0, paddingOuter=0))
    phase_cells = alt.Chart(strip).mark_rect(cornerRadius=6, stroke="#1a1a19", strokeWidth=4).encode(
        x=sx, y=sy, color=alt.Color("state:N", title=None, legend=None, scale=alt.Scale(
            domain=["Complete", "Current phase", "Not started"], range=[BLUE, "#e8e7e3", "#3a3a37"])),
        tooltip=[alt.Tooltip("label:N", title="Phase"), alt.Tooltip("state:N", title="State")])
    phase_text = alt.Chart(strip).mark_text(fontSize=13, fontWeight="bold").encode(
        x=sx, y=sy, text="label:N",
        color=alt.condition(alt.datum.state == "Current phase", alt.value("#1a1a19"),
                            alt.value("white")))
    st.altair_chart((phase_cells + phase_text).properties(height=48).configure_view(strokeWidth=0),
                    width="stretch")
    st.caption("Phase progress. Blue = complete, white = current phase, gray = not started."
               if cur <= 5 else "All phases complete. Program closed after launch.")

    b_all = BUDGET[BUDGET["program_id"] == pid]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Baseline SOP", fmt_date(prog["sop_baseline"]))
    m2.metric("Forecast SOP", fmt_date(prog["sop_forecast"]))
    m3.metric("SOP variance", f"{prog['sop_variance']:+d} days")
    m4.metric("Budget used", f"{100 * b_all['spent_to_date'].sum() / b_all['budget'].sum():.0f}%")

    # ----- gate schedule: plan vs. held / forecast -----
    st.subheader("Gate schedule")
    g = GATES[GATES["program_id"] == pid].sort_values("gate_no").copy()
    g["when"] = g["actual_date"].fillna(g["forecast_date"])
    g["days"] = (g["when"] - g["planned_date"]).dt.days
    g["state"] = "Upcoming, on plan"
    g.loc[~g["held"] & (g["days"] > 0), "state"] = "Upcoming, forecast late"
    g.loc[g["held"] & (g["days"] <= 0), "state"] = "Held on time"
    g.loc[g["held"] & (g["days"] > 0), "state"] = "Held late"
    g["vs_plan"] = g["days"].map(lambda d: "on plan" if d == 0 else f"{d:+d} days")
    g["label"] = g["vs_plan"] + g["result"].map(lambda r: f"  ·  {r}" if isinstance(r, str) else "")
    g["label_at"] = g[["planned_date", "when"]].max(axis=1)
    lo = min(g["planned_date"].min(), g["when"].min()) - timedelta(days=20)
    hi = max(g["planned_date"].max(), g["when"].max()) + timedelta(days=75)
    gx = alt.Scale(domain=[lo, hi])
    gy = alt.Y("gate:N", sort=g["gate"].tolist(), title=None, axis=alt.Axis(labelLimit=220, labelOverlap=False))
    tip = [alt.Tooltip("gate:N", title="Gate"), alt.Tooltip("state:N", title="State"),
           alt.Tooltip("planned_date:T", title="Planned", format="%b %d, %Y"),
           alt.Tooltip("when:T", title="Held / forecast", format="%b %d, %Y"),
           alt.Tooltip("vs_plan:N", title="Vs. plan"), alt.Tooltip("result:N", title="Result")]
    gb = alt.Chart(g).encode(y=gy, tooltip=tip)
    g_link = gb.mark_rule(color="#8a8984", strokeWidth=2).encode(
        x=alt.X("planned_date:T", scale=gx, title=None, axis=alt.Axis(format="%b '%y", tickCount=10)), x2="when:T")
    g_plan = gb.mark_point(shape="circle", size=90, filled=False, color="#b8b7b2", strokeWidth=2).encode(
        x=alt.X("planned_date:T", scale=gx))
    g_dot = gb.mark_circle(size=190, opacity=1, stroke="#1a1a19", strokeWidth=2).encode(
        x=alt.X("when:T", scale=gx),
        color=alt.Color("state:N", title=None, legend=alt.Legend(orient="top"), scale=alt.Scale(
            domain=["Held on time", "Held late", "Upcoming, on plan", "Upcoming, forecast late"],
            range=[BLUE, ORANGE, "#8a8984", "#a35a3a"])))
    g_lbl = gb.mark_text(align="left", dx=14, color="#b8b7b2", fontSize=12).encode(
        x=alt.X("label_at:T", scale=gx), text="label:N")
    asof = alt.Chart(pd.DataFrame({"d": [TS], "t": ["As of " + TS.strftime("%b %d")]}))
    a_rule = asof.mark_rule(color=BLUE, strokeDash=[4, 4]).encode(x=alt.X("d:T", scale=gx))
    a_lbl = asof.mark_text(color=BLUE, dy=-8, align="left", dx=4, fontSize=11).encode(
        x=alt.X("d:T", scale=gx), y=alt.value(0), text="t:N")
    st.altair_chart((a_rule + g_link + g_plan + g_dot + g_lbl + a_lbl).properties(height=230), width="stretch")
    st.caption("Hollow circle = planned date. Dot = date held, or forecast if still to come. "
               "Text = days vs. plan and the gate result.")

    left, right = st.columns(2)
    # ----- risks: score bars -----
    with left:
        st.subheader("Risks")
        r = RISKS[RISKS["program_id"] == pid].copy()
        if r.empty:
            st.caption("No risks logged.")
        else:
            r["s_rank"] = r["status"].map({"Open": 0, "Mitigating": 1, "Closed": 2})
            r = r.sort_values(["s_rank", "score"], ascending=[True, False])
            r["lxs"] = "L" + r["likelihood"].astype(str) + " × S" + r["severity"].astype(str)
            ry = alt.Y("title:N", sort=r["title"].tolist(), title=None,
                       axis=alt.Axis(labelLimit=230, labelOverlap=False))
            rb = alt.Chart(r).encode(y=ry, tooltip=[
                alt.Tooltip("title:N", title="Risk"), alt.Tooltip("category:N", title="Category"),
                alt.Tooltip("status:N", title="Status"), alt.Tooltip("score:Q", title="Score"),
                alt.Tooltip("lxs:N", title="Likelihood × severity"), alt.Tooltip("owner:N", title="Owner"),
                alt.Tooltip("target_date:T", title="Target", format="%b %d, %Y"),
                alt.Tooltip("mitigation:N", title="Mitigation")])
            r_bar = rb.mark_bar(cornerRadiusEnd=4, height=16).encode(
                x=alt.X("score:Q", title="Risk score (likelihood × severity)", scale=alt.Scale(domain=[0, 25])),
                color=alt.Color("status:N", title=None, legend=alt.Legend(orient="top"), scale=alt.Scale(
                    domain=["Open", "Mitigating", "Closed"], range=[ORANGE, BLUE, "#5c5b57"])))
            r_txt = rb.mark_text(align="left", dx=6, color="#b8b7b2", fontSize=11).encode(
                x="score:Q", text="lxs:N")
            hi_rule = alt.Chart(pd.DataFrame({"x": [16], "t": ["High (16+)"]}))
            r_hi = hi_rule.mark_rule(color="#8a8984", strokeDash=[3, 3]).encode(x="x:Q")
            r_hi_t = hi_rule.mark_text(color="#8a8984", dy=-8, align="left", dx=4, fontSize=11).encode(
                x="x:Q", y=alt.value(0), text="t:N")
            st.altair_chart((r_hi + r_bar + r_txt + r_hi_t).properties(height=90 + 46 * len(r)),
                            width="stretch")
            st.caption("Hover a bar for owner, target date and mitigation.")

    # ----- actions: due-date timeline -----
    with right:
        st.subheader("Actions")
        a = ACTIONS[ACTIONS["program_id"] == pid].sort_values("due_date").copy()
        if a.empty:
            st.caption("No actions logged.")
        else:
            a["owner_short"] = a["owner"].str.split(" ").str[0]
            a["late"] = a["days_overdue"].map(lambda d: f"{int(d)} days overdue" if pd.notna(d) else "")
            a["text"] = a["owner_short"] + a["late"].map(lambda t: f" · {t}" if t else "")
            ax_lo = min(a["due_date"].min(), TS) - timedelta(days=10)
            ax_hi = max(a["due_date"].max(), TS) + timedelta(days=40)
            axs = alt.Scale(domain=[ax_lo, ax_hi])
            ay = alt.Y("description:N", sort=a["description"].tolist(), title=None,
                       axis=alt.Axis(labelLimit=230, labelOverlap=False))
            ab = alt.Chart(a).encode(y=ay, tooltip=[
                alt.Tooltip("description:N", title="Action"), alt.Tooltip("owner:N", title="Owner"),
                alt.Tooltip("due_date:T", title="Due", format="%b %d, %Y"),
                alt.Tooltip("completed_date:T", title="Completed", format="%b %d, %Y"),
                alt.Tooltip("state:N", title="State")])
            a_dot = ab.mark_circle(size=170, opacity=1, stroke="#1a1a19", strokeWidth=2).encode(
                x=alt.X("due_date:T", scale=axs, title="Due date", axis=alt.Axis(format="%b %d", tickCount=6)),
                color=alt.Color("state:N", title=None, legend=alt.Legend(orient="top"), scale=alt.Scale(
                    domain=["Overdue", "Open", "Done"], range=[ORANGE, BLUE, "#5c5b57"])))
            a_txt = ab.mark_text(align="left", dx=12, color="#b8b7b2", fontSize=11).encode(
                x=alt.X("due_date:T", scale=axs), text="text:N")
            a_now = alt.Chart(pd.DataFrame({"d": [TS]})).mark_rule(color=BLUE, strokeDash=[4, 4]).encode(
                x=alt.X("d:T", scale=axs))
            st.altair_chart((a_now + a_dot + a_txt).properties(height=90 + 46 * len(a)),
                            width="stretch")
            st.caption("Dot = due date. Dashed line = as-of date. Hover for details.")

    st.subheader("Budget vs. spend")
    b = b_all.copy()
    b["pct"] = (100 * b["spent_to_date"] / b["budget"]).round(0)
    tb, ts_ = b["budget"].sum(), b["spent_to_date"].sum()
    st.caption(f"Total: ${ts_:,.0f} spent of ${tb:,.0f} budget ({100 * ts_ / tb:.0f}%).")
    b["label_x"] = b[["budget", "spent_to_date"]].max(axis=1)
    base = alt.Chart(b).encode(y=alt.Y("category:N", sort=b["category"].tolist(), title=None,
                                       axis=alt.Axis(labelLimit=200)))
    budget_bar = base.mark_bar(color="#8a8984", opacity=0.35, cornerRadiusEnd=4, height=22).encode(
        x=alt.X("budget:Q", title="Dollars", axis=alt.Axis(format="$,.0f")),
        tooltip=[alt.Tooltip("category:N", title="Category"), alt.Tooltip("budget:Q", title="Budget", format="$,.0f"),
                 alt.Tooltip("spent_to_date:Q", title="Spent", format="$,.0f"), alt.Tooltip("pct:Q", title="% used")])
    spent_bar = base.mark_bar(cornerRadiusEnd=4, height=10).encode(
        x="spent_to_date:Q",
        color=alt.condition(alt.datum.pct > 100, alt.value(ORANGE), alt.value(BLUE)),
        tooltip=[alt.Tooltip("category:N", title="Category"), alt.Tooltip("budget:Q", title="Budget", format="$,.0f"),
                 alt.Tooltip("spent_to_date:Q", title="Spent", format="$,.0f"), alt.Tooltip("pct:Q", title="% used")])
    pct = base.mark_text(align="left", dx=6, color="gray").encode(
        x="label_x:Q", text="pct_label:N").transform_calculate(pct_label="format(datum.pct, '.0f') + '%'")
    st.altair_chart((budget_bar + spent_bar + pct).properties(height=200), width="stretch")
    st.caption("Wide gray bar: budget. Narrow bar: spent to date (orange if over budget). Number: % of budget used.")


# ---------- page: risks & actions ----------
elif page == "Risks & actions":
    st.title("Risks and actions")
    live = R[R["status"] != "Closed"]
    od = A[A["state"] == "Overdue"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Open risks", len(live))
    c2.metric("High risks (score 15+)", int((live["score"] >= 15).sum()))
    c3.metric("Overdue actions", len(od))

    left, right = st.columns(2)
    with left:
        st.subheader("Risk heat map")
        st.caption("Open and mitigating risks by likelihood and severity.")
        grid = pd.DataFrame([(l, s) for l in range(1, 6) for s in range(1, 6)], columns=["likelihood", "severity"])
        counts = live.groupby(["likelihood", "severity"]).size().reset_index(name="risks")
        grid = grid.merge(counts, how="left").fillna({"risks": 0})
        grid["risks"] = grid["risks"].astype(int)
        heat = alt.Chart(grid).mark_rect(stroke="white", strokeWidth=2, cornerRadius=4).encode(
            x=alt.X("severity:O", title="Severity"),
            y=alt.Y("likelihood:O", title="Likelihood", sort="descending"),
            color=alt.Color("risks:Q", title="Risks", scale=alt.Scale(scheme="blues")),
            tooltip=[alt.Tooltip("likelihood:O", title="Likelihood"), alt.Tooltip("severity:O", title="Severity"),
                     alt.Tooltip("risks:Q", title="Risks")])
        text = alt.Chart(grid[grid["risks"] > 0]).mark_text(fontSize=14).encode(
            x="severity:O", y=alt.Y("likelihood:O", sort="descending"), text="risks:Q",
            color=alt.condition("datum.risks >= 4", alt.value("white"), alt.value("#1f2328")))
        st.altair_chart((heat + text).properties(height=320), width="stretch")
    with right:
        st.subheader("Open risks by category")
        cat = live.groupby("category").size().reset_index(name="risks").sort_values("risks", ascending=False)
        chart = alt.Chart(cat).mark_bar(color=BLUE, cornerRadiusEnd=4).encode(
            y=alt.Y("category:N", sort=cat["category"].tolist(), title=None, axis=alt.Axis(labelOverlap=False)),
            x=alt.X("risks:Q", title="Risks", axis=alt.Axis(tickMinStep=1)),
            tooltip=[alt.Tooltip("category:N", title="Category"), alt.Tooltip("risks:Q", title="Risks")])
        st.altair_chart(chart.properties(height=320), width="stretch")

    st.subheader("Top risks")
    top = live.sort_values(["score", "target_date"], ascending=[False, True]).head(10)
    st.dataframe(pd.DataFrame({
        "Score": top["score"], "Program": top["code"], "Name": top["name"], "Risk": top["title"],
        "Status": top["status"], "Owner": top["owner"], "Target": top["target_date"].dt.date,
        "Mitigation": top["mitigation"]}), hide_index=True, width="stretch")

    st.subheader("Overdue actions")
    if od.empty:
        st.caption("No overdue actions in this view.")
    else:
        by_owner = od.groupby("owner").size().reset_index(name="actions").sort_values("actions", ascending=False)
        chart = alt.Chart(by_owner).mark_bar(color=ORANGE, cornerRadiusEnd=4).encode(
            y=alt.Y("owner:N", sort=by_owner["owner"].tolist(), title=None, axis=alt.Axis(labelLimit=200, labelOverlap=False)),
            x=alt.X("actions:Q", title="Overdue actions", axis=alt.Axis(tickMinStep=1)),
            tooltip=[alt.Tooltip("owner:N", title="Owner"), alt.Tooltip("actions:Q", title="Overdue")])
        st.altair_chart(chart.properties(height=max(160, 32 * len(by_owner))), width="stretch")
        o = od.sort_values("days_overdue", ascending=False)
        st.dataframe(pd.DataFrame({
            "Days overdue": o["days_overdue"].astype(int), "Program": o["code"], "Action": o["description"],
            "Owner": o["owner"], "Due": o["due_date"].dt.date}), hide_index=True, width="stretch")


# ---------- page: gate performance ----------
elif page == "Gate performance":
    st.title("Gate performance")
    st.caption("Gates already held, for the programs in the current filter. "
               "Turn on “Include closed programs” to see the full history.")
    held = G[G["held"]].copy()
    if held.empty:
        st.info("No gates held yet for the programs in this view.")
        st.stop()
    held["on_time"] = held["slip_days"] <= 0
    c1, c2, c3 = st.columns(3)
    c1.metric("Gates held", len(held))
    c2.metric("On time", f"{100 * held['on_time'].mean():.0f}%")
    c3.metric("Avg slip", f"{held['slip_days'].mean():+.1f} days")

    left, right = st.columns(2)
    with left:
        st.subheader("Average slip by gate")
        s = held.groupby(["gate_no", "gate"]).agg(avg_slip=("slip_days", "mean"), n=("slip_days", "size")).reset_index()
        chart = alt.Chart(s).mark_bar(color=BLUE, cornerRadiusEnd=4).encode(
            y=alt.Y("gate:N", sort=s.sort_values("gate_no")["gate"].tolist(), title=None, axis=alt.Axis(labelLimit=200, labelOverlap=False)),
            x=alt.X("avg_slip:Q", title="Average days vs. plan"),
            tooltip=[alt.Tooltip("gate:N", title="Gate"), alt.Tooltip("avg_slip:Q", title="Avg slip (days)", format=".1f"),
                     alt.Tooltip("n:Q", title="Gates held")])
        zero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color="gray").encode(x="x:Q")
        st.altair_chart((chart + zero).properties(height=240), width="stretch")
    with right:
        st.subheader("Gate results")
        mix = held.groupby(["gate_no", "gate", "result"]).size().reset_index(name="gates")
        chart = alt.Chart(mix).mark_bar(cornerRadiusEnd=4).encode(
            y=alt.Y("gate:N", sort=mix.sort_values("gate_no")["gate"].unique().tolist(), title=None,
                    axis=alt.Axis(labelLimit=200, labelOverlap=False)),
            x=alt.X("gates:Q", title="Gates held", axis=alt.Axis(tickMinStep=1)),
            color=alt.Color("result:N", scale=alt.Scale(domain=["Pass", "Conditional"], range=[BLUE, ORANGE]),
                            title="Result", legend=alt.Legend(orient="top")),
            tooltip=[alt.Tooltip("gate:N", title="Gate"), alt.Tooltip("result:N", title="Result"),
                     alt.Tooltip("gates:Q", title="Gates")])
        st.altair_chart(chart.properties(height=280), width="stretch")

    st.subheader("On-time gates by program manager")
    by_pm = held.groupby("pm").agg(on_time=("on_time", "mean"), n=("on_time", "size")).reset_index()
    by_pm["pct"] = (100 * by_pm["on_time"]).round(0)
    by_pm = by_pm.sort_values("pct", ascending=False)
    chart = alt.Chart(by_pm).mark_bar(color=BLUE, cornerRadiusEnd=4).encode(
        y=alt.Y("pm:N", sort=by_pm["pm"].tolist(), title=None, axis=alt.Axis(labelOverlap=False)),
        x=alt.X("pct:Q", title="Gates held on or before plan (%)", scale=alt.Scale(domain=[0, 100])),
        tooltip=[alt.Tooltip("pm:N", title="Program manager"), alt.Tooltip("pct:Q", title="On time (%)"),
                 alt.Tooltip("n:Q", title="Gates held")])
    text = chart.mark_text(align="left", dx=4, color="gray").encode(text="pct_label:N").transform_calculate(pct_label="format(datum.pct, '.0f') + '%'")
    st.altair_chart((chart + text).properties(height=160), width="stretch")
