# Proyecto Análisis

SaaS que genera visualizaciones automáticas adaptadas al **tipo de negocio** y a la
**estructura de los datos** que sube cada cliente. Contexto completo y decisiones de
producto en [docs/contexto-proyecto-visualizaciones.md](docs/contexto-proyecto-visualizaciones.md).

## Estructura

```
apps/
  api/                 FastAPI + pandas (Python 3.11+)
    app/
      ingestion/       lectura de CSV/Excel y almacenamiento (local → S3)
      profiling/       tipo semántico de cada columna + estadísticas
      recommender/     reglas dato→gráfico, presets por industria, agregación
      routes/          endpoints HTTP
      models.py        tenants, datasets, dashboards (todo con tenant_id)
    tests/
  web/                 Next.js + TypeScript + Tailwind + Recharts
samples/               datos de ejemplo por industria para probar a mano
docs/
```

## Cómo correrlo en local

**API** (terminal 1):

```powershell
cd apps\api
python -m venv .venv                     # solo la primera vez
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

Documentación interactiva: http://localhost:8000/docs

**Web** (terminal 2):

```powershell
cd apps\web
npm install                              # solo la primera vez
npm run dev
```

Abrir http://localhost:3000 y subir cualquier archivo de `samples/`.

**Tests:**

```powershell
cd apps\api; .venv\Scripts\python -m pytest
cd apps\web; npm run lint; npm run build
```

## Cómo funciona el motor de recomendación

1. **Perfilado** (`profiling/profiler.py`): cada columna recibe un tipo semántico:
   numérica, categórica, fecha, sí/no, identificador o texto libre. Detecta fechas y
   montos escritos como texto (`"$1,234.50"`, `"1.234,50"`, `dd/mm/aaaa`), IDs y
   códigos enteros que no deben sumarse (mesa, año, código postal).
2. **Reglas genéricas** (`recommender/rules.py`): fecha + métrica → línea;
   categoría + métrica → barras; pocas categorías → dona; 2 métricas → dispersión;
   métricas → KPIs; siempre una tabla.
3. **Presets de industria** (`recommender/industries.py`): cada industria define
   *roles* (ventas, producto, médico…) que se buscan por palabras clave en los
   nombres de columna, y *plantillas* de gráficos con títulos de negocio. La industria
   se detecta sola o la elige el usuario.
4. **Selección** (`recommender/engine.py`): se combinan, se deduplican y se
   priorizan por score (máx. 12 gráficos).

### Reglas de corrección analítica

Verificadas con tests de referencia (`tests/test_golden.py`, respuestas calculadas a mano):

| Regla | Evita |
|---|---|
| Filas "TOTAL" / "Gran total" se eliminan al cargar | Duplicar las ventas |
| Métricas no aditivas (precio unitario con cantidad, %, tasas, calificaciones) se promedian | "Total de precio unitario" |
| Clave de transacción (ticket, pedido, folio) como unidad de análisis | Ticket promedio por línea en vez de por cuenta |
| Día de la semana / hora como promedio por día del calendario | Que el lunes "gane" por aparecer 13 veces vs. 12 |
| Series de tiempo completas (periodos sin datos = 0) | Que un día sin ventas desaparezca |
| Primer/último periodo incompleto marcado (línea punteada) | Leer una semana a medias como caída |
| Orden día/mes deducido de los datos (25/04 ⇒ día/mes) | Confundir 3 de abril con 4 de marzo |
| Avisos: valores ilegibles, duplicados, atípicos, negativos, vacíos | Errores silenciosos |

Industrias incluidas: **e-commerce**, **restaurante** y **clínica**. Para añadir otra,
basta con definir un `Industry` en `industries.py` y agregar un dataset de ejemplo en
`app/samples.py` con su test.

## Estado del MVP

- [x] Carga de CSV / Excel (detección de separador y codificación)
- [x] Perfilado automático + motor de reglas
- [x] 6 tipos de visualización: barras, líneas, dona, dispersión, KPI, tabla
- [x] 3 plantillas de industria con detección automática
- [x] Dashboards guardables y compartibles por enlace (revocable)
- [x] Aislamiento por organización en todas las consultas
- [x] Registro e inicio de sesión (correo + contraseña)

## Autenticación

- Al registrarse se crean el usuario y su **organización** (el negocio), con rol
  `owner`. Todos los datos (datasets, dashboards) pertenecen a la organización.
- Contraseñas con hash **Argon2**. Bloqueo de 15 min tras 5 intentos fallidos.
- Sesión en cookie `httpOnly` + `SameSite=Lax`; en la base solo se guarda el hash del
  token, y cerrar sesión la revoca en el servidor.
- En producción: `APP_COOKIE_SECURE=true` (solo HTTPS) y servir la web y la API bajo el
  mismo dominio (p. ej. `app.midominio.com` y `api.midominio.com`) para que la cookie
  se comparta.

## Pendiente antes de producción

- **Invitar al equipo** a una organización (el modelo `Membership` ya lo soporta).
- **Recuperar contraseña** y verificación de correo (requiere un proveedor de email,
  p. ej. Resend).
- Login con Google (opcional).
- **Migraciones con Alembic** en lugar de `create_all` al arrancar.
- **Postgres** en lugar de SQLite (solo cambia `APP_DATABASE_URL`) y **S3** para
  archivos (implementar `Storage` en `ingestion/storage.py`).
- **Caché de DataFrames**: hoy se relee el archivo en cada petición.
- Encriptación de archivos en reposo.
