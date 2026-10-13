"""Monta la edición del día a partir de la selección editorial y de los datos recogidos.

Uso: python -m foco.componer seleccion.json --datos data/latest.json --salida edicion.html

La selección solo lleva lo editorial (qué entra, en qué sección, título limpio, lugar,
una línea «clave» y etiquetas). Los datos que pueden equivocarse al copiarse a mano
(plazo, hora, presupuesto, organismo, expediente, CPV, enlace) salen siempre de
data/latest.json por su id. Si un id no existe o ya ha cerrado, se detiene con error.

seleccion.json:
{
  "fecha": "2026-10-14",
  "intro": "Una o dos frases.",
  "secciones": [{"titulo": "Cierran esta semana", "nota": "opcional",
                 "items": [{"id": "...", "titulo": "...", "lugar": "...", "clave": "...",
                            "etiquetas": ["Navidad"]}]}],
  "ayudas": [{"codigo": "934700", "titulo": "...", "clave": "..."}],
  "proximas": [{"id": "...", "titulo": "...", "lugar": "...", "clave": "..."}],
  "adjudicaciones": [{"id": "...", "titulo": "...", "lugar": "...", "clave": "..."}],
  "desiertos": [{"id": "...", "titulo": "...", "lugar": "...", "clave": "..."}],
  "compradores": [{"id": "ayuntamiento de murcia", "clave": "..."}]
}

A cada licitación se le añade sola su precedente del año anterior, si existe (para quitarlo,
"precedente": false en el item). «proximas» son licitaciones del año pasado que aún no han salido
este año; «adjudicaciones», las recién adjudicadas. Sus datos salen del histórico y del archivo
de adjudicaciones, igual que el resto.
"""

import argparse
import json
import os
import sys
from datetime import date

from . import compradores as compradores_mod
from .plantilla import DIAS_LARGOS, MESES_LARGOS, renderizar
from .precedentes import resumen

CAMPOS_LICITACION = ("organo", "fecha_limite", "hora_limite", "presupuesto_sin_iva",
                     "procedimiento", "expediente", "cpv", "url", "fuente")
CAMPOS_AYUDA = ("organo", "fin", "texto_fin", "url")
EDITORIALES = ("titulo", "lugar", "clave", "etiquetas", "fecha_prudente")


class SeleccionInvalida(ValueError):
    pass


def _historico(seleccion, indice, clave_lista, errores, hoy_iso):
    elegidos = []
    for elegido in seleccion.get(clave_lista, []):
        registro = indice.por_id.get(elegido.get("id")) if indice else None
        if registro is None:
            errores.append(f"{clave_lista}: sin datos para {elegido.get('id')}")
            continue
        item = resumen(registro)
        item.update({campo: elegido[campo] for campo in EDITORIALES if elegido.get(campo)})
        elegidos.append(item)
    return elegidos


def _compradores(seleccion, resumenes, errores):
    por_id = {r["id"]: r for r in resumenes or []}
    elegidos = []
    for elegido in seleccion.get("compradores", []):
        resumen_comprador = por_id.get(elegido.get("id"))
        if resumen_comprador is None:
            errores.append(f"compradores: sin datos para {elegido.get('id')}")
            continue
        item = dict(resumen_comprador)
        if elegido.get("clave"):
            item["clave"] = elegido["clave"]
        elegidos.append(item)
    return elegidos


def componer(seleccion, datos, indice=None, compradores=None):
    fecha = seleccion["fecha"]
    hoy = date.fromisoformat(fecha)
    licitaciones = {l["id"]: l for l in datos.get("licitaciones", [])}
    ayudas = {a["codigo"]: a for a in datos.get("ayudas", [])}
    errores = []
    vistos = set()

    secciones = []
    for seccion in seleccion.get("secciones", []):
        items = []
        for elegido in seccion.get("items", []):
            ident = elegido.get("id")
            original = licitaciones.get(ident)
            if original is None:
                errores.append(f"licitación sin datos: {ident}")
                continue
            if ident in vistos:
                errores.append(f"licitación repetida: {ident}")
                continue
            vistos.add(ident)
            if (original.get("fecha_limite") or "") < fecha:
                errores.append(f"licitación ya cerrada: {ident} ({original.get('fecha_limite')})")
                continue
            item = {campo: original.get(campo) for campo in CAMPOS_LICITACION}
            item.update({campo: elegido[campo] for campo in EDITORIALES if elegido.get(campo)})
            item.setdefault("titulo", original.get("titulo"))
            if indice is not None and elegido.get("precedente") is not False:
                previo = indice.precedente(original, hoy)
                if previo:
                    item["precedente"] = previo
            if indice is not None and elegido.get("competencia") is not False:
                competencia = indice.competencia(original.get("titulo"))
                if competencia:
                    item["competencia"] = competencia
            items.append(item)
        if items:
            secciones.append({**{k: v for k, v in seccion.items() if k != "items"}, "items": items})

    lista_ayudas = []
    for elegida in seleccion.get("ayudas", []):
        original = ayudas.get(str(elegida.get("codigo")))
        if original is None:
            errores.append(f"ayuda sin datos: {elegida.get('codigo')}")
            continue
        if original.get("fin") and original["fin"] < fecha:
            errores.append(f"ayuda ya cerrada: {elegida.get('codigo')}")
            continue
        ayuda = {campo: original.get(campo) for campo in CAMPOS_AYUDA}
        ayuda["titulo"] = elegida.get("titulo") or original.get("titulo")
        if elegida.get("clave"):
            ayuda["clave"] = elegida["clave"]
        lista_ayudas.append(ayuda)

    proximas = _historico(seleccion, indice, "proximas", errores, fecha)
    adjudicaciones = _historico(seleccion, indice, "adjudicaciones", errores, fecha)
    desiertos = _historico(seleccion, indice, "desiertos", errores, fecha)
    lista_compradores = _compradores(seleccion, compradores, errores)

    if errores:
        raise SeleccionInvalida("; ".join(errores))
    if not secciones and not lista_ayudas:
        raise SeleccionInvalida("la selección está vacía")

    curada = {"fecha": fecha, "intro": seleccion.get("intro"), "secciones": secciones,
              "ayudas": lista_ayudas, "proximas": proximas, "adjudicaciones": adjudicaciones,
              "desiertos": desiertos, "compradores": lista_compradores}
    if seleccion.get("pie"):
        curada["pie"] = seleccion["pie"]
    total = sum(len(s["items"]) for s in secciones)
    titulo = (f"Foco · {DIAS_LARGOS[hoy.weekday()]} {hoy.day} de {MESES_LARGOS[hoy.month - 1]}: "
              f"{total} {'contrato abierto' if total == 1 else 'contratos abiertos'}")
    if lista_ayudas:
        titulo += f" y {len(lista_ayudas)} {'ayuda' if len(lista_ayudas) == 1 else 'ayudas'}"
    return curada, titulo


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("seleccion")
    parser.add_argument("--datos", default="data/latest.json")
    parser.add_argument("--salida", default="edicion.html")
    args = parser.parse_args(argv)
    with open(args.seleccion, encoding="utf-8") as fichero:
        seleccion = json.load(fichero)
    with open(args.datos, encoding="utf-8") as fichero:
        datos = json.load(fichero)
    from .precedentes import indice_desde
    carpeta = os.path.dirname(os.path.abspath(args.datos))
    indice = indice_desde(carpeta, datos)
    resumenes = compradores_mod.agrupar(compradores_mod.cargar(carpeta)) \
        if seleccion.get("compradores") else []
    try:
        curada, titulo = componer(seleccion, datos, indice, resumenes)
    except SeleccionInvalida as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    html = renderizar(curada)
    with open(args.salida, "w", encoding="utf-8") as fichero:
        fichero.write(html)
    with open("curada.json", "w", encoding="utf-8") as fichero:
        json.dump(curada, fichero, ensure_ascii=False, indent=1)
    print(f"TITULO: {titulo}")
    print(f"Escrito {args.salida} ({len(html)} caracteres)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
