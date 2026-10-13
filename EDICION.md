# Cómo se hace la edición diaria de Foco Licitaciones

Web y boletín: https://focolicitaciones.wordpress.com (WordPress.com, sitio 257926259).
Cada entrada publicada se envía por email a los suscriptores, así que **se publica una sola vez al día** y solo después de comprobarla.

## Para quién escribimos

Empresas pequeñas y medianas de eventos, espectáculos y producción técnica en España: organización de fiestas y cabalgatas, programación artística, sonido, iluminación y escenarios, carpas y estructuras, iluminación y decoración navideña, ferias, atracciones, mercados temáticos, pirotecnia y equipamiento escénico de teatros y auditorios. Quieren saber en dos minutos qué contratos pueden ganar esta semana.

## Pasos

1. `git pull` y comprobar que `data/latest.json` tiene `"fecha"` de hoy. Si no, la recogida aún no ha terminado: esperar y reintentar. Sin datos de hoy no se publica.
2. Candidatos: `python -m foco.edicion data/latest.json --fecha AAAA-MM-DD > candidatos.txt`. Cada línea trae días restantes, título, organismo, lugar, presupuesto, motivo del filtro e `id=`. Debajo, si existe, el precedente del año pasado (`↳ precedente: ...`). Al final, dos listas más: `proximas` (lo que salió el año pasado por estas fechas y este año aún no) y `adjudicaciones` (lo adjudicado en los últimos 7 días).
3. Leer la última edición publicada (posts.list, la más reciente) para no repetir las mismas licitaciones salvo como recordatorio en «Cierran esta semana».
4. Elegir y escribir `seleccion.json` (formato en `foco/componer.py`).
5. Montar: `python -m foco.componer seleccion.json --datos data/latest.json --salida edicion.html`. Imprime el `TITULO:` de la entrada. Si da error, corregir la selección; nunca saltarse la comprobación.
6. Revisar `edicion.html`: que no aparezca `None`, que cada licitación tenga su enlace oficial y que los plazos sean futuros.
7. Publicar con posts.create: `status` publish, `title` el TITULO, `content` el HTML tal cual, `excerpt` la intro, `categories` [158269] (Ediciones) y `tags` [276957, 2366, 1641964, 132379, 19762] (licitaciones, eventos, contratación pública, subvenciones, espectáculos). Comprobar `_content_warnings` y abrir el enlace devuelto.

## Qué entra

- Hasta 12 licitaciones y hasta 4 ayudas. Mejor 6 buenas que 12 flojas.
- Sí: lo que una empresa de eventos puede ejecutar o suministrar (ver «Para quién escribimos»).
- No: obras, mantenimiento de alumbrado público, limpieza, seguridad sola, catering o barras sin evento, gestión de piscinas o instalaciones deportivas, agencias de viajes y congresos de terceros, telefonía, seguros, transporte, formación, publicidad institucional, estudios y consultoría.
- No incluir lo que cierra hoy. Lo que cierra mañana solo si es muy claro, y en «Cierran esta semana».
- Prioridad: las marcadas NUEVA y las que cierran en 2 a 10 días. Las «siempre abiertas» (más de un año) casi nunca.
- Ayudas: solo si una empresa (pyme o autónomo) puede pedirla y está en plazo. Nada de premios, concursos, becas, cine o cortometrajes.

## Secciones, en este orden

1. **Cierran esta semana**: plazo en los próximos 7 días.
2. **Navidad y Reyes** (hasta el 6 de enero): cabalgatas, luces, belenes, Nochevieja, programación navideña.
3. **Más contratos abiertos**: el resto, primero las nuevas.
4. **Lo que viene** (`proximas` en seleccion.json, hasta 5): de la lista `proximas`, lo que más interesa al sector y aniversario más cercano. Es lo que nos diferencia: avisa antes de que salga.
5. **Se quedaron sin empresa** (`desiertos` en seleccion.json, hasta 4): de la lista `desiertos`, los de eventos más claros y con presupuesto que merezca la pena. Son una puerta abierta: el organismo puede adjudicarlos por negociado invitando a empresas.
6. **Quién ganó** (`adjudicaciones` en seleccion.json, hasta 5): de la lista `adjudicaciones`, las más relevantes que no hayan salido ya en una edición anterior.
7. Ayudas: van aparte en `ayudas` y salen al final.

Una sección vacía no se pone. El precedente de cada licitación y la «competencia habitual» de su tipo de contrato los añade `componer` solos; no hay que escribirlos.

## Cómo se escribe

- Español de España, tuteando, directo y sin bombo. Sin emojis ni exclamaciones.
- `intro`: una o dos frases con lo esencial del día (cuántos contratos, el más destacado, el plazo más cercano).
- `titulo`: claro y corto (máximo unos 90 caracteres), en castellano aunque el original esté en catalán, gallego o euskera. Conserva los nombres propios.
- `lugar`: municipio y, si no es obvio, la provincia entre paréntesis.
- `clave`: una frase, máximo 25 palabras, con el ángulo práctico. Solo con lo que dicen los datos (título, lotes, procedimiento, presupuesto, CPV); no se inventa nada que no esté ahí. Ejemplos: «Dos lotes: puedes ofertar solo al de sonido.» «Concesión: cobras de la taquilla, no del ayuntamiento.» «Contrato menor de importe bajo, adecuado para empresas locales.»
- Si el precedente dice algo útil (una sola oferta el año pasado, una baja muy alta, mismo ganador varios años), la `clave` puede comentarlo, siempre con las cifras que trae el candidato.
- `etiquetas`: opcionales, dos como mucho (Navidad, Sonido, Iluminación, Carpas, Programación, Fiestas...).
- Plazos, horas, importes, organismos, expedientes y enlaces **no se escriben a mano**: `componer` los toma de los datos.

## Límites

La publicación diaria es lo único que se hace sin preguntar. No se cambian páginas, ajustes, tema ni suscriptores; no se borra nada; no se aprueban ni contestan comentarios; no se envían otros correos ni se gasta dinero. Si algo falla, no se publica y se avisa.
