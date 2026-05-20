import os
import time
import pandas as pd
import requests
import matplotlib.pyplot as plt
from datetime import datetime

FRED_API_KEY = os.environ["FRED_API_KEY"]

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


def _request_with_retry(url, retries=5, timeout=90):
    for tentativa in range(1, retries + 1):
        try:
            r = requests.get(url, timeout=timeout)
            r.raise_for_status()
            return r
        except (requests.exceptions.ReadTimeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.HTTPError) as e:
            espera = 5 * tentativa
            print(f"  tentativa {tentativa}/{retries} falhou ({e.__class__.__name__}). Esperando {espera}s...")
            time.sleep(espera)
    raise RuntimeError(f"Falhou após {retries} tentativas: {url}")


def get_fred(series_id):
    url = (
        f"https://api.stlouisfed.org/fred/series/observations"
        f"?series_id={series_id}&api_key={FRED_API_KEY}"
        f"&observation_start={START_DATE}&observation_end={END_DATE}"
        f"&file_type=json"
    )
    data = _request_with_retry(url).json()["observations"]
    s = pd.Series({o["date"]: float(o["value"]) for o in data if o["value"] != "."})
    s.index = pd.to_datetime(s.index)
    return s


def get_bcb(code):
    di = "01/01/2000"
    df = datetime.today().strftime("%d/%m/%Y")
    url = (
        f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"
        f"?formato=json&dataInicial={di}&dataFinal={df}"
    )
    data = _request_with_retry(url).json()
    s = pd.Series({r["data"]: float(r["valor"].replace(",", ".")) for r in data})
    s.index = pd.to_datetime(s.index, dayfirst=True)
    return s


print("Baixando FRED...")
fred = {k: get_fred(v) for k, v in FRED_SERIES.items()}
print("Baixando BCB...")
bcb = {k: get_bcb(v) for k, v in BCB_SERIES.items()}

df_usa = pd.DataFrame(fred).resample("ME").last()
df_bra = pd.DataFrame(bcb).resample("ME").last()


def describe_pair(sa, nsa, label):
    print(f"\n--- {label} ---")
    print(f"Correlação SA vs NSA : {sa.corr(nsa):.4f}")
    diff = (sa - nsa).dropna()
    print(f"Diferença média      : {diff.mean():.4f}")
    print(f"Desvio da diferença  : {diff.std():.4f}")


describe_pair(df_usa["ind_prod_sa"], df_usa["ind_prod_nsa"], "Prod. Industrial EUA")
describe_pair(df_bra["ind_prod_sa"], df_bra["ind_prod_nsa"], "Prod. Industrial Brasil")

fig, axes = plt.subplots(2, 2, figsize=(14, 8))
fig.suptitle("Acompanhamento de Atividade e Juros — Brasil e EUA")
df_usa[["ind_prod_sa", "ind_prod_nsa"]].plot(ax=axes[0, 0], title="Prod. Industrial EUA")
df_usa["fed_funds"].plot(ax=axes[0, 1], title="Fed Funds (%)", color="firebrick")
df_bra[["ind_prod_sa", "ind_prod_nsa"]].plot(ax=axes[1, 0], title="Prod. Industrial Brasil")
df_bra["selic"].plot(ax=axes[1, 1], title="Selic (% a.a.)", color="seagreen")
plt.tight_layout()
plt.savefig("relatorio.png", dpi=150)

with pd.ExcelWriter("relatorio_atividade_juros.xlsx", engine="openpyxl") as writer:
    df_usa.to_excel(writer, sheet_name="EUA")
    df_bra.to_excel(writer, sheet_name="Brasil")

df_usa.to_csv("eua.csv")
df_bra.to_csv("brasil.csv")
print("\nArquivos gerados com sucesso.")
