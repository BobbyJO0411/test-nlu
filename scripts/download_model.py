"""Fetch pinned E5 snapshot, hash files; no remote code or TLS bypass."""
import argparse,json,shutil,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from nlu.engine import Recommender,DEFAULT_MODEL
p=argparse.ArgumentParser();p.add_argument('--model-id',default=DEFAULT_MODEL)
p.add_argument('--revision');p.add_argument('--destination',default='/workspace/nlu-model')
a=p.parse_args();engine=Recommender('e5',a.model_id,a.revision)
from huggingface_hub import snapshot_download
source=snapshot_download(a.model_id,revision=engine.metadata['revision'],cache_dir='/workspace/nlu-model-cache',local_files_only=True)
destination=Path(a.destination)
if destination.exists() and any(destination.iterdir()):
    raise SystemExit('Destination exists; choose a new path to preserve existing files')
destination.mkdir(parents=True,exist_ok=True)
for file in engine.metadata['model_files_sha256']:
    src=Path(source)/file;dst=destination/file;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
(destination/'verified_model.json').write_text(json.dumps({'model_id':a.model_id,'revision':engine.metadata['revision'],'files':engine.metadata['model_files_sha256']},indent=2))
print(json.dumps({'path':str(destination),'revision':engine.metadata['revision'],'dimension':engine.metadata['dimension']}))
