import os, sys, json, math, subprocess, threading, queue, shutil, tempfile, wave, webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import cv2
import numpy as np
from PIL import Image, ImageTk
from rounded_button import RoundedButton
from video_preview import VideoPreview

# FFmpeg empaquetado dentro del ejecutable portátil.
if getattr(sys, 'frozen', False):
    os.environ['PATH'] = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable)) + os.pathsep + os.environ.get('PATH', '')

def run_process(args, **kwargs):
    if os.name == 'nt':
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    kwargs.setdefault('stdin', subprocess.DEVNULL)
    return subprocess.run(args, **kwargs)

BG='#111416'; PANEL='#1a1e21'; DARK='#20252a'; ORANGE='#ff9a3d'; FG='#edf0f3'; MUTED='#9aa6b6'; BORDER='#2c333b'

def ffprobe(path):
    p=run_process(['ffprobe','-v','error','-show_streams','-show_format','-of','json',path],capture_output=True,text=True,check=True)
    d=json.loads(p.stdout); v=next(s for s in d['streams'] if s['codec_type']=='video'); a=any(s['codec_type']=='audio' for s in d['streams'])
    r=v.get('avg_frame_rate','25/1'); x,y=map(float,r.split('/')); fps=x/y if y else 25
    return {'width':int(v['width']),'height':int(v['height']),'fps':fps,'duration':float(d['format'].get('duration',0)),'audio':a}

def frame_at(path,sec):
    cap=cv2.VideoCapture(path)
    cap.set(cv2.CAP_PROP_POS_MSEC,max(0,sec)*1000)
    ok,frame=cap.read(); cap.release()
    if not ok: raise ValueError('No se puede leer un fotograma del vídeo')
    return cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)

def audio_samples(path,seconds=240,rate=2000):
    cmd=['ffmpeg','-v','error','-i',path,'-t',str(seconds),'-vn','-ac','1','-ar',str(rate),'-f','f32le','-']
    p=run_process(cmd,capture_output=True)
    if p.returncode: raise RuntimeError('No se pudo extraer el audio')
    return np.frombuffer(p.stdout,dtype=np.float32).copy()

def sync_audio(main,backup):
    rate=2000; a=audio_samples(main); b=audio_samples(backup)
    if len(a)<rate*5 or len(b)<rate*5: raise ValueError('Audio insuficiente para sincronizar')
    # Correlación de envolventes de volumen a 20 Hz, tolerante a diferentes cámaras.
    def envelope(x):
        n=len(x)//100; x=x[:n*100].reshape(n,100)
        z=np.sqrt(np.mean(x*x,axis=1)); return (z-z.mean())/(z.std()+1e-8)
    a=envelope(a); b=envelope(b)
    from numpy.fft import rfft,irfft
    size=1<<(len(a)+len(b)-2).bit_length()
    c=irfft(rfft(a,size)*rfft(b[::-1],size),size)[:len(a)+len(b)-1]
    lag=int(np.argmax(c))-(len(b)-1)
    confidence=float(c.max()/max(1,min(len(a),len(b))))
    if confidence<0.12: raise ValueError('Coincidencia de audio poco fiable; usa imagen o manual')
    # backup_time = main_time + offset
    return -lag/20.0,confidence

def visual_descriptor(img):
    # Perceptual luminance image + edges, normalized; compare frames containing shared material.
    gray=cv2.cvtColor(img,cv2.COLOR_RGB2GRAY)
    gray=cv2.resize(gray,(64,36),interpolation=cv2.INTER_AREA).astype(np.float32)
    gray=(gray-gray.mean())/(gray.std()+1e-4)
    return gray.flatten()

def sync_image(main,backup,meta_main,meta_backup):
    # Sample short sequences at one-second intervals; infer constant offset from matching frames.
    n=min(100,int(meta_main['duration']),int(meta_backup['duration']))
    if n<8: raise ValueError('Duración insuficiente para sincronización por imagen')
    times=np.arange(2,n,2,dtype=float)
    aa=[];bb=[]
    for t in times:
        aa.append(visual_descriptor(frame_at(main,t)))
        bb.append(visual_descriptor(frame_at(backup,t)))
    aa=np.asarray(aa);bb=np.asarray(bb)
    corr=aa@bb.T/aa.shape[1]
    candidates=[]
    for i in range(len(times)):
        j=int(np.argmax(corr[i])); score=float(corr[i,j]);
        if score>0.72: candidates.append((float(times[j]-times[i]),score))
    if len(candidates)<3: raise ValueError('No hay suficientes imágenes comunes. Prueba audio o manual')
    offsets=np.array([c[0] for c in candidates]); offset=float(np.median(offsets))
    votes=sum(abs(o-offset)<=2 for o in offsets)
    if votes<3: raise ValueError('Las coincidencias visuales son ambiguas; ajusta manualmente')
    return offset,float(votes/len(candidates))

def black_intervals(path,rect,meta,threshold=18,black_fraction=.94,padding=.15):
    cap=cv2.VideoCapture(path)
    fps=meta['fps']; x,y,w,h=rect; hits=[]; idx=0
    while True:
        ok,frame=cap.read()
        if not ok: break
        roi=frame[y:y+h,x:x+w]
        if roi.size:
            gray=cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY)
            if float(np.mean(gray<threshold))>=black_fraction: hits.append(idx/fps)
        idx+=1
    cap.release()
    if not hits: return []
    intervals=[]; start=last=hits[0]; step=1/fps
    for t in hits[1:]:
        if t-last>step*1.6:
            intervals.append((max(0,start-padding),min(meta['duration'],last+step+padding)))
            start=t
        last=t
    intervals.append((max(0,start-padding),min(meta['duration'],last+step+padding)))
    merged=[]
    for a,b in intervals:
        if merged and a<=merged[-1][1]:merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
        else:merged.append((a,b))
    return merged

class App:
    def __init__(self,root):
        self.root=root;root.title('Video Backup AutoFix 2.0');root.geometry('1060x640+24+24');root.minsize(960,600);root.configure(bg=BG)
        self.paths=['',''];self.metas=[None,None];self.rects=[None,None];self.offset=tk.DoubleVar(value=0);self.syncmode=tk.StringVar(value='Imagen')
        self.threshold=tk.IntVar(value=18);self.pad=tk.DoubleVar(value=.15);self.lufs=tk.StringVar(value='-16');self.normalize=tk.BooleanVar(value=False)
        self.axis=tk.StringVar(value='Vertical');self.percent=tk.StringVar(value='0');self.output=tk.StringVar(value='');self.intervals=[]
        self.q=queue.Queue();self.busy=False;self.current=0;self.preview_widgets=[]
        style=ttk.Style();style.theme_use('clam');style.configure('TCombobox',fieldbackground=DARK,background=DARK,foreground=FG)
        head=tk.Frame(root,bg=BG);head.pack(fill='x',padx=18,pady=(10,10))
        tk.Label(head,text='Video Backup AutoFix',font=('Segoe UI',13),fg=FG,bg=BG).pack(side='left')
        tk.Label(head,text='2.0',font=('Segoe UI',10),fg='#d6a27b',bg=BG).pack(side='left',padx=12)
        tk.Frame(root,bg=BORDER,height=1).pack(fill='x')
        self.tabs=tk.Frame(root,bg=BG);self.tabs.pack(fill='x',padx=8,pady=0)
        names=['1  Insertar vídeos','2  Sincronización','3  Zonas y reparación','4  Nivelación audio','5  Relación de aspecto','6  Exportación']
        self.tab_buttons=[]
        for i,name in enumerate(names):
            b=RoundedButton(self.tabs,text=name,command=lambda i=i:self.show(i),bg=BG,fg=MUTED,padx=7,pady=10,font=('Segoe UI',8),variant='tab')
            b.pack(side='left',fill='x',expand=True);self.tab_buttons.append(b)
        tk.Frame(root,bg=BORDER,height=1).pack(fill='x')
        foot=tk.Frame(root,bg=BG,padx=18,pady=10);foot.pack(side='bottom',fill='x')
        self.status=tk.Label(foot,text='Preparado',fg=MUTED,bg=BG,font=('Segoe UI',8));self.status.pack(side='left')
        credit=tk.Frame(foot,bg=BG);credit.pack(side='right')
        tk.Label(credit,text='Desarrollado por',fg=MUTED,bg=BG,font=('Segoe UI',8)).pack(side='left',padx=(0,6))
        link=tk.Label(credit,text='Carlos Durán',fg=ORANGE,bg=BG,font=('Segoe UI',8,'bold'),cursor='hand2')
        link.pack(side='left');link.bind('<Button-1>',lambda e:webbrowser.open('https://carlosduran.eu/valcres'))
        tk.Frame(root,bg=BORDER,height=1).pack(side='bottom',fill='x')
        self.body=tk.Frame(root,bg=BG);self.body.pack(fill='both',expand=True,padx=18,pady=(14,8))
        self.show(0);self.root.after(100,self.poll)

    def label(self,parent,text,size=11,color=FG):return tk.Label(parent,text=text,bg=parent['bg'],fg=color,font=('Segoe UI',max(8,size-2)),anchor='w')
    def button(self,parent,text,cmd,accent=False):
        return RoundedButton(parent,text=text,command=cmd,bg=ORANGE if accent else PANEL,fg='#17130f' if accent else FG,padx=14,pady=7,font=('Segoe UI',9),outline=None if accent else '#414b56')
    def panel(self,parent):return tk.Frame(parent,bg=PANEL,padx=12,pady=12,highlightthickness=1,highlightbackground=BORDER)
    def entry(self,parent,var,width=15):return tk.Entry(parent,textvariable=var,width=width,bg=DARK,fg=FG,insertbackground=FG,relief='flat',highlightthickness=1,highlightbackground='#34383e',highlightcolor=ORANGE,font=('Segoe UI',9))
    def show(self,i):
        self.current=i
        for n,b in enumerate(self.tab_buttons):b.set_active(i==n)
        for w in self.body.winfo_children():w.destroy()
        [self.page_files,self.page_sync,self.page_zones,self.page_audio,self.page_aspect,self.page_export][i]()
    def title(self,text):
        clean=text.split('. ',1)[-1] if text[:1].isdigit() else text
        tk.Label(self.body,text=clean,bg=BG,fg=FG,font=('Segoe UI',15,'bold')).pack(anchor='w',pady=(2,12))
    def page_files(self):
        self.title('Insertar vídeos')
        tk.Label(self.body,text='Carga la grabación principal y su respaldo.',bg=BG,fg=MUTED,font=('Segoe UI',9)).pack(anchor='w',pady=(0,14))
        sources=tk.Frame(self.body,bg=BG);sources.pack(fill='both',expand=True)
        sources.grid_rowconfigure(0,weight=1)
        for i,name in enumerate(['Vídeo principal','Vídeo backup']):
            sources.grid_columnconfigure(i,weight=1,uniform='source')
            p=self.panel(sources);p.grid(row=0,column=i,sticky='nsew',padx=(0,5) if i==0 else (5,0))
            tk.Label(p,text=name,bg=PANEL,fg=FG,font=('Segoe UI',11)).pack(anchor='w',pady=(0,10))
            rgb=None
            if self.paths[i]:
                try:rgb=frame_at(self.paths[i],min(1,self.metas[i]['duration']/2))
                except Exception:pass
            monitor=VideoPreview(p,rgb);monitor.pack(fill='both',expand=True,pady=(0,12))
            row=tk.Frame(p,bg=PANEL);row.pack(fill='x')
            RoundedButton(row,text='Seleccionar vídeo',command=lambda i=i:self.choose_video(i),bg=PANEL,fg=FG,
                          padx=12,pady=7,font=('Segoe UI',9),outline='#414b56',icon='folder').pack(side='right',padx=(8,0))
            details=tk.Frame(row,bg=PANEL);details.pack(side='left',fill='both',expand=True)
            filename=os.path.basename(self.paths[i]) or 'Ningún archivo seleccionado'
            if len(filename)>30:filename=filename[:27]+'…'
            tk.Label(details,text=filename,bg=PANEL,fg=FG,font=('Segoe UI',9),anchor='w').pack(fill='x',pady=(1,5))
            m=self.metas[i]
            info=f"{m['width']} × {m['height']} · {m['fps']:g} fps · {'Audio' if m['audio'] else 'Sin audio'}" if m else 'MP4 · MOV · MKV · AVI'
            tk.Label(details,text=info,bg=PANEL,fg=MUTED,font=('Segoe UI',8),anchor='w').pack(fill='x')
        actions=tk.Frame(self.body,bg=BG);actions.pack(fill='x',pady=(14,0))
        self.button(actions,'Siguiente: Sincronización  →',lambda:self.show(1),True).pack(side='right')
    def choose_video(self,i):
        p=filedialog.askopenfilename(filetypes=[('Vídeo','*.mp4 *.mov *.mkv *.avi *.m4v'),('Todos','*.*')]);
        if not p:return
        try:m=ffprobe(p)
        except Exception as e:messagebox.showerror('Error al leer vídeo',str(e));return
        self.paths[i]=p;self.metas[i]=m;self.rects[i]=None;self.intervals=[];self.show(self.current)
    def require(self):
        if not all(self.paths):messagebox.showwarning('Faltan vídeos','Carga el vídeo principal y el backup.');return False
        return True
    def task(self,fn):
        if self.busy:return
        self.busy=True;self.status.config(text='Procesando…')
        def run():
            try:self.q.put(('ok',fn()))
            except Exception as e:self.q.put(('error',str(e)))
        threading.Thread(target=run,daemon=True).start()
    def poll(self):
        try:
            while True:
                kind,data=self.q.get_nowait();self.busy=False
                if kind=='error':self.status.config(text='Error');messagebox.showerror('Error',data)
                else:
                    if callable(data):data()
                    self.status.config(text='Preparado')
        except queue.Empty:pass
        self.root.after(100,self.poll)
    def page_sync(self):
        self.title('2. Sincronización de pistas')
        p=self.panel(self.body);p.pack(fill='x')
        self.label(p,'Método de sincronización',12).pack(anchor='w',pady=(0,8))
        for mode in ['Audio','Imagen','Manual']:
            tk.Radiobutton(p,text=mode,variable=self.syncmode,value=mode,bg=PANEL,fg=FG,selectcolor=DARK,activebackground=PANEL,activeforeground=ORANGE,font=('Segoe UI',9)).pack(side='left',padx=15)
        f=self.panel(self.body);f.pack(fill='x',pady=10)
        self.label(f,'Desfase del backup respecto al principal (segundos):',11).pack(anchor='w')
        self.entry(f,self.offset).pack(anchor='w',pady=9)
        self.label(f,'Tiempo backup = tiempo principal + desfase. Puedes corregir el valor manualmente.',10,MUTED).pack(anchor='w')
        self.button(self.body,'Sincronizar por método seleccionado',self.start_sync,True).pack(anchor='w',pady=10)
        self.button(self.body,'Siguiente: Seleccionar zonas →',lambda:self.show(2)).pack(anchor='e')
    def start_sync(self):
        if not self.require():return
        if self.syncmode.get()=='Manual':messagebox.showinfo('Sincronización manual','Introduce el desfase en segundos (puede ser negativo).');return
        def job():
            if self.syncmode.get()=='Audio':off,conf=sync_audio(*self.paths)
            else:off,conf=sync_image(*self.paths,*self.metas)
            return lambda:(self.offset.set(round(off,3)),messagebox.showinfo('Sincronización',f'Desfase estimado: {off:.3f} s\nConfianza aproximada: {conf:.2f}\nVerifica visualmente antes de exportar.'))
        self.task(job)
    def page_zones(self):
        self.title('3. Seleccionar zonas de sustitución y detectar fallos')
        row=tk.Frame(self.body,bg=BG);row.pack(fill='x')
        for i,name in enumerate(['Principal: zona negra','Backup: zona de reemplazo']):
            p=self.panel(row);p.pack(side='left',fill='both',expand=True,padx=5)
            self.label(p,name,12).pack(anchor='w')
            self.button(p,'Seleccionar rectángulo',lambda i=i:self.select_roi(i),True).pack(anchor='w',pady=10)
            self.label(p,str(self.rects[i]) if self.rects[i] else 'Sin selección',10,MUTED).pack(anchor='w')
        opts=self.panel(self.body);opts.pack(fill='x',pady=12)
        self.label(opts,'Umbral de negro (0–255):').pack(side='left');self.entry(opts,self.threshold,6).pack(side='left',padx=8)
        self.label(opts,'Margen antes/después (s):').pack(side='left',padx=(20,0));self.entry(opts,self.pad,7).pack(side='left',padx=8)
        self.button(self.body,'Analizar fallos negros',self.analyze,True).pack(anchor='w')
        self.label(self.body,f'Fallos detectados: {len(self.intervals)}',12,ORANGE).pack(anchor='w',pady=10)
        listbox=tk.Listbox(self.body,bg=PANEL,fg=FG,selectbackground=ORANGE,relief='flat',height=6)
        listbox.pack(fill='both',expand=True)
        for a,b in self.intervals:listbox.insert('end',f'{a:10.3f} s  —  {b:10.3f} s     ({b-a:.3f} s)')
        self.button(self.body,'Siguiente: Audio →',lambda:self.show(3)).pack(anchor='e',pady=10)
    def select_roi(self,i):
        if not self.paths[i]:messagebox.showwarning('Falta vídeo','Primero carga el vídeo.');return
        try:
            rgb=frame_at(self.paths[i],min(5,self.metas[i]['duration']/2));h,w=rgb.shape[:2]
            maxw,maxh=960,540;factor=min(1,maxw/w,maxh/h)
            shown=cv2.resize(rgb,(int(w*factor),int(h*factor)))
            # OpenCV's native rectangle selector supports drag and resize before confirmation.
            box=cv2.selectROI('Arrastra un rectangulo - ENTER para aceptar',cv2.cvtColor(shown,cv2.COLOR_RGB2BGR),False,False)
            cv2.destroyAllWindows()
            if box[2]>0 and box[3]>0:self.rects[i]=tuple(int(round(v/factor)) for v in box);self.show(2)
        except Exception as e:messagebox.showerror('Selección',str(e))
    def analyze(self):
        if not self.require():return
        if not self.rects[0] or not self.rects[1]:messagebox.showwarning('Zonas','Selecciona los dos rectángulos.');return
        try:
            th=int(self.threshold.get());pad=float(self.pad.get())
            if not (0<=th<=255 and 0<=pad<=5):raise ValueError()
        except:messagebox.showwarning('Parámetros','Usa un umbral 0–255 y margen 0–5 s.');return
        def job():
            intervals=black_intervals(self.paths[0],self.rects[0],self.metas[0],th,padding=pad)
            return lambda:(setattr(self,'intervals',intervals),self.show(2),messagebox.showinfo('Análisis terminado',f'{len(intervals)} intervalos detectados'))
        self.task(job)
    def page_audio(self):
        self.title('4. Nivelación de pista de audio')
        p=self.panel(self.body);p.pack(fill='x')
        tk.Checkbutton(p,text='Normalizar automáticamente el audio original',variable=self.normalize,bg=PANEL,fg=FG,selectcolor=DARK,activebackground=PANEL,activeforeground=ORANGE,font=('Segoe UI',9)).pack(anchor='w')
        self.label(p,'Objetivo de sonoridad (LUFS):',11).pack(anchor='w',pady=(15,4));self.entry(p,self.lufs).pack(anchor='w')
        self.label(p,'Se mantiene el audio del vídeo principal. La normalización utiliza FFmpeg loudnorm.',10,MUTED).pack(anchor='w',pady=12)
        self.button(self.body,'Siguiente: Relación de aspecto →',lambda:self.show(4),True).pack(anchor='e',pady=10)
    def page_aspect(self):
        self.title('5. Relación de aspecto — vídeo final reparado')
        p=self.panel(self.body);p.pack(fill='x')
        self.label(p,'Aplicar al vídeo completo (presentación + sustituciones).',11,MUTED).pack(anchor='w',pady=(0,16))
        row=tk.Frame(p,bg=PANEL);row.pack(anchor='w')
        for mode in ['Horizontal','Vertical']:
            tk.Radiobutton(row,text=mode,variable=self.axis,value=mode,bg=PANEL,fg=FG,selectcolor=DARK,activebackground=PANEL,activeforeground=ORANGE,font=('Segoe UI',9)).pack(side='left',padx=(0,25))
        self.label(p,'Porcentaje (+ estira / − comprime):',11).pack(anchor='w',pady=(15,5))
        self.entry(p,self.percent,10).pack(anchor='w')
        self.button(p,'Restablecer 0 %',lambda:self.percent.set('0')).pack(anchor='w',pady=10)
        self.label(p,'La deformación se aplica justo antes de exportar; no modifica los archivos originales.',10,MUTED).pack(anchor='w')
        self.button(self.body,'Siguiente: Exportación →',lambda:self.show(5),True).pack(anchor='e',pady=10)
    def page_export(self):
        self.title('6. Exportación — lugar de guardado y nombre')
        p=self.panel(self.body);p.pack(fill='x')
        self.label(p,'Archivo de salida (.mp4)',12).pack(anchor='w')
        row=tk.Frame(p,bg=PANEL);row.pack(fill='x',pady=10)
        self.entry(row,self.output,70).pack(side='left',fill='x',expand=True)
        self.button(row,'Examinar…',self.choose_output).pack(side='left',padx=8)
        self.label(p,'Formato: MP4 · H.264 · audio AAC · resolución y fps del principal',10,MUTED).pack(anchor='w',pady=8)
        self.label(p,f'Intervalos para reparar: {len(self.intervals)}',11,ORANGE).pack(anchor='w')
        self.button(self.body,'Reparar y exportar vídeo',self.export,True).pack(anchor='w',pady=12)
    def choose_output(self):
        p=filedialog.asksaveasfilename(defaultextension='.mp4',filetypes=[('MP4','*.mp4')],initialfile='Evento_Reparado.mp4')
        if p:self.output.set(p)
    def export(self):
        if not self.require():return
        if not self.rects[0] or not self.rects[1]:messagebox.showwarning('Zonas','Selecciona ambas zonas antes de exportar.');return
        if not self.intervals and not messagebox.askyesno('Sin fallos','No hay fallos detectados. ¿Exportar igualmente?'):return
        dest=self.output.get().strip()
        if not dest:messagebox.showwarning('Destino','Elige nombre y ubicación de salida.');return
        if os.path.normcase(os.path.realpath(dest)) in [os.path.normcase(os.path.realpath(p)) for p in self.paths]:messagebox.showerror('Destino','No se puede sobrescribir una grabación original.');return
        try:
            percent=float(self.percent.get());lufs=float(self.lufs.get());off=float(self.offset.get())
            if not all(math.isfinite(v) for v in (percent,lufs,off)) or percent<=-100 or percent>300:raise ValueError('Porcentaje fuera de rango (-99 a +300).')
            if not -30<=lufs<=-5:raise ValueError('LUFS fuera de rango (-30 a -5).')
            if not os.path.isdir(os.path.dirname(os.path.abspath(dest))):raise ValueError('La carpeta no existe.')
        except Exception as e:messagebox.showerror('Parámetros',str(e));return
        def job():
            self.render(dest,percent,lufs,off)
            return lambda:messagebox.showinfo('Exportación completada',f'Vídeo guardado en:\n{dest}')
        self.task(job)
    def render(self,dest,percent,lufs,off):
        m=self.metas[0];x,y,w,h=self.rects[0];bx,by,bw,bh=self.rects[1]
        # Shift backup by timestamp, clip to main's time axis. Positive off means backup is ahead.
        # PTS of backup output = original backup PTS - offset.
        filters=[f'[1:v]crop={bw}:{bh}:{bx}:{by},scale={w}:{h},setpts=PTS-STARTPTS-({off:.6f})/TB[backup]']
        current='[0:v]';
        for i,(a,b) in enumerate(self.intervals):
            name=f'v{i}'
            filters.append(f'{current}[backup]overlay={x}:{y}:enable=\'between(t,{a:.6f},{b:.6f})\':eof_action=pass:repeatlast=0[{name}]')
            current=f'[{name}]'
            # split backup feed if reused; handled below by constructing independent crop per overlay
        # Replace repeated backup references with independently labeled branches.
        if len(self.intervals)>1:
            filters=[f'[1:v]crop={bw}:{bh}:{bx}:{by},scale={w}:{h},setpts=PTS-STARTPTS-({off:.6f})/TB,split={len(self.intervals)}'+''.join(f'[b{i}]' for i in range(len(self.intervals)))]
            current='[0:v]'
            for i,(a,b) in enumerate(self.intervals):
                name=f'v{i}';filters.append(f'{current}[b{i}]overlay={x}:{y}:enable=\'between(t,{a:.6f},{b:.6f})\':eof_action=pass:repeatlast=0[{name}]');current=f'[{name}]'
        # For no failures, no backup branch is needed.
        if not self.intervals:filters=[];current='[0:v]'
        factor=1+percent/100
        if abs(percent)>1e-8:
            if self.axis.get()=='Horizontal':
                nw=max(2,round(m['width']*factor/2)*2);nh=m['height']
            else:
                nw=m['width'];nh=max(2,round(m['height']*factor/2)*2)
            filters.append(f'{current}scale={nw}:{nh},crop=w=min(iw\\,{m["width"]}):h=min(ih\\,{m["height"]}),pad={m["width"]}:{m["height"]}:(ow-iw)/2:(oh-ih)/2,setsar=1[vout]')
        else:filters.append(f'{current}null[vout]')
        cmd=['ffmpeg','-hide_banner','-y','-i',self.paths[0],'-i',self.paths[1],'-filter_complex',';'.join(filters),'-map','[vout]']
        if m['audio']:
            if self.normalize.get():cmd+=['-af',f'loudnorm=I={lufs}:TP=-1.5:LRA=11']
            cmd+=['-map','0:a:0','-c:a','aac','-b:a','192k']
        else:cmd+=['-an']
        cmd+=['-c:v','libx264','-preset','fast','-crf','19','-pix_fmt','yuv420p','-t',str(m['duration']),'-movflags','+faststart',dest]
        p=run_process(cmd,capture_output=True,text=True)
        if p.returncode:raise RuntimeError(p.stderr[-3000:])

if __name__=='__main__' and '--self-test' in sys.argv:
    import selftest
    sys.exit(selftest.run(sys.modules[__name__], sys.argv[sys.argv.index('--self-test')+1]))

if __name__=='__main__':
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        root=tk.Tk();root.withdraw();messagebox.showerror('Falta FFmpeg','No se encuentran FFmpeg y FFprobe dentro de la aplicación.');sys.exit(1)
    root=tk.Tk();App(root);root.mainloop()
