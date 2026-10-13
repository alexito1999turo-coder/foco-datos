"""Licitaciones de la Plataforma de Contratación del Sector Público (datos abiertos).

PLACSP publica sus licitaciones en ficheros Atom (formato CODICE). Cada fichero trae
las actualizaciones más recientes y un enlace rel="next" al fichero anterior. Leemos
hacia atrás hasta cubrir los últimos días y nos quedamos con lo que sigue en plazo.
"""

import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

from .comun import a_numero, cpv_limpio, descargar, es_de_eventos, nombre_procedimiento

FEEDS = {
    "PLACSP": "https://contrataciondelestado.es/sindicacion/sindicacion_643/"
              "licitacionesPerfilesContratanteCompleto3.atom",
    "PLACSP (plataformas autonómicas)": "https://contrataciondelestado.es/sindicacion/"
              "sindicacion_1044/PlataformasAgregadasSinMenores.atom",
}


def _local(etiqueta):
    return etiqueta.rsplit("}", 1)[-1]


def _hijo(elemento, nombre):
    if elemento is None:
        return None
    for hijo in elemento:
        if _local(hijo.tag) == nombre:
            return hijo
    return None


def _ruta(elemento, *nombres):
    actual = elemento
    for nombre in nombres:
        actual = _hijo(actual, nombre)
        if actual is None:
            return None
    return actual


def _texto(elemento):
    if elemento is None or elemento.text is None:
        return None
    texto = elemento.text.strip()
    return texto or None


def _descendientes(elemento, nombre):
    if elemento is None:
        return []
    return [e for e in elemento.iter() if _local(e.tag) == nombre]


def _fecha_iso(texto):
    if not texto:
        return None
    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        return None


def parsear_feed(contenido):
    """Devuelve (lista de licitaciones, url del fichero anterior o None)."""
    raiz = ET.fromstring(contenido)
    siguiente = None
    for enlace in raiz:
        if _local(enlace.tag) == "link" and enlace.get("rel") == "next":
            siguiente = enlace.get("href")

    licitaciones = []
    for entrada in raiz:
        if _local(entrada.tag) != "entry":
            continue
        estado_carpeta = None
        for hijo in entrada:
            if _local(hijo.tag) == "ContractFolderStatus":
                estado_carpeta = hijo
        if estado_carpeta is None:
            continue

        enlace = None
        for hijo in entrada:
            if _local(hijo.tag) == "link" and hijo.get("href"):
                enlace = hijo.get("href")
                break

        proyecto = _hijo(estado_carpeta, "ProcurementProject")
        presupuesto = _hijo(proyecto, "BudgetAmount")
        parte = _ruta(estado_carpeta, "LocatedContractingParty", "Party")
        proceso = _hijo(estado_carpeta, "TenderingProcess")
        plazo = _hijo(proceso, "TenderSubmissionDeadlinePeriod")

        lotes = []
        for lote in estado_carpeta:
            if _local(lote.tag) != "ProcurementProjectLot":
                continue
            proyecto_lote = _hijo(lote, "ProcurementProject")
            lotes.append({
                "lote": _texto(_hijo(lote, "ID")),
                "nombre": _texto(_hijo(proyecto_lote, "Name")),
                "presupuesto_sin_iva": a_numero(_texto(_ruta(proyecto_lote, "BudgetAmount", "TaxExclusiveAmount"))),
            })

        cpvs = []
        for codigo in _descendientes(estado_carpeta, "ItemClassificationCode"):
            limpio = cpv_limpio(_texto(codigo))
            if limpio and limpio not in cpvs:
                cpvs.append(limpio)

        hora = _texto(_hijo(plazo, "EndTime"))
        fecha = _texto(_hijo(plazo, "EndDate"))
        licitaciones.append({
            "id": _texto(_hijo(entrada, "id")),
            "actualizado": _texto(_hijo(entrada, "updated")),
            "estado": _texto(_hijo(estado_carpeta, "ContractFolderStatusCode")),
            "expediente": _texto(_hijo(estado_carpeta, "ContractFolderID")),
            "titulo": _texto(_hijo(proyecto, "Name")) or _texto(_hijo(entrada, "title")),
            "organo": _texto(_ruta(parte, "PartyName", "Name")),
            "municipio": _texto(_ruta(parte, "PostalAddress", "CityName")),
            "provincia": _texto(_ruta(proyecto, "RealizedLocation", "CountrySubentity")),
            "nuts": _texto(_ruta(proyecto, "RealizedLocation", "CountrySubentityCode")),
            "presupuesto_sin_iva": a_numero(_texto(_hijo(presupuesto, "TaxExclusiveAmount"))),
            "presupuesto_con_iva": a_numero(_texto(_hijo(presupuesto, "TotalAmount"))),
            "valor_estimado": a_numero(_texto(_hijo(presupuesto, "EstimatedOverallContractAmount"))),
            "procedimiento": nombre_procedimiento(_texto(_hijo(proceso, "ProcedureCode"))),
            "cpv": cpvs,
            "lotes": lotes,
            "fecha_limite": fecha[:10] if fecha else None,
            "hora_limite": hora[:5] if hora else None,
            "url": enlace,
        })
    return licitaciones, siguiente


def recoger(dias=3, hoy=None, max_ficheros=400, descargador=descargar, limite_segundos=None,
            reloj=time.monotonic):
    """Recorre los feeds hacia atrás `dias` días.

    Devuelve (selección, informe, ids_cerradas): la selección son las licitaciones de eventos
    en plazo; ids_cerradas son las que cambiaron a un estado distinto de «en plazo» (evaluación,
    adjudicada, anulada...) y deben salir del listado acumulado.
    `limite_segundos` es el tiempo máximo por feed: si se agota, se para y se guarda lo leído.
    """
    hoy = hoy or date.today()
    hoy_iso = hoy.isoformat()
    limite = datetime.combine(hoy - timedelta(days=dias), datetime.min.time())
    # Para cada id solo vale su versión más reciente. Guardamos la fecha y, si interesa, la licitación.
    vistas = {}
    informe = {}

    for fuente, url in FEEDS.items():
        inicio = reloj()
        leidos = 0
        entradas = 0
        primera = ultima = None
        motivo_parada = "sin fichero anterior"
        while url and leidos < max_ficheros:
            if limite_segundos is not None and reloj() - inicio > limite_segundos:
                motivo_parada = "tiempo agotado"
                break
            licitaciones, url_anterior = parsear_feed(descargador(url))
            leidos += 1
            entradas += len(licitaciones)
            mas_reciente = None
            for lic in licitaciones:
                momento = _fecha_iso(lic["actualizado"])
                if momento is not None:
                    momento = momento.replace(tzinfo=None)
                    mas_reciente = momento if mas_reciente is None else max(mas_reciente, momento)
                    primera = momento if primera is None else max(primera, momento)
                    ultima = momento if ultima is None else min(ultima, momento)
                clave = lic["id"] or lic["url"]
                previa = vistas.get(clave)
                if previa is not None and (lic["actualizado"] or "") <= previa[0]:
                    continue
                guardar = None
                if lic["estado"] != "PUB":
                    guardar = "cerrada"
                elif lic["fecha_limite"] and lic["fecha_limite"] >= hoy_iso:
                    relevante, motivo = es_de_eventos(lic["titulo"], lic["cpv"])
                    if relevante:
                        guardar = {**lic, "fuente": fuente, "motivo": motivo}
                vistas[clave] = (lic["actualizado"] or "", guardar)
            if leidos % 10 == 0:
                print(f"[{fuente}] {leidos} ficheros, {entradas} entradas, hasta "
                      f"{ultima.isoformat(timespec='minutes') if ultima else '?'} "
                      f"({reloj() - inicio:.0f} s)", file=sys.stderr, flush=True)
            # Los ficheros van de más nuevo a más antiguo: paramos cuando uno entero es anterior al límite.
            if mas_reciente is not None and mas_reciente < limite:
                motivo_parada = "límite de días alcanzado"
                break
            url = url_anterior
        else:
            if leidos >= max_ficheros:
                motivo_parada = "máximo de ficheros"
        informe[fuente] = {
            "ficheros": leidos,
            "entradas": entradas,
            "desde": ultima.isoformat(timespec="minutes") if ultima else None,
            "hasta": primera.isoformat(timespec="minutes") if primera else None,
            "parada": motivo_parada,
            "segundos": round(reloj() - inicio),
        }

    seleccion = [guardar for _, guardar in vistas.values() if isinstance(guardar, dict)]
    cerradas = [clave for clave, (_, guardar) in vistas.items() if guardar == "cerrada"]
    seleccion.sort(key=lambda l: (l["fecha_limite"], l["hora_limite"] or "23:59"))
    return seleccion, informe, cerradas
