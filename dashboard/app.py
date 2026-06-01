import os
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import mysql.connector
from ai_agent import run_agent, REPORT_PROMPT
from queries import (
    get_kpis_bookings,
    get_revenue_by_airline,
    get_monthly_revenue,
    get_top_routes_revenue,
    get_load_factor,
    get_worst_routes_revenue,
    get_worst_airlines_revenue,
    get_worst_load_factor,
    get_kpis_flights,
    get_top_routes_flights,
    get_flights_per_airline,
    get_flights_per_weekday,
    get_top_departure_airports,
    get_monthly_flights,
    get_worst_routes_flights,
    DB_CONFIG,
)

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Flughafen BI Dashboard",
    page_icon="",
    layout="wide",
)

# ── Custom styling ────────────────────────────────────────────────────────────

st.markdown("""
<style>
    [data-testid="stMetric"] {
        background: #1e2130;
        border-radius: 10px;
        padding: 16px 20px;
    }
    [data-testid="stMetricLabel"]  { color: #a0aec0; font-size: 0.85rem; }
    [data-testid="stMetricValue"]  { color: #f0f4ff; font-size: 1.6rem; }
    .section-divider { margin: 8px 0 24px; border-top: 1px solid #2d3748; }
</style>
""", unsafe_allow_html=True)

# ── DB connection check ───────────────────────────────────────────────────────

@st.cache_resource
def check_connection():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        conn.close()
        return True
    except Exception as e:
        return str(e)

status = check_connection()
if status is not True:
    st.error(f"Keine Datenbankverbindung: {status}")
    st.info(
        "Stelle sicher, dass MySQL läuft und passe die Verbindungsdaten "
        "über Umgebungsvariablen an: `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`."
    )
    st.stop()

# ── Header ────────────────────────────────────────────────────────────────────

st.title("Flughafen BI Dashboard")
st.caption("Datenquelle: FlughafenDB")


def auto_chart(df, title: str):
    """Wählt automatisch den passenden Diagrammtyp für einen DataFrame."""
    if df.empty or len(df.columns) < 2:
        return None
    num_cols = df.select_dtypes(include="number").columns.tolist()
    str_cols = [c for c in df.columns if c not in num_cols]
    if not num_cols:
        return None
    y = num_cols[0]
    # Zeitreihe
    time_col = next(
        (c for c in df.columns if any(k in c.lower() for k in ["month", "datum", "date", "monat"])),
        None,
    )
    if time_col:
        fig = px.line(
            df.sort_values(time_col), x=time_col, y=num_cols,
            title=title, markers=True,
        )
        fig.update_layout(height=300, margin=dict(l=0, r=0, t=40, b=0))
        return fig
    # Kategorisch → horizontaler Balken
    if str_cols:
        df_s = df.sort_values(y)
        fig = px.bar(
            df_s, x=y, y=str_cols[0], orientation="h", title=title,
            color=y, color_continuous_scale="Blues",
            height=max(280, len(df_s) * 30),
        )
        fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=10, t=40, b=0))
        return fig
    return None


tab1, tab2, tab3 = st.tabs(["Buchungs- & Umsatzanalyse", "Flugbetrieb & Routen", "KI-Analyst"])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Buchungs- & Umsatzanalyse
# ══════════════════════════════════════════════════════════════════════════════

with tab1:

    # KPIs
    with st.spinner("Lade Kennzahlen …"):
        kpis = get_kpis_bookings()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Gesamtumsatz",  f"$ {kpis['total_revenue']:,.0f}")
    c2.metric("Buchungen",     f"{int(kpis['total_bookings']):,}")
    c3.metric("Ø Ticketpreis", f"$ {kpis['avg_price']:.2f}")
    c4.metric("Passagiere",    f"{int(kpis['passengers']):,}")

    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)

    # Row 1 — Umsatz pro Airline + Top Routen
    col_l, col_r = st.columns(2)

    with col_l:
        st.subheader("Umsatz pro Airline (Top 15)")
        with st.spinner():
            df_airline_rev = get_revenue_by_airline()
        df_airline_rev = df_airline_rev.sort_values("total_revenue")
        fig = px.bar(
            df_airline_rev,
            x="total_revenue",
            y="airlinename",
            orientation="h",
            labels={"total_revenue": "Umsatz ($)", "airlinename": "Airline"},
            color="total_revenue",
            color_continuous_scale="Blues",
            height=460,
        )
        fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=10, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

    with col_r:
        st.subheader("Top 10 Routen nach Umsatz")
        with st.spinner():
            df_routes_rev = get_top_routes_revenue()
        df_routes_rev = df_routes_rev.sort_values("revenue")
        fig = px.bar(
            df_routes_rev,
            x="revenue",
            y="route",
            orientation="h",
            labels={"revenue": "Umsatz ($)", "route": "Route"},
            color="revenue",
            color_continuous_scale="Greens",
            height=460,
        )
        fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=10, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

    # Row 2 — Monatlicher Umsatz (dual axis)
    st.subheader("Monatlicher Umsatz & Buchungsvolumen")
    with st.spinner():
        df_monthly = get_monthly_revenue()

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df_monthly["month"],
        y=df_monthly["bookings"],
        name="Buchungen",
        yaxis="y2",
        marker_color="rgba(52,152,219,0.35)",
    ))
    fig.add_trace(go.Scatter(
        x=df_monthly["month"],
        y=df_monthly["revenue"],
        name="Umsatz ($)",
        mode="lines+markers",
        line=dict(color="#2ecc71", width=2),
        marker=dict(size=4),
    ))
    fig.update_layout(
        yaxis=dict(title="Umsatz ($)", tickformat="$,.0f"),
        yaxis2=dict(title="Buchungen", overlaying="y", side="right", tickformat=","),
        legend=dict(orientation="h", y=1.08),
        height=360,
        margin=dict(l=0, r=0, t=30, b=0),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Row 3 — Auslastungsrate
    st.subheader("Auslastungsrate (Seat Load Factor) pro Airline – Top 15")
    with st.spinner():
        df_load = get_load_factor()

    fig = px.bar(
        df_load,
        x="airlinename",
        y="load_factor",
        labels={"airlinename": "Airline", "load_factor": "Auslastung (%)"},
        color="load_factor",
        color_continuous_scale="RdYlGn",
        height=360,
        text="load_factor",
    )
    fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
    fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, use_container_width=True)

    # ── Optimierungspotenzial ────────────────────────────────────────────────
    st.divider()
    st.subheader("Optimierungspotenzial")
    st.caption("Schwache Performer — Basis für Streichungs- oder Restrukturierungsentscheide (min. Buchungsschwelle berücksichtigt)")

    col_l, col_r = st.columns(2)

    with col_l:
        st.markdown("**Schlechteste Routen nach Umsatz** *(min. 50 Buchungen)*")
        with st.spinner():
            df_wr = get_worst_routes_revenue()
        df_wr = df_wr.sort_values("revenue", ascending=False)
        fig = px.bar(
            df_wr, x="revenue", y="route", orientation="h",
            labels={"revenue": "Umsatz ($)", "route": "Route"},
            color="revenue", color_continuous_scale="Reds_r",
            height=380,
            hover_data={"bookings": True, "avg_price": True},
        )
        fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=10, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

    with col_r:
        st.markdown("**Airlines mit geringstem Umsatz** *(min. 500 Buchungen)*")
        with st.spinner():
            df_wa = get_worst_airlines_revenue()
        df_wa = df_wa.sort_values("revenue", ascending=False)
        fig = px.bar(
            df_wa, x="revenue", y="airlinename", orientation="h",
            labels={"revenue": "Umsatz ($)", "airlinename": "Airline"},
            color="revenue", color_continuous_scale="Oranges_r",
            height=380,
            hover_data={"bookings": True, "avg_price": True},
        )
        fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=10, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("**Airlines mit niedrigstem Load Factor** *(min. 1 000 Buchungen — leere Sitze kosten Geld)*")
    with st.spinner():
        df_wlf = get_worst_load_factor()
    fig = px.bar(
        df_wlf, x="airlinename", y="load_factor",
        labels={"airlinename": "Airline", "load_factor": "Auslastung (%)"},
        color="load_factor", color_continuous_scale="RdYlGn",
        height=340, text="load_factor",
        hover_data={"bookings": True, "capacity": True},
    )
    fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
    fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Flugbetrieb & Routen
# ══════════════════════════════════════════════════════════════════════════════

with tab2:

    # KPIs
    with st.spinner("Lade Kennzahlen …"):
        kpis2 = get_kpis_flights()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Gesamtflüge",    f"{int(kpis2['total_flights']):,}")
    c2.metric("Airlines",       f"{int(kpis2['airlines']):,}")
    c3.metric("Flughäfen",      f"{int(kpis2['airports']):,}")
    c4.metric("Flugzeugtypen",  f"{int(kpis2['airplane_types']):,}")

    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)

    # Row 1 — Top Routen + Flüge pro Airline
    col_l, col_r = st.columns(2)

    with col_l:
        st.subheader("Top 10 Routen nach Fluganzahl")
        with st.spinner():
            df_routes_fl = get_top_routes_flights()
        df_routes_fl = df_routes_fl.sort_values("flights")
        fig = px.bar(
            df_routes_fl,
            x="flights",
            y="route",
            orientation="h",
            labels={"flights": "Anzahl Flüge", "route": "Route"},
            color="flights",
            color_continuous_scale="Blues",
            height=420,
        )
        fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=10, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

    with col_r:
        st.subheader("Flüge pro Airline (Top 15)")
        with st.spinner():
            df_al_fl = get_flights_per_airline()
        df_al_fl = df_al_fl.sort_values("flights")
        fig = px.bar(
            df_al_fl,
            x="flights",
            y="airlinename",
            orientation="h",
            labels={"flights": "Anzahl Flüge", "airlinename": "Airline"},
            color="flights",
            color_continuous_scale="Purples",
            height=420,
        )
        fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=10, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

    # Row 2 — Wochentage + Top Abflughäfen
    col_l, col_r = st.columns(2)

    with col_l:
        st.subheader("Flugverteilung nach Wochentag")
        with st.spinner():
            df_wd = get_flights_per_weekday()
        fig = px.bar(
            df_wd,
            x="weekday",
            y="flights",
            labels={"weekday": "Wochentag", "flights": "Anzahl Flüge"},
            color="flights",
            color_continuous_scale="Oranges",
            height=360,
            text="flights",
        )
        fig.update_traces(texttemplate="%{text:,}", textposition="outside")
        fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

    with col_r:
        st.subheader("Top 10 Abflughäfen")
        with st.spinner():
            df_dep = get_top_departure_airports()
        df_dep = df_dep.sort_values("departures")
        df_dep["label"] = df_dep["city"] + " (" + df_dep["country"] + ")"
        fig = px.bar(
            df_dep,
            x="departures",
            y="label",
            orientation="h",
            labels={"departures": "Abflüge", "label": "Stadt"},
            color="departures",
            color_continuous_scale="Teal",
            height=360,
        )
        fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=10, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

    # Row 3 — Monatliche Flugentwicklung
    st.subheader("Monatliche Flugentwicklung")
    with st.spinner():
        df_mfl = get_monthly_flights()

    fig = px.area(
        df_mfl,
        x="month",
        y="flights",
        labels={"month": "Monat", "flights": "Anzahl Flüge"},
        color_discrete_sequence=["#3498db"],
        height=320,
    )
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, use_container_width=True)

    # ── Optimierungspotenzial ────────────────────────────────────────────────
    st.divider()
    st.subheader("Optimierungspotenzial")
    st.caption("Schwache Routen — Basis für Streichungs- oder Konsolidierungsentscheide (min. 10 Flüge)")

    with st.spinner():
        df_wrf = get_worst_routes_flights()

    col_l, col_r = st.columns(2)

    with col_l:
        df_wrf_s = df_wrf.sort_values("flights", ascending=False)
        fig = px.bar(
            df_wrf_s, x="flights", y="route", orientation="h",
            labels={"flights": "Anzahl Flüge", "route": "Route"},
            color="flights", color_continuous_scale="Reds_r",
            height=380,
            hover_data={"bookings": True, "avg_price": True},
        )
        fig.update_layout(
            title="Routen mit den wenigsten Flügen",
            coloraxis_showscale=False, margin=dict(l=0, r=10, t=40, b=0),
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_r:
        st.markdown("**Kennzahlen dieser Routen**")
        st.dataframe(
            df_wrf[["route", "flights", "bookings", "avg_price"]]
            .rename(columns={
                "route": "Route",
                "flights": "Flüge",
                "bookings": "Buchungen",
                "avg_price": "Ø Preis ($)",
            })
            .sort_values("Flüge"),
            use_container_width=True,
            hide_index=True,
            height=380,
        )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — KI-Analyst
# ══════════════════════════════════════════════════════════════════════════════

with tab3:
    st.header("KI-Analyst")
    st.caption("Stelle Fragen in natürlicher Sprache – der Agent schreibt SQL, analysiert und visualisiert automatisch.")

    # API-Key prüfen
    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.warning(
            "Kein `ANTHROPIC_API_KEY` gefunden. "
            "Setze die Umgebungsvariable und starte das Dashboard neu:\n\n"
            "```bash\nexport ANTHROPIC_API_KEY='sk-ant-...'\n"
            "/Users/elia/Library/Python/3.9/bin/streamlit run dashboard/app.py\n```"
        )
        st.stop()

    # Session-State initialisieren
    if "chat_display" not in st.session_state:
        st.session_state.chat_display = []
    if "api_messages" not in st.session_state:
        st.session_state.api_messages = []

    # Steuerleiste
    col_ctrl1, col_ctrl2 = st.columns([5, 1])
    with col_ctrl1:
        if st.button("Report erstellen", type="primary"):
            st.session_state._pending = REPORT_PROMPT
    with col_ctrl2:
        if st.button("Chat leeren", use_container_width=True):
            st.session_state.chat_display = []
            st.session_state.api_messages = []
            st.rerun()

    # Beispielfragen (nur wenn Chat leer und keine ausstehende Frage)
    if not st.session_state.chat_display and "_pending" not in st.session_state:
        st.markdown("**Beispielfragen:**")
        examples = [
            "Top 5 Airlines nach Umsatz",
            "Welche Route ist am rentabelsten?",
            "Umsatzentwicklung über die Monate",
            "Vergleiche Auslastung der Top 10 Airlines",
            "Welcher Wochentag hat die meisten Flüge?",
            "Welche Airlines haben einen Load Factor über 80%?",
        ]
        ex_cols = st.columns(3)
        for i, ex in enumerate(examples):
            if ex_cols[i % 3].button(ex, key=f"ex_{i}", use_container_width=True):
                st.session_state._pending = ex

    # Ausstehende Frage aus Session-State holen
    pending = None
    if "_pending" in st.session_state:
        pending = st.session_state._pending
        del st.session_state._pending

    # Chat-Verlauf anzeigen
    for msg in st.session_state.chat_display:
        with st.chat_message(msg["role"]):
            st.markdown(msg["text"])
            for q in msg.get("queries", []):
                with st.expander(q["description"], expanded=True):
                    fig = auto_chart(q["df"], q["description"])
                    if fig:
                        st.plotly_chart(fig, use_container_width=True)
                    st.dataframe(q["df"], use_container_width=True, hide_index=True)

    # Eingabe verarbeiten
    user_input = pending or st.chat_input("Stelle eine Frage zur Flughafen-Datenbank …")

    if user_input:
        display_text = "Management Report erstellen" if user_input == REPORT_PROMPT else user_input

        with st.chat_message("user"):
            st.markdown(display_text)
        st.session_state.chat_display.append(
            {"role": "user", "text": display_text, "queries": []}
        )

        with st.chat_message("assistant"):
            with st.spinner("Analysiere Daten …"):
                try:
                    result = run_agent(user_input, st.session_state.api_messages)
                except Exception as e:
                    st.error(f"Fehler beim Ausführen des Agenten: {e}")
                    st.stop()

            st.markdown(result["text"])
            for q in result["queries"]:
                with st.expander(q["description"], expanded=True):
                    fig = auto_chart(q["df"], q["description"])
                    if fig:
                        st.plotly_chart(fig, use_container_width=True)
                    st.dataframe(q["df"], use_container_width=True, hide_index=True)

        st.session_state.chat_display.append(
            {"role": "assistant", "text": result["text"], "queries": result["queries"]}
        )
        st.session_state.api_messages = result["api_messages"]
