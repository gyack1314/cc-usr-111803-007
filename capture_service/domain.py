"""解析来源身份及本项目公开资料字段。"""
import json
from pathlib import Path
CONTRACT=json.loads((Path(__file__).resolve().parents[1]/'docs'/'source-contract.json').read_text(encoding='utf-8'))
def decode(raw,receipt):
    doc=json.loads(raw.decode('utf-8'))
    if not all(k in doc for k in ('kind','id','revision')): raise ValueError('资料身份缺失')
    kind=doc['kind']
    if kind not in CONTRACT['roles']: raise ValueError('未知来源类型')
    if any(k not in doc for k in CONTRACT['required_fields'][kind]): raise ValueError('来源业务字段缺失')
    return [{'type':kind,'id':doc['id'],'version':doc['revision'],'payload':{k:v for k,v in doc.items() if k not in ('kind','id','revision')}}]
def _version_key(version):
    text=str(version)
    if text[:1] in ('v','V') and text[1:].isdigit(): return (0,int(text[1:]))
    return (1,text)

def _ref(row):
    return {'type':row['type'],'id':row['id'],'version':row['version'],'source_sha256':row['source']}

def explain(rows,pending_sources=None):
    """方向、路段与公告时段共同决定当前线路状态；每条报价说明列出采用的来源。

    同一公告只以最新已收版次参与当前判断，被修订取代的版次保留在事件时间线；
    解除通知按声明的方向与解除时刻作用于对应路段方向，其他方向不受影响。
    来源目录要求的版次尚未取得时，先前收据不能证明当前方向判断已经核实；
    报价缺少道路公告时保持待核，不能仅由报价变化推断封路。
    """
    pending=[dict(item) for item in (pending_sources or [])]
    road_pending=any(item.get('kind') in ('road_notice','road_release') for item in pending)
    groups={}
    for row in rows: groups.setdefault((row['type'],row['id']),[]).append(row)
    stale=set()
    for key,group in groups.items():
        expected=next((r.get('expected_revision') for r in group if r.get('expected_revision')),'')
        if expected and expected not in {r['version'] for r in group}: stale.add(key)
    timeline={}
    current={}
    for (kind,entity_id),group in groups.items():
        versions=sorted(group,key=lambda r:_version_key(r['version']))
        latest=versions[-1]
        if kind=='road_notice':
            for row in versions:
                key=(row['payload']['segment'],row['payload']['direction'])
                timeline.setdefault(key,[]).append({'kind':'road_notice','id':row['id'],'version':row['version'],
                    'starts_at':row['payload']['starts_at'],'superseded':row is not latest,
                    'source_sha256':row['source']})
            key=(latest['payload']['segment'],latest['payload']['direction'])
            current.setdefault(key,[]).append(('notice',latest['payload']['starts_at'],latest))
        elif kind=='road_release':
            for row in versions:
                key=(row['payload']['segment'],row['payload']['direction'])
                timeline.setdefault(key,[]).append({'kind':'road_release','id':row['id'],'version':row['version'],
                    'released_at':row['payload']['released_at'],'notice_no':row['payload']['notice_no'],
                    'superseded':row is not latest,'source_sha256':row['source']})
            key=(latest['payload']['segment'],latest['payload']['direction'])
            current.setdefault(key,[]).append(('release',latest['payload']['released_at'],latest))
    route_status=[]
    for segment,direction in sorted(set(timeline)|set(current)):
        seq=sorted(current.get((segment,direction),[]),
                   key=lambda e:(e[1],0 if e[0]=='notice' else 1,e[2]['id']))
        state,starts_at,released_at='no_record',None,None
        for kind,when,row in seq:
            if kind=='notice': state,starts_at,released_at='controlled',row['payload']['starts_at'],None
            else: state,released_at='released',row['payload']['released_at']
        involved={(e['kind'],e['id']) for e in timeline.get((segment,direction),[])}
        verified=not road_pending and not any(identity in stale for identity in involved)
        route_status.append({'segment':segment,'direction':direction,'state':state,
            'starts_at':starts_at,'released_at':released_at,'verified':verified,
            'sources':[_ref(row) for _,_,row in seq],
            'events':sorted(timeline.get((segment,direction),[]),
                            key=lambda e:(e.get('starts_at') or e.get('released_at') or '',
                                          e['kind'],e['id'],_version_key(e['version'])))})
    by_segment={}
    for entry in route_status: by_segment.setdefault(entry['segment'],[]).append(entry)
    notice_segments={key[0] for key,events in timeline.items()
                     if any(e['kind']=='road_notice' for e in events)}
    explanations=[]
    quotes=sorted((r for r in rows if r['type']=='farm_quote'),
                  key=lambda r:(r['id'],_version_key(r['version'])))
    for quote in quotes:
        segment=quote['payload']['segment']
        directions=by_segment.get(segment,[])
        reasons=[]
        if segment not in notice_segments: reasons.append('缺少道路公告，报价所属路段状态待核')
        if any(not entry['verified'] for entry in directions): reasons.append('公告或解除通知版次待核，方向判断尚未核实')
        if pending: reasons.append('来源目录存在待收来源')
        if ('farm_quote',quote['id']) in stale: reasons.append('报价新版尚未取得，说明待核')
        sources=[_ref(quote)]
        for entry in directions:
            for ref in entry['sources']:
                if ref not in sources: sources.append(ref)
        explanations.append({'quote':_ref(quote),'segment':segment,
            'farm_region':quote['payload']['farm_region'],'price_cny_kg':quote['payload']['price_cny_kg'],
            'status':'pending' if reasons else 'explained','reasons':reasons,
            'directions':directions,'sources':sources})
    return {'route_status':route_status,'quote_explanations':explanations,'pending_sources':pending}

def assess(rows):
    """按当前双来源契约核对候选关联；后续来源事件仍待业务解释。"""
    left=sorted((r for r in rows if r['type']==CONTRACT['roles'][0]),key=lambda r:r['version'])
    right=sorted((r for r in rows if r['type']==CONTRACT['roles'][1]),key=lambda r:r['version'])
    pairs=[]
    for first in left:
        for second in right:
            a,b=first['payload'],second['payload']
            if a['segment']==b['segment']:
                pairs.append({'left_id':first['id'],'left_version':first['version'],
                              'right_id':second['id'],'right_version':second['version'],
                              'left_source':first['source'],'right_source':second['source']})
    return {'publishable':bool(pairs),'reasons':[] if pairs else ['道路区段与报价来源相同'],
            'received_types':sorted({r['type'] for r in rows}),
            'received_versions':len(rows),'matched_pairs':pairs,
            'candidate_relations':sorted({str(r['payload'].get(CONTRACT['relation_field'])) for r in rows})}
