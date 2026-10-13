"""Ayudas y subvenciones para empresas culturales y de eventos.

Dos fuentes oficiales:
- BDNS (Sistema Nacional de Publicidad de Subvenciones): API pública de búsqueda y detalle.
- BOE: API de datos abiertos del sumario diario (extractos de convocatorias estatales).
"""

import json
import re
import time
import urllib.parse
from datetime import date, datetime, timedelta

from .comun import descargar, normalizar

BDNS_BUSQUEDA = "https://www.infosubvenciones.es/bdnstrans/api/convocatorias/busqueda"
BDNS_DETALLE = "https://www.infosubvenciones.es/bdnstrans/api/convocatorias"
BDNS_FICHA = "https://www.infosubvenciones.es/bdnstrans/GE/es/convocatoria/{}"
BOE_SUMARIO = "https://www.boe.es/datosabiertos/api/boe/sumario/{}"

TERMINOS_BDNS = (
    "festival", "espectaculos", "artes escenicas", "musica", "eventos", "ferias",
    "fiestas", "giras", "industrias culturales", "circo", "teatro", "danza",
    "actividades culturales", "xacobeo", "programacion cultural",
)

SECTOR = re.compile(
    r"\b(cultur|escenic|music|festival|espectacul|circo\b|circ\b|teatr|danza|dansa|evento|"
    r"esdeveniment|feria|fira\b|fires\b|giras|gires|fiestas|festes|xacobeo|industrias creativ)"
)

# Convocatorias que no son para empresas que trabajan eventos: premios, concursos, becas, cine.
EXCLUIR = re.compile(
    r"\b(premios?|concurso|certamen|becas?|cortometrajes?|largometrajes?|rodajes?|"
    r"escuelas? de musica|bandas? de musica|nominativa|convenio)\b"
)

BENEFICIARIOS_EMPRESA = ("pyme", "desarrollan actividad economica", "gran empresa", "autonom",
                         "empresa")


def admite_empresas(beneficiarios):
    """True si algún tipo de beneficiario es una empresa, pyme o autónomo."""
    for beneficiario in beneficiarios:
        texto = normalizar(beneficiario)
        if "no desarrollan" in texto:
            continue
        if any(p in texto for p in BENEFICIARIOS_EMPRESA):
            return True
    return False


def _es_del_sector(texto):
    return bool(SECTOR.search(normalizar(texto)))


def _fecha(texto):
    if not texto:
        return None
    for formato in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto[:10], formato).date()
        except ValueError:
            continue
    return None


def _bdns_busqueda_url(termino, tamano=50, pagina=0):
    return BDNS_BUSQUEDA + "?" + urllib.parse.urlencode({
        "page": pagina, "pageSize": tamano, "order": "fechaRecepcion",
        "direccion": "desc", "descripcion": termino,
    })


def _bdns_detalle_url(numero):
    return BDNS_DETALLE + "?" + urllib.parse.urlencode({"numConv": numero, "vpd": "GE"})


def evaluar_convocatoria(detalle, hoy):
    """Normaliza el detalle de BDNS. Devuelve None si no sirve a una empresa o ya cerró."""
    tipo = normalizar(detalle.get("tipoConvocatoria"))
    if "nominativa" in tipo or "directa" in tipo:
        return None
    beneficiarios = [b.get("descripcion", "") for b in detalle.get("tiposBeneficiarios") or []]
    if not admite_empresas(beneficiarios):
        return None
    titulo = detalle.get("descripcion") or ""
    if EXCLUIR.search(normalizar(titulo)):
        return None
    if not _es_del_sector(titulo + " " + (detalle.get("descripcionFinalidad") or "")):
        return None

    inicio = _fecha(detalle.get("fechaInicioSolicitud"))
    fin = _fecha(detalle.get("fechaFinSolicitud"))
    abierta = detalle.get("abierto")
    if fin is not None and fin < hoy:
        return None
    if fin is None and abierta is False and (inicio is None or inicio < hoy):
        return None

    organo = detalle.get("organo") or {}
    anuncios = detalle.get("anuncios") or []
    return {
        "fuente": "BDNS",
        "codigo": detalle.get("codigoBDNS"),
        "titulo": titulo,
        "organo": " / ".join(x for x in (organo.get("nivel2"), organo.get("nivel3")) if x),
        "ambito": organo.get("nivel1"),
        "regiones": [r.get("descripcion") for r in detalle.get("regiones") or []],
        "beneficiarios": beneficiarios,
        "presupuesto": detalle.get("presupuestoTotal"),
        "inicio": inicio.isoformat() if inicio else None,
        "fin": fin.isoformat() if fin else None,
        "texto_inicio": detalle.get("textInicio"),
        "texto_fin": detalle.get("textFin"),
        "abierta_ahora": bool(abierta),
        "url": BDNS_FICHA.format(detalle.get("codigoBDNS")),
        "boletin": anuncios[0].get("url") if anuncios else None,
    }


def recoger_bdns(hoy=None, dias=7, max_detalles=150, max_paginas=8, descargador=descargar,
                 pausa=0.5, ya_vistas=()):
    """Busca convocatorias recibidas en los últimos `dias` días y devuelve las abiertas que sirven
    a empresas de eventos. `ya_vistas` evita pedir de nuevo el detalle de las que ya tenemos."""
    hoy = hoy or date.today()
    desde = hoy - timedelta(days=dias)
    candidatas = {}
    for termino in TERMINOS_BDNS:
        for pagina in range(max_paginas):
            datos = json.loads(descargador(_bdns_busqueda_url(termino, pagina=pagina)))
            filas = datos.get("content", [])
            for fila in filas:
                recibida = _fecha(fila.get("fechaRecepcion"))
                if recibida is None or recibida < desde:
                    continue
                if EXCLUIR.search(normalizar(fila.get("descripcion"))):
                    continue
                if not _es_del_sector(fila.get("descripcion")):
                    continue
                numero = fila.get("numeroConvocatoria")
                if numero not in ya_vistas:
                    candidatas[numero] = fila
            time.sleep(pausa)
            fechas = [_fecha(f.get("fechaRecepcion")) for f in filas]
            fechas = [f for f in fechas if f]
            if datos.get("last", True) or not fechas or min(fechas) < desde:
                break

    # Primero las más recientes: son las que tienen más probabilidad de seguir abiertas.
    orden = sorted(candidatas, key=lambda n: candidatas[n].get("fechaRecepcion") or "", reverse=True)
    seleccion = []
    evaluadas = 0
    for numero in orden[:max_detalles]:
        try:
            detalle = json.loads(descargador(_bdns_detalle_url(numero)))
        except (OSError, ValueError):
            continue
        evaluadas += 1
        ayuda = evaluar_convocatoria(detalle, hoy)
        if ayuda:
            seleccion.append(ayuda)
        time.sleep(pausa)
    return seleccion, {"candidatas": len(candidatas), "evaluadas": evaluadas}


def _items_boe(nodo, seccion=None, departamento=None):
    """Recorre el sumario del BOE y produce (sección, departamento, item)."""
    if isinstance(nodo, list):
        for elemento in nodo:
            yield from _items_boe(elemento, seccion, departamento)
        return
    if not isinstance(nodo, dict):
        return
    if "identificador" in nodo and "titulo" in nodo:
        yield seccion, departamento, nodo
        return
    if "departamento" in nodo:
        seccion = nodo.get("codigo", seccion)
    if "epigrafe" in nodo or ("item" in nodo and "codigo" in nodo):
        departamento = nodo.get("nombre", departamento)
    for valor in nodo.values():
        if isinstance(valor, (list, dict)):
            yield from _items_boe(valor, seccion, departamento)


def evaluar_item_boe(titulo):
    texto = normalizar(titulo)
    es_convocatoria = ("convoca" in texto or "convocatoria" in texto) and (
        "ayuda" in texto or "subvencion" in texto)
    return es_convocatoria and _es_del_sector(texto)


def recoger_boe(hoy=None, dias=3, descargador=descargar):
    hoy = hoy or date.today()
    seleccion = []
    revisados = 0
    for atras in range(dias):
        dia = hoy - timedelta(days=atras)
        if dia.weekday() == 6:
            continue
        try:
            datos = json.loads(descargador(
                BOE_SUMARIO.format(dia.strftime("%Y%m%d")), {"Accept": "application/json"}))
        except Exception:  # festivos o días sin BOE devuelven error
            continue
        revisados += 1
        for seccion, departamento, item in _items_boe(datos.get("data", {})):
            if not evaluar_item_boe(item.get("titulo")):
                continue
            pdf = item.get("url_pdf")
            seleccion.append({
                "fuente": "BOE",
                "codigo": item.get("identificador"),
                "titulo": item.get("titulo"),
                "organo": departamento,
                "fecha_publicacion": dia.isoformat(),
                "url": pdf.get("texto") if isinstance(pdf, dict) else pdf,
            })
    return seleccion, {"dias_revisados": revisados}
