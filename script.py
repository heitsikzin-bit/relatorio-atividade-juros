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
    "ind_prod_nsa": 21858,
    "selic":        432,
}
START_DATE = "2000-01-01"
END_DATE   = datetime.today().strftime("%Y-%m-%d")


def _get_json(url, retries=3, timeout=60):
    """Retorna lista vazia se falhar — nunca lança exceção."""
    for tentativa in range(1, retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            if r.status_code == 404:
                return []
            if r.status_code >= 400:
                print(f"  HTTP {r.status_code}, tentando de novo...")
                time.sleep(3 * tentativa)
                continue
            if not r.text.strip():
                return []
            try:
                return r.json()
            except ValueError:
                print(f"  resposta não é JSON (primeiros 100 chars): {r.text[:100]!r}")
                time.sleep(3 * tentativa)
                continue
        except (requests.exceptions.ReadTimeout,
                requests.exceptions.ConnectionError) as e:
            print(f"  tentativa {tentativa}/{retries} falhou ({e.__class__.__name__}).")
            time.sleep(3 * tentativa)
    print(f"  AVISO: desisti de {url} após {retries} tentativas.")
    return []


def get_fred(series_id):
    url = (
        f"https://api.stlouisfed.org/fred/series/observations"
        f"?series_id={series_id}&api_key={FRED_API_KEY}"
        f"&observation_start={START_DATE}&observation_end={END_DATE}"
        f"&file_type=json"
    )
    payload = _get_json(url)
    if not payload or "observations" not in payload:
        print(f"  AVISO: FRED {series_id} sem dados.")
        return pd.Series(dtype=float)
    obs = payload["observations"]
    s = pd.Series({o["date"]: float(o["value"]) for o in obs if o["value"] != "."})
    s.index = pd.to_datetime(s.index)
    return s


def get_bcb(code):
    inicio = datetime(2000, 1, 1)
    fim    = datetime.today()
    pedacos = []

    while inicio < fim:
        prox = min(inicio + relativedelta(years=10), fim)
        di = inicio.strftime("%d/%m/%Y")
        df = prox.strftime("%d/%m/%Y")
        url = (
            f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"
            f"?formato=json&dataInicial={di}&dataFinal={df}"
        )
        print(f"  BCB {code}: {di} a {df}")
        data = _get_json(url)
        if isinstance(data, list):
            pedacos.extend(data)
        inicio = prox + relativedelta(days=1)

    if not pedacos:
        print(f"  AVISO: série BCB {code} sem dados.")
        return pd.Series(dtype=float)

    s = pd.Series({r["data"]: float(r["valor"].replace(",", ".")) for r in pedacos})
    s.index = pd.to_datetime(s.index, dayfirst=True)
    s = s[~s.index.duplicated(keep="first")].sort_index()
    return s


print("Baixando FRED...")
fred = {k: get_fred(v) for k, v in FRED_SERIES.items()}

print("\nBaixando BCB...")
bcb = {k: get_bcb(v) for k, v in BCB_SERIES.items()}

df_usa = pd.DataFrame(fred).resample("ME").last()
df_bra = pd.DataFrame(bcb).resample("ME").last()


def describe_pair(df, sa_col, nsa_col, label):
    print(f"\n--- {label} ---")
    if sa_col not in df.columns or nsa_col not in df.columns:
        print("  (uma das séries está ausente)")
        return
    sa, nsa = df[sa_col].dropna(), df[nsa_col].dropna()
    sa_a, nsa_a = sa.align(nsa, join="inner")
    if sa_a.empty:
        print("  (sem sobreposição de datas)")
        return
    print(f"Correlação SA vs NSA : {sa_a.corr(nsa_a):.4f}")
    diff = (sa_a - nsa_a).dropna()
    print(f"Diferença média      : {diff.mean():.4f}")
    print(f"Desvio da diferença  : {diff.std():.4f}")


describe_pair(df_usa, "ind_prod_sa", "ind_prod_nsa", "Prod. Industrial EUA")
describe_pair(df_bra, "ind_prod_sa", "ind_prod_nsa", "Prod. Industrial Brasil")

fig, axes = plt.subplots(2, 2, figsize=(14, 8))
fig.suptitle("Acompanhamento de Atividade e Juros — Brasil e EUA")

cols_usa = [c for c in ["ind_prod_sa", "ind_prod_nsa"] if c in df_usa.columns]
if cols_usa:
    df_usa[cols_usa].plot(ax=axes[0, 0], title="Prod. Industrial EUA")
if "fed_funds" in df_usa.columns:
    df_usa["fed_funds"].plot(ax=axes[0, 1], title="Fed Funds (%)", color="firebrick")

cols_bra = [c for c in ["ind_prod_sa", "ind_prod_nsa"] if c in df_bra.columns]
if cols_bra:
    df_bra[cols_bra].plot(ax=axes[1, 0], title="Prod. Industrial Brasil")
if "selic" in df_bra.columns:
    df_bra["selic"].plot(ax=axes[1, 1], title="Selic (% a.a.)", color="seagreen")

plt.tight_layout()
plt.savefig("relatorio.png", dpi=150)

with pd.ExcelWriter("relatorio_atividade_juros.xlsx", engine="openpyxl") as writer:
    df_usa.to_excel(writer, sheet_name="EUA")
    df_bra.to_excel(writer, sheet_name="Brasil")

df_usa.to_csv("eua.csv")
df_bra.to_csv("brasil.csv")

print("\nArquivos gerados com sucesso.")
