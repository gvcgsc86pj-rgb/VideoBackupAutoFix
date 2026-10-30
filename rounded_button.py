"""Botones compactos con radio de 3 puntos y navegación por teclado."""
import tkinter as tk
from tkinter import font as tkfont
from PIL import Image, ImageDraw, ImageTk


class RoundedButton(tk.Canvas):
    def __init__(self, parent, text, command, bg, fg, font=('Segoe UI', 10), padx=14, pady=7, variant='button', outline=None, icon=None):
        self.button_bg, self.button_fg = bg, fg
        self.command, self.text = command, text
        self.variant, self.outline, self.icon = variant, outline, icon
        self.active = False
        self.button_font = tkfont.Font(root=parent, font=font)
        self.hovered = self.pressed = False
        self.radius = float(parent.tk.call('tk', 'scaling')) * 3
        super().__init__(parent, width=self.button_font.measure(text)+padx*2+(24 if icon else 0),
                         height=self.button_font.metrics('linespace')+pady*2,
                         bg=parent.cget('bg'), highlightthickness=0, borderwidth=0,
                         takefocus=True, cursor='hand2')
        self.bind('<Configure>', self._draw)
        self.bind('<Enter>', lambda e:self._state(hovered=True))
        self.bind('<Leave>', lambda e:self._state(hovered=False, pressed=False))
        self.bind('<ButtonPress-1>', self._down)
        self.bind('<ButtonRelease-1>', self._up)
        self.bind('<Return>', self._invoke)
        self.bind('<space>', self._invoke)
        self.bind('<FocusIn>', self._draw)
        self.bind('<FocusOut>', self._draw)
        self.after_idle(self._draw)

    def configure(self, cnf=None, **kw):
        if isinstance(cnf, dict):
            kw = {**cnf, **kw}; cnf = None
        changed = False
        for key, attribute in [('bg','button_bg'), ('fg','button_fg')]:
            if key in kw:
                setattr(self, attribute, kw.pop(key)); changed = True
        result = super().configure(cnf, **kw) if cnf is not None or kw else None
        if changed:
            self._draw()
        return result

    config = configure

    def set_active(self, active):
        self.active = active
        self._draw()

    def _state(self, **kw):
        for key,value in kw.items(): setattr(self,key,value)
        self._draw()

    def _down(self, event):
        self.focus_set(); self._state(pressed=True)

    def _up(self, event):
        invoke = self.pressed and 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height()
        self._state(pressed=False)
        if invoke: self._invoke()

    def _invoke(self, event=None):
        self.command()
        return 'break'

    def _draw(self, event=None):
        if not self.winfo_exists(): return
        w,h = self.winfo_width(), self.winfo_height()
        if w < 2 or h < 2: return
        if self.variant == 'tab':
            self.delete('all')
            self.create_line(w-1,7,w-1,h-8,fill='#252a30')
            self.create_text(w/2,h/2-1,text=self.text,font=self.button_font,
                             fill='#ff9a3d' if self.active else '#a8b0bc')
            if self.active:
                self.create_line(10,h-2,w-10,h-2,fill='#ff9a3d',width=2)
            if self.focus_get() == self:
                self.create_rectangle(3,3,w-4,h-5,outline='#57616e')
            return
        fill = self.button_bg
        if self.hovered or self.pressed:
            rgb = self.winfo_rgb(fill)
            delta = -12 if self.pressed else 12
            fill = '#'+''.join(f'{max(0,min(255,c//257+delta)):02x}' for c in rgb)
        scale = 3
        image = Image.new('RGB',(w*scale,h*scale),self.master.cget('bg'))
        draw = ImageDraw.Draw(image)
        focused = self.focus_get() == self
        draw.rounded_rectangle((scale,scale,(w-1)*scale,(h-1)*scale),
                               radius=self.radius*scale,fill=fill,
                               outline='#ff943d' if focused else (self.outline or fill),width=scale)
        self._image = ImageTk.PhotoImage(image.resize((w,h),Image.Resampling.LANCZOS),master=self)
        self.delete('all')
        self.create_image(0,0,anchor='nw',image=self._image)
        text_width = self.button_font.measure(self.text)
        if self.icon == 'folder':
            x = (w-text_width-24)/2; y = h/2-6
            self.create_line(x,y+1,x+6,y+1,x+9,y+4,x+17,y+4,x+17,y+13,x,y+13,x,y+1,
                             fill='#ff9a3d',width=1.4,joinstyle='round')
        self.create_text(w/2+(12 if self.icon else 0),h/2,text=self.text,fill=self.button_fg,font=self.button_font)
