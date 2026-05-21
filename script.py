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
    "ind_prod_sa": 21859,  # PIM-PF dessazonalizado (BCB SGS)
    "selic":       432,    # Selic meta
}
START_DATE = "2000-01-01"
END_DATE   = datetime.today().strftime("%Y-%m-%d")


def _get(url, retries=3, timeout=60):
    for tentativa in range(1, retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            if r.status_code == 404 or not r.text.strip():
                return None
            if r.status_code >= 400:
                time.sleep(3 * tentativa); continue
            return r.json()
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError, ValueError):
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
        return pd.Series(dtype=float)
    s = pd.Series({r["data"]: float(r["valor"].replace(",", ".")) for r in pedacos})
    s.index = pd.to_datetime(s.index, dayfirst=True)
    return s[~s.index.duplicated(keep="first")].sort_index()


def get_ibge_pim(variavel_id):
    """PIM-PF do IBGE SIDRA. variavel: 12606=índice, 12607=índice dessaz."""
    url = (f"https://servicodados.ibge.gov.br/api/v3/agregados/8888/"
           f"periodos/-360/variaveis/{variavel_id}?localidades=N1[all]")
    print(f"  IBGE PIM-PF variável {variavel_id}")
    payload = _get(url)
    if not payload:
        return pd.Series(dtype=float)
    serie_dict = payload[0]["resultados"][0]["series"][0]["serie"]
    s = pd.Series({k: float(v) for k, v in serie_dict.items() if v not in ("", "...", "-")})
    s.index = pd.to_datetime(s.index, format="%Y%m")
    return s


print("Baixando FRED...")
fred = {k: get_fred(v) for k, v in FRED_SERIES.items()}

print("\nBaixando BCB...")
bcb = {k: get_bcb(v) for k, v in BCB_SERIES.items()}

print("\nBaixando IBGE (PIM-PF Brasil)...")
ibge = {
    "ind_prod_sa":  get_ibge_pim(12607),  # com ajuste sazonal
    "ind_prod_nsa": get_ibge_pim(12606),  # sem ajuste sazonal
}

df_usa = pd.DataFrame(fred).resample("ME").last()
df_bra = pd.DataFrame({
    "ind_prod_sa":  ibge["ind_prod_sa"],
    "ind_prod_nsa": ibge["ind_prod_nsa"],
    "selic":        bcb["selic"],
}).resample("ME").last()


def describe_pair(df, sa_col, nsa_col, label):
    print(f"\n--- {label} ---")
    if sa_col not in df.columns or nsa_col not in df.columns:
        print("  (uma das séries está ausente)"); return
    sa, nsa = df[sa_col].dropna().align(df[nsa_col].dropna(), join="inner")
    if sa.empty:
        print("  (sem sobreposição de datas)"); return
    print(f"Correlação SA vs NSA : {sa.corr(nsa):.4f}")
    diff = (sa - nsa).dropna()
    print(f"Diferença média      : {diff.mean():.4f}")
    print(f"Desvio da diferença  : {diff.std():.4f}")


describe_pair(df_usa, "ind_prod_sa", "ind_prod_nsa", "Prod. Industrial EUA")
describe_pair(df_bra, "ind_prod_sa", "ind_prod_nsa", "Prod. Industrial Brasil")

fig, axes = plt.subplots(2, 2, figsize=(14, 8))
fig.suptitle("Acompanhamento de Atividade e Juros — Brasil e EUA")

df_usa[["ind_prod_sa", "ind_prod_nsa"]].plot(ax=axes[0, 0], title="Prod. Industrial EUA")
axes[0, 0].legend(["Ajustada", "Não Ajustada"])
df_usa["fed_funds"].plot(ax=axes[0, 1], title="Fed Funds (%)", color="firebrick")
df_bra[["ind_prod_sa", "ind_prod_nsa"]].plot(ax=axes[1, 0], title="Prod. Industrial Brasil (IBGE)")
axes[1, 0].legend(["Ajustada", "Não Ajustada"])
df_bra["selic"].plot(ax=axes[1, 1], title="Selic (% a.a.)", color="seagreen")

plt.tight_layout()
plt.savefig("relatorio.png", dpi=150)

with pd.ExcelWriter("relatorio_atividade_juros.xlsx", engine="openpyxl") as writer:
    df_usa.to_excel(writer, sheet_name="EUA")
    df_bra.to_excel(writer, sheet_name="Brasil")
df_usa.to_csv("eua.csv")
df_bra.to_csv("brasil.csv")

print("\nArquivos gerados com sucesso.")
