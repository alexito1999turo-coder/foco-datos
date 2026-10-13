"""Licitaciones de la Plataforma de serveis de contractació pública (Generalitat).

Usa el conjunto de datos abiertos «Contractació pública a Catalunya: publicacions»
(analisi.transparenciacatalunya.cat, id ybgg-dgi6) a través de su API Socrata.
"""

import json
import urllib.parse
from datetime import date

from .comun import a_numero, cpv_limpio, descargar, es_de_eventos

API = "https://analisi.transparenciacatalunya.cat/resource/ybgg-dgi6.json"

CAMPOS = (
    "nom_organ,lloc_execucio,denominacio,objecte_contracte,procediment,"
    "pressupost_licitacio_sense,pressupost_licitacio_amb,valor_estimat_contracte,"
    "termini_presentacio_ofertes,data_publicacio_anunci,codi_cpv,enllac_publicacio,"
    "codi_expedient,tipus_contracte"
)


def construir_url(hoy, limite=5000):
    parametros = {
        "$select": CAMPOS,
        "$where": (
            "fase_publicacio like 'Anunci de licitaci%' "
            f"AND termini_presentacio_ofertes >= '{hoy.isoformat()}T00:00:00'"
        ),
        "$order": "data_publicacio_anunci DESC",
        "$limit": str(limite),
    }
    return API + "?" + urllib.parse.urlencode(parametros)


def _url(valor):
    if isinstance(valor, dict):
        return valor.get("url")
    return valor


def normalizar_fila(fila):
    termini = fila.get("termini_presentacio_ofertes") or ""
    titulo = fila.get("objecte_contracte") or fila.get("denominacio")
    return {
        "fuente": "Generalitat de Catalunya",
        "id": f"cat:{fila.get('codi_expedient')}:{fila.get('nom_organ')}",
        "expediente": fila.get("codi_expedient"),
        "titulo": titulo,
        "organo": fila.get("nom_organ"),
        "municipio": None,
        "provincia": fila.get("lloc_execucio"),
        "nuts": None,
        "presupuesto_sin_iva": a_numero(fila.get("pressupost_licitacio_sense")),
        "presupuesto_con_iva": a_numero(fila.get("pressupost_licitacio_amb")),
        "valor_estimado": a_numero(fila.get("valor_estimat_contracte")),
        "procedimiento": fila.get("procediment"),
        "cpv": [cpv_limpio(fila.get("codi_cpv"))] if fila.get("codi_cpv") else [],
        "lotes": [],
        "fecha_limite": termini[:10] or None,
        "hora_limite": termini[11:16] or None,
        "url": _url(fila.get("enllac_publicacio")),
        "actualizado": fila.get("data_publicacio_anunci"),
        "estado": "PUB",
    }


def recoger(hoy=None, descargador=descargar):
    hoy = hoy or date.today()
    filas = json.loads(descargador(construir_url(hoy)))
    vistas = set()
    seleccion = []
    for fila in filas:
        lic = normalizar_fila(fila)
        if lic["id"] in vistas:
            continue
        vistas.add(lic["id"])
        relevante, motivo = es_de_eventos(lic["titulo"], lic["cpv"])
        if not relevante:
            continue
        lic["motivo"] = motivo
        seleccion.append(lic)
    seleccion.sort(key=lambda l: (l["fecha_limite"] or "9999", l["hora_limite"] or "23:59"))
    return seleccion, {"filas": len(filas)}
