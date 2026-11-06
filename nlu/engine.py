from __future__ import annotations
import hashlib,json,time,os
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
# NLU_HOME holds the venv, model cache and verified model copies outside the repository (any OS).
NLU_HOME=Path(os.environ.get('NLU_HOME',str(ROOT.parent))).resolve()
CACHE_DIR=NLU_HOME/'nlu-model-cache'
os.environ.setdefault('HF_HOME',str(CACHE_DIR))
os.environ.setdefault('HF_XET_CACHE',str(CACHE_DIR/'xet'))
os.environ.setdefault('TOKENIZERS_PARALLELISM','false')
os.environ.setdefault('HF_HUB_DISABLE_XET','1')
os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING','1')
PROFILES=json.loads((ROOT/'data/model_profiles.json').read_text(encoding='utf-8'))
DEFAULT_MODEL=PROFILES['default_model_id']
STRATEGIES=('passage_only','multiview_hybrid')
ALLOW_PATTERNS=['*.json','*.safetensors','*.txt','*.model','1_Pooling/*','2_Normalize/*','README.md','LICENSE*']
IGNORE_PATTERNS=['onnx/*','openvino/*','*.png','pytorch_model.bin']

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def git_blob_sha1(content):
    return hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()

def default_model_dir(model_id):
    return NLU_HOME/'nlu-models'/model_id.replace('/','__')

def retrieval_settings(model_id,backend):
    config=json.loads((ROOT/'data/retrieval_config.json').read_text(encoding='utf-8'))
    key=model_id if backend=='e5' else 'baseline'
    return dict(config['settings'].get(key,config['fallback']))

def verify_snapshot(path,model_id,revision):
    """Compare every downloaded file with the hub's per-file SHA256 (LFS) or Git blob SHA1.
    Works on Windows caches without symlinks, where blob file names are unavailable."""
    from huggingface_hub import HfApi
    info=HfApi().model_info(model_id,revision=revision,files_metadata=True)
    expected={s.rfilename:s for s in info.siblings}
    checked=0
    for file in Path(path).rglob('*'):
        if not file.is_file():continue
        rel=file.relative_to(path).as_posix()
        if rel not in expected:raise ValueError('Unexpected file not listed upstream: '+rel)
        meta=expected[rel];content=file.read_bytes()
        if meta.lfs:
            if hashlib.sha256(content).hexdigest()!=meta.lfs.sha256:raise ValueError('Upstream SHA256 mismatch: '+rel)
        elif git_blob_sha1(content)!=meta.blob_id:raise ValueError('Upstream Git blob hash mismatch: '+rel)
        checked+=1
    if not checked:raise ValueError('No model files were verified')
    return checked

class Recommender:
    """No gold labels are loaded here. E5 never silently falls back to baseline."""
    def __init__(self, backend='e5', model_id=DEFAULT_MODEL, revision=None, model_path=None,
                 strategy=None, alpha=None, beta=None):
        self.templates=json.loads((ROOT/'data/templates.json').read_text(encoding='utf-8'))
        self.backend=backend
        settings=retrieval_settings(model_id,backend)
        self.strategy=strategy or settings['strategy']
        if self.strategy not in STRATEGIES:raise ValueError('Unsupported retrieval strategy')
        self.alpha=float(settings['alpha'] if alpha is None else alpha)
        self.beta=float(settings['beta'] if beta is None else beta)
        if not (0<=self.alpha<=1 and 0<=self.beta<=1):raise ValueError('alpha and beta must be within [0,1]')
        extra=json.loads((ROOT/'data/template_queries.json').read_text(encoding='utf-8'))['queries']
        passages=[t['representative_query']+' '+t['answer'] for t in self.templates]
        # Question views: the representative question plus authored paraphrases of each template.
        self.view_owner=[];views=[]
        for i,t in enumerate(self.templates):
            for q in [t['representative_query'],*extra.get(t['template_id'],[])]:
                views.append(q);self.view_owner.append(i)
        self.view_owner=np.array(self.view_owner)
        if backend=='e5':
            import torch
            from sentence_transformers import SentenceTransformer
            torch.set_num_threads(int(os.environ.get('NLU_TORCH_THREADS','4')))
            profile=PROFILES['models'].get(model_id,{})
            revision=revision or profile.get('revision')
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
                from huggingface_hub import snapshot_download
                path=Path(snapshot_download(repo_id=model_id,revision=revision,cache_dir=str(CACHE_DIR),
                    allow_patterns=ALLOW_PATTERNS,ignore_patterns=IGNORE_PATTERNS))
                resolved=path.name
            if len(resolved)!=40 or any(c not in '0123456789abcdef' for c in resolved):
                raise ValueError('An exact downloaded model commit is required')
            if revision and len(revision)==40 and resolved!=revision:
                raise ValueError('Downloaded revision differs from the pinned revision')
            if not model_path:
                verify_snapshot(path,model_id,resolved)
            self.query_prefix=profile.get('query_prefix','query: ')
            passage_prefix=profile.get('passage_prefix','passage: ')
            self.model=SentenceTransformer(str(path),device='cpu',trust_remote_code=False)
            self.model.max_seq_length=int(profile.get('max_seq_length',512))
            encode=lambda texts:self.model.encode(texts,normalize_embeddings=True,
                convert_to_numpy=True,batch_size=8,show_progress_bar=False)
            self.index=encode([passage_prefix+p for p in passages])
            # E5 guidance: symmetric question-question matching uses the query prefix on both sides.
            self.view_index=encode([self.query_prefix+v for v in views])
            files={f.relative_to(path).as_posix():digest(f) for f in path.rglob('*') if f.is_file() and f.name!='verified_model.json'}
            self.metadata={'backend':'e5','model_id':model_id,'revision':resolved,
                'model_role':profile.get('role','unregistered'),'korean_fine_tuned':profile.get('korean_fine_tuned'),
                'base_model':profile.get('base_model'),'license':profile.get('license'),
                'dimension':int(self.index.shape[1]),'max_seq_length':self.model.max_seq_length,
                'query_prefix':self.query_prefix,'passage_prefix':passage_prefix,'model_files_sha256':files,
                'note':'Specific E5-Ko acceptance requires test-agency confirmation'}
        elif backend=='baseline':
            self.model=None
            self.metadata={'backend':'baseline','model_id':'char-tfidf-2-5',
                'note':'Lexical baseline only. NOT E5, KoBERT or evidence of embedding NLU readiness.'}
        else:
            raise ValueError('Unsupported backend')
        from sklearn.feature_extraction.text import TfidfVectorizer
        self.lexical=TfidfVectorizer(analyzer='char',ngram_range=(2,5),sublinear_tf=True)
        self.lexical_passages=self.lexical.fit_transform(passages+views)
        self.lexical_views=self.lexical_passages[len(passages):]
        self.lexical_passages=self.lexical_passages[:len(passages)]
        if backend=='baseline':
            # Reference scorer identical to earlier runs: vocabulary fitted on template passages only.
            self.reference=TfidfVectorizer(analyzer='char',ngram_range=(2,5),sublinear_tf=True)
            self.reference_passages=self.reference.fit_transform(passages)
        self.metadata.update(templates_sha256=digest(ROOT/'data/templates.json'),
            template_queries_sha256=digest(ROOT/'data/template_queries.json'),
            retrieval={'strategy':self.strategy,'alpha':self.alpha,'beta':self.beta,
                'view_count':len(views),'retrieval_config_sha256':digest(ROOT/'data/retrieval_config.json'),
                'formula':'passage_only: cos(q,passage) | multiview_hybrid: alpha*max cos(q,question views)+(1-alpha)*cos(q,passage)+beta*max char-tfidf'})

    def _max_by_template(self,view_scores):
        out=np.full(len(self.templates),-1.0)
        np.maximum.at(out,self.view_owner,view_scores)
        return out

    def component_scores(self,query):
        """Per-template dense passage, dense question-view and lexical scores."""
        lq=self.lexical.transform([query])
        lexical=np.maximum((lq@self.lexical_passages.T).toarray()[0],self._max_by_template((lq@self.lexical_views.T).toarray()[0]))
        if self.backend!='e5':
            reference=(self.reference.transform([query])@self.reference_passages.T).toarray()[0]
            return {'passage':reference,'views':self._max_by_template((lq@self.lexical_views.T).toarray()[0]),'lexical':lexical}
        vector=self.model.encode([self.query_prefix+query],normalize_embeddings=True,
            convert_to_numpy=True,show_progress_bar=False)[0]
        return {'passage':self.index@vector,'views':self._max_by_template(self.view_index@vector),'lexical':lexical}

    def combine(self,parts,strategy=None,alpha=None,beta=None):
        strategy=strategy or self.strategy
        alpha=self.alpha if alpha is None else alpha;beta=self.beta if beta is None else beta
        if strategy=='passage_only':return parts['passage']
        return alpha*parts['views']+(1-alpha)*parts['passage']+beta*parts['lexical']

    def recommend(self, query, top_k=3):
        if not query or not query.strip():
            raise ValueError('Question must not be blank')
        if not 1<=top_k<=len(self.templates):
            raise ValueError('top_k outside template count')
        start=time.perf_counter()
        scores=self.combine(self.component_scores(query))
        order=np.argsort(-scores,kind='stable')[:top_k]
        candidates=[{'rank':rank,'template_id':self.templates[int(i)]['template_id'],
            'score':float(scores[i]),'answer':self.templates[int(i)]['answer'],
            'source_ids':self.templates[int(i)]['source_ids']} for rank,i in enumerate(order,1)]
        chosen=candidates[0]
        return {'query':query,'selected_template_id':chosen['template_id'],
            'recommended_answer':chosen['answer'],'candidates':candidates,
            'latency_ms':round((time.perf_counter()-start)*1000,3),
            'mode':'template_direct','retrieval_strategy':self.strategy,'requires_practitioner_review':True}
