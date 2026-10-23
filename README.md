# Easy TT CAD

**Du code Verilog à la puce, dans une seule interface.**

Easy TT CAD est une application de bureau (Python / Tkinter) qui guide pas à pas la conception d'une puce numérique pour [Tiny Tapeout](https://tinytapeout.com) : écriture du Verilog, vérification, simulation, placement-routage (RTL-to-GDS), documentation et publication sur GitHub. Elle masque la ligne de commande derrière des boutons et des assistants, tout en affichant chaque commande exécutée dans une console intégrée.

![Python](https://img.shields.io/badge/Python-3-blue)
![Plateforme](https://img.shields.io/badge/Plateforme-Linux-lightgrey)
![Interface](https://img.shields.io/badge/Interface-Tkinter-informational)
![Tiny Tapeout](https://img.shields.io/badge/Tiny%20Tapeout-compatible-orange)

<!-- Ajoutez une capture d'écran de l'application ici :
![Aperçu d'Easy TT CAD](docs/screenshot.png)
-->

> Easy TT CAD est un outil indépendant. Tiny Tapeout est un projet distinct : consultez sa [documentation officielle](https://tinytapeout.com) pour les règles de soumission, les dates de navette et les tarifs.

---

## Sommaire

- [Fonctionnalités](#fonctionnalités)
- [Prérequis](#prérequis)
- [Installation](#installation)
- [Démarrage rapide](#démarrage-rapide)
- [Les 7 onglets](#les-7-onglets)
- [Structure d'un projet généré](#structure-dun-projet-généré)
- [Technologies prises en charge](#technologies-prises-en-charge)
- [Sécurité et bonnes pratiques](#sécurité-et-bonnes-pratiques)
- [Limitations connues](#limitations-connues)
- [Dépannage](#dépannage)
- [Documentation](#documentation)
- [Contribuer](#contribuer)
- [Licence](#licence)
- [Crédits](#crédits)

---

## Fonctionnalités

- **Création de projet en un clic** : clonage du template Tiny Tapeout, initialisation git, ajout de `tt-support-tools`, création d'un environnement virtuel Python (`tt_env`) et installation des dépendances.
- **Éditeur RTL** avec assistant de code (squelette, portes logiques, compteur 8 bits, clignotant), vérification syntaxique avec **Verilator** et schéma du circuit avec **Yosys** + **netlistsvg**.
- **Éditeur visuel [Digital](https://github.com/hneemann/Digital)** téléchargé et lancé automatiquement, pour dessiner un circuit puis l'exporter en Verilog.
- **Génération automatique du testbench** (`tb.v`) et modèles de tests **cocotb** (logique et séquentiel).
- **Simulation** avec Icarus Verilog et visualisation des chronogrammes dans **GTKWave**.
- **Assistant `info.yaml`** : titre, description et affectation des 24 broches (`ui`, `uo`, `uio`).
- **Place & Route (hardening)** pour SkyWater 130nm, GlobalFoundries 180nm et IHP 130nm, avec ouverture dans OpenROAD.
- **Modèle de documentation** (`docs/info.md`) pour la datasheet du projet.
- **Push vers GitHub** avec rappel des réglages nécessaires (Pages, permissions des Actions) puis accès direct à l'application Tiny Tapeout.

```mermaid
flowchart LR
    A["1. RTL (Verilog)"] --> B["2. Testbench"] --> C["3. Tests cocotb"] --> D["4. info.yaml"]
    D --> E["5. Place #amp; Route"] --> F["6. Documentation"] --> G["7. GitHub / Tapeout"]
```

---

## Prérequis

| Outil | Utilité |
|---|---|
| Linux (Ubuntu / Debian conseillés) | Le logiciel utilise `bash`, `source`, `xdg-open` et `sed` (WSL2 avec WSLg possible sous Windows) |
| Python 3 + Tkinter, `venv`, `pip` | Interface graphique et environnement virtuel du projet |
| `git` | Clonage du template, versionnage, envoi vers GitHub |
| Icarus Verilog (`iverilog`) | Simulation |
| Verilator | Vérification de la syntaxe (lint) |
| Yosys + `netlistsvg` (npm) | Schéma RTL |
| GTKWave | Visualisation des chronogrammes |
| Java (JRE), `unzip`, `curl` | Éditeur Digital (téléchargé au premier lancement) |
| Navigateur web | Liens d'aide, page *Actions* de GitHub, application Tiny Tapeout |

Une connexion Internet est nécessaire pour créer un projet, installer Digital et pousser sur GitHub.

> Selon votre système, le flow RTL-to-GDS peut nécessiter des composants supplémentaires (PDK, Docker…). Référez-vous à la documentation Tiny Tapeout.

---

## Installation

Sur Ubuntu / Debian :

```bash
sudo apt update
sudo apt install git python3 python3-venv python3-pip python3-tk \
     iverilog verilator yosys gtkwave default-jre unzip curl \
     xdg-utils nodejs npm
sudo npm install -g netlistsvg
```

Récupérez ensuite le projet et lancez-le :

```bash
git clone https://github.com/MariusL00/easy_tt_cad.git
cd easy_tt_cad
python3 easy_tt_cad.py
```

Les paquets Python du flow (cocotb, pytest, lark, librelane…) sont installés **automatiquement** dans `tt_env` lors de la création d'un projet : il n'y a rien à installer côté Python pour l'application elle-même, qui n'utilise que la bibliothèque standard.

---

## Démarrage rapide

1. **Fichier > Nouveau > Projet** : choisissez un dossier de destination, un nom de projet, votre pseudo GitHub et la technologie, puis **Initialiser le projet**.
2. **Onglet 1** : générez un modèle de code (par exemple *Compteur 8 bits*) puis cliquez sur **Vérifier le Verilog (Lint)**.
3. **Onglet 2** : **Générer tb.v automatiquement**.
4. **Onglet 3** : générez un modèle de test, **Sauvegarder tout**, puis **Lancer la Simulation** et cherchez `PASS` dans la console.
5. **Onglet 4** : ouvrez l'assistant, nommez vos broches et générez `info.yaml`.
6. **Onglet 6** : générez et complétez la documentation.
7. **Onglet 5** : **Placer et Router (Hardening)** (3 à 5 minutes environ), puis contrôlez DRC et LVS dans la console.
8. **Onglet 7** : réglez GitHub (Pages et permissions), saisissez pseudo, token et URL du dépôt, puis **Push to GitHub**.
9. Vérifiez que les *GitHub Actions* sont vertes et validez sur [app.tinytapeout.com](https://app.tinytapeout.com).

Le tutoriel complet (compteur 8 bits) figure dans le [guide utilisateur](docs/Easy_TT_CAD_Guide_Utilisateur.pdf).

---

## Les 7 onglets

| Onglet | Fichier | Rôle |
|---|---|---|
| 1. RTL (Verilog) | `src/project.v` | Écrire le circuit, lint, schéma, éditeur Digital |
| 2. Testbench | `test/tb.v` | Relier le circuit au simulateur |
| 3. Test | `test/test.py` | Tests cocotb, simulation, GTKWave |
| 4. info.yaml | `info.yaml` | Description du projet et pinout |
| 5. Place & Route | `runs/`, GDS | Génération du dessin physique |
| 6. Documentation | `docs/info.md` | Datasheet |
| 7. GitHub Tapeout | dépôt GitHub | Publication et soumission |

Le module principal est nommé automatiquement `tt_um_<nom>_<pseudo>` (par exemple `tt_um_alu_MariusL00`).

---

## Structure d'un projet généré

```text
mon_projet/
├── info.yaml               description et pinout du projet
├── src/
│   └── project.v           code Verilog
├── test/
│   ├── tb.v                testbench
│   ├── test.py             tests cocotb
│   └── Makefile            réécrit à chaque simulation
├── docs/
│   └── info.md             datasheet
├── .github/workflows/
│   └── docs.yaml           écrit au moment du push
├── tt/                     tt-support-tools (sous-module git)
├── tt_env/                 environnement virtuel Python (ignoré par git)
├── rtl_netlist.json        netlist Yosys (Visualiser RTL)
└── rtl_view.svg            schéma RTL
```

---

## Technologies prises en charge

| Choix à la création | Template cloné |
|---|---|
| SkyWater 130nm (ex. `tt08`) | [`TinyTapeout/tt08-verilog-template`](https://github.com/TinyTapeout/tt08-verilog-template) |
| GlobalFoundries 180nm | [`TinyTapeout/tt-gf180-template`](https://github.com/TinyTapeout/tt-gf180-template) |
| Lien personnalisé | l'URL de votre choix |

Dans l'onglet *Place & Route*, trois PDK sont proposés : SkyWater 130nm (`sky130A`), GlobalFoundries 180nm (`gf180mcuD`) et IHP 130nm (`ihp-sg13g2`). Choisissez le PDK qui correspond au template utilisé.

---

## Sécurité et bonnes pratiques

- Le **push GitHub utilise `--force`** : il écrase la branche `main` du dépôt distant. Utilisez un dépôt dédié au projet.
- Le **token est intégré à l'URL du dépôt distant**, donc stocké dans `.git/config`. Ne partagez pas le dossier `.git` et révoquez le token quand vous n'en avez plus besoin. Il est masqué (`********`) dans la console.
- Le token doit avoir les droits `repo` et `workflow` (ce dernier est indispensable pour envoyer les fichiers de workflow).
- **Sauvegardez avant d'agir** : la simulation, le Place & Route et le push ne sauvegardent pas les éditeurs. Utilisez **Fichier > Sauvegarder tout**.

---

## Limitations connues

- Un seul fichier source Verilog est géré : `src/project.v`.
- Conçu pour Linux ; non prévu pour Windows ou macOS natifs.
- `test/Makefile` est réécrit à chaque simulation (les modifications manuelles sont perdues) et ne compile que `project.v`.
- L'assistant `info.yaml` réécrit tout le fichier : `tiles`, `clock_hz`, `discord` et `source_files` sont à retoucher ensuite à la main.
- Le modèle de test *Logique* contient un `assert` en commentaire : le test réussit tant qu'il n'est pas activé et adapté.
- Le nom du projet est déduit du nom du module en le découpant aux underscores : utilisez uniquement lettres et chiffres dans le nom du projet, et évitez les tirets dans le pseudo.
- Au premier lancement de Digital, la fenêtre « Veuillez patienter » peut rester affichée tant que Digital est ouvert : fermez Digital pour la faire disparaître.

---

## Dépannage

| Symptôme | Piste |
|---|---|
| Code de retour `127` | Programme introuvable : installez l'outil correspondant (voir [Installation](#installation)) |
| « Erreur de Top Module » | La ligne `module tt_um_…` doit correspondre au nom du projet |
| `tt_env/bin/activate` introuvable | Projet non créé avec Easy TT CAD ou installation interrompue : recréez le projet |
| Pas de chronogramme dans GTKWave | Lancez d'abord une simulation réussie ; `tb.v` doit contenir `$dumpfile` |
| Digital ne démarre pas | Vérifiez Java, `unzip`, `curl` ; supprimez `~/.easy_tt_cad/Digital` pour le retélécharger |
| Hardening en échec | Lisez la console ; vérifiez `info.yaml`, la sauvegarde de `project.v` et le PDK choisi |
| Push refusé | Vérifiez pseudo, token (droits `repo` et `workflow`) et URL HTTPS du dépôt |
| Actions GitHub en rouge | Ouvrez le journal du workflow ; vérifiez les réglages *Pages* et *Workflow permissions* |

---

## Documentation

Le [guide utilisateur (PDF)](docs/Easy_TT_CAD_Guide_Utilisateur.pdf) détaille chaque onglet, propose un tutoriel complet et un glossaire.

Liens utiles : [Tiny Tapeout](https://tinytapeout.com) · [Soumettre son projet](https://app.tinytapeout.com)

---

## Contribuer

Les issues et pull requests sont les bienvenues. Pour signaler un problème, indiquez votre distribution Linux, la sortie de la console et les étapes pour le reproduire.

---

## Licence

_À choisir_ (par exemple MIT ou Apache-2.0) : ajoutez un fichier `LICENSE` à la racine du dépôt.

---

## Crédits

Easy TT CAD s'appuie sur d'excellents projets libres :
[Tiny Tapeout](https://tinytapeout.com), [Digital](https://github.com/hneemann/Digital) (H. Neemann), [cocotb](https://www.cocotb.org), [Icarus Verilog](https://steveicarus.github.io/iverilog/), [Verilator](https://www.veripool.org/verilator/), [Yosys](https://yosyshq.net/yosys/), [netlistsvg](https://github.com/nturley/netlistsvg), [GTKWave](https://gtkwave.sourceforge.net) et [OpenROAD](https://theopenroadproject.org) / LibreLane.

Auteur : [@MariusL00](https://github.com/MariusL00)
