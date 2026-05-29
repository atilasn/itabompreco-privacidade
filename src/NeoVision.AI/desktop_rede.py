"""

NeoVision IA — atalho de ambiente só para a página **Monitorização de equipamentos** (rede).

Usa a mesma API e base de dados que o NeoVision-Sistema; a janela abre

`/painel/equipamentos-rede?modo=rede` (interface sem atalhos ao painel completo).

Empacote com `NeoVision-Rede.spec` / `build/publish-rede-desktop-python.ps1`.

"""

from __future__ import annotations

import os

os.environ["NEOVISION_DESKTOP_START"] = "/painel/equipamentos-rede?modo=rede"
os.environ["NEOVISION_DESKTOP_TITLE"] = "NeoVision · Monitorização de equipamentos"


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()

    from desktop_sistema import _embedded_http_boot, _resolve_embedded_port, main as _desktop_main

    embedded = _resolve_embedded_port()
    if embedded is not None:
        _embedded_http_boot(embedded)
    else:
        _desktop_main()
