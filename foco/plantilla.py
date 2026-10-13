"""Convierte la selección curada del día en el HTML de la entrada de WordPress.

Uso: python -m foco.plantilla curada.json --salida edicion.html
El HTML es sencillo a propósito: se publica en la web y WordPress lo envía por email.
"""

import argparse
import json
from datetime import date
from html import escape

from .comun import normalizar
from .edicion import dias_restantes, euros, fecha_corta
from .precedentes import mes_y_anio

DIAS_LARGOS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MESES_LARGOS = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                "septiembre", "octubre", "noviembre", "diciembre")


def fecha_larga(texto):
    dia = date.fromisoformat(texto[:10])
    return f"{DIAS_LARGOS[dia.weekday()]}, {dia.day} de {MESES_LARGOS[dia.month - 1]} de {dia.year}"


# Catalunya publica el procedimiento en catalán; «Otros» no aporta nada al lector.
PROCEDIMIENTO_ES = {
    "obert": "Abierto",
    "obert simplificat": "Abierto simplificado",
    "obert simplificat abreujat": "Abierto simplificado abreviado",
    "restringit": "Restringido",
    "negociat sense publicitat": "Negociado sin publicidad",
    "negociat amb publicitat": "Negociado con publicidad",
    "licitacio amb negociacio": "Licitación con negociación",
    "dialeg competitiu": "Diálogo competitivo",
    "concurs de projectes": "Concurso de proyectos",
    "associacio per a la innovacio": "Asociación para la innovación",
    "basat en acord marc": "Basado en acuerdo marco",
    "contracte menor": "Contrato menor",
}


def procedimiento_es(texto):
    if not texto or texto.strip().lower() in ("otros", "altres"):
        return None
    clave = normalizar(texto).replace("·", "")
    return PROCEDIMIENTO_ES.get(clave, texto)


def _p(contenido):
    return f"<!-- wp:paragraph -->\n<p>{contenido}</p>\n<!-- /wp:paragraph -->"


def _h(contenido, nivel=2):
    atributos = "" if nivel == 2 else f' {{"level":{nivel}}}'
    return (f"<!-- wp:heading{atributos} -->\n<h{nivel} class=\"wp-block-heading\">{contenido}</h{nivel}>"
            "\n<!-- /wp:heading -->")


SEPARADOR = ('<!-- wp:separator -->\n<hr class="wp-block-separator has-alpha-channel-opacity"/>'
             "\n<!-- /wp:separator -->")


def _cierre(item, hoy):
    if not item.get("fecha_limite"):
        return ""
    restantes = dias_restantes(item["fecha_limite"], hoy)
    texto = fecha_corta(item["fecha_limite"])
    if item.get("hora_limite") and not item.get("fecha_prudente"):
        texto += f", {item['hora_limite']} h"
    if restantes is not None and restantes <= 365:
        unidad = "día" if restantes == 1 else "días"
        texto += f" (quedan {restantes} {unidad})" if restantes > 0 else " (cierra hoy)"
    return texto


def _ganador(dato):
    if dato.get("ganador") == "persona física":
        return "un profesional autónomo"
    ganador = dato.get("ganador")
    if ganador and dato.get("varios_ganadores"):
        ganador += " y otras empresas"
    return ganador


def _cifras_adjudicacion(dato):
    """«por 98.000,00 € sin IVA, con 4 ofertas y una baja del 18,3 %»"""
    partes = []
    if dato.get("importe_sin_iva") is not None:
        partes.append(f"por {euros(dato['importe_sin_iva'])} sin IVA")
    extras = []
    if dato.get("ofertas") is not None:
        extras.append(f"{dato['ofertas']} {'oferta' if dato['ofertas'] == 1 else 'ofertas'}")
    if dato.get("baja") is not None:
        extras.append(f"una baja del {str(dato['baja']).replace('.', ',')} %")
    if extras:
        partes.append("con " + " y ".join(extras))
    return ", ".join(partes)


def precedente_texto(previo):
    if not previo or not previo.get("publicada"):
        return None
    cuando = mes_y_anio(previo["publicada"])
    ganador = _ganador(previo)
    if ganador:
        texto = f"en {cuando} lo ganó {ganador}"
        cifras = _cifras_adjudicacion(previo)
        if cifras:
            texto += f" {cifras}"
        if previo.get("lotes_desiertos"):
            n = previo["lotes_desiertos"]
            texto += f"; {n} {'lote quedó desierto' if n == 1 else 'lotes quedaron desiertos'}"
        return f"{texto}."
    if previo.get("presupuesto_sin_iva") is not None:
        return f"se licitó en {cuando} con {euros(previo['presupuesto_sin_iva'])} sin IVA."
    return None


def _porcentaje(valor):
    texto = f"{valor:.1f}".rstrip("0").rstrip(".")
    return texto.replace(".", ",")


def competencia_texto(competencia):
    if not competencia:
        return None
    texto = (f"de {competencia['contratos']} contratos de {competencia['categoria']} por "
             f"procedimiento abierto en el histórico de Foco, el {competencia['una_oferta']} % "
             f"recibió una sola oferta")
    if competencia.get("mediana_baja") is not None:
        texto += f" y la rebaja mediana fue del {_porcentaje(competencia['mediana_baja'])} %"
    return texto[0].upper() + texto[1:] + "."


def licitacion_html(item, hoy):
    partes = []
    lugar = f" · {escape(item['lugar'])}" if item.get("lugar") else ""
    partes.append(_h(f"{escape(item['titulo'])}{lugar}", 3))
    if item.get("etiquetas"):
        partes.append(_p(f"<em>{escape(' · '.join(item['etiquetas']))}</em>"))
    datos = [f"<strong>Cierra:</strong> {escape(_cierre(item, hoy))}"]
    if item.get("presupuesto_sin_iva") is not None:
        datos.append(f"<strong>Presupuesto base:</strong> {escape(euros(item['presupuesto_sin_iva']))} sin IVA")
    if procedimiento_es(item.get("procedimiento")):
        datos.append(f"<strong>Procedimiento:</strong> {escape(procedimiento_es(item['procedimiento']))}")
    if item.get("organo"):
        datos.append(f"<strong>Organismo:</strong> {escape(item['organo'])}")
    partes.append(_p("<br>".join(datos)))
    if item.get("clave"):
        partes.append(_p(escape(item['clave'])))
    previo = precedente_texto(item.get("precedente"))
    if previo:
        enlace = item["precedente"].get("url")
        texto = escape(previo)
        if enlace:
            texto += f' <a href="{escape(enlace, quote=True)}">Ver el del año pasado</a>'
        partes.append(_p(f"<strong>Precedente:</strong> {texto}"))
    competencia = competencia_texto(item.get("competencia"))
    if competencia and not (item.get("precedente") or {}).get("ofertas"):
        partes.append(_p(f"<strong>Competencia habitual:</strong> {escape(competencia)}"))
    if item.get("fecha_prudente"):
        partes.append(_p("<small>Fecha prudente: confirma la hora exacta en el anuncio.</small>"))
    codigos = []
    if item.get("expediente"):
        codigos.append(f"Expte. {item['expediente']}")
    if item.get("cpv"):
        codigos.append("CPV " + ", ".join(item["cpv"][:3]))
    if codigos:
        partes.append(_p(f"<small>{escape(' · '.join(codigos))}</small>"))
    if item.get("url"):
        partes.append(_p(f'<a href="{escape(item["url"], quote=True)}">Ver expediente oficial</a>'))
    return "\n\n".join(partes)


def ayuda_html(ayuda, hoy):
    partes = [_h(escape(ayuda["titulo"]), 3)]
    datos = []
    if ayuda.get("organo"):
        datos.append(f"<strong>Organismo:</strong> {escape(ayuda['organo'])}")
    if ayuda.get("fin"):
        datos.append(f"<strong>Plazo hasta:</strong> {escape(_cierre({'fecha_limite': ayuda['fin']}, hoy))}")
    elif ayuda.get("texto_fin"):
        datos.append(f"<strong>Plazo:</strong> {escape(ayuda['texto_fin'])}")
    if datos:
        partes.append(_p("<br>".join(datos)))
    if ayuda.get("clave"):
        partes.append(_p(escape(ayuda['clave'])))
    if ayuda.get("url"):
        partes.append(_p(f'<a href="{escape(ayuda["url"], quote=True)}">Ver convocatoria oficial</a>'))
    return "\n\n".join(partes)


def proxima_html(item, hoy):
    lugar = f" · {escape(item['lugar'])}" if item.get("lugar") else ""
    partes = [_h(f"{escape(item['titulo'])}{lugar}", 3)]
    datos = []
    if item.get("publicada"):
        datos.append(f"<strong>El año pasado salió:</strong> {escape(fecha_corta(item['publicada']))}"
                     f" de {item['publicada'][:4]}")
    if item.get("presupuesto_sin_iva") is not None:
        datos.append(f"<strong>Presupuesto entonces:</strong> {escape(euros(item['presupuesto_sin_iva']))}"
                     " sin IVA")
    ganador = _ganador(item)
    if ganador:
        cifras = _cifras_adjudicacion(item)
        datos.append(f"<strong>Lo ganó:</strong> {escape(ganador)}" + (f", {escape(cifras)}" if cifras else ""))
    if item.get("organo"):
        datos.append(f"<strong>Organismo:</strong> {escape(item['organo'])}")
    partes.append(_p("<br>".join(datos)))
    if item.get("clave"):
        partes.append(_p(escape(item["clave"])))
    if item.get("url"):
        partes.append(_p(f'<a href="{escape(item["url"], quote=True)}">Ver el expediente del año pasado</a>'))
    return "\n\n".join(partes)


def adjudicacion_html(item, hoy):
    lugar = f" · {escape(item['lugar'])}" if item.get("lugar") else ""
    partes = [_h(f"{escape(item['titulo'])}{lugar}", 3)]
    datos = []
    ganador = _ganador(item)
    if ganador:
        datos.append(f"<strong>Ganador:</strong> {escape(ganador)}")
    if item.get("importe_sin_iva") is not None:
        datos.append(f"<strong>Adjudicado por:</strong> {escape(euros(item['importe_sin_iva']))} sin IVA")
    if item.get("presupuesto_sin_iva") is not None:
        datos.append(f"<strong>Presupuesto base:</strong> {escape(euros(item['presupuesto_sin_iva']))} sin IVA")
    extras = []
    if item.get("ofertas") is not None:
        extras.append(f"{item['ofertas']} {'oferta' if item['ofertas'] == 1 else 'ofertas'}")
    if item.get("baja") is not None:
        extras.append(f"baja del {str(item['baja']).replace('.', ',')} %")
    if extras:
        datos.append(f"<strong>Competencia:</strong> {escape(', '.join(extras))}")
    if item.get("organo"):
        datos.append(f"<strong>Organismo:</strong> {escape(item['organo'])}")
    partes.append(_p("<br>".join(datos)))
    if item.get("clave"):
        partes.append(_p(escape(item["clave"])))
    if item.get("url"):
        partes.append(_p(f'<a href="{escape(item["url"], quote=True)}">Ver expediente oficial</a>'))
    return "\n\n".join(partes)


def desierto_html(item, hoy):
    lugar = f" · {escape(item['lugar'])}" if item.get("lugar") else ""
    partes = [_h(f"{escape(item['titulo'])}{lugar}", 3)]
    datos = []
    if item.get("lotes_adjudicados"):
        n = item.get("lotes_desiertos")
        datos.append(f"<strong>Resultado:</strong> {n} {'lote quedó desierto' if n == 1 else 'lotes quedaron desiertos'}"
                     f"; el resto se adjudicó")
    else:
        datos.append("<strong>Resultado:</strong> desierto, sin adjudicar")
    if item.get("presupuesto_sin_iva") is not None:
        datos.append(f"<strong>Presupuesto base:</strong> {escape(euros(item['presupuesto_sin_iva']))} sin IVA")
    if item.get("organo"):
        datos.append(f"<strong>Organismo:</strong> {escape(item['organo'])}")
    partes.append(_p("<br>".join(datos)))
    if item.get("clave"):
        partes.append(_p(escape(item["clave"])))
    if item.get("url"):
        partes.append(_p(f'<a href="{escape(item["url"], quote=True)}">Ver expediente oficial</a>'))
    return "\n\n".join(partes)


def renderizar(curada):
    hoy = date.fromisoformat(curada["fecha"])
    bloques = [_p(f"<strong>{escape(fecha_larga(curada['fecha']).capitalize())}</strong>")]
    if curada.get("intro"):
        bloques.append(_p(escape(curada["intro"])))
    for seccion in curada.get("secciones", []):
        if not seccion.get("items"):
            continue
        bloques.append(_h(f"{escape(seccion['titulo'])} ({len(seccion['items'])})"))
        if seccion.get("nota"):
            bloques.append(_p(escape(seccion["nota"])))
        for item in seccion["items"]:
            bloques.append(licitacion_html(item, hoy))
            bloques.append(SEPARADOR)
    if curada.get("proximas"):
        bloques.append(_h(f"Lo que viene ({len(curada['proximas'])})"))
        bloques.append(_p("Salieron el año pasado por estas fechas y este año todavía no se han "
                          "publicado. Buen momento para prepararse."))
        for item in curada["proximas"]:
            bloques.append(proxima_html(item, hoy))
            bloques.append(SEPARADOR)
    if curada.get("desiertos"):
        bloques.append(_h(f"Se quedaron sin empresa ({len(curada['desiertos'])})"))
        bloques.append(_p("Nadie se presentó o ninguna oferta valía. El organismo puede volver a "
                          "licitarlos o, si no cambia las condiciones, adjudicarlos por procedimiento "
                          "negociado invitando a empresas (artículo 168 de la Ley de Contratos). "
                          "Si te encaja, preséntate al organismo."))
        for item in curada["desiertos"]:
            bloques.append(desierto_html(item, hoy))
            bloques.append(SEPARADOR)
    if curada.get("adjudicaciones"):
        bloques.append(_h(f"Quién ganó ({len(curada['adjudicaciones'])})"))
        for item in curada["adjudicaciones"]:
            bloques.append(adjudicacion_html(item, hoy))
            bloques.append(SEPARADOR)
    if curada.get("ayudas"):
        bloques.append(_h(f"Ayudas ({len(curada['ayudas'])})"))
        for ayuda in curada["ayudas"]:
            bloques.append(ayuda_html(ayuda, hoy))
            bloques.append(SEPARADOR)
    pie = curada.get("pie") or (
        "Datos de la Plataforma de Contratación del Sector Público, la Plataforma de serveis de "
        "contractació pública de la Generalitat, el BOE y la Base de Datos Nacional de Subvenciones. "
        "Los importes son el presupuesto base de licitación. Antes de ofertar, lee siempre el pliego: "
        "manda el anuncio oficial."
    )
    bloques.append(_p(f"<small>{escape(pie)}</small>"))
    return "\n\n".join(bloques)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("curada")
    parser.add_argument("--salida", default="edicion.html")
    args = parser.parse_args(argv)
    with open(args.curada, encoding="utf-8") as fichero:
        curada = json.load(fichero)
    html = renderizar(curada)
    with open(args.salida, "w", encoding="utf-8") as fichero:
        fichero.write(html)
    print(f"Escrito {args.salida} ({len(html)} caracteres)")


if __name__ == "__main__":
    main()
