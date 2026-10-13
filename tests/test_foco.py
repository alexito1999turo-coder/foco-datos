import json
import os
import tempfile
import unittest
from datetime import date

from foco import ayudas, catalunya, componer, placsp, recoger
from foco.comun import a_numero, es_de_eventos, normalizar
from foco.edicion import agrupar, euros, fecha_corta
from foco.plantilla import fecha_larga, renderizar

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
HOY = date(2026, 10, 13)


def leer(nombre, modo="rb"):
    with open(os.path.join(FIXTURES, nombre), modo) as fichero:
        return fichero.read()


class FiltroEventos(unittest.TestCase):
    def test_cpv_de_eventos(self):
        self.assertTrue(es_de_eventos("Servicio X", ["92312000-1"])[0])
        self.assertTrue(es_de_eventos("Algo", ["79952100"])[0])

    def test_cpv_de_apuestas_no_cuenta(self):
        self.assertFalse(es_de_eventos("Gestión de apuestas", ["92351000"])[0])

    def test_palabras(self):
        self.assertTrue(es_de_eventos("Organización de la Cavalcada de Reis 2027", [])[0])
        self.assertTrue(es_de_eventos("Contratación de orquestas para las fiestas", ["79000000"])[0])
        self.assertTrue(es_de_eventos("Il·luminació festiva de Nadal", ["31527200"])[0])

    def test_no_confunde_palabras_parecidas(self):
        self.assertFalse(es_de_eventos("Plazas concertadas de residencia", ["85000000"])[0])
        self.assertFalse(es_de_eventos("Mantenimiento del alumbrado público", ["50232100"])[0])

    def test_obras_se_descartan(self):
        self.assertFalse(es_de_eventos("Obras de reforma del teatro municipal", ["45212000"])[0])

    def test_utilidades(self):
        self.assertEqual(normalizar("  Música   EN Viu "), "musica en viu")
        self.assertEqual(a_numero("1.234,50"), 1234.5)
        self.assertEqual(a_numero("133206"), 133206.0)
        self.assertIsNone(a_numero(""))
        self.assertEqual(euros(62282.85), "62.282,85 €")
        self.assertEqual(fecha_corta("2026-10-16"), "vie 16 oct")
        self.assertEqual(fecha_larga("2026-10-13"), "martes, 13 de octubre de 2026")


class Placsp(unittest.TestCase):
    def test_parsea_feed(self):
        licitaciones, siguiente = placsp.parsear_feed(leer("placsp.atom"))
        self.assertTrue(siguiente.endswith("_20261012_210000.atom"))
        self.assertEqual(len(licitaciones), 4)
        motril = licitaciones[0]
        self.assertEqual(motril["estado"], "PUB")
        self.assertEqual(motril["organo"], "Alcaldia del Ayuntamiento de Motril")
        self.assertEqual(motril["presupuesto_sin_iva"], 133206.0)
        self.assertEqual(motril["valor_estimado"], 532824.0)
        self.assertEqual(motril["procedimiento"], "Abierto")
        self.assertEqual(motril["fecha_limite"], "2026-10-26")
        self.assertEqual(motril["hora_limite"], "23:59")
        self.assertEqual(motril["provincia"], "Granada")
        self.assertIn("idEvl=AAA", motril["url"])
        santurtzi = licitaciones[3]
        self.assertEqual(santurtzi["fecha_limite"], "2026-10-16")
        self.assertEqual(santurtzi["hora_limite"], "13:00")
        self.assertEqual([l["presupuesto_sin_iva"] for l in santurtzi["lotes"]], [26300.0, 35982.85])
        self.assertIn("92331210", santurtzi["cpv"])

    def test_recoger_filtra_y_para_a_tiempo(self):
        pedidas = []
        ficheros = {
            placsp.FEEDS["PLACSP"]: leer("placsp.atom"),
            "https://contrataciondelestado.es/sindicacion/sindicacion_643/"
            "licitacionesPerfilesContratanteCompleto3_20261012_210000.atom": leer("placsp_anterior.atom"),
        }

        def falso(url, *args, **kwargs):
            pedidas.append(url)
            if url in ficheros:
                return ficheros[url]
            return leer("placsp_anterior.atom").replace(b'rel="next"', b'rel="prev"')

        seleccion, informe, cerradas = placsp.recoger(dias=3, hoy=HOY, descargador=falso)
        titulos = [l["titulo"] for l in seleccion]
        self.assertEqual(len(seleccion), 2)
        self.assertIn("Realización del programa Parque Infantil de Navidad 2026-2027", titulos)
        self.assertTrue(any("Cabalgata" in t for t in titulos))
        self.assertFalse(any("Versión antigua" in t for t in titulos))
        self.assertEqual(seleccion[0]["fecha_limite"], "2026-10-16")
        self.assertEqual(informe["PLACSP"]["ficheros"], 2)
        self.assertEqual(informe["PLACSP"]["parada"], "límite alcanzado")
        self.assertIn("https://contrataciondelestado.es/sindicacion/licitacionesPerfilContratante/1003",
                      cerradas)

    def test_relleno_continua_en_la_siguiente_ejecucion(self):
        base = "https://contrataciondelestado.es/sindicacion/sindicacion_643/"
        anterior = base + "licitacionesPerfilesContratanteCompleto3_20261012_210000.atom"
        mas_antiguo = base + "licitacionesPerfilesContratanteCompleto3_20261001_000000.atom"
        reloj = [0]
        pedidas = []

        def falso(url, *args, **kwargs):
            reloj[0] += 100
            pedidas.append(url)
            if url == placsp.FEEDS["PLACSP"]:
                return leer("placsp.atom")
            if url == anterior:
                return leer("placsp_anterior.atom")
            return leer("placsp_anterior.atom").replace(b'rel="next"', b'rel="prev"')

        _, informe, _ = placsp.recoger(dias=30, hoy=HOY, descargador=falso, limite_segundos=150,
                                       reloj=lambda: reloj[0])
        primero = informe["PLACSP"]
        self.assertEqual(primero["parada"], "tiempo agotado")
        self.assertEqual(primero["siguiente"], mas_antiguo)
        self.assertTrue(primero["relleno_pendiente"])

        reloj[0] = 0
        pedidas.clear()
        _, informe, _ = placsp.recoger(dias=3, hoy=HOY, descargador=falso, limite_segundos=1000,
                                       reloj=lambda: reloj[0], estado_previo=informe)
        segundo = informe["PLACSP"]
        self.assertIn(mas_antiguo, pedidas)
        self.assertIsNone(segundo["siguiente"])
        self.assertFalse(segundo["relleno_pendiente"])
        self.assertEqual(segundo["objetivo"], "2026-09-13T00:00")

    def test_para_si_se_agota_el_tiempo(self):
        momentos = iter(range(0, 10000, 100))
        _, informe, _ = placsp.recoger(dias=30, hoy=HOY, limite_segundos=150,
                                       descargador=lambda url, *a, **k: leer("placsp.atom"),
                                       reloj=lambda: next(momentos))
        self.assertEqual(informe["PLACSP"]["parada"], "tiempo agotado")
        self.assertEqual(informe["PLACSP"]["ficheros"], 1)


class Catalunya(unittest.TestCase):
    def test_recoger(self):
        seleccion, informe = catalunya.recoger(hoy=HOY, descargador=lambda url: leer("catalunya.json"))
        self.assertEqual(informe["filas"], 4)
        self.assertEqual([l["expediente"] for l in seleccion], ["CON.EXP2026000074", "C-39/2026"])
        manresa = seleccion[0]
        self.assertEqual(manresa["hora_limite"], "23:59")
        self.assertEqual(manresa["cpv"], ["37535000"])
        self.assertTrue(manresa["url"].startswith("https://contractaciopublica.cat/"))

    def test_url_filtra_por_plazo(self):
        url = catalunya.construir_url(HOY)
        self.assertIn("2026-10-13T00%3A00%3A00", url)
        self.assertIn("Anunci+de+licitaci%25", url)


class Ayudas(unittest.TestCase):
    def setUp(self):
        self.datos = json.loads(leer("bdns.json"))

    def test_evaluar_convocatorias(self):
        abierta = ayudas.evaluar_convocatoria(self.datos["detalle_abierta"], HOY)
        self.assertEqual(abierta["fin"], "2026-11-10")
        self.assertTrue(abierta["url"].endswith("/934700"))
        self.assertIsNone(ayudas.evaluar_convocatoria(self.datos["detalle_entidades"], HOY))
        self.assertIsNone(ayudas.evaluar_convocatoria(self.datos["detalle_cerrada"], HOY))

    def test_descarta_premios_y_cine(self):
        concurso = {**self.datos["detalle_abierta"],
                    "descripcion": "Concurso de fotografía del festival de jazz"}
        cine = {**self.datos["detalle_abierta"],
                "descripcion": "Subvenciones para la realización de cortometrajes"}
        self.assertIsNone(ayudas.evaluar_convocatoria(concurso, HOY))
        self.assertIsNone(ayudas.evaluar_convocatoria(cine, HOY))

    def test_recoger_bdns(self):
        def falso(url, *args, **kwargs):
            if "busqueda" in url:
                return json.dumps(self.datos["busqueda"]).encode()
            return json.dumps(self.datos["detalle_abierta"]).encode()

        seleccion, informe = ayudas.recoger_bdns(hoy=HOY, descargador=falso, pausa=0)
        self.assertEqual(informe["candidatas"], 1)
        self.assertEqual(len(seleccion), 1)

    def test_recoger_boe(self):
        def falso(url, *args, **kwargs):
            if url.endswith("20261013"):
                return leer("boe.json")
            raise OSError("sin BOE")

        seleccion, informe = ayudas.recoger_boe(hoy=HOY, dias=3, descargador=falso)
        self.assertEqual(len(seleccion), 1)
        self.assertEqual(seleccion[0]["organo"], "MINISTERIO DE CULTURA")
        self.assertTrue(seleccion[0]["url"].endswith("BOE-B-2026-32590.pdf"))


class Acumulacion(unittest.TestCase):
    def _lic(self, ident, fecha, fuente="PLACSP", titulo="Cabalgata de Reyes"):
        return {"id": ident, "fuente": fuente, "titulo": titulo, "organo": "Ayto",
                "expediente": ident, "fecha_limite": fecha, "estado": "PUB"}

    def test_conserva_abiertas_quita_cerradas_y_caducadas(self):
        with tempfile.TemporaryDirectory() as carpeta:
            previo = {"licitaciones": [
                {**self._lic("a", "2026-10-30"), "primera_vez": "2026-10-01"},
                self._lic("b", "2026-10-20"),
                self._lic("c", "2026-10-10"),
                {**self._lic("cat1", "2026-10-25", fuente="Generalitat de Catalunya")},
            ], "ayudas": [
                {"codigo": "x", "fin": "2026-11-01", "primera_vez": "2026-10-05"},
                {"codigo": "y", "fin": "2026-10-01"},
            ]}
            with open(os.path.join(carpeta, "latest.json"), "w", encoding="utf-8") as fichero:
                json.dump(previo, fichero)
            nueva = self._lic("d", "2026-11-02", titulo="Festival de música")
            fuentes = {
                "placsp": lambda: ([nueva], {}, ["b"]),
                "catalunya": lambda: (_ for _ in ()).throw(OSError("caída")),
                "bdns": lambda: ([{"codigo": "z", "fin": "2026-12-01"}], {}),
            }
            resultado = recoger.ejecutar(carpeta, hoy=HOY, fuentes=fuentes)
        ids = {l["id"] for l in resultado["licitaciones"]}
        self.assertEqual(ids, {"a", "d", "cat1"})
        por_id = {l["id"]: l for l in resultado["licitaciones"]}
        self.assertEqual(por_id["a"]["primera_vez"], "2026-10-01")
        self.assertEqual(por_id["d"]["primera_vez"], "2026-10-13")
        self.assertEqual({a["codigo"] for a in resultado["ayudas"]}, {"x", "z"})


class EdicionCompleta(unittest.TestCase):
    def test_ejecutar_y_renderizar(self):
        lic_cat, _ = catalunya.recoger(hoy=HOY, descargador=lambda url: leer("catalunya.json"))
        fuentes = {
            "catalunya": lambda: (lic_cat, {"filas": 4}),
            "placsp": lambda: (_ for _ in ()).throw(OSError("caída")),
        }
        with tempfile.TemporaryDirectory() as carpeta:
            resultado = recoger.ejecutar(carpeta, hoy=HOY, fuentes=fuentes)
            self.assertTrue(os.path.exists(os.path.join(carpeta, "latest.json")))
            self.assertTrue(os.path.exists(os.path.join(carpeta, "historico", "2026-10-13.json")))
        self.assertEqual(resultado["errores"][0]["fuente"], "placsp")
        secciones = agrupar(resultado, HOY)
        self.assertEqual(len(secciones["navidad_reyes"]), 2)
        curada = {
            "fecha": "2026-10-13",
            "intro": "Buenos días.",
            "secciones": [{"titulo": "Navidad y Reyes", "items": [
                {**secciones["navidad_reyes"][0], "lugar": "Manresa", "clave": "Tobogán con taquilla.",
                 "etiquetas": ["Navidad"], "fecha_prudente": True}]}],
            "ayudas": [{"titulo": "Ayudas a festivales", "organo": "Xunta", "fin": "2026-11-10",
                        "clave": "Hasta 60 %.", "url": "https://example.org/a?b=1&c=2"}],
        }
        html = renderizar(curada)
        self.assertIn("Martes, 13 de octubre de 2026", html)
        self.assertIn("43.261,39 € sin IVA", html)
        self.assertIn("Fecha prudente", html)
        self.assertIn("quedan 8 días", html)
        self.assertIn("a?b=1&amp;c=2", html)
        self.assertNotIn("23:59 h", html)


class Componer(unittest.TestCase):
    DATOS = {
        "licitaciones": [
            {"id": "a", "titulo": "Original", "organo": "Ayto", "fecha_limite": "2026-10-20",
             "hora_limite": "14:00", "presupuesto_sin_iva": 1000.0, "url": "https://x/a",
             "expediente": "E1", "cpv": ["92312000"]},
            {"id": "b", "titulo": "Cerrada", "fecha_limite": "2026-10-01"},
        ],
        "ayudas": [{"codigo": "9", "titulo": "Ayuda", "organo": "Xunta", "fin": "2026-11-10",
                    "url": "https://y/9"}],
    }

    def test_toma_los_datos_del_json_y_lo_editorial_de_la_seleccion(self):
        seleccion = {"fecha": "2026-10-13", "intro": "Hola.", "secciones": [
            {"titulo": "Cierran pronto", "items": [
                {"id": "a", "titulo": "Limpio", "clave": "Clave.", "presupuesto_sin_iva": 1}]}],
            "ayudas": [{"codigo": "9", "clave": "Hasta 60 %."}]}
        curada, titulo = componer.componer(seleccion, self.DATOS)
        item = curada["secciones"][0]["items"][0]
        self.assertEqual(item["titulo"], "Limpio")
        self.assertEqual(item["presupuesto_sin_iva"], 1000.0)
        self.assertEqual(item["url"], "https://x/a")
        self.assertEqual(curada["ayudas"][0]["fin"], "2026-11-10")
        self.assertEqual(titulo, "Foco · martes 13 de octubre: 1 contrato abierto y 1 ayuda")
        self.assertIn("1.000,00 € sin IVA", renderizar(curada))

    def test_rechaza_ids_desconocidos_y_cerrados(self):
        for ident in ("zzz", "b"):
            seleccion = {"fecha": "2026-10-13", "secciones": [{"titulo": "X", "items": [{"id": ident}]}]}
            with self.assertRaises(componer.SeleccionInvalida):
                componer.componer(seleccion, self.DATOS)


if __name__ == "__main__":
    unittest.main()
