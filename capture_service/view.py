"""按本项目约定展示已接收资料与明确缺口。"""
from .ledger import entities
from .domain import assess,explain
from .collection import coverage,expected_revisions,pending_required

def overview(c,collection):
    rows=entities(c,collection)
    expected=expected_revisions(c,collection)
    annotated=[dict(row,expected_revision=expected.get(row['source'],'')) for row in rows]
    result=assess(rows)
    result['collection']=collection
    result['records']=[{'type':r['type'],'id':r['id'],'version':r['version'],'source_sha256':r['source']} for r in rows]
    result['coverage']=coverage(c,collection)
    result.update(explain(annotated,pending_required(c,collection)))
    return result
