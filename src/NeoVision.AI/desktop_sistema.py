"""

NeoVision IA — aplicação de ambiente de trabalho só em Python (janela + API local).

Usa pywebview (WebView2 no Windows) e Uvicorn num processo filho.



O filho é arrancado via variável de ambiente NEOVISION_EMBED_HTTP (o PyInstaller nem

sempre repassa argumentos extra ao reexecutar o .exe; evita ERR_CONNECTION_REFUSED).



Desenvolvimento:

  pip install -r requirements-desktop-sistema.txt

  python desktop_sistema.py



Empacote: build/publish-sistema-desktop-python.ps1 e NeoVision-Sistema.spec

Variante só monitorização de rede: desktop_rede.py, NeoVision-Rede.spec, build/publish-rede-desktop-python.ps1

"""



from __future__ import annotations



import os

import socket

import subprocess

import sys

import time

import json

import urllib.error

import urllib.request



# Marca o processo-filho que só serve HTTP (porta em decimal no valor).

_EMBED_ENV = "NEOVISION_EMBED_HTTP"





def _chdir_for_frozen() -> None:

    if getattr(sys, "frozen", False):

        exedir = os.path.dirname(os.path.abspath(sys.executable))

        if exedir:

            os.chdir(exedir)





def _setup_frozen_logging() -> None:

    """Sem consola (windowed), erros vão para ficheiro ao lado do .exe."""

    if not getattr(sys, "frozen", False):

        return

    try:

        base = os.path.dirname(os.path.abspath(sys.executable))

        log_dir = os.path.join(base, "NeoVisionData")

        os.makedirs(log_dir, exist_ok=True)

        log_path = os.path.join(log_dir, "NeoVision-desktop.log")

        f = open(log_path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115

        sys.stderr = f

        sys.stdout = f

    except OSError:

        pass





def _log_line(msg: str) -> None:

    try:

        print(f"[NeoVision] {msg}", flush=True)

    except Exception:

        pass





def _fatal_message(msg: str, title: str = "NeoVision IA") -> None:

    if sys.platform == "win32":

        try:

            import ctypes



            ctypes.windll.user32.MessageBoxW(None, msg, title, 0x10)  # MB_ICONERROR

        except Exception:

            pass

    try:

        print(msg, file=sys.__stderr__)

    except Exception:

        pass





def _pick_port() -> int:

    for p in (12738, 12739, 12740, 18888):

        try:

            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            s.bind(("127.0.0.1", p))

            s.close()

            return p

        except OSError:

            continue

    return 18888





def _wait_tcp_port(port: int, timeout_sec: float = 90.0) -> bool:

    """Confirma que algo está a escutar em 127.0.0.1:porta (antes de HTTP)."""

    deadline = time.monotonic() + timeout_sec

    while time.monotonic() < deadline:

        try:

            s = socket.create_connection(("127.0.0.1", port), timeout=0.5)

            s.close()

            return True

        except OSError:

            time.sleep(0.05)

    return False





def _wait_health(port: int, timeout_sec: float = 30.0) -> bool:

    t0 = time.monotonic()

    url = f"http://127.0.0.1:{port}/health"

    while time.monotonic() - t0 < timeout_sec:

        try:

            req = urllib.request.Request(url, headers={"Accept": "application/json"})

            with urllib.request.urlopen(req, timeout=1.0) as r:

                if r.status == 200:

                    return True

        except (urllib.error.URLError, OSError):

            pass

        time.sleep(0.2)

    return False





def _resolve_embedded_port() -> int | None:

    """Modo servidor embutido: env (preferido) ou argumentos _uvicorn PORTA."""

    raw = os.environ.get(_EMBED_ENV, "").strip()

    if raw:

        try:

            return int(raw)

        except ValueError:

            return None

    if len(sys.argv) >= 3 and sys.argv[1] == "_uvicorn":

        try:

            return int(sys.argv[2])

        except ValueError:

            return None

    return None





def _embedded_http_boot(port: int) -> None:

    """Só o Uvicorn — processo filho."""

    _setup_frozen_logging()

    _chdir_for_frozen()

    _log_line(f"servidor HTTP a arrancar em 127.0.0.1:{port}")

    try:

        from uvicorn import run



        run(

            "app.main:app",

            host="127.0.0.1",

            port=port,

            reload=False,

            log_level="info",

            access_log=False,

        )

    except BaseException as e:  # noqa: BLE001

        _log_line(f"erro no uvicorn: {e!r}")

        raise





def _launcher_command() -> list[str]:

    """Comando para relançar este módulo (frozen = só o .exe; dev = python + script)."""

    exe = sys.executable

    if getattr(sys, "frozen", False):

        return [exe]

    here = os.path.abspath(__file__)

    return [exe, here]





def _spawn_embedded_server(port: int) -> subprocess.Popen:

    """Processo filho com NEOVISION_EMBED_HTTP — sem depender de argv no bootloader."""

    cmd = _launcher_command()

    env = os.environ.copy()

    env[_EMBED_ENV] = str(port)

    creationflags = 0

    if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):

        creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

    return subprocess.Popen(

        cmd,

        cwd=os.path.dirname(cmd[0]) if getattr(sys, "frozen", False) else None,

        env=env,

        stdin=subprocess.DEVNULL,

        creationflags=creationflags,

    )





def main() -> None:

    import multiprocessing



    multiprocessing.freeze_support()

    os.environ.pop(_EMBED_ENV, None)



    os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost,::1")

    os.environ.setdefault("no_proxy", "127.0.0.1,localhost,::1")



    _setup_frozen_logging()

    _chdir_for_frozen()



    raw = (os.environ.get("NEOVISION_DESKTOP_PORT") or "").strip()

    if raw:

        try:

            port = int(raw)

        except ValueError:

            port = _pick_port()

    else:

        port = _pick_port()



    try:

        import app.main  # noqa: F401

    except Exception as e:  # noqa: BLE001

        _fatal_message(

            "O NeoVision IA não conseguiu carregar a API.\n\n"

            f"Detalhe: {e}\n\n"

            "Veja NeoVisionData\\NeoVision-desktop.log junto ao programa."

        )

        sys.exit(1)



    _log_line(f"a iniciar processo servidor na porta {port}")

    try:

        proc = _spawn_embedded_server(port)

    except OSError as e:

        _fatal_message(

            "Não foi possível iniciar o servidor local.\n\n"

            f"{e}\n\n"

            "Tente executar como utilizador normal com permissão de escrita na pasta do programa."

        )

        sys.exit(1)



    if not _wait_tcp_port(port, timeout_sec=90.0):

        rc = proc.poll()

        hint = (

            f"exit={rc}\n\nAbra NeoVisionData\\NeoVision-desktop.log"

            if rc is not None

            else "A porta não abriu a tempo (firewall/antivírus?). Ver NeoVisionData\\NeoVision-desktop.log"

        )

        try:

            proc.terminate()

            proc.wait(timeout=8)

        except Exception:

            try:

                proc.kill()

            except Exception:

                pass

        _fatal_message("NeoVision IA — servidor TCP não respondeu.\n\n" + hint)

        sys.exit(1)



    if not _wait_health(port, timeout_sec=45.0):

        try:

            proc.terminate()

            proc.wait(timeout=8)

        except Exception:

            try:

                proc.kill()

            except Exception:

                pass

        _fatal_message(

            "NeoVision IA — /health não respondeu.\n\n"

            "Veja NeoVisionData\\NeoVision-desktop.log"

        )

        sys.exit(1)



    try:

        import webview

    except ImportError:

        url = f"http://127.0.0.1:{port}/painel"

        _fatal_message(

            "pywebview não está disponível nesta build.\n\n"

            f"Abra no browser: {url}"

        )

        try:

            if proc.poll() is None:

                proc.terminate()

                proc.wait(timeout=8)

        except Exception:

            try:

                proc.kill()

            except Exception:

                pass

        return



    class _NeoVisionDesktopApi:

        """Pontes JS → Python: abrir DVR (Basic Auth ``user:pass@``).

        Usa página HTML inicial com ``location.href`` para o WebView2 não aplicar os

        cortes típicos de ``Uri``/`Source` só com utilizador embutido. Links ``target=_blank``

        ficam dentro do próprio WebView quando ``OPEN_EXTERNAL_LINKS_IN_BROWSER`` está False.

        """



        def open_dvr_url(self, url: str) -> bool:

            s = url.strip() if isinstance(url, str) else ""

            low = s.lower()

            if not low.startswith(("http://", "https://")) or len(s) > 8128:

                return False



            try:

                u_json = json.dumps(s)

                loading_html = f"""<!DOCTYPE html>

<html lang="pt-BR"><head><meta charset="utf-8"/></head>

<body style="margin:0;background:#ffffff;color:#475569;font:14px system-ui,sans-serif;">

<p id="nv-dvr-ts" style="padding:14px;margin:0">A ligar ao equipamento…</p>

<script>

(function () {{

  try {{

    window.location.href = {u_json};

  }} catch (e) {{

    var m = document.getElementById("nv-dvr-ts");

    if (m) {{

      m.style.color = "#b91c1c";

      m.textContent = "Não foi possível abrir: " + (e.message ? e.message : String(e));

    }}

  }}

}})();

</script>

</body>

</html>"""



                webview.create_window(

                    "DVR / NVR",

                    html=loading_html,

                    width=1320,

                    height=860,

                    resizable=True,

                    background_color="#FFFFFF",

                )

                return True

            except Exception:

                try:

                    _log_line("open_dvr_url falhou (URL omitida)")

                except Exception:

                    pass

                return False



        def save_file_dialog(self, filename: str, content_base64: str) -> bool:

            """Abre diálogo para salvar ficheiro (vindo do JS como base64)."""

            import base64

            from webview import active_window



            win = active_window()

            if not win:

                return False



            try:

                dest = win.create_file_dialog(webview.SAVE_DIALOG, save_filename=filename)

                if not dest:

                    return False



                # Se for lista (alguns backends devolvem lista), pega o primeiro

                target = dest[0] if isinstance(dest, (list, tuple)) else dest

                if not target:

                    return False



                # Converte base64 para binário e grava

                raw = base64.b64decode(content_base64)

                with open(target, "wb") as f:

                    f.write(raw)

                return True

            except Exception as e:

                _log_line(f"save_file_dialog falhou: {e!r}")

                return False



    start_path = (os.environ.get("NEOVISION_DESKTOP_START") or "/painel").strip() or "/painel"

    if not start_path.startswith("/"):

        start_path = "/" + start_path

    url = f"http://127.0.0.1:{port}{start_path}"



    desktop_api = _NeoVisionDesktopApi()

    win_title = (os.environ.get("NEOVISION_DESKTOP_TITLE") or "NeoVision IA").strip() or "NeoVision IA"



    webview.create_window(

        win_title,

        url=url,

        js_api=desktop_api,

        width=1280,

        height=760,

        min_size=(920, 560),

        resizable=True,

        background_color="#F8FAFC",

    )

    try:

        try:

            webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False

        except Exception:

            pass



        if sys.platform == "win32":

            webview.start(gui="edgechromium", debug=False)

        else:

            webview.start(debug=False)

    finally:

        if proc.poll() is None:

            try:

                proc.terminate()

                proc.wait(timeout=10)

            except Exception:

                try:

                    proc.kill()

                except Exception:

                    pass

    sys.exit(0)





if __name__ == "__main__":

    import multiprocessing



    multiprocessing.freeze_support()

    embedded = _resolve_embedded_port()

    if embedded is not None:

        _embedded_http_boot(embedded)

    else:

        main()


