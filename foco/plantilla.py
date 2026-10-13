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
    partes.append(f"<h3>{escape(item['titulo'])}{lugar}</h3>")
    if item.get("etiquetas"):
        partes.append(f"<p><em>{escape(' · '.join(item['etiquetas']))}</em></p>")
    datos = [f"<strong>Cierra:</strong> {escape(_cierre(item, hoy))}"]
    if item.get("presupuesto_sin_iva") is not None:
        datos.append(f"<strong>Presupuesto base:</strong> {escape(euros(item['presupuesto_sin_iva']))} sin IVA")
    if item.get("procedimiento"):
        datos.append(f"<strong>Procedimiento:</strong> {escape(item['procedimiento'])}")
    if item.get("organo"):
        datos.append(f"<strong>Organismo:</strong> {escape(item['organo'])}")
    partes.append("<p>" + "<br>".join(datos) + "</p>")
    if item.get("clave"):
        partes.append(f"<p>{escape(item['clave'])}</p>")
    if item.get("fecha_prudente"):
        partes.append("<p><small>Fecha prudente: confirma la hora exacta en el anuncio.</small></p>")
    codigos = []
    if item.get("expediente"):
        codigos.append(f"Expte. {item['expediente']}")
    if item.get("cpv"):
        codigos.append("CPV " + ", ".join(item["cpv"][:3]))
    if codigos:
        partes.append(f"<p><small>{escape(' · '.join(codigos))}</small></p>")
    if item.get("url"):
        partes.append(f'<p><a href="{escape(item["url"], quote=True)}">Ver expediente oficial</a></p>')
    return "\n".join(partes)


def ayuda_html(ayuda, hoy):
    partes = [f"<h3>{escape(ayuda['titulo'])}</h3>"]
    datos = []
    if ayuda.get("organo"):
        datos.append(f"<strong>Organismo:</strong> {escape(ayuda['organo'])}")
    if ayuda.get("fin"):
        datos.append(f"<strong>Plazo hasta:</strong> {escape(_cierre({'fecha_limite': ayuda['fin']}, hoy))}")
    elif ayuda.get("texto_fin"):
        datos.append(f"<strong>Plazo:</strong> {escape(ayuda['texto_fin'])}")
    if datos:
        partes.append("<p>" + "<br>".join(datos) + "</p>")
    if ayuda.get("clave"):
        partes.append(f"<p>{escape(ayuda['clave'])}</p>")
    if ayuda.get("url"):
        partes.append(f'<p><a href="{escape(ayuda["url"], quote=True)}">Ver convocatoria oficial</a></p>')
    return "\n".join(partes)


def renderizar(curada):
    hoy = date.fromisoformat(curada["fecha"])
    bloques = [f"<p><strong>{escape(fecha_larga(curada['fecha']).capitalize())}</strong></p>"]
    if curada.get("intro"):
        bloques.append(f"<p>{escape(curada['intro'])}</p>")
    for seccion in curada.get("secciones", []):
        if not seccion.get("items"):
            continue
        bloques.append(f"<h2>{escape(seccion['titulo'])} ({len(seccion['items'])})</h2>")
        if seccion.get("nota"):
            bloques.append(f"<p>{escape(seccion['nota'])}</p>")
        for item in seccion["items"]:
            bloques.append(licitacion_html(item, hoy))
            bloques.append("<hr>")
    if curada.get("ayudas"):
        bloques.append(f"<h2>Ayudas ({len(curada['ayudas'])})</h2>")
        for ayuda in curada["ayudas"]:
            bloques.append(ayuda_html(ayuda, hoy))
            bloques.append("<hr>")
    pie = curada.get("pie") or (
        "Datos de la Plataforma de Contratación del Sector Público, la Plataforma de serveis de "
        "contractació pública de la Generalitat, el BOE y la Base de Datos Nacional de Subvenciones. "
        "Los importes son el presupuesto base de licitación. Antes de ofertar, lee siempre el pliego: "
        "manda el anuncio oficial."
    )
    bloques.append(f"<p><small>{escape(pie)}</small></p>")
    return "\n".join(bloques)


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
