import os
import re
from typing import Optional

import pandas as pd
import streamlit as st


st.set_page_config(page_title="Dashboard – Risicoprofiel", layout="wide")


@st.cache_data
def load_begroting_provincies(jaar: int = 2026) -> Optional[pd.DataFrame]:
    """
    Lees 'Begroting <jaar>.csv' met structuur:
    rij 1: gemeente;<gemeente1>;<gemeente2>;...
    rij n: <indicator>;<waarde1>;<waarde2>;...
    Retourneert long-form: kolommen ['indicator','gemeente','waarde'].
    """
    bestand = f"Begroting {jaar}.csv"
    if not os.path.exists(bestand):
        return None
    try:
        df_raw = pd.read_csv(bestand, sep=";", engine="python")
    except Exception:
        return None
    if df_raw.shape[1] < 2:
        return None

    indicator_col = df_raw.columns[0]
    df_raw[indicator_col] = df_raw[indicator_col].astype(str).str.strip()
    df_long = df_raw.melt(
        id_vars=[indicator_col],
        # Let op: eerste kolom heet vaak ook 'gemeente' → vermijd naamconflict
        var_name="gemeente_kolom",
        value_name="waarde_raw",
    ).rename(columns={indicator_col: "indicator"})

    def _to_float(x):
        if x is None:
            return None
        s = str(x).strip()
        if not s or s in {"-", "nan", "NaN"}:
            return None
        s = s.replace(".", "").replace(",", ".")
        try:
            return float(s)
        except Exception:
            return None

    df_long["waarde"] = df_long["waarde_raw"].apply(_to_float)
    df_long = df_long.drop(columns=["waarde_raw"])
    df_long = df_long.rename(columns={"gemeente_kolom": "gemeente"})
    df_long["gemeente"] = df_long["gemeente"].astype(str).str.strip()
    return df_long


@st.cache_data
def load_weging_risicomodel() -> Optional[pd.DataFrame]:
    bestand = "Weging risicomodel.csv"
    if not os.path.exists(bestand):
        return None
    try:
        df = pd.read_csv(bestand, sep=";", engine="python")
    except Exception:
        # fallback: comma separated
        try:
            df = pd.read_csv(bestand, engine="python")
        except Exception:
            return None
    # normaliseer kolommen
    df.columns = [str(c).strip() for c in df.columns]
    for c in ["Indicator", "Weging minimaal", "Weging maximaal"]:
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip()
    return df


@st.cache_data
def load_jaarrekening() -> Optional[pd.DataFrame]:
    bestand = "Jaarrekening.csv"
    if not os.path.exists(bestand):
        return None
    try:
        return load_begroting_provincies_from_path(bestand)
    except Exception:
        return None


def load_begroting_provincies_from_path(bestand: str) -> Optional[pd.DataFrame]:
    try:
        df_raw = pd.read_csv(bestand, sep=";", engine="python")
    except Exception:
        return None
    if df_raw.shape[1] < 2:
        return None
    indicator_col = df_raw.columns[0]
    df_raw[indicator_col] = df_raw[indicator_col].astype(str).str.strip()
    df_long = df_raw.melt(
        id_vars=[indicator_col],
        var_name="gemeente_kolom",
        value_name="waarde_raw",
    ).rename(columns={indicator_col: "indicator"})

    def _to_float(x):
        if x is None:
            return None
        s = str(x).strip()
        if not s or s in {"-", "nan", "NaN"}:
            return None
        s = s.replace(".", "").replace(",", ".")
        try:
            return float(s)
        except Exception:
            return None

    df_long["waarde"] = df_long["waarde_raw"].apply(_to_float)
    df_long = df_long.drop(columns=["waarde_raw"])
    df_long = df_long.rename(columns={"gemeente_kolom": "gemeente"})
    df_long["gemeente"] = df_long["gemeente"].astype(str).str.strip()
    df_long["indicator"] = df_long["indicator"].astype(str).str.strip()
    return df_long


@st.cache_data
def load_gemeentefonds_2026() -> Optional[pd.DataFrame]:
    bestand = "Gemeentefonds_2026.csv"
    if not os.path.exists(bestand):
        return None
    try:
        df = pd.read_csv(bestand, sep=";", engine="python", skiprows=4)
    except Exception:
        return None
    # verwacht kolommen: CBS, Naam, ... Overige eigen middelen, Onroerendezaakbelasting, Totaal
    df.columns = [str(c).strip() for c in df.columns]
    if "Naam" not in df.columns:
        return None

    def _to_float_str(x):
        if x is None:
            return None
        s = str(x).strip()
        if not s or s in {"-", "nan", "NaN"}:
            return None
        s = s.replace(" ", "").replace(".", "").replace(",", ".")
        s = re.sub(r"[^0-9\.\-]", "", s)
        try:
            return float(s)
        except Exception:
            return None

    for col in ["Overige eigen middelen", "Onroerendezaakbelasting"]:
        if col in df.columns:
            df[col] = df[col].apply(_to_float_str)
    df["Naam"] = df["Naam"].astype(str).str.strip()
    return df


def parse_weging_cond(cond: str) -> dict:
    """
    Parse voorwaarden zoals '<-0,5%', '>=1%', '<0,8', '>1,4', 'Nee', 'Ja', '1', '3'.
    Retourneert dict met type: 'cmp' of 'eq'.
    """
    c = (cond or "").strip()
    if not c:
        return {"type": "none"}
    # tekst eq
    if c.lower() in {"ja", "nee", "hoger", "lager"}:
        return {"type": "eq", "value": c.lower()}
    # vergelijkingen
    m = re.match(r"^(<=|>=|<|>)(-?\d+(?:[.,]\d+)?)\s*(%)?$", c.replace(" ", ""))
    if m:
        op = m.group(1)
        num = float(m.group(2).replace(",", "."))
        is_pct = bool(m.group(3))
        return {"type": "cmp", "op": op, "num": num, "pct": is_pct}
    # losse getallen
    m2 = re.match(r"^-?\d+(?:[.,]\d+)?$", c)
    if m2:
        return {"type": "num", "num": float(c.replace(",", "."))}
    return {"type": "raw", "raw": c}


def voldoet(value: Optional[float], text_value: Optional[str], cond: dict) -> Optional[bool]:
    if cond.get("type") == "none":
        return None
    if cond["type"] == "eq":
        if text_value is None:
            return False
        return str(text_value).strip().lower() == cond["value"]
    if cond["type"] == "cmp":
        if value is None:
            return False
        v = float(value)
        num = float(cond["num"])
        op = cond["op"]
        if op == "<":
            return v < num
        if op == "<=":
            return v <= num
        if op == ">":
            return v > num
        if op == ">=":
            return v >= num
        return False
    if cond["type"] == "num":
        if value is None:
            return False
        return float(value) == float(cond["num"])
    return None


def score_indicator(
    weging_df: pd.DataFrame,
    indicator: str,
    value: Optional[float],
    text_value: Optional[str] = None,
) -> Optional[float]:
    r = weging_df[weging_df["Indicator"].astype(str).str.strip().str.lower() == indicator.strip().lower()]
    if r.empty:
        return None
    row = r.iloc[0]
    try:
        score_min = float(str(row.get("minimaal", "0")).replace(",", "."))
        score_mid = float(str(row.get("midden", "0")).replace(",", "."))
        score_max = float(str(row.get("maximaal", "0")).replace(",", "."))
    except Exception:
        return None
    cond_min = parse_weging_cond(str(row.get("Weging minimaal", "") or ""))
    cond_max = parse_weging_cond(str(row.get("Weging maximaal", "") or ""))

    ok_min = voldoet(value, text_value, cond_min)
    ok_max = voldoet(value, text_value, cond_max)

    # Als aan max-voorwaarde voldaan: maximaal; als aan min-voorwaarde voldaan: minimaal; anders midden.
    if ok_max is True:
        return score_max
    if ok_min is True:
        return score_min
    # Als geen van beiden matcht maar we hebben wel een waarde: midden
    if value is not None or (text_value is not None and str(text_value).strip()):
        return score_mid
    return None


st.title("Dashboard")

tab_risico, tab_reserves = st.tabs(["Risicoprofiel", "Reserves per inwoner"])

with tab_risico:
    st.subheader("Risicoprofiel")
    st.caption("Bronnen: `Begroting 2026.csv`, `Jaarrekening.csv`, `Weging risicomodel.csv`, `Gemeentefonds_2026.csv`.")

    jaar = st.selectbox("Jaar (dataset)", options=[2026], index=0, key="rp_jaar")
    df_long = load_begroting_provincies(int(jaar))
    weging = load_weging_risicomodel()

    if df_long is None:
        st.warning("Bestand `Begroting 2026.csv` niet gevonden of niet leesbaar.")
        st.stop()
    if weging is None:
        st.warning("Bestand `Weging risicomodel.csv` niet gevonden of niet leesbaar.")
        st.stop()

    jaarrekening_long = load_begroting_provincies_from_path("Jaarrekening.csv")
    gf_2026 = load_gemeentefonds_2026()

    gemeenten = sorted(df_long["gemeente"].dropna().unique().tolist())
    gemeente = st.selectbox("Gemeente", gemeenten, index=0, key="rp_gemeente")


    def val(indicator: str) -> Optional[float]:
        r = df_long[
            (df_long["gemeente"] == gemeente)
            & (
                df_long["indicator"]
                .astype(str)
                .str.strip()
                .str.lower()
                == indicator.strip().lower()
            )
        ]
        if r.empty:
            return None
        v = r.iloc[0]["waarde"]
        return None if pd.isna(v) else float(v)

    def val_text(indicator: str) -> Optional[str]:
        r = df_long[
            (df_long["gemeente"] == gemeente)
            & (
                df_long["indicator"]
                .astype(str)
                .str.strip()
                .str.lower()
                == indicator.strip().lower()
            )
        ]
        if r.empty:
            return None
        # originele waarde staat niet meer; neem indicatorwaarde uit bronbestand via opnieuw lezen (snel genoeg voor 13 gemeenten)
        return None


    def val_from(df: Optional[pd.DataFrame], indicator: str) -> Optional[float]:
        if df is None:
            return None
        r = df[
            (df["gemeente"] == gemeente)
            & (
                df["indicator"].astype(str).str.strip().str.lower()
                == indicator.strip().lower()
            )
        ]
        if r.empty:
            return None
        v = r.iloc[0]["waarde"]
        return None if pd.isna(v) else float(v)


    def val_text_from_begroting(indicator: str) -> Optional[str]:
        # Lees alleen de betreffende rij opnieuw uit het bronbestand om tekstwaarden te behouden
        try:
            df_raw = pd.read_csv("Begroting 2026.csv", sep=";", engine="python")
        except Exception:
            return None
        if df_raw.shape[1] < 2:
            return None
        indicator_col = df_raw.columns[0]
        df_raw[indicator_col] = (
            df_raw[indicator_col].astype(str).str.strip().str.lower()
        )
        row = df_raw[df_raw[indicator_col] == indicator.strip().lower()]
        if row.empty:
            return None
        if gemeente not in row.columns:
            return None
        return str(row.iloc[0][gemeente]).strip()


    def pct(numer: Optional[float], denom: Optional[float]) -> Optional[float]:
        if numer is None or denom is None:
            return None
        if denom == 0:
            return None
        return (float(numer) / float(denom)) * 100.0


    # ---- Indicatoren (zoals jouw lijst) ----
    rows = []

    lasten_2026 = val("Lasten (excl. reservemutaties) 2026")
    lasten_2027 = val("Lasten (excl. reservemutaties) 2027")
    lasten_2028 = val("Lasten (excl. reservemutaties) 2028")
    lasten_2029 = val("Lasten (excl. reservemutaties) 2029")

    res_2026 = val("Geraamd structureel rekeningresultaat 2026")
    res_2027 = val("Geraamd structureel rekeningresultaat 2027")
    res_2028 = val("Geraamd structureel rekeningresultaat 2028")
    res_2029 = val("Geraamd structureel rekeningresultaat 2029")

    br_struct_2026 = pct(res_2026, lasten_2026)
    br_struct_2027 = pct(res_2027, lasten_2027)
    br_struct_2028 = pct(res_2028, lasten_2028)
    br_struct_2029 = pct(res_2029, lasten_2029)

    rows += [
        (
            "Structureel resultaat",
            "Begrotingsresultaat (structureel)",
            br_struct_2026,
            score_indicator(weging, "Begrotingsresultaat (structureel)", br_struct_2026),
        ),
        (
            "Structureel resultaat",
            "Begrotingsresultaat (structureel) t+1",
            br_struct_2027,
            score_indicator(weging, "Begrotingsresultaat (structureel) t+1", br_struct_2027),
        ),
        (
            "Structureel resultaat",
            "Begrotingsresultaat (structureel) t+2",
            br_struct_2028,
            score_indicator(weging, "Begrotingsresultaat (structureel) t+2", br_struct_2028),
        ),
        (
            "Structureel resultaat",
            "Begrotingsresultaat (structureel) t+3",
            br_struct_2029,
            score_indicator(weging, "Begrotingsresultaat (structureel) t+3", br_struct_2029),
        ),
    ]

    # Resultaat jaarrekening (structureel) t-2: Jaarrekening.csv
    jr_struct = val_from(jaarrekening_long, "Gerealiseerd structureel rekeningresultaat")
    jr_lasten = val_from(jaarrekening_long, "Lasten (excl. reservemutaties)")
    jr_pct = pct(jr_struct, jr_lasten)
    rows += [
        (
            "Structureel resultaat",
            "Resultaat jaarrekening (structureel) t-2",
            jr_pct,
            score_indicator(weging, "Resultaat jaarrekening (structureel) t-2", jr_pct),
        ),
    ]

    # Sociaal domein: Hoger/Lager in CSV
    sociaal = val_text_from_begroting("Geraamde lasten sociaal domein")
    sociaal_bool = None
    if sociaal is not None:
        # weging gebruikt Ja/Nee; interpreteer Hoger -> Ja, Lager -> Nee
        if sociaal.strip().lower() == "hoger":
            sociaal_bool = "ja"
        elif sociaal.strip().lower() == "lager":
            sociaal_bool = "nee"
    rows += [
        (
            "Structureel resultaat",
            "Geraamde lasten Sociaal Domein",
            sociaal,
            score_indicator(weging, "Geraamde lasten Sociaal domein", None, sociaal_bool),
        ),
    ]

    # Onderhoud kapitaalgoederen
    beheerplannen = val("Aantal actuele beheerplannen")
    achterstallig = val_text_from_begroting("Achterstallig onderhoud")
    budget_correct = val_text_from_begroting("Beheerplannen budget correct in begroting")
    rows += [
        (
            "Onderhoud Kapitaalgoederen",
            "Aantal actuele beheerplannen (wegen (incl. kunstwerken, riol en gebouwen)",
            beheerplannen,
            score_indicator(
                weging,
                "Aantal actuele beheerplannen (wegen (incl. kunstwerken, riol en gebouwen)",
                beheerplannen,
            ),
        ),
        (
            "Onderhoud Kapitaalgoederen",
            "Achterstallig onderhoud",
            achterstallig,
            score_indicator(
                weging, "Achterstallig onderhoud", None, (achterstallig or "").strip().lower()
            ),
        ),
        (
            "Onderhoud Kapitaalgoederen",
            "Ramingen onderhoud overeenkomstig opgenomen",
            budget_correct,
            score_indicator(
                weging,
                "Ramingen onderhoud overeenkomstig opgenomen",
                None,
                (budget_correct or "").strip().lower(),
            ),
        ),
    ]

    # Taakstellingen/ombuigingen/Bezuinigingen (% van lasten 2026)
    taak = val("Taakstellingen/ombuigingen/Bezuinigingen")
    taak_pct = pct(taak, lasten_2026)
    rows += [
        (
            "Taakstellingen, Ombuigingen en Bezuinigingen",
            "Taakstelling/Ombuiingen/Bezuinigingen",
            taak_pct,
            score_indicator(weging, "Taakstelling/Ombuiingen/Bezuinigingen", taak_pct),
        ),
    ]

    # Weerstandsvermogen
    weerstandsratio = val("Weerstandsratio")
    rows += [
        (
            "Weerstandsvermogen en risicobeheersing",
            "Weestandsratio",
            weerstandsratio,
            score_indicator(weging, "Weestandsratio", weerstandsratio),
        ),
    ]

    # Risicobedrag / t.o.v  10% Gemeentefonds - OZB
    risicobedrag = val("Risicobedrag")
    gf_ratio = None
    if gf_2026 is not None and risicobedrag is not None:
        m = gf_2026[gf_2026["Naam"].str.strip().str.lower() == gemeente.strip().lower()]
        if not m.empty:
            overig = m.iloc[0].get("Overige eigen middelen", None)
            ozb = m.iloc[0].get("Onroerendezaakbelasting", None)
            try:
                basis = (
                    (float(ozb) - float(overig))
                    if ozb is not None and overig is not None
                    else None
                )
            except Exception:
                basis = None
            if basis and basis != 0:
                gf_ratio = (float(risicobedrag) / (0.10 * float(basis))) * 100.0

    rows += [
        (
            "Weerstandsvermogen en risicobeheersing",
            "Risicobedrag / t.o.v  10% Gemeentefonds - OZB",
            gf_ratio,
            score_indicator(weging, "Risicobedrag / t.o.v  10% Gemeentefonds - OZB", gf_ratio),
        ),
    ]

    # Surplus algemene reserve / totale lasten = (algemene reserve - risicobedrag) / lasten * 100
    alg_res = val("Algemene reserves")
    surplus = None
    if alg_res is not None and risicobedrag is not None and lasten_2026:
        surplus = pct(alg_res - risicobedrag, lasten_2026)
    rows += [
        (
            "Weerstandsvermogen en risicobeheersing",
            "Surplus algemene reserve / totale lasten",
            surplus,
            score_indicator(weging, "Surplus algemene reserve / totale lasten", surplus),
        ),
    ]

    # Kengetallen (opgave gemeente)
    schulden = val("Netto schuldquote (opgave gemeente)")
    solv = val("Solvabiliteitsratio (opgave gemeente)")
    onbenut = val("Onbenutte belastingcapaciteit")
    onbenut_pct = pct(onbenut, lasten_2026)
    rows += [
        ("Kengetallen", "Schuldenquote", schulden, score_indicator(weging, "Schuldenquote", schulden)),
        ("Kengetallen", "Solvabiliteitsratio", solv, score_indicator(weging, "Solvabiliteitsratio", solv)),
        (
            "Kengetallen",
            "Onbenutte belastingcapaciteit / totale lasten",
            onbenut_pct,
            score_indicator(weging, "Onbenutte belastingcapaciteit / totale lasten", onbenut_pct),
        ),
    ]

    # Grondexploitaties (%)
    grx = val("Grondexploitatie (opgave gemeente)")
    rows += [
        ("Grondexploitaties", "% Grondexploitatie", grx, score_indicator(weging, "% Grondexploitatie", grx)),
    ]

    # Gemeenschappelijke regelingen / verbonden partijen (% van lasten 2026)
    vp = val("Verbonden partijen")
    vp_pct = pct(vp, lasten_2026)
    rows += [
        (
            "Gemeenschappelijke regelingen",
            "% Verbonden partijen",
            vp_pct,
            score_indicator(weging, "% Verbonden partijen", vp_pct),
        ),
    ]

    df_out = pd.DataFrame(
        rows, columns=["Categorie", "Indicator", "Waarde 2026", "Score 2026"]
    )

    # Format waarde: percentages voor berekende pcts; tekst laten staan
    def fmt_waarde(x):
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return ""
        if isinstance(x, (int, float)):
            return f"{x:,.2f}%"
        return str(x)

    df_show = df_out.copy()
    df_show["Waarde 2026"] = df_show["Waarde 2026"].apply(fmt_waarde)
    df_show["Score 2026"] = df_show["Score 2026"].apply(
        lambda x: ""
        if x is None or (isinstance(x, float) and pd.isna(x))
        else f"{float(x):,.2f}"
    )

    st.dataframe(df_show, width="stretch", hide_index=True)

    totaal = pd.to_numeric(df_out["Score 2026"], errors="coerce").fillna(0).sum()
    st.metric("Totaalscore 2026", f"{totaal:,.2f}")

    if gf_2026 is None:
        st.warning(
            "`Gemeentefonds_2026.csv` ontbreekt of is niet leesbaar; de gemeentefonds-indicator kan dan niet worden berekend."
        )

with tab_reserves:
    st.subheader("Reserves per inwoner")
    st.caption("Bron: `Begroting 2026.csv`.")

    df_beg = load_begroting_provincies(2026)
    if df_beg is None:
        st.warning("Bestand `Begroting 2026.csv` niet gevonden of niet leesbaar.")
        st.stop()

    gemeenten = sorted(df_beg["gemeente"].dropna().unique().tolist())

    def get_val(g: str, indicator: str) -> Optional[float]:
        r = df_beg[
            (df_beg["gemeente"] == g)
            & (
                df_beg["indicator"].astype(str).str.strip().str.lower()
                == indicator.strip().lower()
            )
        ]
        if r.empty:
            return None
        v = r.iloc[0]["waarde"]
        return None if pd.isna(v) else float(v)

    rows_res = []
    for g in gemeenten:
        ar = get_val(g, "Algemene reserves")
        br = get_val(g, "Bestemmingsreserves")
        inwoners = get_val(g, "Aantal inwoners")
        # Reserves staan in bron als x € 1.000 → per inwoner in euro's = (reserve * 1000) / inwoners
        ar_inw = (ar * 1000 / inwoners) if (ar is not None and inwoners and inwoners != 0) else None
        br_inw = (br * 1000 / inwoners) if (br is not None and inwoners and inwoners != 0) else None
        rows_res.append(
            {
                "Gemeente": g,
                "AR inwoner": ar_inw,
                "AR Totaal": ar,
                "BR inwoner": br_inw,
                "BR Totaal": br,
            }
        )

    df_res = pd.DataFrame(rows_res)
    ar_tot = pd.to_numeric(df_res["AR Totaal"], errors="coerce").fillna(0).sum()
    br_tot = pd.to_numeric(df_res["BR Totaal"], errors="coerce").fillna(0).sum()
    inw_tot = 0.0
    for g in gemeenten:
        v = get_val(g, "Aantal inwoners")
        inw_tot += float(v or 0)

    totaal_row = {
        "Gemeente": "Totaal",
        "AR inwoner": (ar_tot * 1000 / inw_tot) if inw_tot else None,
        "AR Totaal": ar_tot,
        "BR inwoner": (br_tot * 1000 / inw_tot) if inw_tot else None,
        "BR Totaal": br_tot,
    }
    df_res = pd.concat([df_res, pd.DataFrame([totaal_row])], ignore_index=True)

    # Kaart (bubbels) – vaste centroid-coördinaten Zeeland
    # Bron: openbare centroid-benaderingen (handmatig), bedoeld voor visualisatie.
    coords = {
        "Borsele": (51.428, 3.804),
        "Goes": (51.504, 3.889),
        "Hulst": (51.280, 4.053),
        "Kapelle": (51.488, 3.959),
        "Middelburg": (51.499, 3.613),
        "Noord-Beveland": (51.577, 3.749),
        "Reimerswaal": (51.450, 4.088),
        "Schouwen-Duiveland": (51.692, 3.936),
        "Sluis": (51.309, 3.386),
        "Terneuzen": (51.336, 3.830),
        "Tholen": (51.531, 4.220),
        "Veere": (51.548, 3.594),
        "Vlissingen": (51.443, 3.574),
    }

    df_map = df_res[df_res["Gemeente"] != "Totaal"].copy()
    df_map["lat"] = df_map["Gemeente"].apply(lambda g: coords.get(g, (None, None))[0])
    df_map["lon"] = df_map["Gemeente"].apply(lambda g: coords.get(g, (None, None))[1])
    df_map = df_map.dropna(subset=["lat", "lon"])

    st.markdown("**Kaart – reserves per inwoner**")
    col_map1, col_map2 = st.columns(2)

    def _bubble_layer(df, value_col: str):
        # radius schaal: px ~ waarde (clamp)
        v = pd.to_numeric(df[value_col], errors="coerce").fillna(0)
        radius = (v.clip(lower=0) / (v[v > 0].median() if (v > 0).any() else 1.0)) * 8000
        df2 = df.copy()
        df2["_radius"] = radius.clip(lower=2000, upper=30000)
        return df2

    import pydeck as pdk

    with col_map1:
        st.caption("Algemene reserve per inwoner (€/inw)")
        df_ar = _bubble_layer(df_map, "AR inwoner")
        view = pdk.ViewState(latitude=51.52, longitude=3.88, zoom=8.2, pitch=0)
        layer = pdk.Layer(
            "ScatterplotLayer",
            data=df_ar,
            get_position="[lon, lat]",
            get_radius="_radius",
            get_fill_color=[70, 170, 70, 160],
            pickable=True,
        )
        st.pydeck_chart(
            pdk.Deck(
                layers=[layer],
                initial_view_state=view,
                tooltip={"text": "{Gemeente}\nAR/inw: {AR inwoner}\nAR totaal: {AR Totaal}"},
            )
        )

    with col_map2:
        st.caption("Bestemmingsreserve per inwoner (€/inw)")
        df_br = _bubble_layer(df_map, "BR inwoner")
        view = pdk.ViewState(latitude=51.52, longitude=3.88, zoom=8.2, pitch=0)
        layer = pdk.Layer(
            "ScatterplotLayer",
            data=df_br,
            get_position="[lon, lat]",
            get_radius="_radius",
            get_fill_color=[70, 170, 70, 160],
            pickable=True,
        )
        st.pydeck_chart(
            pdk.Deck(
                layers=[layer],
                initial_view_state=view,
                tooltip={"text": "{Gemeente}\nBR/inw: {BR inwoner}\nBR totaal: {BR Totaal}"},
            )
        )

    def fmt_num_nl(x, decimals=0):
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return ""
        s = f"{float(x):,.{decimals}f}"
        # NL: duizendtallen met punt, decimalen met komma
        s = s.replace(",", "X").replace(".", ",").replace("X", ".")
        return s

    df_show = df_res.copy()
    df_show["AR inwoner"] = df_show["AR inwoner"].apply(lambda x: fmt_num_nl(x, 0))
    df_show["BR inwoner"] = df_show["BR inwoner"].apply(lambda x: fmt_num_nl(x, 0))
    df_show["AR Totaal"] = df_show["AR Totaal"].apply(lambda x: fmt_num_nl(x, 0))
    df_show["BR Totaal"] = df_show["BR Totaal"].apply(lambda x: fmt_num_nl(x, 0))

    st.dataframe(df_show, width="stretch", hide_index=True)
    st.caption("AR/BR totalen zijn x € 1.000 (zoals in de bron). AR/BR per inwoner is omgerekend naar euro's (× 1.000).")

