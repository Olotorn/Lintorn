# Lintorn
"""La ligne qui tourne pendant l'audit : sans elle, on croit la machine gelée."""

from __future__ import annotations

import shutil
import sys
import threading
import time

# ASCII seulement : le hook tourne aussi sous Git Bash, qui affiche mal l'UTF-8.
_TOURS = "|/-\\"
_PERIODE = 0.1


class Attente:
    """Annonce l'étape en cours, et depuis combien de temps elle dure.

    Seulement dans un TERMINAL : redirigée dans un fichier ou lue par la CI,
    une ligne réécrite cent fois ne serait que du bruit. Elle part sur la
    sortie d'erreur, pour ne jamais se mêler aux résultats. L'animation ne
    démarre qu'à la première étape : la question de l'accord, posée avant,
    ne doit pas être couverte.
    """

    def __init__(self, flux=None):
        self.flux = flux if flux is not None else sys.stderr
        try:
            self.actif = bool(self.flux.isatty())
        except (AttributeError, ValueError):
            self.actif = False
        self._nom = ""
        self._debut = 0.0
        self._fin = threading.Event()
        self._fil: threading.Thread | None = None
        self._largeur = 0

    def etape(self, nom: str) -> None:
        self._nom, self._debut = nom, time.monotonic()
        if self.actif and self._fil is None:
            self._fil = threading.Thread(target=self._tourner, daemon=True)
            self._fil.start()

    def _tourner(self) -> None:
        tour = 0
        while not self._fin.is_set():
            secondes = int(time.monotonic() - self._debut)
            ligne = f"{_TOURS[tour % len(_TOURS)]} Lintorn travaille : {self._nom}"
            if secondes >= 2:
                ligne += f" - {secondes} s"
            # Plus courte que le terminal : une ligne qui déborde se replie, et
            # le retour chariot n'efface plus que sa dernière moitié.
            ligne = ligne[:max(shutil.get_terminal_size().columns - 1, 10)]
            self._ecrire("\r" + ligne.ljust(self._largeur))
            self._largeur = len(ligne)
            tour += 1
            self._fin.wait(_PERIODE)

    def _ecrire(self, texte: str) -> None:
        try:
            self.flux.write(texte)
            self.flux.flush()
        except (OSError, ValueError, UnicodeError):
            self.actif = False
            self._fin.set()

    def __enter__(self) -> Attente:
        return self

    def __exit__(self, *_exception) -> None:
        self._fin.set()
        if self._fil is not None:
            self._fil.join()
            self._ecrire("\r" + " " * self._largeur + "\r")
