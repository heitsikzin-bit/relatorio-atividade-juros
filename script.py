import os
import time
import pandas as pd
import requests
import matplotlib.pyplot as plt
from datetime import datetime
from dateutil.relativedelta import relativedelta

FRED_API_KEY = os.environ["FRED_API_KEY"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (relatorio-eesp-quant)",
    "Accept": "application/json",
}

FRED_SERIES = {
    "ind_prod_sa":  "INDPRO",
    "ind_prod_nsa": "IPB50001N",
    "fed_funds":    "FEDFUNDS",
}

BCB_SERIES = {
    "ind_prod_sa":  21859,
    "ind_prod_nsa": 28503,
    "selic":        432,
}

START_DATE = "2000-01-01"
END_DATE   = datetime.today().strftime("%Y-%m-%d")


# ─── COLETA ──────────────────────────────────────────────────

def _get(url, retries=3, timeout=60):
    for tentativa in range(1, retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            if r.status_code == 404 or not r.text.strip():
                return None
            if r.status_code >= 400:
                time.sleep(3 * tentativa); continue
            return r.json()
        except (requests.exceptions.ReadTimeout,
                requests.exceptions.ConnectionError,
                ValueError):
            time.sleep(3 * tentativa)
    return None


def get_fred(series_id):
    url = (f"https://api.stlouisfed.org/fred/series/observations"
           f"?series_id={series_id}&api_key={FRED_API_KEY}"
           f"&observation_start={START_DATE}&observation_end={END_DATE}&file_type=json")
    payload = _get(url)
    if not payload:
        return pd.Series(dtype=float)
    obs = payload.get("observations", [])
    s = pd.Series({o["date"]: float(o["value"]) for o in obs if o["value"] != "."})
    s.index = pd.to_datetime(s.index)
    return s


def get_bcb(code):
    inicio, fim = datetime(2000, 1, 1), datetime.today()
    pedacos = []
    while inicio < fim:
        prox = min(inicio + relativedelta(years=10), fim)
        url = (f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"
               f"?formato=json&dataInicial={inicio:%d/%m/%Y}&dataFinal={prox:%d/%m/%Y}")
        print(f"  BCB {code}: {inicio:%Y-%m-%d} a {prox:%Y-%m-%d}")
        data = _get(url)
        if isinstance(data, list):
            pedacos.extend(data)
        inicio = prox + relativedelta(days=1)
    if not pedacos:
        print(f"  AVISO: série BCB {code} sem dados.")
        return pd.Series(dtype=float)
    s = pd.Series({r["data"]: float(r["valor"].replace(",", ".")) for r in pedacos})
    s.index = pd.to_datetime(s.index, dayfirst=True)
    return s[~s.index.duplicated(keep="first")].sort_index()


print("Baixando FRED...")
fred = {k: get_fred(v) for k, v in FRED_SERIES.items()}

print("\nBaixando BCB...")
bcb = {k: get_bcb(v) for k, v in BCB_SERIES.items()}

df_usa = pd.DataFrame(fred).resample("ME").last()
df_bra = pd.DataFrame(bcb).resample("ME").last()


# ─── ANÁLISE DESCRITIVA (log) ────────────────────────────────

def describe_pair(df, sa_col, nsa_col, label):
    print(f"\n--- {label} ---")
    if sa_col not in df.columns or nsa_col not in df.columns:
        print("  (uma das séries está ausente)"); return
    sa = df[sa_col].dropna()
    nsa = df[nsa_col].dropna()
    sa_a, nsa_a = sa.align(nsa, join="inner")
    if sa_a.empty:
        print("  (sem sobreposição de datas)"); return
    print(f"Correlação SA vs NSA : {sa_a.corr(nsa_a):.4f}")
    diff = (sa_a - nsa_a).dropna()
    print(f"Diferença média      : {diff.mean():.4f}")
    print(f"Desvio da diferença  : {diff.std():.4f}")


describe_pair(df_usa, "ind_prod_sa", "ind_prod_nsa", "Prod. Industrial EUA")
describe_pair(df_bra, "ind_prod_sa", "ind_prod_nsa", "Prod. Industrial Brasil")


# ─── GRÁFICOS ────────────────────────────────────────────────

def plot_safe(serie_ou_df, ax, title, **kwargs):
    if isinstance(serie_ou_df, pd.Series):
        dados = serie_ou_df.dropna()
    else:
        dados = serie_ou_df.dropna(how="all")
    if dados.empty:
        ax.set_title(f"{title} (sem dados)"); return
    dados.plot(ax=ax, title=title, **kwargs)


fig, axes = plt.subplots(2, 2, figsize=(14, 8))
fig.suptitle("Acompanhamento de Atividade e Juros — Brasil e EUA")

plot_safe(df_usa[["ind_prod_sa", "ind_prod_nsa"]], axes[0, 0], "Prod. Industrial EUA")
plot_safe(df_usa["fed_funds"],                    axes[0, 1], "Fed Funds (%)", color="firebrick")

cols_bra = [c for c in ["ind_prod_sa", "ind_prod_nsa"]
            if c in df_bra.columns and df_bra[c].notna().any()]
if cols_bra:
    plot_safe(df_bra[cols_bra], axes[1, 0], "Prod. Industrial Brasil")
else:
    axes[1, 0].set_title("Prod. Industrial Brasil (sem dados)")

plot_safe(df_bra["selic"], axes[1, 1], "Selic (% a.a.)", color="seagreen")

plt.tight_layout()
plt.savefig("relatorio.png", dpi=150)


# ─── ESTATÍSTICAS DESCRITIVAS ────────────────────────────────

def estatisticas(df, label):
    desc = df.describe().T
    desc.columns = ["N", "Média", "Desvio", "Mínimo", "25%", "Mediana", "75%", "Máximo"]
    desc["País"] = label
    desc.index.name = "Série"
    return desc.reset_index()


def comparacao_sa_nsa(df, sa_col, nsa_col, label):
    if sa_col not in df.columns or nsa_col not in df.columns:
        return None
    sa, nsa = df[sa_col].dropna().align(df[nsa_col].dropna(), join="inner")
    if sa.empty:
        return None
    diff = sa - nsa
    var_sa  = sa.pct_change(12).dropna() * 100
    var_nsa = nsa.pct_change(12).dropna() * 100
    return pd.DataFrame({
        "Métrica": [
            "Correlação SA vs NSA",
            "Diferença média (SA − NSA)",
            "Desvio padrão da diferença",
            "Diferença mínima",
            "Diferença máxima",
            "Variação interanual média SA (%)",
            "Variação interanual média NSA (%)",
            "Período inicial",
            "Período final",
            "Nº de observações",
        ],
        "Valor": [
            f"{sa.corr(nsa):.4f}",
            f"{diff.mean():.4f}",
            f"{diff.std():.4f}",
            f"{diff.min():.4f}",
            f"{diff.max():.4f}",
            f"{var_sa.mean():.2f}",
            f"{var_nsa.mean():.2f}",
            f"{sa.index.min():%Y-%m}",
            f"{sa.index.max():%Y-%m}",
            f"{len(sa)}",
        ],
        "País": label,
    })


desc_usa = estatisticas(df_usa, "EUA")
desc_bra = estatisticas(df_bra, "Brasil")
desc_geral = pd.concat([desc_usa, desc_bra], ignore_index=True)

comp_usa = comparacao_sa_nsa(df_usa, "ind_prod_sa", "ind_prod_nsa", "EUA")
comp_bra = comparacao_sa_nsa(df_bra, "ind_prod_sa", "ind_prod_nsa", "Brasil")
comparacao = pd.concat([c for c in [comp_usa, comp_bra] if c is not None], ignore_index=True)

print("\n=== Estatísticas Descritivas ===")
print(desc_geral.to_string(index=False))
print("\n=== Comparação SA vs NSA ===")
print(comparacao.to_string(index=False))


# ─── EXPORTAÇÃO ──────────────────────────────────────────────

with pd.ExcelWriter("relatorio_atividade_juros.xlsx", engine="openpyxl") as writer:
    df_usa.to_excel(writer, sheet_name="EUA")
    df_bra.to_excel(writer, sheet_name="Brasil")
    desc_geral.to_excel(writer, sheet_name="Estatísticas", index=False)
    comparacao.to_excel(writer, sheet_name="Comparação SA-NSA", index=False)

df_usa.to_csv("eua.csv")
df_bra.to_csv("brasil.csv")
desc_geral.to_csv("estatisticas.csv", index=False)
comparacao.to_csv("comparacao_sa_nsa.csv", index=False)

print("\nArquivos gerados com sucesso.")
