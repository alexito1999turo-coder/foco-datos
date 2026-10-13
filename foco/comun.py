"""Utilidades compartidas: descarga, normalización de texto y filtro de eventos."""

import re
import time
import unicodedata
import urllib.error
import urllib.request

USER_AGENT = "FocoDatos/1.0 (boletin de licitaciones de eventos; datos abiertos)"


def descargar(url, cabeceras=None, intentos=3, espera=4, timeout=90):
    """Descarga una URL con reintentos. Devuelve bytes."""
    ultimo_error = None
    for intento in range(intentos):
        try:
            peticion = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT, **(cabeceras or {})}
            )
            with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
                return respuesta.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            ultimo_error = error
            if intento < intentos - 1:
                time.sleep(espera * (intento + 1))
    raise ultimo_error


def normalizar(texto):
    """Minúsculas, sin acentos y con espacios simples."""
    if not texto:
        return ""
    texto = unicodedata.normalize("NFKD", str(texto))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower().replace("·", "").replace("’", "'")
    return re.sub(r"\s+", " ", texto).strip()


def a_numero(valor):
    """Convierte importes ('1234.5', '1.234,50') a float. None si no se puede."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip().replace("€", "").replace("EUR", "").strip()
    if not texto:
        return None
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto:
        texto = texto.replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


# --- Filtro de relevancia para empresas de eventos ---------------------------

# Prefijos CPV que por sí solos indican eventos, espectáculos o producción técnica.
CPV_EVENTOS = (
    "7995",    # organización de eventos, ferias, festivales y fiestas
    "923",     # servicios de entretenimiento, artísticos, pirotecnia, técnico de sonido
    "92000",   # servicios de esparcimiento, culturales y deportivos (genérico)
    "5131",    # instalación de equipos de sonido y vídeo
    "3234",    # micrófonos, altavoces y equipos de sonido
    "323212",  # equipo audiovisual
    "37535",   # atracciones de feria
    "395225",  # carpas y toldos
    "45237",   # construcción de escenarios
)

# CPV que no queremos aunque estén dentro de un prefijo anterior.
CPV_EXCLUIDOS = (
    "9235",    # juegos de azar y apuestas
)

# Expresiones que bastan para considerar el contrato de eventos (sobre texto normalizado).
PALABRAS_FUERTES = tuple(re.compile(p) for p in (
    r"\bcabalgatas?\b", r"\bcavalcad[ae]s?\b", r"\breyes magos\b", r"\breis mags\b",
    r"\bpapa noel\b", r"\bnavidad\b", r"\bnaviden[oa]s?\b", r"\bnadal\b",
    r"\bnadalen[ca]s?\b", r"\bnochevieja\b", r"\bcap d'any\b", r"\bfin de ano\b",
    r"\bcampanadas\b", r"\bcarnaval(es)?\b", r"\bcarnestoltes\b",
    r"\bfiestas? patronal(es)?\b", r"\bfiestas? mayor(es)?\b", r"\bfesta major\b",
    r"\bfestes majors\b", r"\bfiestas de\b", r"\bfestes de\b", r"\bfestejos?\b",
    r"\bverbenas?\b", r"\brevetll(a|es)\b", r"\bespectaculos?\b", r"\bespectacles?\b",
    r"\bconciertos?\b", r"\bconcerts?\b", r"\borquestas?\b", r"\bactuaciones musicales\b",
    r"\bactuacions musicals\b", r"\bmusica en (directo|vivo|viu|directe)\b",
    r"\bcharangas?\b", r"\bpirotecni\w*", r"\bfuegos artificiales\b",
    r"\bcastillos? de fuegos\b", r"\bfocs artificials\b", r"\bfestival(es|s)?\b",
    r"\bparques? infantil(es)? de\b", r"\bparcs? infantils? de\b", r"\bpista de hielo\b",
    r"\bpista de gel\b", r"\btobogan\b", r"\batracciones de feria\b", r"\batraccions\b",
    r"\banimacion infantil\b", r"\banimacio infantil\b", r"\banimacion de calle\b",
    r"\bsonido e iluminacion\b", r"\bso i illuminacio\b", r"\bsonorizacion\b",
    r"\bsonoritzacio\b", r"\biluminacion (festiva|ornamental|navidena|artistica)\b",
    r"\balumbrado (ornamental|festivo|navideno|artistico)\b",
    r"\benllumenat (de nadal|nadalenc|festiu|ornamental)\b", r"\billuminacio (festiva|nadalenca)\b",
    r"\bdrone show\b", r"\bespectaculo de drones\b", r"\bprogramacio(n)? cultural\b",
    r"\bferias? de\b", r"\bfires? de\b",
))

# Si el título solo encaja por ser obra o mantenimiento, lo descartamos salvo CPV de eventos.
PALABRAS_OBRA = (
    "obras de", "obra de", "rehabilitacion", "reforma de", "urbanizacion",
    "pavimentacion", "redaccion del proyecto", "mantenimiento del alumbrado publico",
    "alumbrado publico", "enllumenat public", "eficiencia energetica",
)


def cpv_limpio(codigo):
    """'92312000-1' -> '92312000'."""
    return re.sub(r"[^0-9]", "", str(codigo or "").split("-")[0])


def es_de_eventos(titulo, cpvs):
    """Devuelve (True/False, motivo). Prioriza CPV y usa palabras como respaldo."""
    cpvs = [cpv_limpio(c) for c in (cpvs or []) if cpv_limpio(c)]
    texto = normalizar(titulo)

    for cpv in cpvs:
        if cpv.startswith(CPV_EXCLUIDOS):
            continue
        if cpv.startswith(CPV_EVENTOS):
            return True, f"CPV {cpv}"

    es_obra = any(p in texto for p in PALABRAS_OBRA)
    for patron in PALABRAS_FUERTES:
        encontrado = patron.search(texto)
        if encontrado:
            if es_obra:
                return False, "obra o mantenimiento"
            return True, f"palabra «{encontrado.group(0)}»"
    return False, ""


# --- Etiquetas de procedimiento (códigos CODICE de PLACSP) ------------------

PROCEDIMIENTOS = {
    "1": "Abierto",
    "2": "Restringido",
    "3": "Negociado sin publicidad",
    "4": "Negociado con publicidad",
    "5": "Diálogo competitivo",
    "6": "Contrato menor",
    "7": "Derivado de acuerdo marco",
    "8": "Concurso de proyectos",
    "9": "Abierto simplificado",
    "10": "Asociación para la innovación",
    "11": "Derivado de asociación para la innovación",
    "12": "Basado en sistema dinámico de adquisición",
    "13": "Licitación con negociación",
    "100": "Normas internas",
    "999": "Otros",
}


def nombre_procedimiento(codigo):
    codigo = str(codigo or "").strip()
    if not codigo:
        return None
    return PROCEDIMIENTOS.get(codigo, codigo)
