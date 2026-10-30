import tkinter as tk
from PIL import Image, ImageTk


class VideoPreview(tk.Canvas):
    """Static source preview, resized only when its panel changes size."""
    def __init__(self, parent, rgb=None):
        super().__init__(parent,bg='#0e1012',height=225,width=320,
                         highlightthickness=1,highlightbackground='#30363d',borderwidth=0)
        self.source = Image.fromarray(rgb) if rgb is not None else None
        self.bind('<Configure>',self.redraw)

    def redraw(self,event=None):
        w,h=self.winfo_width(),self.winfo_height()
        if min(w,h)<8:return
        self.delete('all')
        if self.source is not None:
            img=self.source.copy()
            img.thumbnail((w-12,h-12),Image.Resampling.LANCZOS)
            self.photo=ImageTk.PhotoImage(img,master=self)
            self.create_image(w/2,h/2,image=self.photo)
        else:
            self.create_text(w/2,h/2-13,text='▷',fill='#59616b',font=('Segoe UI',25))
            self.create_text(w/2,h/2+22,text='Sin vídeo seleccionado',fill='#87909d',font=('Segoe UI',9))
