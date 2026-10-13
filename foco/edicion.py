"""Prepara los candidatos de la edición del día a partir de data/latest.json.

Uso: python -m foco.edicion data/latest.json --fecha 2026-10-14
Imprime un listado compacto agrupado por secciones y guarda edicion-candidatos.json.
No usa la red: solo lee el JSON que deja la recogida diaria.
"""

import argparse
import json
import os
import re
from datetime import date, timedelta

from .comun import normalizar
from .precedentes import indice_desde, mes_y_anio

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


def texto_precedente(previo):
    if not previo:
        return ""
    partes = [mes_y_anio(previo["publicada"])]
    if previo.get("ganador"):
        partes.append(f"ganó {previo['ganador']}" + (" (y otros)" if previo.get("varios_ganadores") else ""))
    if previo.get("lotes_desiertos"):
        partes.append(f"{previo['lotes_desiertos']} lote(s) desierto(s)")
    if previo.get("importe_sin_iva") is not None:
        partes.append(f"por {euros(previo['importe_sin_iva'])}")
    elif previo.get("presupuesto_sin_iva") is not None:
        partes.append(f"presupuesto {euros(previo['presupuesto_sin_iva'])}")
    if previo.get("ofertas") is not None:
        partes.append(f"{previo['ofertas']} ofertas")
    if previo.get("baja") is not None:
        partes.append(f"baja {previo['baja']} %")
    return " · ".join(partes)


def adjudicaciones_recientes(carpeta, hoy, dias=7):
    try:
        with open(os.path.join(carpeta, "adjudicaciones.json"), encoding="utf-8") as fichero:
            archivo = json.load(fichero)
    except (OSError, ValueError):
        return []
    desde = (hoy - timedelta(days=dias)).isoformat()
    return sorted((r for r in archivo.values() if (r.get("vista") or "") >= desde),
                  key=lambda r: r.get("vista") or "", reverse=True)


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
    carpeta = os.path.dirname(os.path.abspath(args.datos))
    indice = indice_desde(carpeta, datos)
    for nombre in ("cierra_7_dias", "navidad_reyes", "resto"):
        for item in secciones[nombre]:
            item["precedente"] = indice.precedente(item, hoy)
    secciones["proximas"] = indice.proximas(hoy)
    from .precedentes import resumen
    secciones["adjudicaciones"] = [
        {**resumen(r), "municipio": r.get("municipio"), "provincia": r.get("provincia")}
        for r in adjudicaciones_recientes(carpeta, hoy)]
    with open(args.salida, "w", encoding="utf-8") as fichero:
        json.dump(secciones, fichero, ensure_ascii=False, indent=1)
    print(f"Histórico disponible: {len(indice)} licitaciones de eventos")
    for nombre, items in secciones.items():
        print(f"\n## {nombre} ({len(items)})")
        if nombre in ("proximas", "adjudicaciones"):
            for item in items[:40]:
                print(f"- [{item.get('publicada')}] {(item.get('titulo') or '')[:200]} | "
                      f"{item.get('organo')} | {texto_precedente(item)} | id={item.get('id')}")
            continue
        for item in items[:80]:
            marca = "NUEVA " if item.get("nueva") else ""
            titulo = (item.get("titulo") or "")[:220]
            ident = item.get("id") or item.get("codigo")
            lugar = " / ".join(x for x in (item.get("municipio"), item.get("provincia")) if x)
            print(f"- {marca}[{item.get('dias_restantes')}d · {item.get('cierra')}] {titulo} | "
                  f"{item.get('organo')} | {lugar or '-'} | "
                  f"{item.get('presupuesto_texto') or item.get('presupuesto')} | "
                  f"{item.get('motivo') or item.get('fuente')} | id={ident}")
            if item.get("precedente"):
                print(f"    ↳ precedente: {texto_precedente(item['precedente'])}")
    if datos.get("errores"):
        print("\nErrores de recogida:", datos["errores"])


if __name__ == "__main__":
    main()
