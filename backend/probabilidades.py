import numpy as np
from scipy.stats import poisson

# Fator de vantagem de jogar em casa
FATOR_CASA = 1.1
MAX_GOLS = 7


def calcular_analise_completa(stats_casa: dict, stats_fora: dict) -> dict:
    sc = stats_casa["stats"]
    sf = stats_fora["stats"]

    # Força de ataque e defesa usando médias cruzadas (Dixon-Coles simplificado)
    # Casa ataca em casa, fora ataca fora
    lambda_casa = sc["gols_marcados_media_casa"] * sf["gols_sofridos_media_fora"] * FATOR_CASA
    lambda_fora = sf["gols_marcados_media_fora"] * sc["gols_sofridos_media_casa"]

    # Garante valores mínimos razoáveis
    lambda_casa = max(lambda_casa, 0.3)
    lambda_fora = max(lambda_fora, 0.3)

    gols = _probabilidades_gols(lambda_casa, lambda_fora)
    escanteios = _probabilidades_escanteios(
        sc["escanteios_marcados_media"],
        sf["escanteios_marcados_media"],
    )

    return {
        "lambda_casa": round(lambda_casa, 3),
        "lambda_fora": round(lambda_fora, 3),
        "resultado": gols["resultado"],
        "over_under_gols": gols["over_under"],
        "placares_top": gols["placares_top"],
        "escanteios": escanteios,
    }


def _probabilidades_gols(lam_casa: float, lam_fora: float) -> dict:
    matriz = np.zeros((MAX_GOLS, MAX_GOLS))

    for i in range(MAX_GOLS):
        for j in range(MAX_GOLS):
            matriz[i][j] = poisson.pmf(i, lam_casa) * poisson.pmf(j, lam_fora)

    vitoria_casa = float(np.sum(np.tril(matriz, -1)))
    empate = float(np.sum(np.diag(matriz)))
    vitoria_fora = float(np.sum(np.triu(matriz, 1)))

    # Normaliza para 100% (truncagem em MAX_GOLS gera pequena perda)
    total = vitoria_casa + empate + vitoria_fora
    vitoria_casa /= total
    empate /= total
    vitoria_fora /= total

    over_1_5 = 1 - float(np.sum(matriz[:2, :2]))
    over_2_5 = 1 - float(np.sum(matriz[:3, :3]))
    over_3_5 = 1 - float(np.sum(matriz[:4, :4]))
    btts = float(np.sum(matriz[1:, 1:]))  # ambos marcam

    # Top 10 placares mais prováveis
    placares = []
    for i in range(MAX_GOLS):
        for j in range(MAX_GOLS):
            placares.append({"placar": f"{i}x{j}", "prob": round(matriz[i][j] * 100, 2)})
    placares.sort(key=lambda x: x["prob"], reverse=True)

    return {
        "resultado": {
            "vitoria_casa": round(vitoria_casa * 100, 1),
            "empate": round(empate * 100, 1),
            "vitoria_fora": round(vitoria_fora * 100, 1),
        },
        "over_under": {
            "over_1_5": round(over_1_5 * 100, 1),
            "over_2_5": round(over_2_5 * 100, 1),
            "over_3_5": round(over_3_5 * 100, 1),
            "btts": round(btts * 100, 1),
        },
        "placares_top": placares[:10],
    }


def _probabilidades_escanteios(media_casa: float, media_fora: float) -> dict:
    media_total = media_casa + media_fora
    media_total = max(media_total, 1.0)

    return {
        "media_total": round(media_total, 1),
        "over_7_5": round((1 - poisson.cdf(7, media_total)) * 100, 1),
        "over_8_5": round((1 - poisson.cdf(8, media_total)) * 100, 1),
        "over_9_5": round((1 - poisson.cdf(9, media_total)) * 100, 1),
        "over_10_5": round((1 - poisson.cdf(10, media_total)) * 100, 1),
        "over_11_5": round((1 - poisson.cdf(11, media_total)) * 100, 1),
    }
