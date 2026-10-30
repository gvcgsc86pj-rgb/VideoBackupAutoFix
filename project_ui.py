import os
import tkinter as tk
from tkinter import filedialog,messagebox
import project_io
from theme import BG,PANEL,FG,MUTED,ORANGE


class ProjectMixin:
    def init_project(self):
        self.project_path='';self.dirty=False;self._restoring=False
        self.project_vars={'offset':self.offset,'sync_method':self.syncmode,'threshold':self.threshold,
                           'padding':self.pad,'lufs':self.lufs,'normalize':self.normalize,
                           'axis':self.axis,'percent':self.percent}
        for var in [*self.project_vars.values(),self.output,self.export_start,self.export_end]:
            var.trace_add('write',self.mark_dirty)
        self.root.protocol('WM_DELETE_WINDOW',self.close_project)

    def mark_dirty(self,*args):
        if self._restoring:return
        self.dirty=True;self.update_project_title()

    def update_project_title(self):
        name=os.path.basename(self.project_path) if self.project_path else 'Nuevo proyecto'
        self.root.title('Video Backup AutoFix 2.0 — '+name+(' *' if self.dirty else ''))

    def confirm_project_change(self):
        if self.busy:
            messagebox.showinfo('Procesando','Espera a que termine la operación.');return False
        if not self.dirty:return True
        choice=messagebox.askyesnocancel('Guardar proyecto','¿Quieres guardar los cambios de este proyecto?')
        return False if choice is None else (self.save_project_dialog() if choice else True)

    def project_data(self):
        return {'format':project_io.FORMAT,'schema_version':1,'app_version':'2.0',
                'videos':list(self.paths),'settings':{k:v.get() for k,v in self.project_vars.items()},
                'rectangles':[list(r) if r else None for r in self.rects],
                'intervals':[list(r) for r in self.intervals],
                'export':{'output':self.output.get(),'start':self.export_start.get(),'end':self.export_end.get()}}

    def save_project_dialog(self):
        path=self.project_path or filedialog.asksaveasfilename(title='Guardar proyecto',
            defaultextension='.toñadas',filetypes=[('Proyecto AutoFix','*.toñadas')],initialfile='Mi proyecto.toñadas')
        if not path:return False
        try:
            project_io.save_project(path,self.project_data())
            self.project_path=path;self.dirty=False;self.update_project_title()
            self.status.config(text='Proyecto guardado')
            return True
        except Exception as exc:
            messagebox.showerror('Guardar proyecto',str(exc));return False

    def open_project_dialog(self):
        if not self.confirm_project_change():return
        path=filedialog.askopenfilename(title='Abrir proyecto',filetypes=[('Proyecto AutoFix','*.toñadas'),('Todos','*.*')])
        if path:self.open_project_path(path)

    def open_project_path(self,path):
        try:
            data=project_io.load_project(path)
            metas=[];relinked=False
            for index,video in enumerate(data['videos']):
                if video and not os.path.isfile(video):
                    messagebox.showinfo('Localizar vídeo','No se encuentra:\n'+video+'\n\nSelecciona su nueva ubicación.')
                    replacement=filedialog.askopenfilename(title='Localizar vídeo '+('principal' if index==0 else 'backup'))
                    if not replacement:return False
                    data['videos'][index]=video=replacement;relinked=True
                meta=self.probe_video(video) if video else None
                metas.append(meta)
                rect=data['rectangles'][index]
                if rect and meta and (rect[0]+rect[2]>meta['width'] or rect[1]+rect[3]>meta['height']):
                    raise ValueError('Una zona guardada queda fuera del vídeo. Abre el vídeo original.')
            duration=metas[0]['duration'] if metas[0] else 0
            if duration and (data['export']['start']>=duration or data['export']['end']>duration+.1):
                raise ValueError('El tramo guardado queda fuera del vídeo principal.')
            self.stop_preview();self._restoring=True
            try:
                self.paths=data['videos'];self.metas=metas
                self.rects=[tuple(r) if r else None for r in data['rectangles']]
                self.intervals=[tuple(i) for i in data['intervals']]
                for key,var in self.project_vars.items():var.set(data['settings'][key])
                self.output.set(data['export']['output']);self.export_start.set(data['export']['start'])
                self.export_end.set(data['export']['end'] or duration);self.preview_pos.set(self.export_start.get())
                self.project_path=os.path.abspath(path);self.dirty=relinked
            finally:self._restoring=False
            self.show(0);self.update_project_title();self.status.config(text='Proyecto abierto')
            return True
        except Exception as exc:
            self._restoring=False;messagebox.showerror('Abrir proyecto',str(exc));return False

    def new_project(self):
        if not self.confirm_project_change():return
        self.stop_preview();self._restoring=True
        try:
            self.paths=['',''];self.metas=[None,None];self.rects=[None,None];self.intervals=[]
            defaults={'offset':0,'sync_method':'Imagen','threshold':18,'padding':.15,
                      'lufs':-16,'normalize':False,'axis':'Vertical','percent':0}
            for key,var in self.project_vars.items():var.set(defaults[key])
            self.output.set('');self.export_start.set(0);self.export_end.set(0);self.preview_pos.set(0)
            self.project_path='';self.dirty=False
        finally:self._restoring=False
        self.show(0);self.update_project_title();self.status.config(text='Preparado')

    def show_start(self):
        for b in self.tab_buttons:b.set_active(False)
        for child in self.body.winfo_children():child.destroy()
        box=tk.Frame(self.body,bg=BG);box.pack(expand=True)
        tk.Label(box,text='Video Backup AutoFix',font=('Segoe UI',23,'bold'),bg=BG,fg=FG).pack(pady=(0,8))
        tk.Label(box,text='Un nuevo proyecto o justo donde lo dejaste.',font=('Segoe UI',10),bg=BG,fg=MUTED).pack(pady=(0,26))
        row=tk.Frame(box,bg=BG);row.pack()
        self.button(row,'Crear nuevo',self.new_project,True).pack(side='left',padx=6)
        self.button(row,'Abrir proyecto .toñadas',self.open_project_dialog).pack(side='left',padx=6)
        tk.Label(box,text='Los proyectos guardan ajustes y referencias a tus vídeos.',font=('Segoe UI',8),bg=BG,fg=MUTED).pack(pady=20)
        self.current=-1

    def close_project(self):
        if not self.confirm_project_change():return
        self.stop_preview();self.root.destroy()
