#!/usr/bin/env python3
"""Idempotent desktop launcher; one loopback process, no login item."""
from pathlib import Path
import fcntl,json,subprocess,sys,time,urllib.request
ROOT=Path(__file__).resolve().parent
config=json.loads((ROOT/'config.json').read_text());port=config['port'];url=f'http://127.0.0.1:{port}'

def healthy():
    try:
        with urllib.request.urlopen(url+'/healthz',timeout=.7) as r:
            return json.load(r).get('service')=='zzlab-local-optics-editor'
    except Exception:return False

def main():
    (ROOT/'data').mkdir(exist_ok=True)
    with (ROOT/'data/launcher.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if not healthy():
            with (ROOT/'data/server.log').open('ab') as log:
                proc=subprocess.Popen([sys.executable,'-B',str(ROOT/'server.py')],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
            for _ in range(60):
                if healthy():break
                if proc.poll() is not None:raise RuntimeError('本地服务启动失败，请查看 data/server.log；可能是端口被占用。')
                time.sleep(.1)
            else:raise RuntimeError('本地服务启动超时，请查看 data/server.log。')
        if '--no-open' not in sys.argv:subprocess.run(['/usr/bin/open',url+'/optics-kits/'],check=True)
    print(url+'/optics-kits/')
if __name__=='__main__':main()
