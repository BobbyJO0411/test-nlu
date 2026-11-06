"""Fetch a pinned embedding model snapshot, verify every file against upstream hashes, keep a hashed copy.
No remote code, no TLS or checksum bypass. Works on Linux and Windows (no symlink requirement)."""
import argparse,json,shutil,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from nlu.engine import (PROFILES,DEFAULT_MODEL,CACHE_DIR,ALLOW_PATTERNS,IGNORE_PATTERNS,
    default_model_dir,digest,verify_snapshot)
p=argparse.ArgumentParser()
p.add_argument('--model-id',default=DEFAULT_MODEL)
p.add_argument('--revision',help='40-char commit; defaults to the pinned revision in data/model_profiles.json')
p.add_argument('--destination',help='defaults to $NLU_HOME/nlu-models/<model>')
a=p.parse_args()
revision=a.revision or PROFILES['models'].get(a.model_id,{}).get('revision')
if not revision or len(revision)!=40:raise SystemExit('A pinned 40-character revision is required')
destination=Path(a.destination) if a.destination else default_model_dir(a.model_id)
if destination.exists() and any(destination.iterdir()):
    raise SystemExit(f'Destination exists: {destination}. Choose a new path to preserve existing files')
from huggingface_hub import snapshot_download
source=Path(snapshot_download(a.model_id,revision=revision,cache_dir=str(CACHE_DIR),
    allow_patterns=ALLOW_PATTERNS,ignore_patterns=IGNORE_PATTERNS))
if source.name!=revision:raise SystemExit('Downloaded revision differs from the pinned revision')
checked=verify_snapshot(source,a.model_id,revision)
destination.mkdir(parents=True,exist_ok=True)
files={}
for file in sorted(source.rglob('*')):
    if not file.is_file():continue
    rel=file.relative_to(source).as_posix();dst=destination/rel
    dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(file,dst)
    files[rel]=digest(dst)
    if files[rel]!=digest(file):raise SystemExit('Copy hash mismatch: '+rel)
manifest={'model_id':a.model_id,'revision':revision,'upstream_verified_files':checked,'files':files}
(destination/'verified_model.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'path':str(destination),'model_id':a.model_id,'revision':revision,'files':len(files)}))
