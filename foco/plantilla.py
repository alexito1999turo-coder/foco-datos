"""Convierte la selección curada del día en el HTML de la entrada de WordPress.

Uso: python -m foco.plantilla curada.json --salida edicion.html
El HTML es sencillo a propósito: se publica en la web y WordPress lo envía por email.
"""

import argparse
import json
from datetime import date
from html import escape

from .edicion import dias_restantes, euros, fecha_corta

DIAS_LARGOS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MESES_LARGOS = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                "septiembre", "octubre", "noviembre", "diciembre")


def fecha_larga(texto):
    dia = date.fromisoformat(texto[:10])
    return f"{DIAS_LARGOS[dia.weekday()]}, {dia.day} de {MESES_LARGOS[dia.month - 1]} de {dia.year}"


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


def licitacion_html(item, hoy):
    partes = []
    lugar = f" · {escape(item['lugar'])}" if item.get("lugar") else ""
    partes.append(_h(f"{escape(item['titulo'])}{lugar}", 3))
    if item.get("etiquetas"):
        partes.append(_p(f"<em>{escape(' · '.join(item['etiquetas']))}</em>"))
    datos = [f"<strong>Cierra:</strong> {escape(_cierre(item, hoy))}"]
    if item.get("presupuesto_sin_iva") is not None:
        datos.append(f"<strong>Presupuesto base:</strong> {escape(euros(item['presupuesto_sin_iva']))} sin IVA")
    if item.get("procedimiento"):
        datos.append(f"<strong>Procedimiento:</strong> {escape(item['procedimiento'])}")
    if item.get("organo"):
        datos.append(f"<strong>Organismo:</strong> {escape(item['organo'])}")
    partes.append(_p("<br>".join(datos)))
    if item.get("clave"):
        partes.append(_p(escape(item['clave'])))
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
