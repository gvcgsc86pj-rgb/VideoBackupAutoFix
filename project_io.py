"""Versioned UTF-8 .toñadas files. Never embeds or executes source media."""
import json
import math
import os
from pathlib import Path
import tempfile

FORMAT = 'VideoBackupAutoFix'

def number(value, low=None, high=None):
    value=float(value)
    if not math.isfinite(value) or (low is not None and value<low) or (high is not None and value>high):
        raise ValueError('El proyecto contiene un valor fuera de rango.')
    return value

def validate(data):
    if not isinstance(data,dict) or data.get('format')!=FORMAT or data.get('schema_version')!=1:
        raise ValueError('No es un proyecto .toñadas compatible.')
    paths=data.get('videos')
    if not isinstance(paths,list) or len(paths)!=2 or not all(isinstance(p,str) for p in paths):
        raise ValueError('Referencias de vídeo no válidas.')
    settings=data['settings']; export=data['export']
    if settings['sync_method'] not in ['Imagen','Audio','Manual'] or settings['axis'] not in ['Horizontal','Vertical']:
        raise ValueError('Método o eje no válido.')
    number(settings['offset']);number(settings['threshold'],0,255);number(settings['padding'],0,5)
    number(settings['lufs'],-30,-5);number(settings['percent'],-99.999,300)
    if not isinstance(settings['normalize'],bool):raise ValueError('Audio no válido.')
    rects=data['rectangles']
    if not isinstance(rects,list) or len(rects)!=2:raise ValueError('Zonas no válidas.')
    for rect in rects:
        if rect is None:continue
        if not isinstance(rect,list) or len(rect)!=4:raise ValueError('Zona no válida.')
        for value in rect:number(value,0)
        if rect[2]<=0 or rect[3]<=0 or any(int(v)!=v for v in rect):raise ValueError('Zona no válida.')
    if not isinstance(data['intervals'],list):raise ValueError('Intervalos no válidos.')
    previous=-1
    for interval in data['intervals']:
        if not isinstance(interval,list) or len(interval)!=2:raise ValueError('Intervalo no válido.')
        a=number(interval[0],0);b=number(interval[1],0)
        if b<=a or a<previous:raise ValueError('Orden de intervalos no válido.')
        previous=b
    start=number(export['start'],0);end=number(export['end'],0)
    if end and end<=start:raise ValueError('Marcas de exportación no válidas.')
    if not isinstance(export['output'],str):raise ValueError('Destino no válido.')
    return data

def relative(path, directory):
    if not path:return ''
    try:return os.path.relpath(str(Path(path).resolve()),str(Path(directory).resolve()))
    except ValueError:return str(Path(path).resolve())

def save_project(path,data):
    path=Path(path).resolve()
    data=json.loads(json.dumps(data,ensure_ascii=False))
    validate(data)
    data['videos']=[relative(p,str(path.parent)) for p in data['videos']]
    data['export']['output']=relative(data['export']['output'],str(path.parent))
    temp=None
    try:
        with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=path.parent,suffix='.tmp',delete=False) as out:
            temp=out.name
            json.dump(data,out,ensure_ascii=False,indent=2,allow_nan=False)
            out.flush();os.fsync(out.fileno())
        os.replace(temp,path)
    finally:
        if temp and os.path.exists(temp):os.unlink(temp)

def load_project(path):
    path=Path(path).resolve()
    if path.stat().st_size>4*1024*1024:raise ValueError('El proyecto es demasiado grande.')
    with path.open(encoding='utf-8-sig') as source:data=validate(json.load(source))
    def absolute(p):return str((path.parent/p).resolve()) if p else ''
    data['videos']=[absolute(p) for p in data['videos']]
    data['export']['output']=absolute(data['export']['output'])
    return data
