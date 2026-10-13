"""Histórico de licitaciones de eventos a partir de los ficheros comprimidos de PLACSP.

La Plataforma publica, además de los feeds del día, un zip por mes (y uno por año para los años
cerrados) con todos los Atom de ese periodo. De ahí sale el histórico que alimenta los precedentes
(«el año pasado lo ganó X por Y €») y el aviso de lo que va a salir.

Uso:
  python -m foco.historico probar 202510 2025          # ¿existen los zips? ¿cuánto pesan?
  python -m foco.historico cargar --periodo 202510 --feed estado --salida parcial
  python -m foco.historico unir parcial --salida data/historico_eventos

`cargar` descarga el zip a disco por partes, lee cada Atom y guarda solo las licitaciones de
eventos, con su fecha de publicación y su resultado. `unir` junta los parciales en un fichero
por periodo, quedándose con la versión más reciente de cada licitación.
"""

import argparse
import glob
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

from .comun import es_de_eventos
from .placsp import parsear_feed

ZIPS = {
    "estado": ("PLACSP", "https://contrataciondelestado.es/sindicacion/sindicacion_643/"
                         "licitacionesPerfilesContratanteCompleto3_{periodo}.zip"),
    "agregadas": ("PLACSP (plataformas autonómicas)",
                  "https://contrataciondelestado.es/sindicacion/sindicacion_1044/"
                  "PlataformasAgregadasSinMenores_{periodo}.zip"),
}
CABECERAS = {"User-Agent": "foco-datos/1.0 (+https://focolicitaciones.wordpress.com)"}
CAMPOS = ("id", "expediente", "titulo", "organo", "municipio", "provincia", "nuts", "estado",
          "presupuesto_sin_iva", "valor_estimado", "procedimiento", "cpv", "fecha_limite",
          "url", "publicada", "actualizado", "resultados")


def aviso(texto):
    """Imprime y, dentro de GitHub Actions, deja una anotación legible desde la API."""
    print(texto, flush=True)
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::notice title=foco::{texto}", flush=True)


def probar(periodos, abrir=urllib.request.urlopen):
    for periodo in periodos:
        for clave, (_, plantilla) in ZIPS.items():
            url = plantilla.format(periodo=periodo)
            peticion = urllib.request.Request(url, method="HEAD", headers=CABECERAS)
            try:
                with abrir(peticion, timeout=60) as respuesta:
                    tamano = int(respuesta.headers.get("Content-Length") or 0)
                    aviso(f"{periodo} {clave}: {respuesta.status} {tamano / 1e6:.0f} MB")
            except urllib.error.HTTPError as error:
                aviso(f"{periodo} {clave}: HTTP {error.code}")
            except OSError as error:
                aviso(f"{periodo} {clave}: error {error!r}")


def descargar_a_disco(url, destino, abrir=urllib.request.urlopen, trozo=1 << 20):
    inicio = time.monotonic()
    leidos = 0
    siguiente_aviso = 50e6
    with abrir(urllib.request.Request(url, headers=CABECERAS), timeout=300) as respuesta, \
            open(destino, "wb") as fichero:
        while True:
            bloque = respuesta.read(trozo)
            if not bloque:
                break
            fichero.write(bloque)
            leidos += len(bloque)
            if leidos >= siguiente_aviso:
                velocidad = leidos / max(time.monotonic() - inicio, 1) / 1e6
                print(f"  {leidos / 1e6:.0f} MB ({velocidad:.1f} MB/s)", file=sys.stderr, flush=True)
                siguiente_aviso += 50e6
    return leidos


def compactar(lic, fuente):
    registro = {campo: lic.get(campo) for campo in CAMPOS}
    registro["fuente"] = fuente
    return registro


def fusionar(previo, nuevo):
    """La versión más reciente manda; la fecha de publicación es la más antigua conocida y el
    resultado es el último que exista."""
    if previo is None:
        return nuevo
    reciente, antigua = ((nuevo, previo) if (nuevo.get("actualizado") or "")
                         >= (previo.get("actualizado") or "") else (previo, nuevo))
    fusion = dict(reciente)
    fechas = [f for f in (previo.get("publicada"), nuevo.get("publicada")) if f]
    fusion["publicada"] = min(fechas) if fechas else None
    if not fusion.get("resultados"):
        fusion["resultados"] = antigua.get("resultados") or []
    return fusion


def leer_zip(ruta, fuente):
    eventos = {}
    with zipfile.ZipFile(ruta) as archivo:
        nombres = [n for n in archivo.namelist() if n.endswith(".atom")]
        for numero, nombre in enumerate(nombres, 1):
            try:
                licitaciones, _ = parsear_feed(archivo.read(nombre))
            except Exception as error:  # un Atom roto no tumba el periodo
                print(f"  {nombre}: {error!r}", file=sys.stderr)
                continue
            for lic in licitaciones:
                if not es_de_eventos(lic["titulo"], lic["cpv"])[0]:
                    continue
                clave = lic["id"] or lic["url"]
                eventos[clave] = fusionar(eventos.get(clave), compactar(lic, fuente))
            if numero % 100 == 0:
                print(f"  {numero}/{len(nombres)} ficheros, {len(eventos)} de eventos",
                      file=sys.stderr, flush=True)
    return eventos


def cargar(periodo, feed, salida, abrir=urllib.request.urlopen):
    fuente, plantilla = ZIPS[feed]
    url = plantilla.format(periodo=periodo)
    os.makedirs(salida, exist_ok=True)
    with tempfile.TemporaryDirectory() as carpeta:
        ruta = os.path.join(carpeta, "periodo.zip")
        print(f"Descargando {url}", file=sys.stderr, flush=True)
        inicio = time.monotonic()
        tamano = descargar_a_disco(url, ruta, abrir=abrir)
        aviso(f"{periodo} {feed}: {tamano / 1e6:.0f} MB en {time.monotonic() - inicio:.0f} s")
        eventos = leer_zip(ruta, fuente)
    destino = os.path.join(salida, f"{periodo}-{feed}.json")
    with open(destino, "w", encoding="utf-8") as fichero:
        json.dump(eventos, fichero, ensure_ascii=False)
    aviso(f"{periodo} {feed}: {len(eventos)} licitaciones de eventos")
    return eventos


def unir(carpetas, salida):
    """Junta los parciales (periodo-feed.json) en un fichero por periodo."""
    por_periodo = {}
    for carpeta in carpetas:
        for ruta in sorted(glob.glob(os.path.join(carpeta, "**", "*.json"), recursive=True)):
            periodo = os.path.basename(ruta).split("-", 1)[0]
            with open(ruta, encoding="utf-8") as fichero:
                parcial = json.load(fichero)
            destino = por_periodo.setdefault(periodo, {})
            for clave, registro in parcial.items():
                destino[clave] = fusionar(destino.get(clave), registro)
    os.makedirs(salida, exist_ok=True)
    for periodo, eventos in por_periodo.items():
        ruta = os.path.join(salida, f"{periodo}.json")
        try:
            with open(ruta, encoding="utf-8") as fichero:
                existentes = json.load(fichero)
        except (OSError, ValueError):
            existentes = {}
        for clave, registro in eventos.items():
            existentes[clave] = fusionar(existentes.get(clave), registro)
        with open(ruta, "w", encoding="utf-8") as fichero:
            json.dump(existentes, fichero, ensure_ascii=False, indent=0, sort_keys=True)
        aviso(f"{periodo}: {len(existentes)} licitaciones de eventos en total")


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="orden", required=True)
    p_probar = sub.add_parser("probar")
    p_probar.add_argument("periodos", nargs="+")
    p_cargar = sub.add_parser("cargar")
    p_cargar.add_argument("--periodo", required=True)
    p_cargar.add_argument("--feed", choices=sorted(ZIPS), required=True)
    p_cargar.add_argument("--salida", default="parcial")
    p_unir = sub.add_parser("unir")
    p_unir.add_argument("carpetas", nargs="+")
    p_unir.add_argument("--salida", default="data/historico_eventos")
    args = parser.parse_args(argv)
    if args.orden == "probar":
        probar(args.periodos)
    elif args.orden == "cargar":
        cargar(args.periodo, args.feed, args.salida)
    else:
        unir(args.carpetas, args.salida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
