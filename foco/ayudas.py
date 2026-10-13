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
    "audiovisual", "actividades culturales", "turismo",
)

SECTOR = re.compile(
    r"\b(cultur|escenic|music|festival|espectacul|circo\b|circ\b|teatr|danza|dansa|evento|"
    r"esdeveniment|feria|fira\b|fires\b|giras|gires|audiovisual|cinematograf|fiestas|festes|"
    r"xacobeo|industrias creativ|turism)"
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


def _bdns_busqueda_url(termino, tamano=50):
    return BDNS_BUSQUEDA + "?" + urllib.parse.urlencode({
        "page": 0, "pageSize": tamano, "order": "fechaRecepcion",
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


def recoger_bdns(hoy=None, dias=7, max_detalles=80, descargador=descargar, pausa=0.5):
    hoy = hoy or date.today()
    desde = hoy - timedelta(days=dias)
    candidatas = {}
    for termino in TERMINOS_BDNS:
        datos = json.loads(descargador(_bdns_busqueda_url(termino)))
        for fila in datos.get("content", []):
            recibida = _fecha(fila.get("fechaRecepcion"))
            if recibida is None or recibida < desde:
                continue
            if "nominativa" in normalizar(fila.get("descripcion")):
                continue
            candidatas[fila.get("numeroConvocatoria")] = fila
        time.sleep(pausa)

    seleccion = []
    for numero in list(candidatas)[:max_detalles]:
        detalle = json.loads(descargador(_bdns_detalle_url(numero)))
        ayuda = evaluar_convocatoria(detalle, hoy)
        if ayuda:
            seleccion.append(ayuda)
        time.sleep(pausa)
    return seleccion, {"candidatas": len(candidatas)}


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
