#!/usr/bin/env python3
"""Local-only ZZLab editor; deliberately contains no account/cart/order routes."""
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, unquote, parse_qs, quote
import argparse, hashlib, json, mimetypes, os, re, socket, subprocess, sys, threading, time, gzip
from bom import APIError, aggregate, load_catalog
from layout import choose_mounting_holes, layout_document, layout_svg
from registered_boards import catalog_operation
from local_expert import expert_mode
ROOT=Path(__file__).resolve().parent
SERVICE='zzlab-local-optics-editor'
PREFIX='/optics-kits'
MAX_BODY=8*1024*1024
STRUCTURAL_ISSUES={'invalid_layout','invalid_elevation','invalid_post_selection','invalid_stage_motion','unknown_kit','invalid_mounting_holes'}

def expert_preview(preview, notes):
    """Keep physical checks visible while permitting professional layout exports."""
    validation=preview.get('layoutValidation')
    if validation:
        physical=[dict(issue,severity='warning') for issue in validation['issues'] if issue['code'] not in STRUCTURAL_ISSUES]
        validation['issues']=[issue for issue in validation['issues'] if issue['code'] in STRUCTURAL_ISSUES]
        validation['warnings']=validation.get('warnings',[])+physical+list(notes)
        validation['valid']=not validation['issues']
        preview['warnings']=[w for w in preview.get('warnings',[]) if not w.startswith('布局尚不可用：')]
        if validation['warnings']:
            preview['warnings'].insert(0,f"专业编辑：{len(validation['warnings'])} 项安装提示，请按实际装配核对；可继续编辑与导出。")
    preview['expertMode']=True
    return preview

@catalog_operation
def export_layout(catalog,preview,base,fmt):
    """Keep the page's pinned registry active through all export geometry reads."""
    if fmt=='layout-json':
        return json.dumps(layout_document(preview),ensure_ascii=False,indent=2).encode(),'application/json; charset=utf-8','光路布局.json'
    svg=layout_svg(preview,base)
    from local_board_library import beam_markup
    from registered_boards import registered, definition
    board=preview['layout']['board']
    if registered(board):
        if isinstance(svg,bytes):svg=svg.decode('utf-8')
        svg=svg.replace('</svg>',beam_markup(board,definition(board))+'</svg>')
    return svg.encode() if isinstance(svg,str) else svg,'image/svg+xml; charset=utf-8','光路总俯视图.svg'

class Library:
    def __init__(self, root):
        self.root=root;self.lock=threading.RLock();self.sync_state={'running':False};self.snapshots={}
        self.config=json.loads((root/'config.json').read_text())
        self.stop=threading.Event();self.wake=threading.Event();self.observed=None;self.last_audit=0
        self.refresh()
    def snapshot(self,name=None):
        with self.lock:
            name=name or self.active
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,150}',name):
                raise APIError('invalid_library','元件库版本无效。',400)
            if name not in self.snapshots:
                path=self.root/'data/libraries'/name
                if not (path/'receipt.json').is_file():
                    raise APIError('library_unavailable','此页的元件库缓存不可用，请先保存工程再重新打开。',409)
                catalog=load_catalog(path/'catalog.json')
                from local_board_library import extend_catalog
                catalog=extend_catalog(catalog,self.root)
                receipt=json.loads((path/'receipt.json').read_text())
                self.snapshots[name]=(catalog,path,receipt)
            return name,self.snapshots[name]
    def refresh(self):
        name=json.loads((self.root/'data/current.json').read_text())['release']
        _,(catalog,path,receipt)=self.snapshot(name)
        with self.lock:
            self.active=name
            self.catalog_json=json.dumps(catalog,ensure_ascii=False,separators=(',',':')).encode()
    def current(self):
        _,(catalog,path,_)=self.snapshot()
        return catalog,path
    def status(self):
        with self.lock:
            name,(cat,path,receipt)=self.snapshot()
            return {'service':SERVICE,'version':'1.2.3','expertMode':True,'catalogVersion':cat['version'],
                'snapshot':name,'kitCount':len(cat['kits']),'componentCount':len(cat['components']),
                'sourceMode':'web-runtime','sourceRoot':self.config['webLibraryRoot'],
                'sourceVerified':receipt.get('sourceVerified',False),'nasVerified':receipt.get('nasVerified',False),
                'verifiedAt':receipt.get('verifiedAt'),'sourceRelease':receipt['release'],
                'autoSyncSeconds':self.config.get('autoSyncSeconds',2),'sync':dict(self.sync_state)}
    def start(self):
        if self.config.get('hksopFrozen'):return
        self.worker=threading.Thread(target=self.watch,daemon=True)
        self.worker.start()
    def close(self):
        self.stop.set();self.wake.set()
    def synchronize(self):
        if self.config.get('hksopFrozen'):
            raise APIError('frozen_library','HKSOP 使用冻结的元件库；请运行 hksop.py runtime build 更新。',409)
        self.wake.set()
    def watch(self):
        from sync_library import source_signature
        while not self.stop.is_set():
            forced=self.wake.is_set();self.wake.clear()
            try:
                signature=source_signature(self.root)
                if forced or signature!=self.observed or time.monotonic()-self.last_audit>=self.config.get('sourceAuditSeconds',60):
                    self.receive(signature)
                else:
                    with self.lock:self.sync_state['checkedAt']=time.time()
            except Exception as exc:
                with self.lock:self.sync_state={'running':False,'ok':False,'message':'网页版库暂不可用，继续使用本地缓存；将自动重试。','detail':str(exc)}
            delay=self.config.get('autoSyncSeconds',2) if self.sync_state.get('ok',True) else 10
            self.wake.wait(max(.2,delay))
    def receive(self,signature):
        with self.lock:
            self.sync_state={'running':True,'message':'正在同步网页版元件库，画布可继续编辑。'}
            before=self.active
        try:
            result=subprocess.run([sys.executable,'-B',str(self.root/'sync_library.py'),'--root',str(self.root)],
                capture_output=True,text=True,timeout=self.config.get('syncTimeoutSeconds',90))
            data=json.loads(result.stdout)
            if result.returncode or not data.get('ok'):raise ValueError(data.get('message','元件库更新失败'))
            self.refresh();self.observed=signature;self.last_audit=time.monotonic()
            with self.lock:self.sync_state={'running':False,'ok':True,'checkedAt':time.time(),'message':'已与网页版元件库同步','version':data['version']}
            if before!=self.active:
                with (self.root/'PROJECT_LOG.md').open('a') as file:
                    file.write('\n## '+data['verifiedAt']+'｜网页版同源库自动更新\n\n- 状态：完成。本地缓存 '+data['snapshot']+'，目录 '+data['version']+'，'+str(data['fileCount'])+' 文件逐项 SHA256 回读一致。\n- 来源只读：'+data['source']+'；回执 data/libraries/'+data['snapshot']+'/receipt.json。网站/NAS/工程未改写；缓存 keep-local。\n')
        except Exception as exc:
            with self.lock:self.sync_state={'running':False,'ok':False,'message':'同步未完成，继续使用本地缓存；将自动重试。','detail':str(exc)}

class Handler(BaseHTTPRequestHandler):
    server_version='ZZLabLocal/1.2.1'
    def setup(self):super().setup();self.connection.settimeout(15)
    def log_message(self,*args):pass
    def route(self):
        parsed=urlsplit(self.path);path=unquote(parsed.path)
        if path==PREFIX or path.startswith(PREFIX+'/'):path=path[len(PREFIX):] or '/'
        return path,parse_qs(parsed.query)
    def check_request(self,mutation=False):
        expected={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
        hosts=self.headers.get_all('Host',[])
        if len(hosts)!=1 or hosts[0] not in expected:raise APIError('local_only','仅接受本机访问。',403)
        if self.headers.get('Sec-Fetch-Site')=='cross-site':raise APIError('local_only','不接受跨站请求。',403)
        origins=self.headers.get_all('Origin',[])
        if origins and (len(origins)!=1 or origins[0]!='http://'+hosts[0]):raise APIError('local_only','不接受跨站请求。',403)
        if mutation and self.headers.get('X-ZZLab-Local')!='1':raise APIError('local_only','请使用本地编辑器。',403)
    def send_bytes(self,status,data,mime,filename=None,cache=False,headers=None):
        etag='"'+hashlib.sha256(data).hexdigest()+'"'
        if cache and self.headers.get('If-None-Match')==etag:
            self.send_response(304);self.send_header('ETag',etag);self.end_headers();return
        compressed=len(data)>2048 and 'gzip' in self.headers.get('Accept-Encoding','')
        if compressed:data=gzip.compress(data,compresslevel=3)
        self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-cache' if cache else 'no-store');self.send_header('ETag',etag)
        self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
        if compressed:self.send_header('Content-Encoding','gzip');self.send_header('Vary','Accept-Encoding')
        if filename:self.send_header('Content-Disposition',"attachment; filename=\"download\"; filename*=UTF-8''"+quote(filename))
        for key,value in (headers or {}).items():self.send_header(key,value)
        self.end_headers();self.wfile.write(data)
    def send_json(self,status,value):self.send_bytes(status,json.dumps(value,ensure_ascii=False,separators=(',',':')).encode(),'application/json; charset=utf-8')
    def error(self,e):self.send_json(e.status,e.payload())
    def read_payload(self):
        if self.headers.get('Transfer-Encoding') or self.headers.get_content_type()!='application/json':raise APIError('invalid_request','请求必须为 JSON。',415)
        try:length=int(self.headers.get('Content-Length','0'))
        except ValueError:raise APIError('invalid_request','无效请求长度。')
        if not 0<length<=MAX_BODY:raise APIError('request_too_large','请求超过 8 MiB 或为空。',413)
        try:
            data=self.rfile.read(length)
            if len(data)!=length:raise ValueError()
            return json.loads(data,parse_constant=lambda x:(_ for _ in ()).throw(ValueError(x)))
        except (ValueError,UnicodeError,RecursionError,socket.timeout):raise APIError('invalid_json','JSON 内容无效。')
    def do_GET(self):
        try:
            self.check_request();path,query=self.route();library=self.server.library
            if path in ('/healthz','/api/local/status'):return self.send_json(200,library.status())
            if path=='/api/session':return self.send_json(200,{'role':'guest','canPublish':False,'canDownload':True,'canDownloadManufacturing':False,'localOnly':True,'expertMode':True})
            if path=='/api/catalog':
                name,(catalog,_,_)=library.snapshot(query.get('snapshot',[None])[0])
                return self.send_bytes(200,json.dumps(catalog,ensure_ascii=False,separators=(',',':')).encode(),
                    'application/json; charset=utf-8',headers={'X-ZZLab-Library':name})
            if path.startswith('/api/') or path.startswith('/auth/'):raise APIError('disabled','本地版仅支持光路编辑、渲染和工程导出。',403)
            if path in ('/','/index.html'):relative='index.html'
            else:relative=path.lstrip('/')
            if '\\' in relative or any(p in ('','.','..') for p in relative.split('/')):raise APIError('not_found','文件不存在。',404)
            base=library.snapshot(query.get('library',[None])[0])[1][1] if relative.startswith('topviews/') else self.server.root/'static'
            target=(base/relative).resolve()
            if not target.is_relative_to(base.resolve()) or target.suffix not in ('.html','.css','.js','.svg','.png','.webp','.ico') or not target.is_file():raise APIError('not_found','文件不存在。',404)
            self.send_bytes(200,target.read_bytes(),mimetypes.guess_type(target)[0] or 'application/octet-stream',cache=True)
        except APIError as e:self.error(e)
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception:self.error(APIError('read_failed','本地文件读取失败，请重新启动编辑器。',500))
    def do_POST(self):
        try:
            self.check_request(mutation=True);path,query=self.route();library=self.server.library
            if path=='/api/local/sync':library.synchronize();return self.send_json(202,library.status())
            if path=='/api/local/project-library':
                from project_library import resolve
                name,(catalog,_,_)=resolve(library,self.read_payload())
                return self.send_bytes(200,json.dumps(catalog,ensure_ascii=False,separators=(',',':')).encode(),
                    'application/json; charset=utf-8',headers={'X-ZZLab-Library':name})
            if path not in ('/api/preview','/api/mounting-holes','/api/export'):raise APIError('disabled','本地版没有下单、购物车或共享发布接口。',403)
            fmt=query.get('format',[''])[0]
            if path=='/api/export' and (set(query)!={'format'} or len(query['format'])!=1 or fmt not in ('layout-json','layout-svg')):raise APIError('disabled','只允许布局 JSON 和总俯视图导出；工程请点击“保存工程”。',403)
            if path!='/api/export' and query:raise APIError('invalid_request','不接受查询参数。')
            payload=self.read_payload();_,(catalog,base,_)=library.snapshot(self.headers.get('X-ZZLab-Library'))
            with expert_mode() as notes:
                if path=='/api/mounting-holes':return self.send_json(200,choose_mounting_holes(catalog,payload))
                preview=expert_preview(aggregate(catalog,payload,require_items=False),notes)
                from local_board_library import layout_warnings
                extra=layout_warnings(preview.get('layout',{}),catalog)
                if extra and preview.get('layoutValidation') is not None:preview['layoutValidation'].setdefault('warnings',[]).extend(extra)
                if path=='/api/preview':return self.send_json(200,preview)
                self.send_bytes(200,*export_layout(catalog,preview,base,fmt))
        except APIError as e:self.error(e)
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception as e:
            import traceback;traceback.print_exc()
            self.error(APIError('operation_failed','操作未完成，原工程保留；请检查本地服务日志。',500))
    def do_OPTIONS(self):self.error(APIError('disabled','不接受跨站访问。',405))

def create_server(root=ROOT,port=18933,watch=True):
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler);server.daemon_threads=True
    server.root=Path(root);server.library=Library(server.root)
    if watch:server.library.start()
    return server
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int);args=parser.parse_args()
    config=json.loads((ROOT/'config.json').read_text());server=create_server(port=args.port or config['port'])
    print('Local editor ready on port',server.server_port,flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.library.close();server.server_close()
