"""Pruebas funcionales que también se ejecutan desde el EXE empaquetado."""
import json
import os
from pathlib import Path
import tempfile
import traceback
import wave


def run(app, report_path):
    report = {'status': 'running', 'checks': [], 'platform': os.name}
    root = None
    def passed(name):
        report['checks'].append(name)
    try:
        import numpy as np
        import tkinter as tk
        with tempfile.TemporaryDirectory(prefix='AutoFix prueba ñ ') as td:
            td = Path(td)
            def ff(*args):
                result = app.run_process(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', *map(str, args)], capture_output=True, text=True)
                if result.returncode:
                    raise RuntimeError(result.stderr)
            for tool in ['ffmpeg', 'ffprobe']:
                r = app.run_process([tool, '-version'], capture_output=True, text=True, check=True)
                report[tool] = r.stdout.splitlines()[0]
            passed('FFmpeg y FFprobe disponibles')
            rng = np.random.default_rng(42)
            rate = 16000
            envelope = np.repeat(rng.uniform(.05, .8, 200), rate // 20)
            sound = (rng.uniform(-1, 1, len(envelope)) * envelope * 20000).astype('<i2')
            wav = td / 'audio.wav'
            with wave.open(str(wav), 'wb') as out:
                out.setnchannels(1); out.setsampwidth(2); out.setframerate(rate); out.writeframes(sound.tobytes())
            main = td / 'principal ñ.mp4'
            backup = td / 'respaldo ñ.mp4'
            ff('-f', 'lavfi', '-i', 'color=c=blue:s=320x180:r=25:d=10', '-i', wav,
               '-vf', "drawbox=x=40:y=40:w=80:h=60:color=black:t=fill:enable='between(t,2,3)+between(t,6,7)'",
               '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', main)
            ff('-f', 'lavfi', '-i', 'color=c=red:s=320x180:r=25:d=10', '-i', wav,
               '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', backup)
            mm, mb = app.ffprobe(str(main)), app.ffprobe(str(backup))
            assert (mm['width'], mm['height']) == (320, 180) and mm['audio']
            passed('Lectura de vídeos y rutas con espacios y tildes')
            off, confidence = app.sync_audio(str(main), str(backup))
            assert abs(off) <= .1, (off, confidence)
            passed('Sincronización por audio')
            pattern = td / 'patron.mp4'
            ff('-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=25:d=10', '-c:v', 'libx264', pattern)
            mp = app.ffprobe(str(pattern))
            off, confidence = app.sync_image(str(pattern), str(pattern), mp, mp)
            assert abs(off) <= .1, (off, confidence)
            passed('Sincronización por imagen')
            intervals = app.black_intervals(str(main), (40,40,80,60), mm, padding=0)
            assert len(intervals) == 2, intervals
            assert abs(intervals[0][0]-2) < .1 and abs(intervals[1][0]-6) < .1
            passed('Detección de dos fallos negros')
            root = tk.Tk()
            ui_errors = []
            root.report_callback_exception = lambda *exc: ui_errors.append(str(exc))
            ui = app.App(root)
            ui.paths = [str(main),str(backup)]; ui.metas = [mm, mb]
            ui.rects = [(40,40,80,60), (40,40,80,60)]
            for page in range(6):
                ui.show(page); root.update()
                assert ui.current == page and ui.body.winfo_children()
            root.after(250, root.quit); root.mainloop()
            assert not ui_errors, ui_errors
            passed('Apertura, animación y seis espacios de trabajo')
            for count in [0,1,2]:
                ui.intervals = intervals[:count]
                out = td / ('reparado%d.mp4' % count)
                ui.render(str(out), 0, -16, 0)
                metadata = app.ffprobe(str(out))
                assert metadata['audio'] and abs(metadata['duration']-10) < .2
                assert (metadata['width'],metadata['height']) == (320,180)
                rgb = app.frame_at(str(out), 2.5)[60,60]
                assert (rgb[0] > 180) if count else (rgb.max() < 35), rgb
                rgb = app.frame_at(str(out), 6.5)[60,60]
                assert (rgb[0] > 180) if count == 2 else (rgb.max() < 35), rgb
                assert app.frame_at(str(out), 1)[60,60,2] > 180
                assert app.frame_at(str(out), 2.5)[120,200,2] > 180
            passed('Exportación H.264/AAC con cero, uno y dos fallos; píxeles reparados y exterior preservado')
            ui.intervals = intervals
            for axis, percent in [('Horizontal', 20), ('Vertical', -20)]:
                ui.axis.set(axis); ui.normalize.set(True)
                out = td / (axis+'.mp4')
                ui.render(str(out), percent, -16, 0)
                metadata = app.ffprobe(str(out))
                assert (metadata['width'],metadata['height']) == (320,180) and metadata['audio']
            passed('Relación de aspecto en ambos ejes y normalización de audio')
            ui.normalize.set(False)
            for offset in [-.5, .5]:
                out = td / ('desfase%s.mp4' % offset)
                ui.render(str(out), 0, -16, offset)
                assert app.frame_at(str(out), 2.5)[60,60,0] > 180
            passed('Exportación con desfase manual positivo y negativo')
        report['status'] = 'passed'
        return_code = 0
    except Exception:
        report['status'] = 'failed'; report['error'] = traceback.format_exc(); return_code = 1
    finally:
        if root is not None:
            root.destroy()
        Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return return_code
