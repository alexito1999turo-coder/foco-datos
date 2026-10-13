"""Quién compra eventos sin licitar: los contratos menores agrupados por organismo.

Un contrato menor (hasta 15.000 € sin IVA en servicios y suministros) no se licita: el organismo
elige a quién se lo encarga. Por eso es donde viven muchas empresas pequeñas de eventos, y por eso
saber quién compra, cuánto, qué y cuándo es una lista de clientes a los que presentarse.

Fuente: data/menores_eventos/*.json (contratos menores de PLACSP filtrados como de eventos).
Solo se nombran proveedores que son empresas, nunca personas físicas.
"""

import glob
import json
import os
import re
from collections import Counter

from .comun import normalizar
from .precedentes import categoria, clave_organo

FORMAS = re.compile(r"\b(s\.?\s?l\.?\s?u?|s\.?\s?a\.?\s?u?|sociedad limitada( unipersonal)?|"
                    r"sociedad anonima|slu|sll|slp|sccl|scp)\b")


def clave_proveedor(nombre):
    texto = FORMAS.sub(" ", normalizar(nombre))
    return " ".join(re.findall(r"[a-z0-9ñç]+", texto))

MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
         "octubre", "noviembre", "diciembre")
PRINCIPAL = re.compile(r"(ayuntamiento|ajuntament|concello|udala|diputaci[oó]n|diputaci[oó]|"
                       r"cabildo|consell|mancomunidad|comarca)\b.*", re.IGNORECASE)
SECUNDARIO = re.compile(r"(generalitat|consejer[ií]a|conselleria|departament|instituto|institut|"
                        r"patronato|patronat|fundaci[oó]n?|consorci[oa]?|sociedad|empresa)\b.*",
                        re.IGNORECASE)


def nombre_visible(organo):
    """«Junta de Gobierno del Ayuntamiento de Murcia» -> «Ayuntamiento de Murcia»."""
    texto = re.sub(r"\s*-\s*(alcald|pleno|junta|concejal|presidente|gerente).*$", "", organo or "",
                   flags=re.IGNORECASE).strip()
    encontrado = PRINCIPAL.search(texto) or SECUNDARIO.search(texto)
    nombre = encontrado.group(0) if encontrado else texto
    return nombre[:1].upper() + nombre[1:]


def provincia_visible(provincia):
    if provincia and provincia.isupper():
        return " ".join(p.capitalize() if len(p) > 2 else p.lower() for p in provincia.split())
    return provincia


def cargar(carpeta_datos):
    """Registros de contratos menores, con el mes del fichero del que salen (AAAAMM)."""
    registros = []
    for ruta in sorted(glob.glob(os.path.join(carpeta_datos, "menores_eventos", "*.json"))):
        periodo = os.path.basename(ruta)[:-5]
        with open(ruta, encoding="utf-8") as fichero:
            for registro in json.load(fichero).values():
                registros.append({**registro, "periodo_fichero": periodo})
    return registros


def _importe(registro):
    adjudicados = [r for r in registro.get("resultados") or []
                   if r.get("resultado") in ("adjudicado", "formalizado")]
    importes = [r.get("importe_sin_iva") for r in adjudicados if r.get("importe_sin_iva")]
    if importes:
        return sum(importes)
    return registro.get("presupuesto_sin_iva") or 0


def _mes(registro):
    for resultado in registro.get("resultados") or []:
        if resultado.get("fecha"):
            return int(resultado["fecha"][5:7])
    fecha = registro.get("publicada") or (registro.get("actualizado") or "")[:10]
    return int(fecha[5:7]) if fecha else None


def agrupar(registros):
    """Un resumen por organismo comprador."""
    grupos = {}
    for registro in registros:
        clave = clave_organo(registro.get("organo"))
        if not clave:
            continue
        grupo = grupos.setdefault(clave, {
            "id": clave, "nombres": Counter(), "municipio": None, "provincia": None,
            "contratos": 0, "gasto": 0.0, "tipos": Counter(), "meses": Counter(),
            "gasto_por_mes": Counter(), "proveedores": Counter(), "ejemplos": [],
        })
        importe = _importe(registro)
        mes = _mes(registro)
        grupo["nombres"][nombre_visible(registro.get("organo"))] += 1
        grupo["municipio"] = grupo["municipio"] or registro.get("municipio")
        grupo["provincia"] = grupo["provincia"] or registro.get("provincia")
        grupo["contratos"] += 1
        grupo["gasto"] += importe
        grupo["tipos"][categoria(registro.get("titulo")) or "otros"] += 1
        if mes:
            grupo["meses"][mes] += 1
            grupo["gasto_por_mes"][mes] += importe
        for resultado in registro.get("resultados") or []:
            if resultado.get("ganador_empresa") and resultado.get("ganador"):
                clave_p = clave_proveedor(resultado["ganador"])
                grupo["proveedores"][clave_p] += resultado.get("importe_sin_iva") or 0
                grupo.setdefault("variantes", {}).setdefault(clave_p, Counter())[
                    resultado["ganador"].strip().rstrip(",")] += 1
        grupo["ejemplos"].append((importe, registro.get("titulo"), registro.get("url")))
    meses_fichero = sorted({r["periodo_fichero"] for r in registros
                            if len(r.get("periodo_fichero") or "") == 6})
    periodo = None
    if meses_fichero:
        inicio, fin = meses_fichero[0], meses_fichero[-1]
        periodo = (f"publicados de {MESES[int(inicio[4:]) - 1]} de {inicio[:4]} a "
                   f"{MESES[int(fin[4:]) - 1]} de {fin[:4]}")
    resumenes = []
    for grupo in grupos.values():
        tipos = [t for t, _ in grupo["tipos"].most_common() if t != "otros"][:3]
        resumenes.append({
            "id": grupo["id"],
            "nombre": grupo["nombres"].most_common(1)[0][0],
            "municipio": grupo["municipio"],
            "provincia": provincia_visible(grupo["provincia"]),
            "contratos": grupo["contratos"],
            "periodo": periodo,
            "gasto": round(grupo["gasto"], 2),
            "tipos": tipos,
            "meses_fuertes": [m for m, _ in grupo["gasto_por_mes"].most_common(3)],
            "gasto_por_mes": {str(m): round(v, 2) for m, v in grupo["gasto_por_mes"].items()},
            "proveedores": [grupo["variantes"][p].most_common(1)[0][0]
                            for p, _ in grupo["proveedores"].most_common(3)],
            "ejemplos": [{"importe": round(i, 2), "titulo": t, "url": u}
                         for i, t, u in sorted(grupo["ejemplos"], key=lambda e: e[0],
                                                reverse=True)[:3]],
        })
    resumenes.sort(key=lambda r: r["gasto"], reverse=True)
    return resumenes


def para_estas_fechas(resumenes, mes_actual, meses=2, minimo_contratos=3):
    """Los que más gastan en los próximos meses según su calendario de compras."""
    proximos = [((mes_actual - 1 + i) % 12) + 1 for i in range(meses + 1)]
    candidatos = []
    for resumen in resumenes:
        if resumen["contratos"] < minimo_contratos:
            continue
        gasto = sum(resumen["gasto_por_mes"].get(str(m), 0) for m in proximos)
        if gasto > 0:
            candidatos.append({**resumen, "gasto_proximos": round(gasto, 2)})
    candidatos.sort(key=lambda r: r["gasto_proximos"], reverse=True)
    return candidatos


def nombre_mes(numero):
    return MESES[numero - 1]
