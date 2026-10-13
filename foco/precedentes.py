"""Precedentes y previsiones a partir del histórico de licitaciones de eventos.

- precedente(lic): la licitación equivalente del mismo organismo en la campaña anterior, con su
  presupuesto y, si se adjudicó, quién ganó, por cuánto, con cuántas ofertas y qué baja hubo.
- proximas(hoy): lo que el año pasado se publicó en las próximas semanas y este año aún no ha
  salido. Casi todo en eventos se repite cada año (cabalgatas, luces, fiestas mayores).

Fuentes: data/historico_eventos/*.json (zips de PLACSP), data/adjudicaciones.json (lo adjudicado
que se va viendo cada día) y las licitaciones abiertas de data/latest.json.
"""

import glob
import json
import os
import re
from collections import Counter
from datetime import date, timedelta

from .comun import es_de_eventos, normalizar

VACIAS = set("""
de del la las el los y e o u en a al para por con sin su sus un una unos unas que se lo
servicio servicios servei serveis contrato contratacion contractacio contracte suministro
subministrament subministraments prestacion prestacio realizacion realitzacio ejecucion execucio
organizacion organitzacio gestion gestio mediante procedimiento abierto obert lote lotes lot lots
municipio municipal municipales ayuntamiento ajuntament concello ciudad ciutat vila villa ano any
objeto objecte expediente actividades activitats arrendamiento lloguer alquiler regimen regim
diversos diverses necesarios necessaris dels les per amb pel als
""".split())
EQUIVALENCIAS = {
    "cavalcada": "cabalgata", "reis": "reyes", "mags": "magos", "nadal": "navidad",
    "nadalenc": "navideno", "nadalenca": "navideno", "nadalencs": "navideno",
    "nadalenques": "navideno", "navidena": "navideno", "navidenos": "navideno",
    "navidenas": "navideno", "enllumenat": "alumbrado", "llums": "luces", "llum": "luces",
    "festes": "fiestas", "festa": "fiesta", "fires": "ferias", "fira": "feria", "so": "sonido",
    "sonoritzacio": "sonido", "sonorizacion": "sonido", "il": "iluminacio", "luminacio": "iluminacio",
    "iluminacion": "iluminacio", "espectacles": "espectaculos", "carrosses": "carrozas",
    "escenaris": "escenarios", "escenari": "escenario",
}
ORGANO = re.compile(r"(ayuntamiento|ajuntament|concello|udala|diputacion|diputacio|cabildo|"
                    r"consell|consejo insular|comarca|mancomunidad|junta de|generalitat|gobierno|"
                    r"consejeria|conselleria|departament|instituto|institut|patronato|patronat|"
                    r"fundacion|fundacio|consorcio|consorci|sociedad|empresa)\b.*")
PREFIJOS_ORGANO = re.compile(r"^(alcaldia|pleno|junta de gobierno( local)?|concejal\w*|"
                             r"presidencia|gerencia|consejo de administracion)\b[^,]*? del? ")
MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")


def palabras(titulo):
    texto = normalizar(titulo).replace("l·l", "ll").replace("'", " ").replace("’", " ")
    resultado = set()
    for palabra in re.findall(r"[a-zñç]+", texto):
        palabra = EQUIVALENCIAS.get(palabra, palabra)
        if len(palabra) > 2 and palabra not in VACIAS:
            resultado.add(palabra)
    return resultado


# Lo que se contrata. Si dos títulos nombran cosas distintas (sonido frente a luces), no son el
# mismo contrato aunque compartan la ocasión (fiestas, Navidad).
OBJETO = set("""
sonido iluminacio luces alumbrado escenario escenarios carpa carpas cabalgata carrozas pirotecnia
fuegos atracciones hinchables inflables mercado mercat belen pessebre parque parc pista patinaje
tren trenet trenets conciertos concierto orquesta orquestas verbena verbenas teatro circo mapping
decoracion decorativos ornamentacion ornamental casetas stand congreso exposicion programacion
animacion talleres catering seguridad limpieza tobogan noria juguetes cestas
""".split())


def similitud(a, b):
    """Parecido entre dos títulos: media entre solapamiento y Jaccard, y cero si nombran cosas
    distintas o comparten menos de dos palabras."""
    if not a or not b:
        return 0.0
    comunes = a & b
    if len(comunes) < 2:
        return 0.0
    objeto_a, objeto_b = a & OBJETO, b & OBJETO
    if objeto_a and objeto_b and not (objeto_a & objeto_b):
        return 0.0
    return 0.5 * len(comunes) / min(len(a), len(b)) + 0.5 * len(comunes) / len(a | b)


def clave_organo(organo):
    texto = normalizar(organo)
    texto = re.sub(r"\s*-\s*(alcald|pleno|junta|concejal|presidente|gerente).*$", "", texto)
    texto = PREFIJOS_ORGANO.sub("", texto)
    encontrado = ORGANO.search(texto)
    return (encontrado.group(0) if encontrado else texto).strip()


def fecha_referencia(registro):
    return registro.get("publicada") or (registro.get("actualizado") or "")[:10] or None


def mes_y_anio(texto):
    dia = date.fromisoformat(texto[:10])
    return f"{MESES[dia.month - 1]} {dia.year}"


def resumen(registro):
    """Lo que se cuenta de un precedente: cuándo, cuánto y, si lo hay, quién ganó.

    Con un solo resultado se dan importe, ofertas y baja. Con varios lotes, el ganador principal
    y cuántos lotes quedaron desiertos; el importe solo si se adjudicaron todos, y sin baja. Un
    importe por debajo del 10 % del presupuesto suele ser un precio unitario: no se muestra."""
    todos = registro.get("resultados") or []
    adjudicados = [r for r in todos if r.get("resultado") in ("adjudicado", "formalizado")]
    datos = {
        "id": registro.get("id"),
        "titulo": registro.get("titulo"),
        "organo": registro.get("organo"),
        "publicada": fecha_referencia(registro),
        "presupuesto_sin_iva": registro.get("presupuesto_sin_iva"),
        "url": registro.get("url"),
        "estado": registro.get("estado"),
        "lotes_adjudicados": len(adjudicados),
        "lotes_desiertos": sum(1 for r in todos if r.get("resultado") == "desierto"),
    }
    if not adjudicados:
        return datos
    empresas = Counter(r["ganador"] for r in adjudicados
                       if r.get("ganador") and r.get("ganador_empresa"))
    if empresas:
        datos["ganador"] = empresas.most_common(1)[0][0]
        datos["varios_ganadores"] = len(empresas) > 1 or any(
            r.get("ganador") == "persona física" for r in adjudicados)
    elif any(r.get("ganador") for r in adjudicados):
        datos["ganador"] = "persona física"
    presupuesto = registro.get("presupuesto_sin_iva")
    importes = [r.get("importe_sin_iva") for r in adjudicados]
    if len(todos) > 1:
        datos["por_lotes"] = True
        if len(adjudicados) == len(todos) and all(i is not None for i in importes):
            datos["importe_sin_iva"] = round(sum(importes), 2)
    else:
        unico = adjudicados[0]
        datos["importe_sin_iva"] = unico.get("importe_sin_iva")
        datos["ofertas"] = unico.get("ofertas")
        if datos["importe_sin_iva"] is not None and presupuesto:
            baja = 1 - datos["importe_sin_iva"] / presupuesto
            if 0 <= baja < 0.6:
                datos["baja"] = round(baja * 100, 1)
    if (datos.get("importe_sin_iva") is not None and presupuesto
            and datos["importe_sin_iva"] < 0.1 * presupuesto):
        datos.pop("importe_sin_iva")
        datos.pop("baja", None)
    return {k: v for k, v in datos.items() if v is not None}


# Para ordenar «lo que viene»: lo que más claramente es trabajo de una empresa de eventos.
DESTACADAS = OBJETO | set("""
cabalgata navideno navidad reyes fiestas fiesta festival feria ferias carnaval nochevieja
verbena patronales mayor
""".split())


def cubre_esta_temporada(titulo, hoy):
    """Un contrato del año pasado que nombra el año que viene (p. ej. «2026 y 2027» visto en
    2026) es plurianual: este año no se volverá a licitar."""
    anios = [int(a) for a in re.findall(r"\b(20[2-4]\d)\b", titulo or "")]
    return any(a >= hoy.year + 1 for a in anios)


class Indice:
    def __init__(self, registros):
        self.por_organo = {}
        self.por_id = {}
        vistos = set()
        for registro in registros:
            clave = registro.get("id") or registro.get("url")
            if not clave or clave in vistos or not fecha_referencia(registro):
                continue
            vistos.add(clave)
            self.por_id[clave] = registro
            organo = clave_organo(registro.get("organo"))
            entrada = (palabras(registro.get("titulo")) - palabras(organo), registro)
            self.por_organo.setdefault(organo, []).append(entrada)

    def __len__(self):
        return sum(len(lista) for lista in self.por_organo.values())

    def _parecidos(self, lic, desde, hasta, umbral):
        organo = clave_organo(lic.get("organo"))
        firma = palabras(lic.get("titulo")) - palabras(organo)
        candidatos = []
        for palabras_previas, registro in self.por_organo.get(organo, []):
            fecha = fecha_referencia(registro)
            if not (desde <= fecha <= hasta) or registro.get("id") == lic.get("id"):
                continue
            puntos = similitud(firma, palabras_previas)
            if puntos >= umbral:
                candidatos.append((puntos, fecha, registro))
        candidatos.sort(key=lambda c: (c[0], c[1]), reverse=True)
        return candidatos

    def precedente(self, lic, hoy, umbral=0.45):
        """La licitación equivalente de la campaña anterior (entre 6 y 20 meses antes)."""
        desde = (hoy - timedelta(days=600)).isoformat()
        hasta = (hoy - timedelta(days=180)).isoformat()
        candidatos = self._parecidos(lic, desde, hasta, umbral)
        if not candidatos:
            return None
        # Entre los parecidos, mejor el que tiene adjudicación.
        candidatos.sort(key=lambda c: (bool(c[2].get("resultados")), c[0], c[1]), reverse=True)
        return resumen(candidatos[0][2])

    def proximas(self, hoy, dias=21, umbral=0.45):
        """Lo publicado el año pasado entre hoy y hoy+dias que este año aún no ha salido."""
        inicio = (hoy - timedelta(days=365)).isoformat()
        fin = (hoy - timedelta(days=365 - dias)).isoformat()
        este_anio_desde = (hoy - timedelta(days=150)).isoformat()
        resultado = []
        for lista in self.por_organo.values():
            for _, registro in lista:
                fecha = fecha_referencia(registro)
                if not (inicio <= fecha <= fin):
                    continue
                if self._parecidos(registro, este_anio_desde, "9999", umbral):
                    continue  # ya ha salido este año
                if registro.get("estado") == "ANUL":
                    continue
                if not es_de_eventos(registro.get("titulo"), registro.get("cpv") or [])[0]:
                    continue
                if cubre_esta_temporada(registro.get("titulo"), hoy):
                    continue  # contrato plurianual: ya incluye la campaña de este año
                datos = resumen(registro)
                datos["dias_para_aniversario"] = (
                    date.fromisoformat(fecha) + timedelta(days=365) - hoy).days
                destacadas = len(palabras(registro.get("titulo")) & DESTACADAS)
                presupuesto = registro.get("presupuesto_sin_iva") or 0
                datos["prioridad"] = (destacadas + (1 if presupuesto >= 30000 else 0)
                                      + (1 if datos.get("ganador") else 0))
                datos["municipio"] = registro.get("municipio")
                datos["provincia"] = registro.get("provincia")
                resultado.append(datos)
        resultado.sort(key=lambda d: (-d["prioridad"], d["dias_para_aniversario"],
                                      d.get("titulo") or ""))
        return resultado


def cargar_registros(carpeta_datos, latest=None):
    registros = []
    for ruta in sorted(glob.glob(os.path.join(carpeta_datos, "historico_eventos", "*.json"))):
        with open(ruta, encoding="utf-8") as fichero:
            registros.extend(json.load(fichero).values())
    try:
        with open(os.path.join(carpeta_datos, "adjudicaciones.json"), encoding="utf-8") as fichero:
            registros.extend(json.load(fichero).values())
    except (OSError, ValueError):
        pass
    if latest:
        registros.extend(latest.get("licitaciones", []))
    # Primero lo más reciente, para que una misma licitación se quede con su última versión.
    registros.sort(key=lambda r: r.get("actualizado") or "", reverse=True)
    return registros


def indice_desde(carpeta_datos, latest=None):
    return Indice(cargar_registros(carpeta_datos, latest))
