import math
import time
import tkinter as tk
from tkinter import messagebox
import cv2
import numpy as np
from theme import BG,PANEL,DARK,ORANGE,FG,MUTED,BORDER
from video_preview import VideoPreview


def timecode(seconds):
    ms=max(0,round(float(seconds)*1000));hours,ms=divmod(ms,3600000);minutes,ms=divmod(ms,60000);sec,ms=divmod(ms,1000)
    return f'{hours:02}:{minutes:02}:{sec:02}.{ms:03}'


class ExportMixin:
    def init_export(self):
        self.export_start=tk.DoubleVar(value=0);self.export_end=tk.DoubleVar(value=0)
        self.preview_pos=tk.DoubleVar(value=0);self._play_id=None;self._scrub_id=None
        self._playing=False;self._preview_caps={};self._timeline_drag='cursor'
        for var in [self.export_start,self.export_end]:var.trace_add('write',self.update_export_labels)

    def duration(self):return self.metas[0]['duration'] if self.metas[0] else 0

    def stop_preview(self):
        self._playing=False
        for name in ['_play_id','_scrub_id']:
            job=getattr(self,name,None)
            if job:
                self.root.after_cancel(job);setattr(self,name,None)
        for cap in getattr(self,'_preview_caps',{}).values():cap.release()
        self._preview_caps={}

    def page_export(self):
        self.title('Exportación')
        if self.duration() and not self.export_end.get():self.export_end.set(self.duration())
        output=tk.Frame(self.body,bg=PANEL,padx=10,pady=8,highlightthickness=1,highlightbackground=BORDER)
        output.pack(fill='x',pady=(0,8))
        tk.Label(output,text='Archivo MP4',bg=PANEL,fg=MUTED,font=('Segoe UI',8)).pack(side='left',padx=(0,10))
        self.entry(output,self.output,50).pack(side='left',fill='x',expand=True)
        self.button(output,'Examinar…',self.choose_output).pack(side='left',padx=(10,0))
        viewer=tk.Frame(self.body,bg=PANEL,padx=10,pady=8,highlightthickness=1,highlightbackground=BORDER)
        viewer.pack(fill='both',expand=True)
        row=tk.Frame(viewer,bg=PANEL);row.pack(fill='x',pady=(0,6))
        tk.Label(row,text='Vista previa · vídeo reparado',bg=PANEL,fg=FG,font=('Segoe UI',9)).pack(side='left')
        tk.Label(row,text='Vista previa sin audio',bg=PANEL,fg=MUTED,font=('Segoe UI',8)).pack(side='right')
        self.export_viewer=VideoPreview(viewer);self.export_viewer.configure(height=135)
        self.export_viewer.pack(fill='both',expand=True)
        self.timeline=tk.Canvas(viewer,bg=PANEL,height=44,highlightthickness=0,bd=0,cursor='hand2')
        self.timeline.pack(fill='x',pady=(4,0))
        self.timeline.bind('<Configure>',lambda e:self.draw_timeline())
        self.timeline.bind('<Button-1>',self.timeline_down)
        self.timeline.bind('<B1-Motion>',self.timeline_move)
        transport=tk.Frame(viewer,bg=PANEL);transport.pack(fill='x')
        self.play_button=self.button(transport,'Reproducir',self.toggle_preview)
        self.play_button.pack(side='left')
        self.position_label=tk.Label(transport,text=timecode(0),bg=PANEL,fg=FG,font=('Consolas',9));self.position_label.pack(side='left',padx=10)
        for text,command in [('Marcar inicio [',lambda:self.set_mark('start')),('Marcar fin ]',lambda:self.set_mark('end'))]:
            self.button(transport,text,command).pack(side='left',padx=3)
        self.range_label=tk.Label(transport,bg=PANEL,fg=MUTED,font=('Segoe UI',8));self.range_label.pack(side='right')
        marks=tk.Frame(self.body,bg=BG);marks.pack(fill='x',pady=(8,0))
        for label,var in [('Inicio (s)',self.export_start),('Fin (s)',self.export_end)]:
            tk.Label(marks,text=label,bg=BG,fg=MUTED,font=('Segoe UI',8)).pack(side='left',padx=(0,6))
            self.entry(marks,var,9).pack(side='left',padx=(0,16))
        self.button(marks,'Vídeo completo',self.reset_range).pack(side='left')
        actions=tk.Frame(self.body,bg=BG);actions.pack(fill='x',pady=(8,0))
        tk.Label(actions,text=f'H.264 · AAC · {len(self.intervals)} fallos detectados',bg=BG,fg=MUTED,font=('Segoe UI',8)).pack(side='left')
        self.button(actions,'Guardar proyecto',self.save_project_dialog).pack(side='right',padx=(8,0))
        self.button(actions,'Exportar tramo',self.export,True).pack(side='right')
        self.update_export_labels()
        self.scrub_to(min(max(0,self.preview_pos.get()),self.duration()),immediate=True)

    def update_export_labels(self,*args):
        if self.current!=5 or not hasattr(self,'range_label') or not self.range_label.winfo_exists():return
        try:
            start,end=self.export_start.get(),self.export_end.get()
            self.range_label.config(text=f'Tramo: {timecode(start)} — {timecode(end)}')
            self.draw_timeline()
        except (tk.TclError,ValueError):pass

    def timeline_x(self,t):return 12+(max(1,self.timeline.winfo_width()-24)*t/max(.001,self.duration()))
    def timeline_time(self,x):return max(0,min(self.duration(),(x-12)*self.duration()/max(1,self.timeline.winfo_width()-24)))

    def draw_timeline(self):
        if self.current!=5 or not hasattr(self,'timeline') or not self.timeline.winfo_exists():return
        try:start,end=self.export_start.get(),self.export_end.get()
        except tk.TclError:return
        c=self.timeline;c.delete('all');w=c.winfo_width()
        c.create_rectangle(12,17,w-12,25,fill='#343b44',outline='')
        for a,b in self.intervals:
            c.create_rectangle(self.timeline_x(a),18,self.timeline_x(b),24,fill='#7b8794',outline='')
        c.create_rectangle(self.timeline_x(start),20,self.timeline_x(end),23,fill=ORANGE,outline='')
        for t,side in [(start,1),(end,-1)]:
            x=self.timeline_x(t)
            c.create_polygon(x,10,x+side*7,10,x,17,fill=ORANGE)
            c.create_line(x,10,x,30,fill=ORANGE,width=2)
        x=self.timeline_x(self.preview_pos.get());c.create_line(x,15,x,29,fill=FG,width=2)
        c.create_text(12,37,text=timecode(0),anchor='w',fill=MUTED,font=('Segoe UI',7))
        c.create_text(w-12,37,text=timecode(self.duration()),anchor='e',fill=MUTED,font=('Segoe UI',7))

    def timeline_down(self,event):
        self.pause_preview()
        start,end=self.export_start.get(),self.export_end.get()
        distances=[abs(event.x-self.timeline_x(start)),abs(event.x-self.timeline_x(end))]
        self._timeline_drag=('start' if distances[0]<=distances[1] else 'end') if min(distances)<9 else 'cursor'
        self.timeline_move(event)

    def timeline_move(self,event):
        t=self.timeline_time(event.x);step=1/(self.metas[0]['fps'] if self.metas[0] else 25)
        if self._timeline_drag=='start':self.export_start.set(max(0,min(t,self.export_end.get()-step)))
        elif self._timeline_drag=='end':self.export_end.set(min(self.duration(),max(t,self.export_start.get()+step)))
        self.scrub_to(t)

    def scrub_to(self,t,immediate=False):
        self.preview_pos.set(t)
        if hasattr(self,'position_label') and self.position_label.winfo_exists():self.position_label.config(text=timecode(t))
        self.draw_timeline()
        if self._scrub_id:self.root.after_cancel(self._scrub_id);self._scrub_id=None
        if immediate:self.update_preview()
        else:self._scrub_id=self.root.after(70,self.update_preview)

    def _read_preview(self,index,t):
        path=self.paths[index]
        if not path:raise ValueError('No hay vídeo')
        if index not in self._preview_caps:self._preview_caps[index]=cv2.VideoCapture(path)
        cap=self._preview_caps[index]
        cap.set(cv2.CAP_PROP_POS_MSEC,max(0,t)*1000)
        ok,frame=cap.read()
        if not ok:raise ValueError('Fotograma no disponible')
        return cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)

    def preview_rgb(self,t):
        m=self.metas[0];t=min(t,max(0,m['duration']-1/m['fps']))
        frame=self._read_preview(0,t)
        backup_time=t+self.offset.get()
        if all(self.rects) and self.metas[1] and 0<=backup_time<self.metas[1]['duration'] and any(a<=t<=b for a,b in self.intervals):
            other=self._read_preview(1,backup_time);x,y,w,h=self.rects[0];bx,by,bw,bh=self.rects[1]
            patch=other[by:by+bh,bx:bx+bw]
            frame[y:y+h,x:x+w]=cv2.resize(patch,(w,h))
        percent=float(self.percent.get());factor=1+percent/100
        if not math.isfinite(percent) or not 0<factor<=4:raise ValueError('Porcentaje no válido')
        if percent:
            width,height=m['width'],m['height'];nw,nh=width,height
            if self.axis.get()=='Horizontal':nw=max(2,round(width*factor/2)*2)
            else:nh=max(2,round(height*factor/2)*2)
            resized=cv2.resize(frame,(nw,nh));cw,ch=min(width,nw),min(height,nh)
            crop=resized[(nh-ch)//2:(nh-ch)//2+ch,(nw-cw)//2:(nw-cw)//2+cw]
            frame=np.zeros((height,width,3),dtype=np.uint8)
            frame[(height-ch)//2:(height-ch)//2+ch,(width-cw)//2:(width-cw)//2+cw]=crop
        return frame

    def update_preview(self):
        self._scrub_id=None
        if self.current!=5 or not self.metas[0]:return
        try:
            from PIL import Image
            self.export_viewer.source=Image.fromarray(self.preview_rgb(self.preview_pos.get()))
            self.export_viewer.redraw()
        except Exception as exc:self.status.config(text='Vista previa: '+str(exc))

    def set_mark(self,which):
        t=self.preview_pos.get()
        if (which=='start' and t>=self.export_end.get()) or (which=='end' and t<=self.export_start.get()):
            messagebox.showwarning('Tramo','El inicio debe estar antes del final.');return
        (self.export_start if which=='start' else self.export_end).set(round(t,3))

    def reset_range(self):
        self.export_start.set(0);self.export_end.set(self.duration());self.scrub_to(0,immediate=True)

    def pause_preview(self):
        self._playing=False
        if self._play_id:self.root.after_cancel(self._play_id);self._play_id=None
        if hasattr(self,'play_button') and self.play_button.winfo_exists():
            self.play_button.text='Reproducir';self.play_button._draw()

    def toggle_preview(self):
        if self._playing:self.pause_preview();return
        if not self.metas[0]:return
        if self.preview_pos.get()>=self.export_end.get():self.scrub_to(self.export_start.get(),immediate=True)
        self._playing=True;self._play_origin=time.monotonic()-self.preview_pos.get()
        self.play_button.text='Pausar';self.play_button._draw();self.preview_tick()

    def preview_tick(self):
        self._play_id=None
        if not self._playing or self.current!=5:return
        t=time.monotonic()-self._play_origin
        if t>=self.export_end.get():
            self.scrub_to(self.export_end.get(),immediate=True);self.pause_preview();return
        self.scrub_to(t,immediate=True);self._play_id=self.root.after(80,self.preview_tick)
