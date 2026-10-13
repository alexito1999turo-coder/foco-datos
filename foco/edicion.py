"""Prepara los candidatos de la edición del día a partir de data/latest.json.

Uso: python -m foco.edicion data/latest.json --fecha 2026-10-14
Imprime un listado compacto agrupado por secciones y guarda edicion-candidatos.json.
No usa la red: solo lee el JSON que deja la recogida diaria.
"""

import argparse
import json
import re
from datetime import date

from .comun import normalizar

NAVIDAD = re.compile(
    r"\b(navidad|naviden[oa]s?|nadal|nadalen[ca]s?|cabalgatas?|cavalcad[ae]s?|reyes magos|"
    r"reis mags|nochevieja|cap d'any|papa noel|campanadas|belen|pessebre)\b"
)

DIAS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")
MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")


def fecha_corta(texto):
    if not texto:
        return None
    dia = date.fromisoformat(texto[:10])
    return f"{DIAS[dia.weekday()]} {dia.day} {MESES[dia.month - 1]}"


def euros(valor):
    if valor is None:
        return None
    entero, decimales = f"{valor:,.2f}".split(".")
    return f"{entero.replace(',', '.')},{decimales} €"


def dias_restantes(texto, hoy):
    return (date.fromisoformat(texto[:10]) - hoy).days if texto else None


def agrupar(datos, hoy):
    secciones = {"cierra_7_dias": [], "navidad_reyes": [], "resto": [], "siempre_abiertas": []}
    for lic in datos.get("licitaciones", []):
        restantes = dias_restantes(lic.get("fecha_limite"), hoy)
        if restantes is None or restantes < 0:
            continue
        lic = {**lic, "dias_restantes": restantes, "cierra": fecha_corta(lic.get("fecha_limite")),
               "presupuesto_texto": euros(lic.get("presupuesto_sin_iva")),
               "nueva": lic.get("primera_vez") == hoy.isoformat()}
        if restantes > 365:
            secciones["siempre_abiertas"].append(lic)
        elif restantes <= 7:
            secciones["cierra_7_dias"].append(lic)
        elif NAVIDAD.search(normalizar(lic.get("titulo"))):
            secciones["navidad_reyes"].append(lic)
        else:
            secciones["resto"].append(lic)
    ayudas = []
    for ayuda in datos.get("ayudas", []):
        restantes = dias_restantes(ayuda.get("fin"), hoy) if ayuda.get("fin") else None
        ayudas.append({**ayuda, "dias_restantes": restantes, "cierra": fecha_corta(ayuda.get("fin")),
                       "nueva": ayuda.get("primera_vez") == hoy.isoformat()})
    secciones["ayudas"] = ayudas
    return secciones


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("datos")
    parser.add_argument("--fecha", default=None)
    parser.add_argument("--salida", default="edicion-candidatos.json")
    args = parser.parse_args(argv)
    hoy = date.fromisoformat(args.fecha) if args.fecha else date.today()
    with open(args.datos, encoding="utf-8") as fichero:
        datos = json.load(fichero)
    secciones = agrupar(datos, hoy)
    with open(args.salida, "w", encoding="utf-8") as fichero:
        json.dump(secciones, fichero, ensure_ascii=False, indent=1)
    for nombre, items in secciones.items():
        print(f"\n## {nombre} ({len(items)})")
        for item in items[:80]:
            marca = "NUEVA " if item.get("nueva") else ""
            titulo = (item.get("titulo") or "")[:220]
            print(f"- {marca}[{item.get('dias_restantes')}d · {item.get('cierra')}] {titulo} | "
                  f"{item.get('organo')} | {item.get('presupuesto_texto') or item.get('presupuesto')} | "
                  f"{item.get('motivo') or item.get('fuente')}")
    if datos.get("errores"):
        print("\nErrores de recogida:", datos["errores"])


if __name__ == "__main__":
    main()
