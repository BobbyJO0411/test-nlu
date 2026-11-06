from __future__ import annotations
import hashlib,json,time,os
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('HF_HOME',str(ROOT.parent/'nlu-model-cache'))
os.environ.setdefault('HF_XET_CACHE',str(ROOT.parent/'nlu-model-cache/xet'))
os.environ.setdefault('TOKENIZERS_PARALLELISM','false')
os.environ.setdefault('HF_HUB_DISABLE_XET','1')
DEFAULT_MODEL='intfloat/multilingual-e5-small'

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

class Recommender:
    """No gold labels are loaded here. E5 never silently falls back to baseline."""
    def __init__(self, backend='e5', model_id=DEFAULT_MODEL, revision=None, model_path=None):
        self.templates=json.loads((ROOT/'data/templates.json').read_text(encoding='utf-8'))
        self.backend=backend
        passages=[t['representative_query']+' '+t['answer'] for t in self.templates]
        if backend=='e5':
            import torch
            from huggingface_hub import snapshot_download
            from sentence_transformers import SentenceTransformer
            torch.set_num_threads(2)
            if model_path:
                path=Path(model_path).resolve()
                manifest=json.loads((path/'verified_model.json').read_text(encoding='utf-8'))
                if manifest['model_id']!=model_id:
                    raise ValueError('Model identity differs from recorded manifest')
                for file,sha in manifest['files'].items():
                    if digest(path/file)!=sha:
                        raise ValueError('Model file hash mismatch: '+file)
                resolved=manifest['revision']
            else:
                path=Path(snapshot_download(repo_id=model_id,revision=revision,
                    cache_dir=str(ROOT.parent/'nlu-model-cache'),
                    allow_patterns=['*.json','*.safetensors','*.txt','*.model','1_Pooling/*','README.md','LICENSE*'],
                    ignore_patterns=['onnx/*','openvino/*']))
                resolved=path.name
            if len(resolved)!=40 or any(c not in '0123456789abcdef' for c in resolved):
                raise ValueError('An exact downloaded model commit is required')
            if not model_path:
                for file in path.rglob('*'):
                    if not file.is_file():continue
                    blob=file.resolve().name
                    if len(blob)==64 and digest(file)!=blob:
                        raise ValueError('Upstream SHA256 mismatch: '+file.name)
                    if len(blob)==40:
                        content=file.read_bytes()
                        git_hash=hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()
                        if git_hash!=blob:raise ValueError('Upstream Git blob hash mismatch: '+file.name)
            self.model=SentenceTransformer(str(path),device='cpu',trust_remote_code=False)
            self.model.max_seq_length=512
            self.index=self.model.encode(['passage: '+p for p in passages],
                normalize_embeddings=True,convert_to_numpy=True,batch_size=8,show_progress_bar=False)
            files={str(f.relative_to(path)):digest(f) for f in path.rglob('*') if f.is_file() and f.name!='verified_model.json'}
            self.metadata={'backend':'e5','model_id':model_id,'revision':resolved,
                'dimension':int(self.index.shape[1]),'max_seq_length':512,
                'query_prefix':'query: ','passage_prefix':'passage: ','model_files_sha256':files,
                'note':'E5 family supports Korean; specific E5-Ko acceptance requires test-agency confirmation'}
        elif backend=='baseline':
            from sklearn.feature_extraction.text import TfidfVectorizer
            self.model=TfidfVectorizer(analyzer='char',ngram_range=(2,5),sublinear_tf=True)
            self.index=self.model.fit_transform(passages)
            self.metadata={'backend':'baseline','model_id':'char-tfidf-2-5',
                'note':'Lexical baseline only. NOT E5, KoBERT or evidence of embedding NLU readiness.'}
        else:
            raise ValueError('Unsupported backend')
        self.metadata['templates_sha256']=digest(ROOT/'data/templates.json')

    def recommend(self, query, top_k=3):
        if not query or not query.strip():
            raise ValueError('Question must not be blank')
        if not 1<=top_k<=len(self.templates):
            raise ValueError('top_k outside template count')
        start=time.perf_counter()
        if self.backend=='e5':
            vector=self.model.encode(['query: '+query],normalize_embeddings=True,
                convert_to_numpy=True,show_progress_bar=False)
            scores=(vector@self.index.T)[0]
        else:
            vector=self.model.transform([query]); scores=(vector@self.index.T).toarray()[0]
        order=np.argsort(-scores,kind='stable')[:top_k]
        candidates=[{'rank':rank,'template_id':self.templates[int(i)]['template_id'],
            'score':float(scores[i]),'answer':self.templates[int(i)]['answer'],
            'source_ids':self.templates[int(i)]['source_ids']} for rank,i in enumerate(order,1)]
        chosen=candidates[0]
        return {'query':query,'selected_template_id':chosen['template_id'],
            'recommended_answer':chosen['answer'],'candidates':candidates,
            'latency_ms':round((time.perf_counter()-start)*1000,3),
            'mode':'template_direct','requires_practitioner_review':True}
