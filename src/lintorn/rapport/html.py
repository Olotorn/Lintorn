# Lintorn
"""Le rapport en PAGE HTML — le même contenu que `rapport.md`, en plus lisible.

⚠️ CE MODULE NE DÉCIDE RIEN. Il n'ajoute aucun verdict, n'en retire aucun, ne
calcule aucun chiffre que le Markdown n'aurait pas : il REND la même liste de
`Resultat`. Deux rapports qui se contrediraient seraient pires que pas de
page du tout — c'est la règle « deux gabarits pour un document = deux
vérités », et elle vaut ici comme ailleurs.

⚠️ ZÉRO DÉPENDANCE, comme le reste : pas de bibliothèque Markdown, pas de
police ni de feuille de style téléchargée. La page s'ouvre hors ligne, dans
n'importe quel navigateur, et ne parle à personne.

Le Markdown rendu est CELUI QUE LINTORN ÉCRIT, pas le Markdown complet :
titres `###`, citations, listes, tableaux, blocs de code, gras, italique,
`code`, liens, et le `<br>` que les détails insèrent eux-mêmes.
"""

from __future__ import annotations

import html
import re
from datetime import datetime

from .. import __version__, config
from ..base import Resultat, detail_du_rapport

# Le mot affiché dans la pastille, et la couleur qui va avec. ⚠️ Le MOT est
# obligatoire : une page qui ne distingue ses états que par la couleur ne dit
# rien à qui la lit en noir et blanc, ou ne distingue pas le rouge du vert.
ETATS = {
    "OK": ("OK", "ok"),
    "ALERTE": ("ALERTE", "alerte"),
    "VERIF": ("À VÉRIFIER", "verif"),
    "ERREUR": ("ERREUR", "erreur"),
    "INDISPONIBLE": ("INDISPONIBLE", "indispo"),
}

# Le compteur se lit en français : « 2 alertes », pas « 2 alerte ».
COMPTEURS = {
    "OK": ("au vert", "au vert"),
    "ALERTE": ("alerte", "alertes"),
    "VERIF": ("à vérifier", "à vérifier"),
    "ERREUR": ("erreur", "erreurs"),
    "INDISPONIBLE": ("indisponible", "indisponibles"),
}

_RX_LIEN_SUR = re.compile(r"^(?:https?://|[^:]*$|[^:]*/)", re.I)


def _echapper(texte: str) -> str:
    """Neutralise le HTML du texte, puis rend à Lintorn ce qu'il a écrit.

    ⚠️ Un dépôt hostile peut nommer un fichier `<img onerror=...>` : ce nom
    arrive dans le rapport, donc dans cette page, qui s'ouvre sur la machine
    du lecteur. Tout est donc échappé d'abord, SANS exception.

    Ensuite seulement on rétablit les deux choses que Lintorn produit
    lui-même : le `<br>` de ses détails, et les entités que `_cellule` a déjà
    posées (`&lt;`, `&gt;`) — sans quoi elles s'afficheraient littéralement.
    """
    sur = html.escape(texte, quote=False)
    sur = sur.replace("&amp;lt;", "&lt;").replace("&amp;gt;", "&gt;")
    return sur.replace("&lt;br&gt;", "<br>")


def _url_sure(url: str) -> bool:
    """Un lien relatif (`../src/x.py`) ou http(s) — jamais `javascript:`."""
    return bool(_RX_LIEN_SUR.match(url.strip()))


def _inline(texte: str) -> str:
    """Le Markdown « en ligne » : `code`, **gras**, *italique*, [liens].

    Les `code` sont mis de côté AVANT le reste : sans ça, un motif de règle
    contenant `**` ou `_` se retrouvait à moitié en gras dans la page.

    Les échappements `\\[`, `\\\\`… aussi, hors du code comme en Markdown :
    `base._cellule` les pose pour neutraliser ce qui vient d'un outil tiers,
    et la page les affichait tels quels là où `rapport.md` ne les montre pas.
    """
    morceaux: list[str] = []

    def garder(trouve: re.Match) -> str:
        morceaux.append(f"<code>{trouve.group(1)}</code>")
        return f"\x00{len(morceaux) - 1}\x00"

    def litteral(trouve: re.Match) -> str:
        morceaux.append(trouve.group(1))
        return f"\x00{len(morceaux) - 1}\x00"

    texte = re.sub(r"`([^`\n]+)`", garder, texte)
    texte = re.sub(r"\\([!-/:-@\[-`{-~])", litteral, texte)
    texte = re.sub(r"\[([^\]\n]+)\]\(([^)\s]+)\)",
                   lambda t: (f'<a href="{html.escape(t.group(2), quote=True)}">{t.group(1)}</a>'
                              if _url_sure(t.group(2)) else t.group(1)),
                   texte)
    texte = re.sub(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", texte)
    texte = re.sub(r"(?<![*\w])\*([^*\n]+)\*(?!\w)", r"<em>\1</em>", texte)
    return re.sub(r"\x00(\d+)\x00", lambda t: morceaux[int(t.group(1))], texte)


def _texte(brut: str) -> str:
    """Le contenu d'une ligne : neutralisé, PUIS rendu. Jamais l'inverse."""
    return _inline(_echapper(brut))


def _cellules(ligne: str) -> list[str]:
    """Les cellules d'une ligne de tableau Markdown.

    ⚠️ `\\|` est une barre DANS la cellule, pas une séparation : `base._cellule`
    échappe ainsi les plages de versions de npm (`<=1.1.17 || 2.0.0 - 2.1.3`).
    Coupée dessus, la ligne gagnait deux cellules, et la colonne « Correctif »
    affichait `\\` à la place du correctif — sur des données de sécurité.
    """
    nu = ligne.strip()
    nu = nu[1:] if nu.startswith("|") else nu
    cellules: list[str] = []
    courante = ""
    rang = 0
    while rang < len(nu):
        car = nu[rang]
        if car == "\\" and rang + 1 < len(nu):
            suivant = nu[rang + 1]
            courante += "|" if suivant == "|" else car + suivant
            rang += 2
            continue
        if car == "|":
            cellules.append(courante.strip())
            courante = ""
        else:
            courante += car
        rang += 1
    if courante.strip():
        cellules.append(courante.strip())
    return cellules


def _tableau(lignes: list[str]) -> list[str]:
    """Un tableau Markdown → un vrai tableau, en-tête compris."""
    rendu = ["<table>"]
    for numero, ligne in enumerate(lignes):
        cellules = _cellules(ligne)
        if numero == 1 and all(set(c) <= set("-: ") for c in cellules):
            continue        # la ligne de séparation `|---|---|`
        balise = "th" if numero == 0 else "td"
        rendu.append("<tr>" + "".join(
            f"<{balise}>{_texte(c)}</{balise}>" for c in cellules) + "</tr>")
    rendu.append("</table>")
    return rendu


def _rendre(markdown: str) -> str:
    """Le Markdown des détails → du HTML. Le sous-ensemble que Lintorn écrit.

    ⚠️ ON ANALYSE LE TEXTE BRUT, on neutralise le HTML ligne par ligne au
    moment de l'écrire. Échapper d'abord transformait le `>` d'une citation
    en `&gt;` : la ligne n'était plus reconnue comme une citation, et le
    chevron s'affichait au milieu du rapport.
    """
    lignes = markdown.split("\n")
    rendu: list[str] = []
    liste_ouverte = False
    numero = 0

    def fermer_liste() -> None:
        nonlocal liste_ouverte
        if liste_ouverte:
            rendu.append("</ul>")
            liste_ouverte = False

    while numero < len(lignes):
        ligne = lignes[numero]
        nu = ligne.strip()

        if nu.startswith("```"):
            fermer_liste()
            fin = numero + 1
            while fin < len(lignes) and not lignes[fin].strip().startswith("```"):
                fin += 1
            rendu.append("<pre><code>"
                         + _echapper("\n".join(lignes[numero + 1:fin])) + "</code></pre>")
            numero = fin + 1
            continue

        if nu.startswith("|") and nu.endswith("|"):
            fermer_liste()
            fin = numero
            while fin < len(lignes) and lignes[fin].strip().startswith("|"):
                fin += 1
            rendu += _tableau(lignes[numero:fin])
            numero = fin
            continue

        if nu.startswith("#"):
            fermer_liste()
            # Le titre de la FICHE est un h2 : un titre de détail vient donc
            # en dessous, sans jamais descendre plus bas que h4 (illisible).
            niveau = 3 if len(nu) - len(nu.lstrip("#")) <= 3 else 4
            rendu.append(f"<h{niveau}>{_texte(nu.lstrip('# '))}</h{niveau}>")
        elif nu.startswith("> "):
            fermer_liste()
            rendu.append(f"<blockquote>{_texte(nu[2:])}</blockquote>")
        elif nu.startswith("- "):
            if not liste_ouverte:
                rendu.append("<ul>")
                liste_ouverte = True
            rendu.append(f"<li>{_texte(nu[2:])}</li>")
        elif nu:
            fermer_liste()
            rendu.append(f"<p>{_texte(nu)}</p>")
        else:
            fermer_liste()
        numero += 1

    fermer_liste()
    return "\n".join(rendu)


def _pastille(statut: str) -> str:
    mot, classe = ETATS.get(statut, (statut, "indispo"))
    return f'<span class="pastille {classe}">{html.escape(mot)}</span>'


def _fiche(resultat: Resultat) -> str:
    """Un contrôle : sa pastille, son résumé, et son détail à déplier.

    Le détail est REPLIÉ par défaut : ouvert, une page de vingt contrôles
    devient un mur qu'on ne lit plus. Sauf ce qui demande une action — un
    rouge se lit tout de suite, sans un clic de plus.
    """
    montrer = resultat.detail and (resultat.statut != "OK" or resultat.detail_meme_au_vert)
    entete = (f'<div class="entete"><h2>{_echapper(resultat.titre)}</h2>'
              f'{_pastille(resultat.statut)}</div>'
              f'<p class="resume">{_echapper(resultat.resume)}</p>')
    if not montrer:
        return f'<article class="{ETATS.get(resultat.statut, ("", "indispo"))[1]}">{entete}</article>'

    detail = detail_du_rapport(resultat)
    corps = _rendre(detail) if resultat.detail_markdown else (
        f"<pre><code>{_echapper(detail)}</code></pre>")
    # Un rouge s'OUVRE, bloquant ou non : c'est ce qu'on vient lire. Le reste
    # se replie, sinon une page de vingt controles devient un mur.
    ouvert = " open" if resultat.statut in ("ALERTE", "ERREUR") else ""
    return (f'<article class="{ETATS.get(resultat.statut, ("", "indispo"))[1]}">{entete}'
            f'<details{ouvert}><summary>Le détail</summary>'
            f'<div class="detail">{corps}</div></details></article>')


# Le titre du contrôle `controles/outillage/hook_git.py`.
_TITRE_HOOK = "Hook pre-push (Lintorn)"


def _ce_que_fait_le_push(resultats: list[Resultat]) -> str:
    """La suite du verdict rouge : ce rouge arrêtera-t-il vraiment le push ?

    ⚠️ C'est le HOOK qui refuse un push, pas le rapport. La page annonçait
    « le push est refusé » sur des projets où la même page disait « hook pas
    encore installe » : une protection promise que rien n'assurait. On ne
    promet donc que ce que le contrôle du hook a constaté, et rien quand il
    n'a pas tourné.
    """
    hook = next((r for r in resultats if r.titre == _TITRE_HOOK), None)
    if hook is None:
        return "."
    if hook.statut in ("OK", "VERIF"):
        return " — le hook pre-push refuse le push tant qu'ils le sont."
    if hook.statut == "ERREUR":
        return f". L'état du hook pre-push est inconnu : {_texte(hook.resume)}."
    return (" — mais <strong>rien ne refuse le push</strong> : le hook pre-push "
            f"n'est pas actif ({_texte(hook.resume)}).")


def page(resultats: list[Resultat], moment: datetime | None = None) -> str:
    """La page complète, autonome : ni police ni feuille de style à charger.

    `moment` : celui du rapport Markdown écrit dans le même passage. Deux
    horodatages différents feraient croire à deux audits.
    """
    compte = {statut: sum(1 for r in resultats if r.statut == statut) for statut in ETATS}
    bloquants = [r for r in resultats if r.en_echec]
    if bloquants:
        verdict = (f'<p class="verdict alerte">{len(bloquants)} contrôle(s) bloquant(s) '
                   f"en alerte{_ce_que_fait_le_push(resultats)}</p>")
    else:
        verdict = ('<p class="verdict ok">Aucun contrôle bloquant en alerte. '
                   "Ce qui suit informe ; rien n'empêche de pousser.</p>")

    resume = " · ".join(
        f'<span class="{ETATS[statut][1]}">{nombre} '
        f'{COMPTEURS[statut][0] if nombre == 1 else COMPTEURS[statut][1]}</span>'
        for statut, nombre in compte.items() if nombre)

    return _MODELE.format(
        projet=html.escape(config.RACINE.name),
        horodatage=(moment or datetime.now()).strftime("%d/%m/%Y à %H:%M"),
        version=html.escape(__version__),
        resume=resume,
        verdict=verdict,
        fiches="\n".join(_fiche(resultat) for resultat in resultats),
        markdown=html.escape(config.RAPPORT.name),
    )


# ⚠️ Tout est EN LIGNE, volontairement : la page doit s'ouvrir depuis un
# dossier, sans réseau, sans serveur, et rester lisible sur un téléphone.
_MODELE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lintorn — {projet}</title>
<style>
  :root {{
    --fond: #f6f7f9; --carte: #fff; --texte: #1c2024; --doux: #5b6672;
    --bord: #dfe3e8; --ok: #1a7f4b; --alerte: #c02626; --verif: #9a6700;
    --erreur: #7c3aed; --indispo: #6b7280; --code: #f0f2f5;
  }}
  /* Le theme du systeme, sans bouton ni JavaScript : la page reste un
     fichier qu'on ouvre, pas une application. */
  @media (prefers-color-scheme: dark) {{
    :root {{
      --fond: #14171a; --carte: #1c2024; --texte: #e6e9ec; --doux: #9aa4af;
      --bord: #2c3238; --ok: #4ade80; --alerte: #f87171; --verif: #fbbf24;
      --erreur: #c4b5fd; --indispo: #9ca3af; --code: #24292e;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--fond); color: var(--texte);
    font: 16px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  }}
  .page {{ max-width: 980px; margin: 0 auto; padding: 32px 16px 64px; }}
  header h1 {{ font-size: 1.5rem; margin: 0 0 4px; letter-spacing: -.02em; }}
  header p {{ margin: 0; color: var(--doux); font-size: .9rem; }}
  .compteurs {{ margin: 14px 0 0; font-size: .9rem; font-weight: 600; }}
  .compteurs span {{ margin-right: 14px; white-space: nowrap; }}
  .verdict {{
    margin: 22px 0 28px; padding: 14px 16px; border-radius: 10px;
    border: 1px solid var(--bord); background: var(--carte); font-weight: 600;
  }}
  .verdict.ok {{ border-left: 5px solid var(--ok); }}
  .verdict.alerte {{ border-left: 5px solid var(--alerte); }}
  article {{
    background: var(--carte); border: 1px solid var(--bord);
    border-left: 5px solid var(--indispo); border-radius: 10px;
    padding: 14px 16px; margin: 0 0 12px;
  }}
  article.ok {{ border-left-color: var(--ok); }}
  article.alerte {{ border-left-color: var(--alerte); }}
  article.verif {{ border-left-color: var(--verif); }}
  article.erreur {{ border-left-color: var(--erreur); }}
  .entete {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
  .entete h2 {{ font-size: 1.02rem; margin: 0; flex: 1 1 auto; }}
  .pastille {{
    font-size: .72rem; font-weight: 700; letter-spacing: .04em;
    padding: 3px 9px; border-radius: 999px; border: 1px solid currentColor;
    white-space: nowrap;
  }}
  /* La couleur ne colorie QUE la pastille, le compteur et le bord gauche :
     appliquee a la fiche entiere, elle teintait le titre, et une page de
     quinze verts ne laissait plus rien ressortir. */
  .pastille.ok, .compteurs .ok {{ color: var(--ok); }}
  .pastille.alerte, .compteurs .alerte, .verdict.alerte {{ color: var(--alerte); }}
  .pastille.verif, .compteurs .verif {{ color: var(--verif); }}
  .pastille.erreur, .compteurs .erreur {{ color: var(--erreur); }}
  .pastille.indispo, .compteurs .indispo {{ color: var(--indispo); }}
  .resume {{ margin: 6px 0 0; color: var(--doux); font-size: .93rem; }}
  details {{ margin-top: 10px; }}
  summary {{
    cursor: pointer; font-size: .85rem; color: var(--doux);
    font-weight: 600; padding: 2px 0;
  }}
  .detail {{ margin-top: 10px; font-size: .93rem; overflow-x: auto; }}
  .detail h3, .detail h4 {{ font-size: .98rem; margin: 18px 0 6px; }}
  .detail p {{ margin: 8px 0; }}
  .detail ul {{ margin: 8px 0; padding-left: 22px; }}
  .detail li {{ margin: 3px 0; }}
  .detail blockquote {{
    margin: 8px 0; padding: 6px 12px; color: var(--doux);
    border-left: 3px solid var(--bord);
  }}
  .detail table {{ border-collapse: collapse; margin: 10px 0; font-size: .88rem; }}
  .detail th, .detail td {{
    border: 1px solid var(--bord); padding: 6px 10px; text-align: left;
    vertical-align: top;
  }}
  .detail th {{ background: var(--code); }}
  code {{
    background: var(--code); padding: 1px 5px; border-radius: 5px;
    font: .86em ui-monospace, SFMono-Regular, Consolas, monospace;
    word-break: break-word;
  }}
  pre {{
    background: var(--code); padding: 12px 14px; border-radius: 8px;
    overflow-x: auto; margin: 10px 0;
  }}
  pre code {{ background: none; padding: 0; }}
  a {{ color: inherit; text-decoration: underline; text-underline-offset: 2px; }}
  footer {{ margin-top: 36px; color: var(--doux); font-size: .82rem; }}
</style>
</head>
<body>
<div class="page">
<header>
  <h1>Lintorn — {projet}</h1>
  <p>Généré le {horodatage} par lintorn {version}. Page régénérée à chaque exécution : ne rien y écrire à la main.</p>
  <p class="compteurs">{resume}</p>
</header>
{verdict}
{fiches}
<footer>Même contenu que <code>{markdown}</code>, qui reste la source.</footer>
</div>
</body>
</html>
"""
