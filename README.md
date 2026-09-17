# aioli-screencap

Capture un écran à intervalle régulier (secondes, minutes ou heures), avec Play / Pause / Stop.
Pensé pour documenter une session de travail sur un second écran (3ds Max, ComfyUI, Photoshop…)
sans rien perturber : la capture lit simplement l'image affichée, sans prendre le focus.

Windows 10/11, Python 3.9+ (3.12 conseillé, avec tkinter, coché par défaut dans l'installateur python.org).

## Installation

1. Place le dossier où tu veux.
2. Double-clic sur `setup.bat` (pas en administrateur).

Le script crée un environnement isolé `.venv\` dans le dossier et y installe `mss` et `Pillow`.

## Utilisation

Double-clic sur `screencap.bat`. Choisis l'écran, le dossier, l'intervalle et son unité, le format, puis ▶ Play.

- **Identifier** : affiche 2 secondes le numéro de chaque écran en son centre (l'écran choisi en blanc). Ces numéros sont ceux de l'outil, pas forcément ceux des paramètres d'affichage de Windows.
- **Dossier** : n'importe quel dossier, via Parcourir… ou en tapant le chemin. Les 8 derniers utilisés sont proposés dans la liste déroulante.
- **Nom de session** (optionnel) : le sous-dossier s'appelle alors `NomDeSession_AAAA-MM-JJ_HH-MM-SS`.

- **Pause** suspend la session ; **Play** la reprend avec une capture immédiate.
- **Stop** termine la session.
- Sans nom, chaque session crée un sous-dossier `session_AAAA-MM-JJ_HH-MM-SS`.
- Les réglages sont mémorisés dans `config.json`.
- En cas de souci, lance `screencap.bat debug` ou regarde `logs\screencap.log`.

## Ce qui est écrit, et où

| Quoi | Où |
| --- | --- |
| Python + dépendances | `.venv\` dans ce dossier |
| Réglages et dossiers récents | `config.json` dans ce dossier |
| Journal d'erreurs | `logs\` dans ce dossier (1 Mo max × 3) |
| Captures | le dossier que tu choisis (par défaut `%USERPROFILE%\Pictures\Captures`, affiché « Images » dans l'Explorateur) |

Rien d'autre : pas de pip global, pas de cache pip, pas de registre, pas de raccourci.
Le programme ne fait aucune connexion réseau ; seul `setup.bat` télécharge les dépendances depuis PyPI.

## Désinstaller

Supprime le dossier. Les captures restent, puisqu'elles sont ailleurs.

## Choix de sécurité de setup.bat

- Il se place toujours dans son propre dossier : même lancé depuis ailleurs, le venv ne peut pas atterrir ailleurs.
- Il refuse les droits administrateur.
- Il utilise le chemin réel de `python.exe` et ignore l'alias du Microsoft Store.
- pip est appelé via le Python du venv, avec les options suivantes :
  - `--require-virtualenv` : pip refuse de toucher au Python système.
  - `--isolated` : pip ignore ta config pip et tes variables d'environnement.
  - `--no-cache-dir` : pip n'écrit pas de cache dans `%LOCALAPPDATA%`.
  - `--only-binary=:all:` : aucun code de compilation n'est exécuté.
- Il vérifie les imports à la fin de l'installation.

## Licence

MIT, pour notre code seulement — voir `LICENSE`. Python, `mss` et `Pillow` gardent leurs propres licences.

---

ai.oli collective — victor.oli with ai.claude, 2026.
