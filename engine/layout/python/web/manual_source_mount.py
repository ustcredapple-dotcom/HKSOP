"""User-declared manual source placement; XY optical reference is never a screw hole."""
import math
import copy
from bom import APIError

def invalid(message):raise APIError('invalid_manual_mount',message,409)
def finite(v):return type(v) in (int,float) and math.isfinite(v)
def source_reference(geometry):
 policy=geometry.get('manualMountingPolicy')
 reference=geometry.get('sourceAlignmentReference')
 if policy is None and reference is None:return None
 if not isinstance(policy,dict) or set(policy)-{'version','mode','targetAxisHeightMm'} or type(policy.get('version')) is not int or policy['version']!=1 or policy.get('mode')!='user-support-and-clamp':invalid('手动光源安装需要目录v1人工支撑/压板协议。')
 if 'targetAxisHeightMm' in policy and (not finite(policy['targetAxisHeightMm']) or not 0<=policy['targetAxisHeightMm']<=10000):invalid('手调目标轴高仅能使用有限参考值。')
 if geometry.get('opticalType')!='source' or geometry.get('opticalAssembly') is not None or geometry.get('mountingHoleOffsetsMm')!=[] or geometry.get('mountingConfirmed') is not False:invalid('手动安装仅适用于无已确认安装孔的独立源，不能冒充螺钉孔或内部整装。')
 if not isinstance(reference,dict) or set(reference)!={'version','portId'} or type(reference.get('version')) is not int or reference['version']!=1:invalid('出光口吸附必须引用目录固定v1光口。')
 ports=geometry.get('opticalPortsMm');port=ports[0] if isinstance(ports,list) and len(ports)==1 else None
 if not isinstance(port,dict) or reference.get('portId')!=port.get('id') or not isinstance(port.get('id'),str) or not port['id'] or any(not finite(port.get(k)) for k in ['xMm','yMm','directionX','directionY']) or math.hypot(port['directionX'],port['directionY'])<1e-9:invalid('出光口吸附需要唯一固定主光口的有限XY与水平方向。')
 if geometry.get('opticalAxisHeightMm') is not None or geometry.get('opticalDatumVerified') is not False:invalid('人工支撑前的实际板面光高须保持未知；用户声明不得修改目录已验证状态。')
 return port

def normalize_fields(instance,kit):
 reference=source_reference(kit.get('layout',{}))
 if reference is not None and (isinstance(instance.get('laserAdapter'),dict) and instance['laserAdapter'].get('enabled') is True or instance.get('elevationMm',0)!=0 or 'universalPostSelection' in instance):invalid('人工支撑轴高由用户声明，不能叠加自动转接底座、换柱或器件抬高。')
 if 'manualMount' not in instance:return {}
 if kit.get('category')!='laser' or reference is None:invalid('此套件未登记人工支撑光源安装协议。')
 value=instance['manualMount'];required={'version','confirmed','nominalOutputReferenceAccepted'}
 if not isinstance(value,dict) or set(value)-required-{'axisHeightMm'} or not required<=set(value):invalid('人工安装仅允许版本、确认、名义出光参考接受状态和用户声明轴高。')
 if type(value['version']) is not int or value['version']!=1 or type(value['confirmed']) is not bool or type(value['nominalOutputReferenceAccepted']) is not bool:invalid('人工安装版本及两项确认无效。')
 result={k:value[k] for k in ['version','confirmed','nominalOutputReferenceAccepted']}
 if 'axisHeightMm' in value:
  height=value['axisHeightMm']
  if not finite(height) or not 0<=height<=10000:invalid('手调后的光轴高需明确填写为板面起0–10000mm的有限数字；空白不是62.5。')
  result['axisHeightMm']=round(height,6)
 if result['confirmed'] and ('axisHeightMm' not in result or not result['nominalOutputReferenceAccepted']):invalid('确认人工安装前需填写实际手调光高，并明确接受名义出光参考平面。')
 return {'manualMount':result}

def accepted_height(instance,geometry):
 if source_reference(geometry) is None:return None
 value=instance.get('manualMount',{})
 return value.get('axisHeightMm') if value.get('version')==1 and value.get('confirmed') is True and value.get('nominalOutputReferenceAccepted') is True and finite(value.get('axisHeightMm')) and 0<=value['axisHeightMm']<=10000 else None

def output_point(instance,geometry):
 port=source_reference(geometry)
 if port is None:return None
 from layout import transform_point
 return transform_point(instance,(port['xMm'],port['yMm']))

def output_aligned(instance,geometry,board):
 from registered_boards import holes
 point=output_point(instance,geometry)
 return point is not None and any(math.hypot(point[0]-h['xMm'],point[1]-h['yMm'])<=1e-5 for h in holes(board))

def upgrade_legacy_r3_project(project,catalog):
 """Load the frozen pre-manual R3 project without inventing a mount declaration.

 Only that recorded catalogue version is eligible. Explicit manualMount values
 still require their capability; normalized exports always declare it. This
 returns a copy and never writes the saved project or guesses an axis height.
 """
 capability='zzlab-manual-source-mount-v1'
 if not isinstance(project,dict):return project,False
 if project.get('catalogVersion')!='2026-10-06.11-periscope-r3-rf180':return project,False
 requirements=project.get('requires',[]);layout=project.get('layout')
 if not isinstance(requirements,list) or capability in requirements or not isinstance(layout,dict):return project,False
 instances=layout.get('instances')
 if not isinstance(instances,list) or any(not isinstance(i,dict) or 'manualMount' in i for i in instances):return project,False
 manual_ids={k['id'] for k in catalog.get('kits',[]) if k.get('layout',{}).get('manualMountingPolicy')}
 if not any(i.get('kitId') in manual_ids for i in instances):return project,False
 result=copy.deepcopy(project);result['requires']=requirements+[capability];result['catalogVersion']=catalog['version']
 return result,True
