# foco-datos

Recogida diaria de licitaciones públicas y ayudas para empresas de eventos, espectáculos y producción técnica. Alimenta el boletín **Foco Licitaciones** (focolicitaciones.wordpress.com).

## Qué hace

Cada mañana laborable, GitHub Actions ejecuta `python -m foco.recoger`, que:

1. Lee los feeds Atom de la **Plataforma de Contratación del Sector Público** (licitaciones propias y de las plataformas autonómicas agregadas) de los últimos 3 días.
2. Consulta los **datos abiertos de contratación de la Generalitat de Catalunya** (licitaciones en plazo).
3. Busca convocatorias recientes en la **Base de Datos Nacional de Subvenciones** y en el sumario del **BOE**.
4. Filtra lo que interesa a una empresa de eventos (códigos CPV de eventos, espectáculos, sonido, iluminación festiva, carpas y atracciones, más palabras como cabalgata, Navidad o festival).
5. Guarda el resultado en `data/latest.json` y una copia en `data/historico/`.

Una fuente caída no detiene a las demás: el error queda anotado en `errores`.

## Edición del día

```
python -m foco.edicion data/latest.json          # candidatos agrupados por sección
python -m foco.plantilla curada.json --salida edicion.html   # HTML de la entrada
```

`curada.json` es la selección que se publica: secciones con las licitaciones elegidas, una línea «clave» por cada una y las ayudas abiertas.

## Pruebas

```
python -m unittest discover -s tests -t .
```

Solo librería estándar de Python. Las pruebas no tocan la red.

## Fuentes y licencias

Datos abiertos reutilizables de la PLACSP (Ministerio de Hacienda), de la Generalitat de Catalunya, del BOE y del Sistema Nacional de Publicidad de Subvenciones. Se cita la fuente y se enlaza siempre el anuncio oficial.
