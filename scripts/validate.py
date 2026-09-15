"""JSON/JSONL 스키마 검증. 사용: python scripts/validate.py <file> --schema <name>"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from jsonschema import Draft7Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "templates" / "schemas"

def _load_schema(name_or_uri: str) -> dict:
    # "$ref": "conclusion.schema.json" 처럼 스키마 파일명만 쓰므로 마지막 경로 조각을 templates/schemas에서 찾는다.
    fname = name_or_uri.split("/")[-1]
    if not fname.endswith(".schema.json"):
        fname = f"{fname}.schema.json"
    return json.loads((SCHEMA_DIR / fname).read_text(encoding="utf-8"))

def _retrieve(uri: str) -> Resource:
    return Resource.from_contents(_load_schema(uri), default_specification=DRAFT7)

def _validator(schema_name: str) -> Draft7Validator:
    schema = _load_schema(schema_name)
    return Draft7Validator(schema, registry=Registry(retrieve=_retrieve))

def validate_obj(obj, schema_name: str) -> list[str]:
    v = _validator(schema_name)
    return [f"{'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}" for e in v.iter_errors(obj)]

def validate_file(path, schema_name: str) -> list[str]:
    path = Path(path); errs = []
    if path.suffix == ".jsonl":
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip(): continue
            errs += [f"행 {i}: {m}" for m in validate_obj(json.loads(line), schema_name)]
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else [data]
        for i, obj in enumerate(items, 1):
            errs += [f"항목 {i}: {m}" for m in validate_obj(obj, schema_name)]
    return errs

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("file"); ap.add_argument("--schema", required=True)
    a = ap.parse_args(argv); errs = validate_file(a.file, a.schema)
    print("검증 통과" if not errs else "\n".join(errs)); return 0 if not errs else 1

if __name__ == "__main__":
    sys.exit(main())
