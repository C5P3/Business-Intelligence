"""
Dashboard V3 — Route Decision Cockpit (FlughafenDB)

Ziel: aus den Daten eine konkrete Entscheidung ableiten — welche Routen
streichen, welche beobachten, welche behalten. Aufbau:

  Sidebar  – Datenbasis, Gewichte des Streich-Scores, Schwellen, Schutzregeln
  Tab 1    – Netzwerk-Überblick (KPIs + Empfehlungs-Verteilung + Landkarte LF×Umsatz)
  Tab 2    – Streich-Scorecard (gerankte Kandidaten, erklärbar, exportierbar)
  Tab 3    – Routen-Cockpit (Detail + Impact-Simulation + lokales LLM-Memo)
  Tab 4    – Was-wäre-wenn (mehrere Routen streichen → aggregierter Impact)

Das LLM (Tab 3) begründet nur — die Entscheidung selbst fällt deterministisch
in scoring.py. Läuft kein Ollama, erscheint ein regelbasiertes Memo.
"""



# streamlit run app.py
"""
cd Business-Intelligence/dashboard-v3
source .venv/bin/activate
streamlit run app.py
"""



import os
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

import queries
import scoring
import llm


st.set_page_config(page_title="Route Decision Cockpit", page_icon="🛫", layout="wide")

st.markdown("""
<style>
    [data-testid="stMetric"] {
        background: #1e2130; border-radius: 10px; padding: 14px 18px;
    }
    [data-testid="stMetricLabel"] { color: #a0aec0; font-size: 0.82rem; }
    [data-testid="stMetricValue"] { color: #f0f4ff; font-size: 1.5rem; }
    .decision-box { border-radius: 10px; padding: 14px 18px; margin: 4px 0; font-weight: 600; }
    .memo-box { background:#161a26; border-left:4px solid #6c8cff; border-radius:8px;
                padding:16px 20px; line-height:1.5; }
</style>
""", unsafe_allow_html=True)

COLORS = {
    scoring.REC_KEEP:  "#2ecc71",
    scoring.REC_WATCH: "#f39c12",
    scoring.REC_CUT:   "#e74c3c",
}


def money(x, dec=0):
    return f"$ {x:,.{dec}f}"


@st.cache_data(ttl=30)
def llm_models():
    return llm.list_models()


st.sidebar.title("Steuerung")

min_flights = st.sidebar.slider(
    "Mindest-Flüge je Route", 5, 200, 20, step=5,
    help="Routen mit weniger Flügen werden als statistisch zu dünn ausgeblendet.",
)

st.sidebar.markdown("**Gewichtung Streich-Score**")
st.sidebar.caption("Wie stark zählt jedes Schwäche-Signal? (wird normalisiert)")
w_lf = st.sidebar.slider("Auslastung", 0.0, 1.0, 0.30, 0.05)
w_rev = st.sidebar.slider("Umsatz", 0.0, 1.0, 0.25, 0.05)
w_rpf = st.sidebar.slider("Umsatz / Flug", 0.0, 1.0, 0.20, 0.05)
w_vol = st.sidebar.slider("Buchungsvolumen", 0.0, 1.0, 0.15, 0.05)
w_trend = st.sidebar.slider("Trend", 0.0, 1.0, 0.10, 0.05)
weights = {
    "load_factor": w_lf, "revenue": w_rev, "rev_per_flight": w_rpf,
    "bookings": w_vol, "trend": w_trend,
}

with st.sidebar.expander("Schwellen & Schutzregeln"):
    cut_th = st.slider("Schwelle „Streichen prüfen“", 50, 90, 65)
    watch_th = st.slider("Schwelle „Beobachten“", 20, 60, 45)
    protect_rev = st.slider("Top-Umsatz schützen (%)", 0, 40, 15,
                            help="Diese umsatzstärksten Routen werden nie zum "
                                 "Streichen vorgeschlagen.") / 100.0
    protect_lf = st.slider("Auslastung schützen ab (%)", 60, 100, 85)

dataset = queries.get_dataset(min_flights=min_flights)
scorecard = dataset["scorecard"]
source = dataset["source"]
network = queries.network_kpis(scorecard)

analyzed = scoring.analyze(
    scorecard, weights=weights,
    cut_threshold=cut_th, watch_threshold=watch_th,
    protect_top_revenue_pct=protect_rev, protect_load_factor=protect_lf,
)

if source == "demo":
    st.warning(
        "**Demo-Modus** — keine Verbindung zur `flughafendb`. Es werden synthetische "
        "Beispieldaten angezeigt, damit du das Dashboard testen kannst. Starte MySQL "
        "lokal (oder setze die DB_* Umgebungsvariablen), um echte Daten zu sehen.",
        icon="⚠️",
    )

st.title("Route Decision Cockpit")
st.caption("Entscheidungsgrundlage: Routen streichen, beobachten oder behalten — FlughafenDB (Jun–Aug 2015)")

tab1, tab2, tab3, tab4 = st.tabs([
    "Netzwerk-Überblick", "Streich-Scorecard", "Routen-Cockpit", "Was-wäre-wenn",
])


with tab1:
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Umsatz gesamt", money(network["total_revenue"]))
    c2.metric("Buchungen", f"{network['total_bookings']:,}")
    c3.metric("Flüge", f"{network['total_flights']:,}")
    c4.metric("Routen", f"{network['n_routes']:,}")
    c5.metric("Ø Ticketpreis", money(network["avg_ticket"], 2))
    c6.metric("Netz-Auslastung", f"{network['network_load_factor']:.1f}%")

    st.divider()

    counts = analyzed["recommendation"].value_counts()
    rev_by_rec = analyzed.groupby("recommendation")["revenue"].sum()

    cols = st.columns(3)
    for col, label in zip(cols, [scoring.REC_CUT, scoring.REC_WATCH, scoring.REC_KEEP]):
        n = int(counts.get(label, 0))
        rev = float(rev_by_rec.get(label, 0.0))
        rev_share = rev / network["total_revenue"] * 100 if network["total_revenue"] else 0
        color = COLORS[label]
        col.markdown(
            f"<div class='decision-box' style='background:{color}22;border-left:4px solid {color}'>"
            f"<span style='color:{color}'>{label}</span><br>"
            f"<span style='font-size:1.8rem;color:#f0f4ff'>{n}</span> Routen "
            f"<span style='color:#a0aec0'>· {rev_share:.1f}% des Umsatzes</span></div>",
            unsafe_allow_html=True,
        )

    st.markdown("")
    col_l, col_r = st.columns([3, 2])

    with col_l:
        st.subheader("Routen-Landkarte: Auslastung × Umsatz")
        st.caption("Unten links = wenig Auslastung & wenig Umsatz = Streich-Kandidat. Grösse = Flüge.")
        fig = px.scatter(
            analyzed, x="load_factor", y="revenue", color="recommendation",
            color_discrete_map=COLORS, size="total_flights", size_max=28,
            hover_name="route", log_y=True,
            hover_data={"cut_score": ":.0f", "avg_price": ":.2f", "trend_pct": ":+.1f",
                        "load_factor": ":.1f", "revenue": ":,.0f", "recommendation": False},
            labels={"load_factor": "Load Factor (%)", "revenue": "Umsatz ($, log)",
                    "recommendation": "Empfehlung"},
            height=460,
        )
        fig.update_layout(margin=dict(l=0, r=0, t=10, b=0),
                          legend=dict(orientation="h", y=-0.18))
        st.plotly_chart(fig, use_container_width=True)

    with col_r:
        st.subheader("Verteilung")
        dist = (analyzed["recommendation"].value_counts()
                .reindex([scoring.REC_CUT, scoring.REC_WATCH, scoring.REC_KEEP])
                .fillna(0).astype(int).reset_index())
        dist.columns = ["Empfehlung", "Routen"]
        fig = px.bar(dist, x="Routen", y="Empfehlung", orientation="h",
                     color="Empfehlung", color_discrete_map=COLORS, text="Routen", height=230)
        fig.update_layout(showlegend=False, margin=dict(l=0, r=0, t=10, b=0),
                          yaxis_title="", xaxis_title="")
        st.plotly_chart(fig, use_container_width=True)

        st.caption("Umsatzkonzentration")
        top10_share = analyzed.nlargest(10, "revenue")["revenue"].sum() / network["total_revenue"] * 100 \
            if network["total_revenue"] else 0
        st.metric("Top-10-Routen = Anteil am Umsatz", f"{top10_share:.1f}%")


with tab2:
    st.subheader("Streich-Scorecard")
    st.caption(
        "Streich-Score 0–100 (höher = schwächer). Perzentil-normalisierte Signale, "
        "gewichtet wie in der Sidebar. „Streichen prüfen“-Kandidaten zuerst."
    )

    f1, f2 = st.columns([2, 3])
    with f1:
        rec_filter = st.multiselect(
            "Empfehlung filtern",
            [scoring.REC_CUT, scoring.REC_WATCH, scoring.REC_KEEP],
            default=[scoring.REC_CUT, scoring.REC_WATCH],
        )
    view = analyzed[analyzed["recommendation"].isin(rec_filter)].sort_values(
        "cut_score", ascending=False
    )

    st.markdown("**Top-Kandidaten nach Streich-Score**")
    top = view.head(15).iloc[::-1]
    if not top.empty:
        fig = px.bar(
            top, x="cut_score", y="route", orientation="h",
            color="recommendation", color_discrete_map=COLORS,
            hover_data={"load_factor": ":.1f", "revenue": ":,.0f",
                        "trend_pct": ":+.1f", "main_driver": True, "recommendation": False},
            labels={"cut_score": "Streich-Score", "route": "", "recommendation": "Empfehlung"},
            height=min(560, 60 + len(top) * 30),
        )
        fig.update_layout(margin=dict(l=0, r=0, t=6, b=0),
                          legend=dict(orientation="h", y=-0.12))
        st.plotly_chart(fig, use_container_width=True)

    disp = view[[
        "route", "cut_score", "recommendation", "main_driver", "load_factor",
        "revenue", "rev_per_flight", "trend_pct", "bookings", "total_flights", "protected",
    ]].rename(columns={
        "route": "Route", "cut_score": "Score", "recommendation": "Empfehlung",
        "main_driver": "Haupttreiber", "load_factor": "Load %", "revenue": "Umsatz $",
        "rev_per_flight": "Umsatz/Flug $", "trend_pct": "Trend %", "bookings": "Buchungen",
        "total_flights": "Flüge", "protected": "Geschützt",
    })
    st.dataframe(disp, use_container_width=True, hide_index=True, height=380)

    st.download_button(
        "Scorecard als CSV",
        view.to_csv(index=False).encode("utf-8"),
        file_name="streich_scorecard.csv", mime="text/csv",
    )


with tab3:
    st.subheader("Routen-Cockpit")

    # Default: stärkster Streich-Kandidat.
    ranked = analyzed.sort_values("cut_score", ascending=False)
    options = ranked["route"].tolist()
    selected = st.selectbox("Route wählen (sortiert nach Streich-Score)", options, index=0)
    row = analyzed[analyzed["route"] == selected].iloc[0]

    rec = row["recommendation"]
    color = COLORS[rec]
    st.markdown(
        f"<div class='decision-box' style='background:{color}22;border-left:4px solid {color}'>"
        f"Empfehlung: <span style='color:{color}'>{rec}</span> · Streich-Score "
        f"{row['cut_score']:.0f}/100 · Haupttreiber: {row['main_driver']}"
        + (" · <i>strategisch geschützt</i>" if row["protected"] else "")
        + "</div>",
        unsafe_allow_html=True,
    )

    m1, m2, m3, m4, m5 = st.columns(5)
    price_vs_market = (row["avg_price"] - network["avg_ticket"]) / network["avg_ticket"] * 100 \
        if network["avg_ticket"] else 0
    m1.metric("Load Factor", f"{row['load_factor']:.1f}%",
              delta=f"{row['load_factor'] - network['network_load_factor']:+.1f} pp vs. Netz")
    m2.metric("Ø Preis", money(row["avg_price"], 2), delta=f"{price_vs_market:+.1f}% vs. Markt")
    m3.metric("Umsatz", money(row["revenue"]),
              delta=f"{row['revenue'] / network['total_revenue'] * 100:.2f}% des Netzes"
              if network["total_revenue"] else None)
    m4.metric("Umsatz / Flug", money(row["rev_per_flight"]))
    m5.metric("Trend", f"{row['trend_pct']:+.1f}%")

    col_l, col_r = st.columns(2)

    with col_l:
        st.markdown("**Monatlicher Verlauf**")
        mon = queries.route_monthly(dataset, int(row["von"]), int(row["nach"]))
        if mon.empty:
            st.info("Keine Monatsdaten für diese Route.")
        else:
            fig = go.Figure()
            fig.add_trace(go.Bar(x=mon["month"], y=mon["revenue"], name="Umsatz $",
                                 marker_color="#6c8cff"))
            fig.add_trace(go.Scatter(x=mon["month"], y=mon["bookings"], name="Buchungen",
                                     yaxis="y2", mode="lines+markers", line=dict(color="#f39c12")))
            fig.update_layout(
                height=300, margin=dict(l=0, r=0, t=10, b=0),
                yaxis=dict(title="Umsatz $"),
                yaxis2=dict(title="Buchungen", overlaying="y", side="right", showgrid=False),
                legend=dict(orientation="h", y=-0.2),
            )
            st.plotly_chart(fig, use_container_width=True)

    with col_r:
        st.markdown("**Schwäche-Signale (0–1, höher = schwächer)**")
        radar = go.Figure()
        radar.add_trace(go.Scatterpolar(
            r=[row["cut_lf"], row["cut_rev"], row["cut_rpf"], row["cut_vol"], row["cut_trend"]],
            theta=["Auslastung", "Umsatz", "Umsatz/Flug", "Volumen", "Trend"],
            fill="toself", line=dict(color=color),
        ))
        radar.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=20),
                            polar=dict(radialaxis=dict(range=[0, 1], showticklabels=True)),
                            showlegend=False)
        st.plotly_chart(radar, use_container_width=True)

    airlines = queries.route_airlines(dataset, int(row["von"]), int(row["nach"]))
    st.markdown(f"**Airlines auf dieser Strecke:** {', '.join(airlines) if airlines else '–'}")

    st.divider()

    st.markdown("**Impact-Simulation: diese Route streichen**")
    rebook = st.slider("Angenommene Umbuchungsquote (Buchungen, die auf andere Routen wechseln)",
                       0, 80, 0, 5, help="0 % = konservativ (gesamter Umsatz verloren).") / 100.0
    mask = analyzed["route"] == selected
    impact = scoring.simulate_cut(analyzed, mask, rebooking_rate=rebook)
    i1, i2, i3, i4 = st.columns(4)
    i1.metric("Umsatz-Verlust (netto)", money(impact["revenue_lost_net"]),
              delta=f"{impact['pct_of_network_revenue']:.2f}% des Netzes", delta_color="inverse")
    i2.metric("Frei werdende Flüge", f"{impact['flights_freed']:,}",
              delta=f"{impact['pct_of_flights']:.2f}% der Flüge")
    i3.metric("Freie Sitzplätze", f"{int(impact['seats_freed']):,}")
    i4.metric("Betroffene Buchungen", f"{impact['bookings_affected']:,}",
              delta=f"{impact['pct_of_bookings']:.2f}% des Netzes", delta_color="inverse")

    st.divider()

    st.markdown("**KI-Entscheidungs-Memo (lokales LLM)**")
    models = llm_models()
    if models:
        chosen = llm.pick_model()
        st.success(f"Ollama erreichbar — Modell `{chosen}` wird verwendet.", icon="✅")
    else:
        st.info(
            "Ollama nicht erreichbar — es wird ein regelbasiertes Memo erzeugt. "
            "Für KI-Memos: `ollama serve` starten und ein Modell laden "
            "(z. B. `ollama pull llama3.2:3b`). Details in der README.",
            icon="💡",
        )

    if st.button("Memo generieren", type="primary"):
        facts = scoring.route_facts(row, network)
        with st.spinner("Memo wird erstellt …"):
            result = llm.generate_decision_memo(facts, impact=impact)
        st.markdown(f"<div class='memo-box'>{result['text']}</div>", unsafe_allow_html=True)
        if result["source"] == "llm":
            st.caption(f"Generiert mit `{result['model']}` (lokal via Ollama).")
        else:
            st.caption("Regelbasiertes Memo (kein lokales LLM aktiv).")


with tab4:
    st.subheader("Was-wäre-wenn: mehrere Routen streichen")
    st.caption("Wähle ein Streich-Portfolio und sieh den aggregierten Effekt aufs Netz.")

    cut_candidates = analyzed[analyzed["recommendation"] == scoring.REC_CUT]["route"].tolist()
    chosen_routes = st.multiselect(
        "Zu streichende Routen", analyzed.sort_values("cut_score", ascending=False)["route"].tolist(),
        default=cut_candidates,
        help="Vorbelegt mit allen „Streichen prüfen“-Routen — frei anpassbar.",
    )
    rebook2 = st.slider("Umbuchungsquote", 0, 80, 0, 5, key="rebook2") / 100.0

    mask = analyzed["route"].isin(chosen_routes)
    impact = scoring.simulate_cut(analyzed, mask, rebooking_rate=rebook2)

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Routen gestrichen", f"{impact['n_routes_cut']:,}")
    k2.metric("Umsatz-Verlust (netto)", money(impact["revenue_lost_net"]),
              delta=f"{impact['pct_of_network_revenue']:.2f}% des Netzes", delta_color="inverse")
    k3.metric("Frei werdende Flüge", f"{impact['flights_freed']:,}",
              delta=f"{impact['pct_of_flights']:.2f}% der Flüge")
    k4.metric("Betroffene Buchungen", f"{impact['bookings_affected']:,}",
              delta=f"{impact['pct_of_bookings']:.2f}% des Netzes", delta_color="inverse")

    if chosen_routes:
        sel = analyzed[mask].sort_values("revenue", ascending=False)
        st.markdown("**Umsatz-Verlust je gestrichener Route**")
        fig = px.bar(sel.head(25), x="revenue", y="route", orientation="h",
                     color="cut_score", color_continuous_scale="Reds",
                     labels={"revenue": "Umsatz $ (entfällt)", "route": "", "cut_score": "Score"},
                     height=min(620, 80 + len(sel.head(25)) * 24))
        fig.update_layout(margin=dict(l=0, r=0, t=6, b=0))
        st.plotly_chart(fig, use_container_width=True)

        st.markdown(
            f"**Fazit:** Streichen dieser {impact['n_routes_cut']} Routen kostet netto "
            f"{money(impact['revenue_lost_net'])} ({impact['pct_of_network_revenue']:.2f}% des "
            f"Netzumsatzes) und entlastet {impact['flights_freed']:,} Flüge "
            f"({impact['pct_of_flights']:.2f}%). Kapazität, die für stärkere Routen frei wird."
        )
    else:
        st.info("Keine Routen ausgewählt.")
