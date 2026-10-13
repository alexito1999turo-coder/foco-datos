"""Punto de entrada: recoge todas las fuentes y guarda data/latest.json.

Uso: python -m foco.recoger --salida data --dias 3
Una fuente que falla no tumba las demás; el error queda anotado en el JSON.
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone

from . import ayudas, catalunya, placsp
from .comun import normalizar


def _completitud(lic):
    return sum(1 for campo in ("presupuesto_sin_iva", "url", "hora_limite", "procedimiento")
               if lic.get(campo))


def quitar_duplicados(licitaciones):
    """La misma licitación catalana llega por la Generalitat y por PLACSP agregada."""
    por_clave = {}
    for lic in licitaciones:
        clave = normalizar(lic.get("expediente")) or lic.get("id")
        clave = f"{clave}|{normalizar(lic.get('organo'))[:25]}"
        previa = por_clave.get(clave)
        if previa is None or _completitud(lic) > _completitud(previa):
            por_clave[clave] = lic
    return sorted(por_clave.values(),
                  key=lambda l: (l.get("fecha_limite") or "9999", l.get("hora_limite") or "23:59"))


def ejecutar(salida, dias=3, hoy=None, fuentes=None):
    hoy = hoy or date.today()
    fuentes = fuentes or {
        "placsp": lambda: placsp.recoger(dias=dias, hoy=hoy),
        "catalunya": lambda: catalunya.recoger(hoy=hoy),
        "bdns": lambda: ayudas.recoger_bdns(hoy=hoy),
        "boe": lambda: ayudas.recoger_boe(hoy=hoy, dias=dias),
    }
    resultado = {
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fecha": hoy.isoformat(),
        "licitaciones": [],
        "ayudas": [],
        "informe": {},
        "errores": [],
    }
    for nombre, funcion in fuentes.items():
        try:
            lista, informe = funcion()
        except Exception as error:  # una fuente caída no detiene el resto
            resultado["errores"].append({"fuente": nombre, "error": repr(error)[:500]})
            continue
        destino = "ayudas" if nombre in ("bdns", "boe") else "licitaciones"
        resultado[destino].extend(lista)
        resultado["informe"][nombre] = {**informe, "seleccionadas": len(lista)}

    resultado["licitaciones"] = quitar_duplicados(resultado["licitaciones"])

    os.makedirs(os.path.join(salida, "historico"), exist_ok=True)
    texto = json.dumps(resultado, ensure_ascii=False, indent=1)
    with open(os.path.join(salida, "latest.json"), "w", encoding="utf-8") as fichero:
        fichero.write(texto)
    with open(os.path.join(salida, "historico", f"{hoy.isoformat()}.json"), "w",
              encoding="utf-8") as fichero:
        fichero.write(texto)
    return resultado


def main(argv=None):
    parser = argparse.ArgumentParser(description="Recoge licitaciones y ayudas de eventos.")
    parser.add_argument("--salida", default="data")
    parser.add_argument("--dias", type=int, default=3)
    args = parser.parse_args(argv)
    resultado = ejecutar(args.salida, dias=args.dias)
    print(f"Licitaciones: {len(resultado['licitaciones'])} · Ayudas: {len(resultado['ayudas'])}")
    for error in resultado["errores"]:
        print(f"ERROR en {error['fuente']}: {error['error']}", file=sys.stderr)
    todas_fallan = len(resultado["errores"]) == 4
    return 1 if todas_fallan else 0


if __name__ == "__main__":
    sys.exit(main())
