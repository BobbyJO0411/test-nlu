import json,os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
from .engine import Recommender,DEFAULT_MODEL,ROOT

WEB_DIR=Path(__file__).resolve().parent/'web'

@asynccontextmanager
async def lifespan(app):
    app.state.engine=Recommender(backend=os.getenv('NLU_BACKEND','e5'),
        model_id=os.getenv('NLU_MODEL_ID',DEFAULT_MODEL),revision=os.getenv('NLU_MODEL_REVISION'),
        model_path=os.getenv('NLU_MODEL_PATH'))
    yield
app=FastAPI(title='상표 응답 추천 — 개발·평가용',lifespan=lifespan)
app.mount('/static',StaticFiles(directory=WEB_DIR),name='static')
class Query(BaseModel):
    query:str=Field(min_length=1,max_length=3000,pattern=r'.*\S.*')
    top_k:int=Field(default=3,ge=1,le=30)
@app.get('/health')
def health():
    return {'status':'ready','engine':app.state.engine.metadata,'expert_approval':'pending'}
@app.get('/',include_in_schema=False)
def index():
    return FileResponse(WEB_DIR/'index.html')
@app.get('/datasets')
def datasets():
    return {
        'questions':json.loads((ROOT/'data/questions_100.json').read_text(encoding='utf-8')),
        'templates':json.loads((ROOT/'data/templates.json').read_text(encoding='utf-8')),
    }
@app.post('/recommend')
def recommend(query:Query):
    result=app.state.engine.recommend(query.query,query.top_k)
    if os.getenv('NLU_MODE','template_direct')=='llm_select':
        from .llm import select
        result=select(query.query,result,os.getenv('NLU_LLM_MODEL','gpt-4.1-mini'))
    return result
