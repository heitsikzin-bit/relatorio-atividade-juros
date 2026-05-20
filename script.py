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


def _get_json(url, retries=5, timeout=90):
    for tentativa in range(1, retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            if r.status_code == 404:
                print(f"  série/intervalo inexistente (404). Retornando vazio.")
                return []
            r.raise_for_status()
            if not r.text.strip():
                print(f"  resposta vazia do servidor. Tratando como 'sem dados'.")
                return []
            return r.json()
        except (requests.exceptions.ReadTimeout,
                requests.exceptions.ConnectionError) as e:
            espera = 5 * tentativa
            print(f"  tentativa {tentativa}/{retries} falhou ({e.__class__.__name__}). Esperando {espera}s...")
            time.sleep(espera)
        except (requests.exceptions.HTTPError, ValueError) as e:
            espera = 5 * tentativa
            print(f"  tentativa {tentativa}/{retries} falhou ({e.__class__.__name__}: {e}). Esperando {espera}s...")
            time.sleep(espera)
    raise RuntimeError(f"Falhou após {retries} tentativas: {url}")


def get_fred(series_id):
    url = (
        f"https://api.stlouisfed.org/fred/series/observations"
        f"?series_id={series_id}&api_key={FRED_API_KEY}"
        f"&observation_start={START_DATE}&observation_end={END_DATE}"
        f"&file_type=json"
    )
    data = _get_json(url)["observations"]
    s = pd.Series({o["date"]: float(o["value"]) for o in data if o["value"] != "."})
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
        pedacos.extend(data)
        inicio = prox + relativedelta(days=1)

    if not pedacos:
        print(f"  AVISO: série {code} não retornou dados em nenhum período.")
        return pd.Series(dtype=float)

    s = pd.Series({r["data"]: float(r["valor"].replace(",", ".")) for r in pedacos})
    s.index = pd.to_datetime(s.index, dayfirst=True)
    s = s[~s.index.duplicated(keep="first")].sort_index()
    return s


print("Baixando FRED...")
fred = {k: get_fred(v) for k, v in FRED_SERIES.items()}

print("Baixando BCB...")
bcb = {k: get_bcb(v) for k, v in BCB_SERIES.items()}

df_usa = pd.DataFrame(fred).resample("ME").last()
df_bra = pd.DataFrame(bcb).resample("ME").last()


def describe_pair(sa, nsa, label):
    print(f"\n--- {label} ---")
    sa_aligned, nsa_aligned = sa.align(nsa, join="inner")
    if sa_aligned.empty or nsa_aligned.empty:
        print("  (sem dados sobrepostos para comparar)")
        return
    print(f"Correlação SA vs NSA : {sa_aligned.corr(nsa_aligned):.4f}")
    diff = (sa_aligned - nsa_aligned).dropna()
    print(f"Diferença média      : {diff.mean():.4f}")
    print(f"Desvio da diferença  : {diff.std():.4f}")


describe_pair(df_usa["ind_prod_sa"], df_usa["ind_prod_nsa"], "Prod. Industrial EUA")
describe_pair(df_bra["ind_prod_sa"], df_bra["ind_prod_nsa"], "Prod. Industrial Brasil")

fig, axes = plt.subplots(2, 2, figsize=(14, 8))
fig.suptitle("Acompanhamento de Atividade e Juros — Brasil e EUA")

df_usa[["ind_prod_sa", "ind_prod_nsa"]].plot(ax=axes[0, 0], title="Prod. Industrial EUA")
axes[0, 0].legend(["Ajustada", "Não Ajustada"])

df_usa["fed_funds"].plot(ax=axes[0, 1], title="Fed Funds (%)", color="firebrick")

df_bra[["ind_prod_sa", "ind_prod_nsa"]].plot(ax=axes[1, 0], title="Prod. Industrial Brasil")
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
