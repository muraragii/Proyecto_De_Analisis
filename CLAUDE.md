# CLAUDE.md

Monorepo: `apps/api` (FastAPI + pandas) y `apps/web` (Next.js 16 + Recharts). Ver README.md.

## Comandos

- API tests: `cd apps/api && .venv/Scripts/python -m pytest`
- API dev: `cd apps/api && .venv/Scripts/python -m uvicorn app.main:app --reload --port 8000`
- Web: `cd apps/web && npm run dev | npm run lint | npm run build`

## Convenciones

- Código, comentarios, textos de UI y mensajes de error en **español**.
- **Multi-tenancy**: toda consulta de datos de negocio filtra por `tenant_id`
  (usar `get_dataset` / `get_dashboard` de `app/services.py`, nunca `session.get`
  directo). Todo endpoint nuevo necesita un test de aislamiento entre tenants.
- El motor de recomendación es puro (perfil → `ChartSpec`); el cálculo de datos
  vive en `recommender/aggregate.py`. No mezclar.
- Cada industria nueva: `Industry` en `recommender/industries.py` + dataset en
  `app/samples.py` + tests en `tests/test_recommender.py`.
- Frontend: colores solo vía tokens CSS de `globals.css` (paleta validada para
  daltonismo, modo claro/oscuro). Recharts recibe los colores resueltos con `useTheme`.
- Next.js 16: en páginas cliente usar `useParams()`; `params` en server components es una Promise.
