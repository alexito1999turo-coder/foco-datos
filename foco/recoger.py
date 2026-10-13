"""Punto de entrada: recoge todas las fuentes y guarda data/latest.json.

Uso: python -m foco.recoger --salida data --dias 3 --dias-ayudas 7

El listado es acumulativo: cada día se suman las licitaciones nuevas, se quitan las que
cerraron plazo o cambiaron de estado y se conserva el resto. Así una licitación publicada
hace dos semanas sigue en la edición mientras esté abierta.
Una fuente que falla no tumba las demás; el error queda anotado en el JSON.
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

from . import ayudas, catalunya, placsp
from .comun import es_de_eventos, normalizar

CATALUNYA = "Generalitat de Catalunya"
# Tiempo máximo por feed de PLACSP. Con dos feeds deja margen dentro de los 60 min del trabajo.
# Lo nuevo de un día se lee en pocos minutos; el resto del tiempo se dedica al relleno pendiente.
SEGUNDOS_POR_FEED = 22 * 60


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


def guardar_adjudicaciones(salida, nuevas, hoy_iso):
    """Suma las adjudicaciones de eventos a data/adjudicaciones.json, el archivo de precios del
    sector, y devuelve las que no se habían visto antes (para la sección «Quién ganó»)."""
    ruta = os.path.join(salida, "adjudicaciones.json")
    try:
        with open(ruta, encoding="utf-8") as fichero:
            archivo = json.load(fichero)
    except (OSError, ValueError):
        archivo = {}
    recien = []
    for registro in nuevas:
        previo = archivo.get(registro["id"])
        registro = {**registro, "vista": (previo or {}).get("vista") or hoy_iso}
        if previo is None:
            recien.append(registro)
        archivo[registro["id"]] = registro
    os.makedirs(salida, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as fichero:
        json.dump(archivo, fichero, ensure_ascii=False, indent=0, sort_keys=True)
    return sorted(recien, key=lambda r: r.get("titulo") or "")


def _cargar_previo(salida):
    try:
        with open(os.path.join(salida, "latest.json"), encoding="utf-8") as fichero:
            return json.load(fichero)
    except (OSError, ValueError):
        return {}


def _sigue_abierta(lic, hoy_iso):
    return (lic.get("fecha_limite") or "") >= hoy_iso


def _sigue_interesando(lic):
    """Si los filtros cambian, lo acumulado de días anteriores se vuelve a pasar por ellos."""
    return es_de_eventos(lic.get("titulo"), lic.get("cpv") or [])[0]


def _ayuda_vigente(ayuda, hoy):
    if ayudas.EXCLUIR.search(normalizar(ayuda.get("titulo"))):
        return False
    if ayuda.get("fin"):
        return ayuda["fin"] >= hoy.isoformat()
    if ayuda.get("fuente") == "BOE":
        publicada = ayuda.get("fecha_publicacion") or "0000"
        return publicada >= (hoy - timedelta(days=30)).isoformat()
    return bool(ayuda.get("abierta_ahora"))


def ejecutar(salida, dias=3, dias_ayudas=7, hoy=None, fuentes=None):
    hoy = hoy or date.today()
    hoy_iso = hoy.isoformat()
    previo = _cargar_previo(salida)
    primera_vez = {l.get("id"): l.get("primera_vez") for l in previo.get("licitaciones", [])}
    primera_vez.update({a.get("codigo"): a.get("primera_vez") for a in previo.get("ayudas", [])})

    acumuladas = {l["id"]: l for l in previo.get("licitaciones", [])
                  if not l.get("fuente", "").startswith(CATALUNYA) and _sigue_abierta(l, hoy_iso)
                  and _sigue_interesando(l)}
    catalanas = [l for l in previo.get("licitaciones", [])
                 if l.get("fuente") == CATALUNYA and _sigue_abierta(l, hoy_iso)]
    ayudas_vigentes = {a["codigo"]: a for a in previo.get("ayudas", []) if _ayuda_vigente(a, hoy)}

    estado_placsp = (previo.get("informe") or {}).get("placsp") or {}
    fuentes = fuentes or {
        "placsp": lambda: placsp.recoger(dias=dias, hoy=hoy, limite_segundos=SEGUNDOS_POR_FEED,
                                         estado_previo=estado_placsp),
        "catalunya": lambda: catalunya.recoger(hoy=hoy),
        "bdns": lambda: ayudas.recoger_bdns(hoy=hoy, dias=dias_ayudas,
                                            ya_vistas=set(ayudas_vigentes)),
        "boe": lambda: ayudas.recoger_boe(hoy=hoy, dias=min(dias, 7)),
    }
    resultado = {
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fecha": hoy_iso,
        "licitaciones": [],
        "ayudas": [],
        "informe": {},
        "errores": [],
        "adjudicaciones_nuevas": [],
    }
    for nombre, funcion in fuentes.items():
        try:
            respuesta = funcion()
        except Exception as error:  # una fuente caída no detiene el resto
            resultado["errores"].append({"fuente": nombre, "error": repr(error)[:500]})
            if nombre == "placsp" and estado_placsp:
                # Se conserva dónde se quedó la lectura para continuar mañana.
                resultado["informe"]["placsp"] = {**estado_placsp, "arrastrado": True}
            continue
        lista, informe = respuesta[0], respuesta[1]
        cerradas = respuesta[2] if len(respuesta) > 2 else []
        if nombre == "placsp":
            for clave in cerradas:
                acumuladas.pop(clave, None)
            for lic in lista:
                acumuladas[lic["id"]] = lic
            nuevas_adjudicaciones = respuesta[3] if len(respuesta) > 3 else []
            resultado["adjudicaciones_nuevas"] = guardar_adjudicaciones(
                salida, nuevas_adjudicaciones, hoy_iso)
        elif nombre == "catalunya":
            catalanas = lista
        else:
            for ayuda in lista:
                ayudas_vigentes[ayuda["codigo"]] = ayuda
        resultado["informe"][nombre] = {**informe, "seleccionadas": len(lista)}

    licitaciones = [l for l in list(acumuladas.values()) + catalanas if _sigue_abierta(l, hoy_iso)]
    for lic in licitaciones:
        lic["primera_vez"] = primera_vez.get(lic.get("id")) or hoy_iso
    lista_ayudas = [a for a in ayudas_vigentes.values() if _ayuda_vigente(a, hoy)]
    for ayuda in lista_ayudas:
        ayuda["primera_vez"] = primera_vez.get(ayuda.get("codigo")) or hoy_iso

    resultado["licitaciones"] = quitar_duplicados(licitaciones)
    resultado["ayudas"] = sorted(lista_ayudas, key=lambda a: a.get("fin") or "9999")

    os.makedirs(os.path.join(salida, "historico"), exist_ok=True)
    texto = json.dumps(resultado, ensure_ascii=False, indent=1)
    with open(os.path.join(salida, "latest.json"), "w", encoding="utf-8") as fichero:
        fichero.write(texto)
    with open(os.path.join(salida, "historico", f"{hoy_iso}.json"), "w",
              encoding="utf-8") as fichero:
        fichero.write(texto)
    return resultado


def main(argv=None):
    parser = argparse.ArgumentParser(description="Recoge licitaciones y ayudas de eventos.")
    parser.add_argument("--salida", default="data")
    parser.add_argument("--dias", type=int, default=3, help="días hacia atrás en los feeds de PLACSP")
    parser.add_argument("--dias-ayudas", type=int, default=7, help="días hacia atrás en la BDNS")
    args = parser.parse_args(argv)
    resultado = ejecutar(args.salida, dias=args.dias, dias_ayudas=args.dias_ayudas)
    print(f"Licitaciones: {len(resultado['licitaciones'])} · Ayudas: {len(resultado['ayudas'])}")
    print(json.dumps(resultado["informe"], ensure_ascii=False))
    for error in resultado["errores"]:
        print(f"ERROR en {error['fuente']}: {error['error']}", file=sys.stderr)
    todas_fallan = len(resultado["errores"]) == 4
    return 1 if todas_fallan else 0


if __name__ == "__main__":
    sys.exit(main())
