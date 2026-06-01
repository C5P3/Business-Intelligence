import os
import numpy as np
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import mysql.connector
from queries import (
    DB_CONFIG,
    get_kpis,
    get_price_distribution,
    get_weekday_prices,
    get_monthly_prices,
    get_price_load_matrix,
    get_overpriced_routes,
    get_underpriced_routes,
    get_price_outliers,
    get_route_selector,
    get_route_detail,
)
from gemma import generate_pricing_memo, is_available, OLLAMA_MODEL

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Pricing Intelligence",
    page_icon="💰",
    layout="wide",
)

st.markdown("""
<style>
    [data-testid="stMetric"] {
        background: #1e2130;
        border-radius: 10px;
        padding: 16px 20px;
    }
    [data-testid="stMetricLabel"] { color: #a0aec0; font-size: 0.85rem; }
    [data-testid="stMetricValue"] { color: #f0f4ff; font-size: 1.6rem; }
    .decision-box {
        border-radius: 10px;
        padding: 16px 20px;
        margin: 4px 0;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

# ── DB-Check ──────────────────────────────────────────────────────────────────

@st.cache_resource
def check_db():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        conn.close()
        return True
    except Exception as e:
        return str(e)

if check_db() is not True:
    st.error(f"Keine Datenbankverbindung: {check_db()}")
    st.stop()

# ── Header ────────────────────────────────────────────────────────────────────

st.title("Pricing Intelligence Dashboard")
st.caption("Entscheidungsgrundlage für Preisanpassungen im Streckennetz — FlughafenDB")

tab1, tab2, tab3, tab4 = st.tabs([
    "Marktüberblick",
    "Entscheidungsmatrix",
    "Route Benchmarking",
    "KI-Memo",
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Marktüberblick
# ══════════════════════════════════════════════════════════════════════════════

with tab1:
    with st.spinner("Lade Marktdaten …"):
        kpis = get_kpis()

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Ø Ticketpreis",    f"$ {kpis['avg_price']:,.2f}")
    c2.metric("Tiefster Preis",   f"$ {kpis['min_price']:,.2f}")
    c3.metric("Höchster Preis",   f"$ {kpis['max_price']:,.2f}")
    c4.metric("Std.abweichung",   f"$ {kpis['std_price']:,.2f}")
    c5.metric("Buchungen gesamt", f"{int(kpis['total_bookings']):,}")

    st.divider()
    col_l, col_r = st.columns(2)

    with col_l:
        st.subheader("Preisverteilung")
        with st.spinner():
            df_dist = get_price_distribution()
        fig = px.bar(
            df_dist, x="bucket", y="bookings",
            labels={"bucket": "Preisklasse", "bookings": "Buchungen"},
            color="bookings", color_continuous_scale="Blues",
            height=340,
        )
        fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

    with col_r:
        st.subheader("Ø Preis nach Wochentag")
        with st.spinner():
            df_wd = get_weekday_prices()
        global_avg = kpis["avg_price"]
        fig = px.bar(
            df_wd, x="weekday", y="avg_price",
            labels={"weekday": "Wochentag", "avg_price": "Ø Preis ($)"},
            color="avg_price", color_continuous_scale="RdYlGn",
            height=340,
            text="avg_price",
        )
        fig.add_hline(y=global_avg, line_dash="dash", line_color="white",
                      annotation_text=f"Gesamt-Ø ${global_avg:.2f}", annotation_position="top right")
        fig.update_traces(texttemplate="$%{text:.2f}", textposition="outside")
        fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Preisentwicklung nach Monat")
    with st.spinner():
        df_mp = get_monthly_prices()
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_mp["month"], y=df_mp["avg_price"], name="Ø Preis ($)",
        mode="lines+markers", line=dict(color="#3498db", width=2), marker=dict(size=6),
    ))
    fig.add_hline(y=global_avg, line_dash="dot", line_color="rgba(255,255,255,0.4)",
                  annotation_text=f"Gesamt-Ø ${global_avg:.2f}")
    fig.update_layout(height=280, margin=dict(l=0, r=0, t=10, b=0),
                      yaxis_title="Ø Preis ($)")
    st.plotly_chart(fig, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Entscheidungsmatrix
# ══════════════════════════════════════════════════════════════════════════════

with tab2:
    st.subheader("Preis × Auslastung — Entscheidungsmatrix")
    st.caption(
        "Jeder Punkt = eine Route. Achsen-Referenzlinien am Median. "
        "Quadrant bestimmt die Massnahme."
    )

    with st.spinner("Berechne Matrix …"):
        df_matrix = get_price_load_matrix()

    if df_matrix.empty:
        st.warning("Keine Daten verfügbar.")
    else:
        med_price = df_matrix["avg_price"].median()
        med_lf    = df_matrix["load_factor"].median()

        # Quadrant-Klassifikation
        def classify(row):
            high_p = row["avg_price"]  >= med_price
            high_l = row["load_factor"] >= med_lf
            if high_p and high_l:  return "Optimal — beibehalten"
            if not high_p and high_l: return "Preis erhöhen"
            if high_p and not high_l: return "Preis senken"
            return "Route prüfen / streichen"

        df_matrix["Empfehlung"] = df_matrix.apply(classify, axis=1)

        color_map = {
            "Optimal — beibehalten":    "#2ecc71",
            "Preis erhöhen":            "#3498db",
            "Preis senken":             "#e67e22",
            "Route prüfen / streichen": "#e74c3c",
        }

        # Zusammenfassung
        counts = df_matrix["Empfehlung"].value_counts()
        c1, c2, c3, c4 = st.columns(4)
        for col, (label, color) in zip(
            [c1, c2, c3, c4],
            [
                ("Optimal — beibehalten",    "#2ecc71"),
                ("Preis erhöhen",            "#3498db"),
                ("Preis senken",             "#e67e22"),
                ("Route prüfen / streichen", "#e74c3c"),
            ],
        ):
            n = counts.get(label, 0)
            col.markdown(
                f"<div class='decision-box' style='background:{color}22;border-left:4px solid {color}'>"
                f"<span style='color:{color}'>{label}</span><br>"
                f"<span style='font-size:1.8rem;color:#f0f4ff'>{n}</span> Routen</div>",
                unsafe_allow_html=True,
            )

        st.markdown("")

        fig = px.scatter(
            df_matrix,
            x="load_factor",
            y="avg_price",
            color="Empfehlung",
            color_discrete_map=color_map,
            size="bookings",
            size_max=30,
            hover_name="route",
            hover_data={
                "bookings": True,
                "total_flights": True,
                "min_price": True,
                "max_price": True,
                "load_factor": ":.1f",
                "avg_price": ":.2f",
                "Empfehlung": False,
            },
            labels={
                "load_factor": "Load Factor (%)",
                "avg_price":   "Ø Preis ($)",
            },
            height=520,
        )
        fig.add_vline(x=med_lf,    line_dash="dash", line_color="rgba(255,255,255,0.35)",
                      annotation_text=f"Median LF {med_lf:.1f}%")
        fig.add_hline(y=med_price, line_dash="dash", line_color="rgba(255,255,255,0.35)",
                      annotation_text=f"Median Preis ${med_price:.2f}")

        # Quadrant-Beschriftungen
        x_max = df_matrix["load_factor"].max()
        y_max = df_matrix["avg_price"].max()
        y_min = df_matrix["avg_price"].min()
        x_min = df_matrix["load_factor"].min()
        for text, x, y, color in [
            ("Preis erhöhen",            x_min + (med_lf - x_min) * 0.1,  y_min + (med_price - y_min) * 0.05, "#3498db"),
            ("Optimal",                  med_lf + (x_max - med_lf) * 0.05, y_max - (y_max - med_price) * 0.15, "#2ecc71"),
            ("Route prüfen",             x_min + (med_lf - x_min) * 0.1,  y_max - (y_max - med_price) * 0.15, "#e74c3c"),
            ("Preis senken",             med_lf + (x_max - med_lf) * 0.05, y_min + (med_price - y_min) * 0.05, "#e67e22"),
        ]:
            fig.add_annotation(x=x, y=y, text=text, showarrow=False,
                               font=dict(size=11, color=color), opacity=0.6)

        fig.update_layout(margin=dict(l=0, r=0, t=10, b=0),
                          legend=dict(orientation="h", y=-0.12))
        st.plotly_chart(fig, use_container_width=True)

        with st.expander("Rohdaten anzeigen"):
            st.dataframe(
                df_matrix[["route", "avg_price", "load_factor", "bookings",
                            "total_flights", "Empfehlung"]]
                .rename(columns={
                    "route": "Route", "avg_price": "Ø Preis ($)",
                    "load_factor": "Load Factor (%)", "bookings": "Buchungen",
                    "total_flights": "Flüge", "Empfehlung": "Empfehlung",
                })
                .sort_values("Empfehlung"),
                use_container_width=True, hide_index=True,
            )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Route Benchmarking
# ══════════════════════════════════════════════════════════════════════════════

with tab3:
    col_l, col_r = st.columns(2)

    with col_l:
        st.subheader("Teuerste Routen mit schwachem Load Factor")
        st.caption("Preis senken oder Route überdenken")
        with st.spinner():
            df_over = get_overpriced_routes()
        df_over_s = df_over.sort_values("avg_price")
        fig = px.bar(
            df_over_s, x="avg_price", y="route", orientation="h",
            color="load_factor", color_continuous_scale="RdYlGn",
            labels={"avg_price": "Ø Preis ($)", "route": "Route",
                    "load_factor": "Load Factor (%)"},
            height=460,
            hover_data={"bookings": True, "load_factor": True},
        )
        fig.update_layout(coloraxis_showscale=True, margin=dict(l=0, r=10, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

    with col_r:
        st.subheader("Günstigste Routen mit hohem Load Factor")
        st.caption("Preis erhöhen — die Nachfrage trägt es")
        with st.spinner():
            df_under = get_underpriced_routes()
        df_under_s = df_under.sort_values("avg_price", ascending=False)
        fig = px.bar(
            df_under_s, x="avg_price", y="route", orientation="h",
            color="load_factor", color_continuous_scale="Blues",
            labels={"avg_price": "Ø Preis ($)", "route": "Route",
                    "load_factor": "Load Factor (%)"},
            height=460,
            hover_data={"bookings": True, "load_factor": True},
        )
        fig.update_layout(coloraxis_showscale=True, margin=dict(l=0, r=10, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("Preis-Ausreisser")
    st.caption("Buchungen mit starker Abweichung vom Routendurchschnitt (Z-Score > 1.8)")
    with st.spinner():
        df_out = get_price_outliers()

    if df_out.empty:
        st.info("Keine signifikanten Ausreisser gefunden.")
    else:
        color_map_out = {"zu teuer": "#e74c3c", "zu günstig": "#3498db"}
        fig = px.scatter(
            df_out, x="z_score", y="route",
            color="typ", color_discrete_map=color_map_out,
            size=np.abs(df_out["z_score"]).tolist(),
            size_max=20,
            hover_data={"price": True, "route_avg": True, "airline": True},
            labels={"z_score": "Z-Score", "route": "Route", "typ": "Bewertung"},
            height=max(350, len(df_out) * 18),
        )
        fig.add_vline(x=0, line_dash="dot", line_color="rgba(255,255,255,0.3)")
        fig.update_layout(margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

        st.dataframe(
            df_out.rename(columns={
                "route": "Route", "airline": "Airline", "price": "Preis ($)",
                "route_avg": "Routen-Ø ($)", "z_score": "Z-Score", "typ": "Bewertung",
            }),
            use_container_width=True, hide_index=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — KI-Memo
# ══════════════════════════════════════════════════════════════════════════════

with tab4:
    st.subheader("KI-Pricing-Memo")
    st.caption(
        f"Generiert mit **{OLLAMA_MODEL}** via Ollama (lokal). "
        "Wähle eine Route — das Modell analysiert die Daten und schreibt eine Preisempfehlung."
    )

    # Ollama-Status
    ollama_ok = is_available()
    if ollama_ok:
        st.success(f"Ollama läuft — Modell `{OLLAMA_MODEL}` bereit.", icon="✓")
    else:
        st.warning(
            f"Ollama nicht erreichbar oder Modell `{OLLAMA_MODEL}` nicht geladen.\n\n"
            "```bash\nollama serve\n"
            f"ollama pull {OLLAMA_MODEL}\n```",
        )

    st.divider()

    # Route-Selektor
    with st.spinner("Lade Routen …"):
        df_sel = get_route_selector()

    route_options = df_sel["route"].tolist()
    selected_route = st.selectbox(
        "Route auswählen",
        options=route_options,
        index=0,
        help="Routen mit min. 200 Buchungen, sortiert nach Buchungsvolumen",
    )

    sel_row = df_sel[df_sel["route"] == selected_route].iloc[0]
    von_id  = int(sel_row["von_id"])
    nach_id = int(sel_row["nach_id"])

    # Route-Detail-Kacheln
    with st.spinner("Lade Routendetails …"):
        detail = get_route_detail(von_id, nach_id)

    market_avg   = float(detail["market_avg"])
    avg_price    = float(detail["avg_price"])
    price_diff   = (avg_price - market_avg) / market_avg * 100

    d1, d2, d3, d4, d5 = st.columns(5)
    d1.metric("Ø Preis",      f"$ {avg_price:.2f}",
              delta=f"{price_diff:+.1f}% vs. Markt")
    d2.metric("Preisrange",   f"$ {detail['min_price']:.2f} – $ {detail['max_price']:.2f}")
    d3.metric("Std.abw.",     f"$ {detail['std_price']:.2f}")
    d4.metric("Load Factor",  f"{detail['load_factor']:.1f}%")
    d5.metric("Flüge / Buchungen",
              f"{int(detail['total_flights']):,} / {int(detail['bookings']):,}")

    st.markdown(f"**Airlines auf dieser Strecke:** {', '.join(detail['airlines']) or '–'}")

    st.divider()

    # Memo generieren
    if st.button("Pricing-Memo generieren", type="primary", disabled=not ollama_ok):
        with st.spinner(f"{OLLAMA_MODEL} analysiert …"):
            memo = generate_pricing_memo(
                route         = selected_route,
                avg_price     = avg_price,
                min_price     = float(detail["min_price"]),
                max_price     = float(detail["max_price"]),
                std_price     = float(detail["std_price"]),
                market_avg    = market_avg,
                load_factor   = float(detail["load_factor"]),
                total_flights = int(detail["total_flights"]),
                bookings      = int(detail["bookings"]),
                airlines      = detail["airlines"],
            )
        st.markdown("### Empfehlung")
        st.info(memo)

    if not ollama_ok:
        st.markdown(
            "**Ohne Ollama:** Du kannst trotzdem die Daten oben und die "
            "Entscheidungsmatrix in Tab 2 für manuelle Entscheide nutzen."
        )
