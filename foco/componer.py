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
  "ayudas": [{"codigo": "934700", "titulo": "...", "clave": "..."}]
}
"""

import argparse
import json
import sys
from datetime import date

from .plantilla import DIAS_LARGOS, MESES_LARGOS, renderizar

CAMPOS_LICITACION = ("organo", "fecha_limite", "hora_limite", "presupuesto_sin_iva",
                     "procedimiento", "expediente", "cpv", "url", "fuente")
CAMPOS_AYUDA = ("organo", "fin", "texto_fin", "url")
EDITORIALES = ("titulo", "lugar", "clave", "etiquetas", "fecha_prudente")


class SeleccionInvalida(ValueError):
    pass


def componer(seleccion, datos):
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

    if errores:
        raise SeleccionInvalida("; ".join(errores))
    if not secciones and not lista_ayudas:
        raise SeleccionInvalida("la selección está vacía")

    curada = {"fecha": fecha, "intro": seleccion.get("intro"), "secciones": secciones,
              "ayudas": lista_ayudas}
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
    try:
        curada, titulo = componer(seleccion, datos)
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
