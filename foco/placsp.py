"""Licitaciones de la Plataforma de Contratación del Sector Público (datos abiertos).

PLACSP publica sus licitaciones en ficheros Atom (formato CODICE). Cada fichero trae
las actualizaciones más recientes y un enlace rel="next" al fichero anterior. Leemos
hacia atrás hasta cubrir los últimos días y nos quedamos con lo que sigue en plazo.
"""

import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

from .comun import (a_numero, cpv_limpio, descargar, es_de_eventos, nombre_procedimiento,
                    normalizar)

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


RESULTADOS = {"8": "adjudicado", "9": "formalizado", "3": "desierto", "4": "desistimiento",
              "5": "renuncia"}
# Primera letra del NIF de una persona jurídica. Un DNI (dígitos) o un NIE (X, Y, Z) es una persona
# física: de esas no guardamos el nombre.
LETRAS_SOCIEDAD = set("ABCDEFGHJNPQRSUVW")
FORMA_SOCIETARIA = re.compile(
    r"\b(s\.?l\.?u?|s\.?a\.?u?|slu|sll|slp|sccl|scp|coop|cooperativa|ute|sociedad|fundacion|"
    r"fundacio|asociacion|associacio|limitada|anonima)\b")


def es_persona_juridica(nif, nombre):
    if nif:
        return nif.strip()[:1].upper() in LETRAS_SOCIEDAD
    return bool(FORMA_SOCIETARIA.search(normalizar(nombre)))


def _entero(texto):
    return int(texto) if texto and texto.isdigit() else None


def _resultados(estado_carpeta):
    """Resultados de adjudicación. Nunca se guarda el NIF ni el nombre de una persona física."""
    lista = []
    for resultado in estado_carpeta:
        if _local(resultado.tag) != "TenderResult":
            continue
        ganador = _hijo(resultado, "WinningParty")
        nif = _texto(_ruta(ganador, "PartyIdentification", "ID"))
        nombre = _texto(_ruta(ganador, "PartyName", "Name"))
        empresa = es_persona_juridica(nif, nombre) if (nif or nombre) else None
        proyecto = _hijo(resultado, "AwardedTenderedProject")
        totales = _hijo(proyecto, "LegalMonetaryTotal")
        codigo = _texto(_hijo(resultado, "ResultCode"))
        fecha = _texto(_hijo(resultado, "AwardDate"))
        lista.append({
            "resultado": RESULTADOS.get(codigo, "otro"),
            "fecha": fecha[:10] if fecha else None,
            "ofertas": _entero(_texto(_hijo(resultado, "ReceivedTenderQuantity"))),
            "oferta_minima": a_numero(_texto(_hijo(resultado, "LowerTenderAmount"))),
            "oferta_maxima": a_numero(_texto(_hijo(resultado, "HigherTenderAmount"))),
            "pyme": _texto(_hijo(resultado, "SMEAwardedIndicator")) == "true",
            "ganador": nombre if empresa else ("persona física" if nombre else None),
            "ganador_empresa": empresa,
            "lote": _texto(_hijo(proyecto, "ProcurementProjectLotID")),
            "importe_sin_iva": a_numero(_texto(_hijo(totales, "TaxExclusiveAmount"))),
            "importe_con_iva": a_numero(_texto(_hijo(totales, "PayableAmount"))),
        })
    return lista


def _fecha_publicacion(estado_carpeta):
    """Fecha del anuncio de licitación (o del primer anuncio publicado, si no hay)."""
    avisos = {}
    for aviso in estado_carpeta:
        if _local(aviso.tag) != "ValidNoticeInfo":
            continue
        tipo = _texto(_hijo(aviso, "NoticeTypeCode")) or "?"
        fechas = [f[:10] for f in (_texto(e) for e in _descendientes(aviso, "IssueDate")) if f]
        if fechas:
            avisos[tipo] = min([avisos[tipo], *fechas] if tipo in avisos else fechas)
    if not avisos:
        return None
    return avisos.get("DOC_CN") or avisos.get("DOC_CD") or min(avisos.values())


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
            "publicada": _fecha_publicacion(estado_carpeta),
            "resultados": _resultados(estado_carpeta),
        })
    return licitaciones, siguiente


def _leer_hacia_atras(url, limite, vistas, fuente, hoy_iso, descargador, max_ficheros,
                     tiempo_restante, reloj):
    """Lee ficheros desde `url` hacia atrás hasta que uno entero sea anterior a `limite`.

    Devuelve un dict con ficheros, entradas, primera/ultima (fechas vistas), parada y siguiente
    (el fichero anterior que queda por leer, o None).
    """
    inicio = reloj()
    leidos = entradas = 0
    primera = ultima = None
    parada = "sin fichero anterior"
    while url:
        if leidos >= max_ficheros:
            parada = "máximo de ficheros"
            break
        if tiempo_restante is not None and reloj() - inicio > tiempo_restante:
            parada = "tiempo agotado"
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
            vistas[clave] = (lic["actualizado"] or "", *clasificar(lic, fuente, hoy_iso))
        if leidos % 5 == 0:
            print(f"[{fuente}] {leidos} ficheros, {entradas} entradas, hasta "
                  f"{ultima.isoformat(timespec='minutes') if ultima else '?'} "
                  f"({reloj() - inicio:.0f} s)", file=sys.stderr, flush=True)
        url = url_anterior
        # Los ficheros van de más nuevo a más antiguo: paramos cuando uno entero es anterior al límite.
        if mas_reciente is not None and mas_reciente < limite:
            parada = "límite alcanzado"
            break
    return {"ficheros": leidos, "entradas": entradas, "primera": primera, "ultima": ultima,
            "parada": parada, "siguiente": url, "segundos": reloj() - inicio}


def clasificar(lic, fuente, hoy_iso):
    """Devuelve (tipo, registro): «abierta» con la licitación si es de eventos y sigue en plazo;
    «cerrada» si ya no está en plazo, con el registro de adjudicación si es de eventos y lo tiene;
    «nada» en otro caso."""
    if lic["estado"] != "PUB":
        registro = None
        if lic["estado"] in ("ADJ", "RES") and lic.get("resultados"):
            relevante, motivo = es_de_eventos(lic["titulo"], lic["cpv"])
            if relevante:
                registro = {**{k: v for k, v in lic.items() if k not in ("lotes", "fecha_limite",
                                                                      "hora_limite")},
                            "fuente": fuente, "motivo": motivo}
        return "cerrada", registro
    if lic["fecha_limite"] and lic["fecha_limite"] >= hoy_iso:
        relevante, motivo = es_de_eventos(lic["titulo"], lic["cpv"])
        if relevante:
            return "abierta", {**lic, "fuente": fuente, "motivo": motivo}
    return "nada", None


def _iso(momento):
    return momento.isoformat(timespec="minutes") if momento else None


def recoger(dias=3, hoy=None, max_ficheros=400, descargador=descargar, limite_segundos=None,
            reloj=time.monotonic, estado_previo=None):
    """Lee los feeds de PLACSP y devuelve (selección, informe, ids_cerradas, adjudicadas).

    La selección son las licitaciones de eventos en plazo; ids_cerradas, las que pasaron a otro
    estado (evaluación, adjudicada, anulada...) y deben salir del listado acumulado; adjudicadas,
    las de eventos con resultado (ganador, importe, número de ofertas).

    Cada feed se lee en dos fases dentro de `limite_segundos`:
    1. Lo nuevo: desde el fichero más reciente hasta donde llegó la ejecución anterior.
    2. El relleno: si aún no se cubren los días pedidos (`dias`, o un objetivo pendiente de una
       carga anterior), se sigue hacia atrás desde el último fichero leído.
    El informe guarda por feed: hasta, desde, siguiente y objetivo, que la próxima ejecución
    recibe en `estado_previo` para continuar donde se quedó.
    """
    hoy = hoy or date.today()
    hoy_iso = hoy.isoformat()
    objetivo_dias = datetime.combine(hoy - timedelta(days=dias), datetime.min.time())
    # Para cada id solo vale su versión más reciente. Guardamos la fecha y, si interesa, la licitación.
    vistas = {}
    informe = {}

    for fuente, url_inicial in FEEDS.items():
        inicio = reloj()
        previo = (estado_previo or {}).get(fuente) or {}
        hasta_previo = _fecha_iso(previo.get("hasta"))
        desde_previo = _fecha_iso(previo.get("desde"))
        objetivo = objetivo_dias
        if _fecha_iso(previo.get("objetivo")):
            objetivo = min(objetivo, _fecha_iso(previo["objetivo"]))
        continuable = bool(hasta_previo and desde_previo and previo.get("siguiente"))

        limite_nuevo = objetivo
        if continuable:
            limite_nuevo = max(objetivo, hasta_previo - timedelta(hours=12))
        fase1 = _leer_hacia_atras(url_inicial, limite_nuevo, vistas, fuente, hoy_iso, descargador,
                                  max_ficheros, limite_segundos, reloj)
        hasta = fase1["primera"] or hasta_previo
        if continuable and fase1["parada"] == "límite alcanzado" and limite_nuevo > objetivo:
            # Lo nuevo empalma con lo ya cubierto: el relleno sigue desde donde se quedó.
            desde, siguiente = desde_previo, previo["siguiente"]
        else:
            desde, siguiente = fase1["ultima"], fase1["siguiente"]

        fase2 = None
        restante = None if limite_segundos is None else limite_segundos - (reloj() - inicio)
        if (siguiente and desde and desde > objetivo
                and fase1["parada"] != "tiempo agotado" and (restante is None or restante > 0)):
            fase2 = _leer_hacia_atras(siguiente, objetivo, vistas, fuente, hoy_iso, descargador,
                                      max_ficheros, restante, reloj)
            if fase2["ultima"]:
                desde = min(desde, fase2["ultima"])
            siguiente = fase2["siguiente"]

        parada = (fase2 or fase1)["parada"]
        informe[fuente] = {
            "ficheros": fase1["ficheros"] + (fase2["ficheros"] if fase2 else 0),
            "entradas": fase1["entradas"] + (fase2["entradas"] if fase2 else 0),
            "desde": _iso(desde),
            "hasta": _iso(hasta),
            "siguiente": siguiente,
            "objetivo": _iso(objetivo),
            "relleno_pendiente": bool(siguiente and desde and desde > objetivo),
            "parada": parada,
            "segundos": round(reloj() - inicio),
        }

    seleccion = [registro for _, tipo, registro in vistas.values() if tipo == "abierta"]
    cerradas = [clave for clave, (_, tipo, _) in vistas.items() if tipo == "cerrada"]
    adjudicadas = [registro for _, tipo, registro in vistas.values()
                   if tipo == "cerrada" and registro]
    seleccion.sort(key=lambda l: (l["fecha_limite"], l["hora_limite"] or "23:59"))
    return seleccion, informe, cerradas, adjudicadas
