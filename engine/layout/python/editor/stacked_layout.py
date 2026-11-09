"""Two-level breadboard assemblies. Instance coordinates stay local to their board."""
from copy import deepcopy
from bom import APIError
from breadboard import normalize_board, board_specs, BreadboardError
from layout import (number, transform_point, polygon_bounds, world_geometry, shapes_touch,
                    hole_obstructs_shape, EPSILON)
from registered_boards import (registered, aligned as registered_aligned, world_outline,
                               holes as board_holes, contains_polygon, plates_overlap,
                               overlaps_polygon, circle_touches, definition)

MAX_SUB_BOARDS = 24

def aligned(parent, point):
    if registered(parent):return registered_aligned(parent,point)
    indices = []
    for coordinate, size in zip(point, (parent['widthMm'], parent['heightMm'])):
        n = (coordinate-parent['edgeOffsetMm'])/parent['pitchMm']
        if n < -EPSILON or coordinate > size-parent['edgeOffsetMm']+EPSILON or abs(n-round(n)) > EPSILON:
            return False
        indices.append(round(n))
    return not any((h['columnIndex'], h['rowIndex']) == tuple(indices) for h in parent.get('mountingHoles', []))

def plate_polygon(plate):
    return world_outline(plate)

def global_instance(instance, plates):
    plate = plates.get(instance.get('boardId'))
    # Optical settings have nested source/waveplate state. A world-space view
    # must not share mutable configuration with the editable local instance.
    result = deepcopy({k:v for k,v in instance.items() if k != 'boardId'})
    if plate is None:
        return result
    x,y = transform_point(plate, (instance['xMm'], instance['yMm']))
    return result | {'xMm':x,'yMm':y,'rotationDeg':(plate['rotationDeg']+instance['rotationDeg'])%360}


def plate_mounting_alignment(plate, parent, shapes, table=False):
    if plate.get('stageMotion'):
        from moving_stages import mounting_alignment
        return mounting_alignment(plate, parent, table)
    holes = []
    spec=board_specs(plate['board'])
    for hole in spec['mountingHoles']:
        point = transform_point(plate, (hole['xMm'],hole['yMm']))
        support = definition(plate['board']).get('customElevationSupport') if registered(plate['board']) else None
        offsets = support.get('baseMountingOffsetsMm', []) if support and abs(support['heightMm']-plate.get('elevationMm',0)) < EPSILON else []
        mounting_points = [transform_point(plate,(hole['xMm']+o['xMm'],hole['yMm']+o['yMm'])) for o in offsets] or [point]
        matches = table or all(aligned(parent,p) for p in mounting_points)
        radius=hole.get('counterboreDiameterMm',hole.get('diameterMm',11))/2
        obstructed = any(hole_obstructs_shape(point,radius,shape) for shape in shapes)
        usable = matches and not obstructed
        holes.append({'id':hole['label'],'label':hole['label'],'xMm':hole['xMm'],'yMm':hole['yMm'],
                      'globalXMm':round(point[0],6),'globalYMm':round(point[1],6),
                      'supportBasePointsMm':[{'xMm':x,'yMm':y} for x,y in mounting_points],
                      'aligned':matches,'obstructed':obstructed,'usable':usable,'spare':not usable})
    return {'boardId':plate['id'],'onTable':table,'totalCount':len(holes),
            'requiredCount':0 if table and not holes else spec.get('minimumAlignedMountingHoles',4),
            'alignedCount':sum(h['aligned'] for h in holes),'usableCount':sum(h['usable'] for h in holes),'holes':holes}

def validate_stacked(raw, kits):
    from collision_overrides import normalize_fields as normalize_overrides, local_fields, pair_keys, permits
    from layout import validate_layout, MAX_INSTANCES, base_mode_fields
    from elevation import ELEVATION_FIELDS, POST_SELECTION_FIELDS, normalize_fields, axis_validation
    from laser_adapter import beam_alignment
    if not {'board','instances','subBoards'} <= set(raw) or set(raw)-{'board','instances','subBoards','baseMode','collisionOverrides'} or not isinstance(raw['subBoards'], list) or len(raw['subBoards']) > MAX_SUB_BOARDS:
        raise APIError('invalid_layout', f'叠装布局必须包含大板、器件和最多 {MAX_SUB_BOARDS} 块小板。')
    mode = base_mode_fields(raw)
    table = mode.get('baseMode') == 'table'
    if not isinstance(raw['instances'], list) or len(raw['instances']) > MAX_INSTANCES:
        raise APIError('invalid_layout', '整份工程最多支持 500 个器件。')
    plates, metadata, issues, instances, ids, alignments, adapters = {}, {}, [], [], set(), [], []
    for p in raw['subBoards']:
        required={'id','name','board','xMm','yMm','rotationDeg'}
        if not isinstance(p,dict) or not required <= set(p) or set(p)-required-ELEVATION_FIELDS-{'stageMotion'}:
            raise APIError('invalid_layout','小面包板需要编号、名称、板参数和安装位置。')
        pid = p['id']
        if not isinstance(pid,str) or not 1<=len(pid)<=80 or pid in plates or pid in ('base','__proto__','constructor','prototype') or any(ord(c)<32 for c in pid):
            raise APIError('invalid_layout','小面包板编号无效或重复。')
        if not isinstance(p['name'],str) or not p['name'].strip() or len(p['name'])>160:
            raise APIError('invalid_layout','请为小面包板填写不超过160字的名称。')
        if type(p['rotationDeg']) is not int or p['rotationDeg'] not in (0,90,180,270):
            raise APIError('invalid_layout','小板方向只支持0、90、180、270度。')
        try:b=normalize_board(p['board'])
        except BreadboardError as e:raise APIError(e.code,str(e),e.status) from e
        from moving_stages import normalize_stage_motion
        motion = normalize_stage_motion({**p, 'board':b})
        plates[pid]={**p,**motion,'board':b,'xMm':number(p['xMm'],'小板X',-5000,10000),'yMm':number(p['yMm'],'小板Y',-5000,10000),**normalize_fields(p)}
    groups={None:[]}|{pid:[] for pid in plates}
    for i in raw['instances']:
        if not isinstance(i,dict) or not isinstance(i.get('id'),str) or i['id'] in ids:
            raise APIError('invalid_layout','整份工程的器件编号必须唯一。')
        ids.add(i['id'])
        owner=i.get('boardId')
        if ('boardId' in i and (not isinstance(owner,str) or owner not in plates)) or set(i)-{'id','kitId','xMm','yMm','rotationDeg','boardId','laserAdapter','optics','internalOptics','sourcePorts','manualMount'}-ELEVATION_FIELDS-POST_SELECTION_FIELDS:
            raise APIError('invalid_layout','器件引用的小面包板不存在，或包含未知字段。')
        groups[owner].append({k:v for k,v in i.items() if k!='boardId'})
    overrides = normalize_overrides(raw, ids)
    waived_pairs = pair_keys(overrides)
    parent=None
    for pid, group in groups.items():
        local, meta, validation = validate_layout({'board':raw['board'] if pid is None else plates[pid]['board'],'instances':group,**(mode if pid is None else {}),**local_fields(overrides, group)},kits,allow_stage_top=pid is not None and bool(plates[pid].get('stageMotion')))
        if pid is None:parent=local['board']
        metadata.update(meta)
        instances.extend([{**i,**({'boardId':pid} if pid else {})} for i in local['instances']])
        eight = pid is not None and (registered(plates[pid]['board']) or len(plates[pid]['board']['mountingHoles']) == 8)
        issues.extend([{**i,**({'boardId':pid,'message':plates[pid]['name']+'：'+i['message']} if pid else {})} for i in validation['issues'] if i['code'] not in ('axis_height_mismatch','adapter_beam_off_grid') and not (eight and i['code']=='mounting_hole_obstructed')])
        adapters.extend({**record,'boardId':pid} for record in validation.get('laserAdapters',[]))
        for alignment in validation.get('mountingAlignment', []):
            record = {**alignment, **({'boardId':pid} if pid else {})}
            record['globalAlignedPositionsMm'] = [
                {'xMm':round(point[0],6),'yMm':round(point[1],6)}
                for hole in alignment['alignedPositionsMm']
                for point in [transform_point(plates[pid],(hole['xMm'],hole['yMm'])) if pid else (hole['xMm'],hole['yMm'])]]
            alignments.append(record)
    if not table and parent['pitchMm'] not in (12.5,25):
        raise APIError('invalid_board','承载大板的孔距须为12.5或25 mm。')
    if not table and parent['holeType']!='M6_through':
        raise APIError('invalid_board','承载大板使用M6通螺纹孔，以固定小面包板。')
    def issue(code,message,board_id=None,**details):
        issues.append({'code':code,'instanceIds':[], 'message':message,**({'boardId':board_id} if board_id else {}),**details})
    shapes=[world_geometry(global_instance(i,plates),metadata[i['kitId']]) for i in instances]
    for index, a in enumerate(instances):
        for j,b in enumerate(instances[:index]):
            if a.get('boardId')!=b.get('boardId') and not permits('collision',[a['id'],b['id']],waived_pairs) and shapes_touch(shapes[index],shapes[j]) and len(issues)<250:
                issue('collision','不同面包板上的器件俯视轮廓相交，请调整小板或器件位置。',instanceIds=[a['id'],b['id']])
    boxes={pid:polygon_bounds(plate_polygon(p)) for pid,p in plates.items()}
    board_alignments=[]
    stage_reports=[]
    for pid,p in plates.items():
        box=boxes[pid];label=p['name'];b=p['board'];spec=board_specs(b)
        if p.get('stageMotion'):
            from moving_stages import module_for, fixed_pose
            base_bounds=module_for(p)['runtime'].get('baseBoundsMm')
            if base_bounds:
                fixed=fixed_pose(p)
                base_outline=[transform_point(fixed,point) for point in [(base_bounds['xMin'],base_bounds['yMin']),(base_bounds['xMax'],base_bounds['yMin']),(base_bounds['xMax'],base_bounds['yMax']),(base_bounds['xMin'],base_bounds['yMax'])]]
                if not contains_polygon(parent,base_outline):
                    issue('sub_board_out_of_bounds',label+'：固定底座超出承载面包板；移动顶板允许悬出。',pid)
        elif not contains_polygon(parent,plate_polygon(p)):
            issue('sub_board_out_of_bounds',label+'：小板底面超出大面包板。',pid)
        if not table and not p.get('stageMotion'):
            matches=[h for h in board_holes(b) if aligned(parent,transform_point(p,(h['xMm'],h['yMm'])))]
            if not matches:issue('sub_board_no_overlap',label+'：没有孔与大板重合，请移动小板。',pid)
            if not b['mountingHoles']:issue('sub_board_unfastened',label+'：尚未选择与大板对齐的固定沉孔。',pid)
        if p.get('stageMotion'):
            from moving_stages import validation as stage_validation
            stage_reports.append(stage_validation(p,parent,table))
        mounting_report=plate_mounting_alignment(p,parent,shapes,table)
        board_alignments.append(mounting_report)
        eight=registered(b) or len(spec['mountingHoles'])==8
        required=mounting_report['requiredCount']
        if p.get('stageMotion') and mounting_report['usableCount']<required:
            issue('stage_mounting_mismatch',f'{label}：固定基座有 {mounting_report["alignedCount"]}/{required} 个安装孔对准母板；请移动整个模块，不要用台面行程调整固定基座。',pid,alignedCount=mounting_report['alignedCount'],requiredCount=required)
        elif eight and mounting_report['usableCount']<required:
            condition='无遮挡' if table else '对齐且无遮挡'
            issue('sub_board_mounting_insufficient',f'{label}：{len(spec["mountingHoles"])} 个固定孔中只有 {mounting_report["usableCount"]} 个{condition}的可用固定孔，至少需要 {required} 个；其余孔可作为备用。',pid,usableCount=mounting_report['usableCount'],requiredCount=required,alignedCount=mounting_report['alignedCount'])
        for h in ([] if eight else spec['mountingHoles']):
            point=transform_point(p,(h['xMm'],h['yMm']))
            if not table and not aligned(parent,point):issue('sub_board_mounting_mismatch',f'{label}：{h["label"]} 沉孔未与大板有效螺纹孔重合，请重新选孔。',pid,holeIds=[h['label']],positionMm={'xMm':point[0],'yMm':point[1]})
            for i,shape in zip(instances,shapes):
                if i.get('boardId')!=pid and hole_obstructs_shape(point,5.5,shape):issue('mounting_hole_obstructed',f'{label}：{h["label"]} 被另一块板上的器件遮挡。',pid,holeIds=[h['label']],instanceIds=[i['id']])
        for qid,q in plates.items():
            if pid>=qid or p.get('stageMotion') or q.get('stageMotion'):continue
            other=boxes[qid]
            if min(box['right'],other['right'])-max(box['left'],other['left'])>EPSILON and min(box['bottom'],other['bottom'])-max(box['top'],other['top'])>EPSILON and plates_overlap(p,q):
                issue('sub_board_collision',f'{label} 与 {q["name"]} 的板面重叠。',pid,boardIds=[pid,qid])
        for i,shape in zip(instances,shapes):
            if i.get('boardId') is None and not p.get('stageMotion'):
                from layout import polygons_touch
                if any(overlaps_polygon(b,p,poly,touch=True) for poly in shape['polygons']):issue('collision',label+' 与直接安装在大板上的器件相交。',pid,instanceIds=[i['id']])
        for h in ([] if table else board_specs(parent)['mountingHoles']):
            from layout import circle_touches_polygon
            if circle_touches(b,p,(h['xMm'],h['yMm']),h.get('counterboreDiameterMm',h.get('diameterMm',11))/2):issue('mounting_hole_obstructed','大板安装沉孔被小板 '+label+' 遮挡。',pid,holeIds=[h['label']])
    # Module-owned children may overlap their carrier. External keepout checks
    # use measured frame transforms and conservative 3D module boxes.
    from moving_stages import boxes_overlap
    for n, report in enumerate(stage_reports):
        pid=report['boardId']; plate=plates[pid]
        for other in stage_reports[:n]:
            if any(boxes_overlap(a,b) for a in report['collisionBodies'] for b in other['collisionBodies']):
                issue('stage_keepout_collision',plate['name']+' 与 '+plates[other['boardId']]['name']+' 的保守禁入区重叠；请调整模块位置（此项为包围盒筛查）。',pid,boardIds=[pid,other['boardId']])
        for qid,q in plates.items():
            if qid==pid or q.get('stageMotion'):continue
            box=boxes[qid]; z=q.get('elevationMm',0)
            other={'xMin':box['left'],'xMax':box['right'],'yMin':box['top'],'yMax':box['bottom'],'zMin':z,'zMax':z+q['board']['thicknessMm']}
            if any(boxes_overlap(body,other) for body in report['collisionBodies']):
                issue('stage_keepout_collision',plate['name']+' 的保守禁入区与 '+q['name']+' 重叠，请调整布局。',pid,boardIds=[pid,qid])
        for i,shape in zip(instances,shapes):
            if i.get('boardId')==pid:continue
            # Ordinary kit Z envelopes are not yet catalogued: retain conservative
            # XY screening instead of claiming that unknown height clears a stage.
            from layout import polygons_touch
            if any(any(polygons_touch(poly,[(body['xMin'],body['yMin']),(body['xMax'],body['yMin']),(body['xMax'],body['yMax']),(body['xMin'],body['yMax'])]) for poly in shape['polygons']) for body in report['collisionBodies']):
                issue('stage_keepout_collision',plate['name']+' 的保守禁入区与器件 '+i['id']+' 重叠；未登记器件完整Z包络，需调整或核验。',pid,instanceIds=[i['id']])
    normalized={'board':parent,'subBoards':list(plates.values()),'instances':instances,**mode,**overrides}
    instance_map={i['id']:i for i in instances}
    for record in adapters:
        instance=instance_map[record['instanceId']]
        record.update(beam_alignment(instance,metadata[instance['kitId']],parent,plates.get(instance.get('boardId'))))
        if not table and not record['beamAligned']:
            issue('adapter_beam_off_grid','激光器光口未沿大面包板有效孔行或孔列出光，请调整激光器或小板位置。',record['boardId'],instanceIds=[record['instanceId']])
    axes,axis_issues=axis_validation(normalized,metadata,alignments,uniform=False)
    issues.extend(axis_issues)
    return normalized,metadata,{'valid':not issues,'issues':issues,**axes,'messages':list(dict.fromkeys(i['message'] for i in issues)),
                               'mountingAlignment':alignments,'stageModules':stage_reports,'laserAdapters':adapters,'subBoardMountingAlignment':board_alignments,
                               'collisions':[i for i in issues if i['code'] in ('collision','sub_board_collision','stage_keepout_collision')],
                               'outOfBounds':[i for i in issues if i['code'] in ('out_of_bounds','sub_board_out_of_bounds')],
                               'mountingHoleObstructions':[i for i in issues if i['code']=='mounting_hole_obstructed']}

def choose_stacked(catalog,payload):
    from layout import choose_mounting_holes, validate_layout
    from copy import deepcopy
    from collision_overrides import local_fields
    raw=deepcopy(payload['layout']);pid=payload.get('boardId')
    if not isinstance(raw.get('subBoards'),list) or any(not isinstance(p,dict) or not isinstance(p.get('board'),dict) for p in raw['subBoards']) or not isinstance(raw.get('board'),dict):raise APIError('invalid_layout','叠装面包板数据无效。')
    if raw.get('baseMode') == 'table' and pid is None:
        raise APIError('no_root_breadboard','桌子／无大板没有待加工的根板；请选择小面包板打孔，或切换为大面包板模式。')
    targets=[p for p in raw.get('subBoards',[]) if pid in ('all',p.get('id'))]
    if pid is not None and not targets:raise APIError('invalid_layout','请选择需要打孔的小面包板。')
    if pid is None:
        targets=[{'id':None,'name':'大面包板','board':raw['board'],'xMm':0,'yMm':0,'rotationDeg':0}]
    skipped=[p['id'] for p in targets if p.get('stageMotion')]
    if skipped and pid!='all':
        raise APIError('stage_fixed_holes','位移模块固定孔来自登记的下接口，不能对其顶板自动重打固定沉孔。')
    if pid=='all':
        targets=[p for p in targets if not p.get('stageMotion')]
        if not targets:
            validate_layout(raw,{k['id']:k for k in catalog['kits']})
            return {'boards':[],'skippedBoardIds':skipped,'note':'所选均为已登记固定接口的位移模块；保留原孔，不新增沉孔。'}
    for p in targets:p['board']['mountingHoles']=[]
    normalized,metadata,_=validate_layout(raw,{k['id']:k for k in catalog['kits']})
    plates={p['id']:p for p in normalized['subBoards']}
    result=[]
    for target in targets:
        owner=target['id'];local={'board':target['board'],'instances':[{k:v for k,v in i.items() if k!='boardId'} for i in normalized['instances'] if i.get('boardId')==owner]}
        local.update(local_fields(normalized, local['instances']))
        other_shapes=[world_geometry(global_instance(i,plates),metadata[i['kitId']]) for i in normalized['instances'] if i.get('boardId')!=owner]
        def candidate(x,y,require_alignment=True):
            point=transform_point(target,(x,y))
            if require_alignment and owner is not None and normalized.get('baseMode') != 'table' and not aligned(normalized['board'],point):return False
            if any(hole_obstructs_shape(point,5.5,s) for s in other_shapes):return False
            from layout import circle_touches_polygon
            return not any(p['id']!=owner and circle_touches(p['board'],p,point,5.5) for p in normalized['subBoards'])
        if payload.get('holeCount',4)==8 and owner is not None and normalized.get('baseMode')!='table' and not registered(local['board']):
            row,column=payload.get('rowParity','any'),payload.get('columnParity','any')
            if row not in ('any','odd','even') or column not in ('any','odd','even'):
                raise APIError('invalid_parity','行列奇偶选项无效。')
            options=[]
            for rp in (('odd','even') if row=='any' else (row,)):
                for cp in (('odd','even') if column=='any' else (column,)):
                    parities=((rp,cp),('even' if rp=='odd' else 'odd','even' if cp=='odd' else 'odd'))
                    # Only one four-hole group must mount to the carrier. Try
                    # either parity group as the mounting group, retaining the
                    # opposite four as unobstructed spare holes.
                    for primary in (0,1):
                        try:
                            groups=[choose_mounting_holes(catalog,{'catalogVersion':catalog['version'],'layout':local,'holeCount':4,'rowParity':r,'columnParity':c,**({'requires':payload['requires']} if 'requires' in payload else {})},
                                                          candidate_filter=lambda x,y,active=index==primary:candidate(x,y,active))
                                    for index,(r,c) in enumerate(parities)]
                            b=normalize_board({**local['board'],'mountingHoles':groups[0]['mountingHoles']+groups[1]['mountingHoles']})
                            spec=board_specs(b)
                            score=sum(min(h['xMm'],b['widthMm']-h['xMm'])**2+min(h['yMm'],b['heightMm']-h['yMm'])**2 for h in spec['mountingHoles'])
                            _,_,validation=validate_layout({**local,'board':b},{k['id']:k for k in catalog['kits']})
                            options.append((score,{'board':b,'mountingHoles':b['mountingHoles'],'holes':spec['mountingHoles'],'counterbore':spec['counterbore'],
                                                  'layoutValidation':validation,'selection':{'rowParity':rp,'columnParity':cp},
                                                  'note':'已选择两组共8个无遮挡沉孔；其中至少4个对齐大板作为固定孔，其余可备用。'}))
                        except (APIError,BreadboardError):
                            continue
            if not options:
                raise APIError('mounting_holes_unavailable','无法找到8个加工条件合格的沉孔，并保证其中至少4个对齐大板且无遮挡；请调整小板位置、行列奇偶或器件布局。',409)
            selected=min(options,key=lambda item:item[0])[1]
        else:
            selected=choose_mounting_holes(catalog,{'catalogVersion':catalog['version'],'layout':local,**{k:payload[k] for k in ('rowParity','columnParity','holeCount','requires') if k in payload}},candidate_filter=candidate)
        target['board']['mountingHoles']=selected['mountingHoles'];result.append({'boardId':owner,**selected})
    return {'boards':result,**({'skippedBoardIds':skipped} if skipped else {}),'note':'已为所选小面包板选择无遮挡的固定孔；桌面网格只作参考。' if normalized.get('baseMode') == 'table' else '已为所选面包板选择无遮挡的固定孔；小板8孔方案至少4孔与大板重合，其余可备用。'}

def stacked_svg(preview, static_root):
    import html
    from layout import layout_svg
    p=deepcopy(preview);layout=p['layout'];plates={b['id']:b for b in layout.pop('subBoards')}
    alignment={r['boardId']:r for r in p.get('layoutValidation',{}).get('subBoardMountingAlignment',[])}
    layout['instances']=[global_instance(i,plates) for i in layout['instances']]
    svg=layout_svg(p,static_root).decode('utf-8');height=layout['board']['heightMm'];parts=[]
    for index,plate in enumerate(plates.values()):
        b=plate['board'];spec=board_specs(b);key=f'subgrid{index}'
        if plate.get('stageMotion'):
            from moving_stages import svg_layers
            parts.append(svg_layers(plate,height,static_root))
        if registered(b):
            from registered_boards import svg_markup
            parts.append(f'<g data-sub-board="{html.escape(plate["id"],quote=True)}" transform="translate({plate["xMm"]:g} {height-plate["yMm"]:g}) rotate({-plate["rotationDeg"]})"><title>{html.escape(plate["name"])}</title><g transform="translate(0 {-b["heightMm"]:g})">{svg_markup(b,static_root) if not plate.get('stageMotion') else ''}</g><text x="3" y="{-b["heightMm"]-3:g}" font-size="5" fill="#174e48">{html.escape(plate["name"])}</text></g>')
            continue
        parts.append(f'<g data-sub-board="{html.escape(plate["id"],quote=True)}" transform="translate({plate["xMm"]:g} {height-plate["yMm"]:g}) rotate({-plate["rotationDeg"]})"><title>{html.escape(plate["name"])}</title><rect x="0" y="{-b["heightMm"]:g}" width="{b["widthMm"]:g}" height="{b["heightMm"]:g}" fill="#f8faf7" stroke="#58766f" stroke-width="1"/>')
        for row in range(spec['gridRows']):
            for col in range(spec['gridColumns']):
                x=b['edgeOffsetMm']+col*b['pitchMm'];y=b['edgeOffsetMm']+row*b['pitchMm']
                color='#16736f' if aligned(layout['board'],transform_point(plate,(x,y))) else '#b3bdb6'
                parts.append(f'<circle cx="{x:g}" cy="{-y:g}" r="1.2" fill="{color}"/>')
        for h in spec['mountingHoles']:
            color='#795ba0' if layout.get('baseMode') == 'table' or aligned(layout['board'],transform_point(plate,(h['xMm'],h['yMm']))) else '#c84c45'
            state=next((r for r in alignment.get(plate['id'],{}).get('holes',[]) if r['id']==h['label']),None)
            spare=len(spec['mountingHoles'])==8 and state is not None and state['spare']
            if spare:color='#a77625'
            parts.append(f'<circle cx="{h["xMm"]:g}" cy="{-h["yMm"]:g}" r="5.5" fill="none" stroke="{color}"/><text x="{h["xMm"]+6:g}" y="{-h["yMm"]-6:g}" font-size="4" fill="{color}">{h["label"]}{" 备用" if spare else ""}</text>')
        parts.append(f'<text x="3" y="{-b["heightMm"]-3:g}" font-size="5" fill="#174e48">{html.escape(plate["name"])}</text></g>')
    marker='<!-- board-surfaces-end -->'
    return svg.replace(marker,marker+''.join(parts),1).encode('utf-8')
