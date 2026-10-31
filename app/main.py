"""FastAPI service and same-origin, local-only administrator UI."""
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import get_db_path
from .demo import DEMOS
from .engine import TriageEngine
from .models import QueueAction, TicketIn, TriageOut
from .store import QueueStore

STATIC = Path(__file__).parent / 'static'


@asynccontextmanager
async def lifespan(app):
    app.state.engine = TriageEngine()
    app.state.store = QueueStore(get_db_path())
    if not app.state.store.list():
        for demo in DEMOS:
            app.state.store.add(demo, app.state.engine.triage(demo), is_demo=True)
        app.state.engine.reset_dedup()
    yield


app = FastAPI(title='Grand Mobile · Support Copilot', version='0.1.0', lifespan=lifespan,
              description='Локальный MVP. Черновики и статусы не отправляются в Grand Mobile.')
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost', '127.0.0.1', '[::1]', 'testserver'])


@app.middleware('http')
async def local_boundary(request: Request, call_next):
    origin = request.headers.get('origin')
    if request.method in {'POST', 'PATCH', 'DELETE', 'PUT'} and origin:
        if urlsplit(origin).netloc != request.headers.get('host'):
            return JSONResponse({'detail': 'Запросы изменения состояния разрешены только с этой страницы.'}, status_code=403)
    size = request.headers.get('content-length', '')
    if size.isdigit() and int(size) > 2_000_000:
        return JSONResponse({'detail': 'Размер запроса превышает 2 МБ.'}, status_code=413)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
    if request.url.path in {'/docs', '/redoc'}:
        # FastAPI's interactive reference uses its official CDN assets.
        del response.headers['Content-Security-Policy']
    return response


def predict(ticket: TicketIn, *, synthetic=False):
    try:
        return app.state.engine.triage(ticket.model_dump(), synthetic=synthetic)
    except ValueError as exc:
        raise HTTPException(422, detail='Некорректные данные или kind отсутствует в taxonomy.json.') from exc


@app.get('/health')
def health():
    return {'status': 'ok', 'mode': 'demo' if app.state.engine.taxonomy.get('demo') else 'case', 'rules_count': len(app.state.engine.rules), 'categories_count': len(app.state.engine.categories)}


@app.post('/triage', response_model=TriageOut)
def triage(ticket: TicketIn):
    return predict(ticket)


@app.get('/api/meta')
def meta():
    return {'taxonomy': app.state.engine.taxonomy, 'rules_count': len(app.state.engine.rules), 'mode': 'demo' if app.state.engine.taxonomy.get('demo') else 'case', 'ai': app.state.engine.ai.status()}


@app.get('/api/tickets')
def tickets():
    return app.state.store.list()


@app.post('/api/tickets', status_code=201)
def create_ticket(ticket: TicketIn):
    return app.state.store.add(ticket.model_dump(), predict(ticket))


@app.patch('/api/tickets/{item_id}')
def review_ticket(item_id: str, action: QueueAction):
    try:
        updated = app.state.store.update(item_id, action.action, action.draft_text)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(404, detail='Обращение не найдено.')
    return updated


@app.post('/api/tickets/{item_id}/reanalyze')
def reanalyze(item_id: str):
    item = next((t for t in app.state.store.list() if t['id'] == item_id), None)
    if not item:
        raise HTTPException(404, detail='Обращение не найдено.')
    if item['status'] != 'new':
        raise HTTPException(409, detail='Сохранённые правки защищены от замены повторным анализом.')
    try:
        return app.state.store.replace_analysis(item_id, predict(TicketIn.model_validate(item['ticket']), synthetic=item['is_demo']))
    except ValueError as exc:
        raise HTTPException(409, detail=str(exc)) from exc


@app.get('/', include_in_schema=False)
def index():
    return FileResponse(STATIC / 'index.html')


app.mount('/static', StaticFiles(directory=STATIC), name='static')
