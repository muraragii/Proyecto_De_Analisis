# Contexto del proyecto: App de visualización de datos por tipo de negocio

## Idea central
App web (SaaS) que genera visualizaciones de datos (barras, líneas, pastel, dispersión, etc.)
de forma automática, adaptando el tipo de gráfico según:
1. El tipo de negocio/industria del usuario (ej. e-commerce, restaurante, clínica, etc.)
2. La estructura de la fuente de datos que se cargue

## Decisiones ya tomadas
- **Tipo de producto**: App web SaaS, multi-tenant (varios negocios/clientes usando la
  plataforma, con datos aislados por cuenta).
- **Fuentes de datos a soportar**: todas — archivos (CSV/Excel), conexión a bases de datos,
  y APIs de terceros (ej. Shopify, Google Analytics, Google Sheets).
- **Capacidad técnica**: se puede programar full-stack (frontend y backend). El código se
  generará con Claude Code.

## Motor de recomendación de visualización (el diferenciador del producto)
1. **Perfilado de datos**: al cargar una fuente, analizar tipos de columna (categórica,
   numérica, fecha, texto libre, geográfica), cardinalidad, nulos, distribución.
2. **Reglas de mapeo dato → gráfico** (heurísticas tipo Tableau "Show Me"):
   - 1 categórica + 1 numérica → barras
   - Serie temporal + numérica → líneas
   - Proporciones de un total (pocas categorías) → pastel/dona
   - 2 numéricas → dispersión (scatter)
   - Geolocalización → mapa
   - Múltiples métricas → KPIs + tabla
3. **Capa de "tipo de negocio"**: plantillas/presets por industria (ej. e-commerce prioriza
   ventas por producto, funnel de conversión, cohortes; restaurante prioriza ocupación,
   ticket promedio, horarios pico). Empezar con reglas heurísticas; más adelante se puede
   sumar un LLM para casos ambiguos.

## Arquitectura sugerida
- **Frontend**: React o Next.js + librería de charts (Recharts o Chart.js para lo estándar;
  D3 para visualizaciones custom más adelante).
- **Backend**: Node/Nest o Python/FastAPI (Python es cómodo para perfilado de datos con
  pandas).
- **Ingesta de datos**: parsers CSV/Excel (pandas, openpyxl), conectores DB (SQLAlchemy),
  conectores API (empezar incremental: 2-3 integraciones populares).
- **Datos**: Postgres para metadata/config/dashboards guardados; storage tipo S3 para
  archivos subidos; multi-tenancy diseñada desde el día uno (aislar datos por cuenta).

## MVP propuesto (fase 1)
1. Carga de CSV/Excel únicamente (dejar DB y APIs para fase 2)
2. Perfilado automático + motor de reglas heurísticas (sin LLM todavía)
3. 4-5 tipos de gráfico (barras, líneas, pastel, dispersión, tabla)
4. 2-3 plantillas de industria predefinidas
5. Dashboard guardable y compartible (link)

## Riesgos / decisiones pendientes
- Modelo de monetización (freemium, por dashboards, por volumen de datos)
- Seguridad y privacidad de datos de negocio reales (encriptación desde temprano)
- Diferenciación frente a Looker Studio, Metabase, Tableau — probablemente la ventaja
  esté en simplicidad + personalización por industria, no en potencia analítica bruta

## Entorno de desarrollo (ya definido)
- Git
- Node.js (LTS)
- Python 3.11+
- Claude Code (`npm install -g @anthropic-ai/claude-code`)
- VS Code — instalado con "Configuración del usuario" (sin permisos de administrador)
- Docker Desktop (opcional, para Postgres local)
- Proveedor de hosting a definir (Vercel o Railway sugeridos)

## Próximo paso sugerido
Definir la estructura inicial del proyecto (carpetas, stack definitivo) y armar el primer
prompt para Claude Code.
