#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Easy TT CAD - Flow RTL-to-GDS pour Tiny Tapeout (version corrigée)."""

import base64
import json
import os
import queue
import re
import shlex
import shutil
import subprocess
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk, filedialog, messagebox, simpledialog

# ----------------------------------------------------------------------------
# Constantes
# ----------------------------------------------------------------------------
UNKNOWN_TOP = "tt_um_inconnu"
MAX_CONSOLE_LINES = 5000          # taille max de l'historique de la console
MAX_QUEUE_ITEMS_PER_TICK = 500    # évite de figer l'UI avec les logs OpenLane
TYPST_VERSION = "v0.13.1"         # version fixe de Typst pour le workflow docs
MAKEFILE_MARKER = "# Généré par Easy TT CAD"

CUSTOM_TEMPLATE = "Lien personnalisé"
SKYWATER_TEMPLATE = "SkyWater 130nm (ex: tt08)"
TEMPLATES = {
    SKYWATER_TEMPLATE: {
        "url": "https://github.com/TinyTapeout/tt08-verilog-template",
        "pdk": "SkyWater 130nm",
    },
    "GlobalFoundries 180nm (ex: GF26)": {
        "url": "https://github.com/TinyTapeout/tt-gf180-template",
        "pdk": "GlobalFoundries 180nm",
    },
    CUSTOM_TEMPLATE: {"url": None, "pdk": None},
}

# Options de tt_tool.py par PDK (vérifiées au lancement avec --help)
PDK_SETTINGS = {
    "SkyWater 130nm": {"env": "sky130A", "create": "--create-user-config", "harden": "--harden"},
    "GlobalFoundries 180nm": {"env": "gf180mcuD", "create": "--gf-create-user-config", "harden": "--gf-harden"},
    "IHP 130nm": {"env": "ihp-sg13g2", "create": "--ihp-create-user-config", "harden": "--ihp-harden"},
}


def safe_identifier(text):
    """Transforme un texte quelconque en identifiant utilisable dans un nom de module Verilog."""
    return re.sub(r"[^A-Za-z0-9_]", "_", text)


# ----------------------------------------------------------------------------
# Onglet éditeur
# ----------------------------------------------------------------------------
class EditorTab(ttk.Frame):
    def __init__(self, master, app, rel_path):
        super().__init__(master)
        self.app = app
        self.rel_path = rel_path
        self.load_failed = False  # True si le fichier existait mais n'a pas pu être lu

        self.toolbar = ttk.Frame(self)
        self.toolbar.pack(fill=tk.X, pady=5)

        ttk.Button(self.toolbar, text="Importer...", command=self.import_file).pack(side=tk.LEFT, padx=5)
        ttk.Button(self.toolbar, text="Sauvegarder", command=self.save).pack(side=tk.LEFT, padx=5)

        self.custom_frame = ttk.Frame(self)
        self.custom_frame.pack(fill=tk.X, pady=2)

        self.text_frame = ttk.Frame(self)
        self.text_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.text = tk.Text(self.text_frame, font=("Monospace", 11), undo=True)
        self.scrollbar = ttk.Scrollbar(self.text_frame, orient=tk.VERTICAL, command=self.text.yview)
        self.text.configure(yscrollcommand=self.scrollbar.set)

        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def full_path(self):
        return os.path.join(self.app.project_dir, self.rel_path)

    def is_empty(self):
        return not self.text.get("1.0", "end-1c").strip()

    def is_modified(self):
        return bool(self.text.edit_modified())

    def set_content(self, content):
        """Remplace le contenu (action volontaire de l'utilisateur : Ctrl+Z reste possible)."""
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", content)
        self.load_failed = False

    def load(self):
        if not self.app.project_dir:
            return
        self.load_failed = False
        self.text.delete("1.0", tk.END)  # Toujours vider l'éditeur d'abord
        full_path = self.full_path()
        if os.path.exists(full_path):
            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    self.text.insert("1.0", f.read())
            except (OSError, UnicodeDecodeError) as e:
                self.load_failed = True
                self.app.log_console(f"❌ Erreur de lecture de {full_path} : {e}\n"
                                     f"   (le fichier ne sera pas écrasé tant que vous ne le modifiez pas)")
        # Ctrl+Z ne doit pas ramener à un éditeur vide
        self.text.edit_reset()
        self.text.edit_modified(False)

    def save(self):
        if not self.app.project_dir:
            return False
        # Fichier illisible et non modifié : on ne l'écrase surtout pas avec du vide
        if self.load_failed and not self.is_modified():
            return True
        full_path = self.full_path()
        try:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(self.text.get("1.0", "end-1c"))
        except OSError as e:
            messagebox.showerror("Erreur de sauvegarde", f"Impossible d'écrire {full_path} :\n{e}")
            return False
        self.load_failed = False
        self.text.edit_modified(False)
        return True

    def import_file(self):
        filepath = filedialog.askopenfilename(title="Importer un fichier")
        if not filepath:
            return
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError) as e:
            messagebox.showerror("Erreur", f"Impossible de lire le fichier : {e}")
            return
        if not self.is_empty() and not messagebox.askyesno(
                "Remplacer le contenu", "Importer ce fichier va remplacer le contenu actuel de l'éditeur. Continuer ?"):
            return
        self.set_content(content)
        self.app.log_console(f"✅ Fichier importé : {filepath}")


# ----------------------------------------------------------------------------
# Application
# ----------------------------------------------------------------------------
class EasyTTCad(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Easy TT CAD - Flow RTL-to-GDS")
        self.geometry("1100x850")

        self.project_dir = ""
        self.project_name = ""
        self.project_template = ""
        self.top_module = ""
        self.cmd_queue = queue.Queue()
        self.loading_win = None
        self.editors = []

        # 1. On charge les préférences AVANT de créer l'UI
        self.load_global_config()

        self.setup_menu()
        self.setup_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.check_console_queue()
        self.after(300, self.offer_reopen_last)

    # ------------------------------------------------------------------ config
    def get_global_config_path(self):
        config_dir = os.path.expanduser("~/.config/easy_tt_cad")
        os.makedirs(config_dir, exist_ok=True)
        return os.path.join(config_dir, "config.json")

    def load_global_config(self):
        self.global_config = {"github_user": "", "last_project": ""}
        path = self.get_global_config_path()
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self.global_config.update(json.load(f))
            except (OSError, json.JSONDecodeError):
                pass

    def save_global_config(self):
        path = self.get_global_config_path()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.global_config, f, indent=4)
        except OSError as e:
            print(f"Erreur de sauvegarde config globale: {e}")

    def write_project_config(self, github_user):
        conf = {
            "name": self.project_name,
            "github_user": github_user,
            "top_module": self.top_module,
            "template": self.project_template,
        }
        try:
            with open(os.path.join(self.project_dir, ".easy_tt_cad.json"), "w", encoding="utf-8") as f:
                json.dump(conf, f, indent=4)
        except OSError as e:
            self.log_console(f"⚠️ Impossible d'écrire .easy_tt_cad.json : {e}")

    def offer_reopen_last(self):
        last = self.global_config.get("last_project", "")
        if last and os.path.isdir(last) and not self.project_dir:
            if messagebox.askyesno("Dernier projet", f"Rouvrir le dernier projet ?\n\n{last}"):
                self.load_project(last, silent=True)

    # ----------------------------------------------------------------- fermeture
    def has_unsaved_changes(self):
        return any(e.is_modified() for e in self.editors)

    def confirm_unsaved(self):
        """Retourne True si on peut continuer (rien à perdre, ou l'utilisateur a choisi)."""
        if not self.project_dir or not self.has_unsaved_changes():
            return True
        answer = messagebox.askyesnocancel("Modifications non sauvegardées",
                                           "Sauvegarder les modifications avant de continuer ?")
        if answer is None:
            return False
        if answer:
            return self.save_all()
        return True

    def on_close(self):
        if self.confirm_unsaved():
            self.destroy()

    # ---------------------------------------------------------------------- menu
    def setup_menu(self):
        menubar = tk.Menu(self)
        self.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Fichier", menu=file_menu)

        new_proj_menu = tk.Menu(file_menu, tearoff=0)
        file_menu.add_cascade(label="Nouveau", menu=new_proj_menu)
        new_proj_menu.add_command(label="Projet", command=self.create_new_project)

        file_menu.add_command(label="Charger un projet...", command=self.load_project)
        file_menu.add_separator()
        file_menu.add_command(label="Sauvegarder tout", command=self.save_all)
        file_menu.add_separator()
        file_menu.add_command(label="Quitter", command=self.on_close)

        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Aide & Liens", menu=help_menu)
        help_menu.add_command(label="Vérifier l'installation (Dépendances)", command=self.check_dependencies)
        help_menu.add_separator()
        help_menu.add_command(label="Documentation Tiny Tapeout", command=lambda: webbrowser.open("https://tinytapeout.com"))
        help_menu.add_command(label="Soumettre son projet (App)", command=lambda: webbrowser.open("https://app.tinytapeout.com"))

    # ------------------------------------------------------------------------ UI
    def setup_ui(self):
        self.welcome_frame = ttk.Frame(self)
        self.welcome_frame.pack(fill=tk.BOTH, expand=True)

        lbl_welcome = ttk.Label(
            self.welcome_frame,
            text="Bienvenue dans Easy TT CAD\n\nAllez dans Fichier > Nouveau ou Charger\npour initialiser votre environnement de conception.",
            font=("Helvetica", 16),
            justify=tk.CENTER,
            foreground="gray"
        )
        lbl_welcome.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        self.paned = ttk.PanedWindow(self, orient=tk.VERTICAL)

        self.notebook = ttk.Notebook(self.paned)
        self.paned.add(self.notebook, weight=3)

        self.tab_rtl = EditorTab(self.notebook, self, "src/project.v")
        self.tab_tbv = EditorTab(self.notebook, self, "test/tb.v")
        self.tab_testpy = EditorTab(self.notebook, self, "test/test.py")
        self.tab_yaml = EditorTab(self.notebook, self, "info.yaml")
        self.tab_doc = EditorTab(self.notebook, self, "docs/info.md")

        self.tab_pnr = ttk.Frame(self.notebook)
        self.tab_git = ttk.Frame(self.notebook)

        # Alias de confort
        self.txt_rtl = self.tab_rtl.text
        self.txt_tbv = self.tab_tbv.text
        self.txt_testpy = self.tab_testpy.text
        self.txt_yaml = self.tab_yaml.text
        self.txt_doc = self.tab_doc.text

        # Liste pour sauvegarder / charger d'un seul coup
        self.editors = [self.tab_rtl, self.tab_tbv, self.tab_testpy, self.tab_yaml, self.tab_doc]

        self.notebook.add(self.tab_rtl, text="1. RTL (Verilog)")
        self.notebook.add(self.tab_tbv, text="2. Testbench (tb.v)")
        self.notebook.add(self.tab_testpy, text="3. Test (test.py)")
        self.notebook.add(self.tab_yaml, text="4. info.yaml")
        self.notebook.add(self.tab_pnr, text="5. Place & Route")
        self.notebook.add(self.tab_doc, text="6. Documentation")
        self.notebook.add(self.tab_git, text="7. GitHub Tapeout")

        self.build_rtl_tab()
        self.build_tbv_tab()
        self.build_testpy_tab()
        self.build_yaml_tab()
        self.build_pnr_tab()
        self.build_doc_tab()
        self.build_git_tab()

        console_frame = ttk.LabelFrame(self.paned, text="Console d'exécution")
        self.paned.add(console_frame, weight=1)

        self.console_scroll = ttk.Scrollbar(console_frame, orient=tk.VERTICAL)
        # state=DISABLED : lecture seule
        self.console = tk.Text(console_frame, bg="black", fg="lightgreen", font=("Courier", 10),
                               yscrollcommand=self.console_scroll.set, state=tk.DISABLED)
        self.console_scroll.config(command=self.console.yview)

        self.console_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.console.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    def show_workspace(self):
        self.welcome_frame.pack_forget()
        self.paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    def load_editors(self):
        for editor in self.editors:
            editor.load()

    def apply_project_pdk(self):
        """Sélectionne automatiquement le PDK correspondant au template du projet."""
        pdk = TEMPLATES.get(self.project_template, {}).get("pdk")
        if pdk:
            self.cbox_pdk.set(pdk)

    # ------------------------------------------------------------------ helpers
    def ensure_top_module(self):
        if not self.project_dir or not self.top_module:
            messagebox.showerror("Erreur", "Veuillez d'abord créer ou charger un projet.")
            return False
        if self.top_module == UNKNOWN_TOP:
            messagebox.showerror(
                "Module top inconnu",
                "Le nom du module top est inconnu.\nAjoutez 'top_module' dans info.yaml puis rechargez le projet.")
            return False
        return True

    def confirm_replace(self, editor, label):
        if editor.is_empty():
            return True
        return messagebox.askyesno("Remplacer le code",
                                   f"{label} va écraser le contenu actuel de l'éditeur. Continuer ?")

    def src_files(self):
        """Liste des fichiers .v de src/ (par défaut project.v)."""
        try:
            files = sorted(f for f in os.listdir(os.path.join(self.project_dir, "src")) if f.endswith(".v"))
        except OSError:
            files = []
        return files or ["project.v"]

    def launch_detached(self, args, cwd=None, shell=False):
        try:
            subprocess.Popen(args, cwd=cwd, shell=shell,
                             executable="/bin/bash" if shell else None,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            return True
        except OSError as e:
            messagebox.showerror("Erreur", f"Impossible de lancer la commande :\n{e}")
            return False

    def check_dependencies(self):
        tools = ["git", "python3", "make", "curl", "unzip", "iverilog", "verilator",
                 "yosys", "netlistsvg", "gtkwave", "java", "xdg-open"]
        missing, found = [], []
        for tool in tools:
            (found if shutil.which(tool) else missing).append(tool)

        # Sur Debian/Ubuntu, python3-venv est un paquet séparé
        try:
            venv_ok = subprocess.run(["python3", "-c", "import venv, ensurepip"],
                                     capture_output=True).returncode == 0
        except OSError:
            venv_ok = False
        (found if venv_ok else missing).append("python3-venv")

        msg = ("Outils détectés :\n" + "\n".join(f"✅ {t}" for t in found) +
               "\n\nOutils manquants :\n" + "\n".join(f"❌ {t}" for t in missing))
        if missing:
            msg += "\n\nVeuillez installer les outils manquants (ex: sudo apt install ...)"
            if "python3-venv" in missing:
                msg += "\nPour python3-venv : sudo apt install python3-venv"
            messagebox.showwarning("Vérification des dépendances", msg)
        else:
            messagebox.showinfo("Vérification des dépendances",
                                msg + "\n\nTout est parfaitement installé sur ce système Linux/WSL !")

    # --------------------------------------------------------- nouveau / charger
    def create_new_project(self):
        if not self.confirm_unsaved():
            return
        folder = filedialog.askdirectory(title="Sélectionner le dossier de destination")
        if not folder:
            return

        dialog = tk.Toplevel(self)
        dialog.title("Configuration du projet")
        dialog.transient(self)
        dialog.resizable(False, False)
        dialog.grab_set()

        v_name = tk.StringVar(value="alu")
        v_user = tk.StringVar(value=self.global_config.get("github_user", "") or "VotrePseudo")
        v_tech = tk.StringVar(value=SKYWATER_TEMPLATE)
        v_custom = tk.StringVar(value="")
        result = {}

        ttk.Label(dialog, text="Nom du projet (ex: alu) :").pack(pady=(15, 2), padx=30)
        ttk.Entry(dialog, textvariable=v_name, width=30).pack(pady=2)

        ttk.Label(dialog, text="Pseudo GitHub :").pack(pady=(10, 2))
        ttk.Entry(dialog, textvariable=v_user, width=30).pack(pady=2)

        ttk.Label(dialog, text="Choix de la technologie (Template) :").pack(pady=(10, 2))
        cb_tech = ttk.Combobox(dialog, textvariable=v_tech, values=list(TEMPLATES.keys()),
                               state="readonly", width=35)
        cb_tech.pack(pady=2)

        lbl_custom = ttk.Label(dialog, text="URL du dépôt GitHub personnalisé :")
        ent_custom = ttk.Entry(dialog, textvariable=v_custom, width=40)

        def on_tech_change(_event=None):
            if v_tech.get() == CUSTOM_TEMPLATE:
                # before=btn_submit : les champs apparaissent AU-DESSUS du bouton
                lbl_custom.pack(pady=(10, 2), before=btn_submit)
                ent_custom.pack(pady=2, before=btn_submit)
            else:
                lbl_custom.pack_forget()
                ent_custom.pack_forget()

        cb_tech.bind("<<ComboboxSelected>>", on_tech_change)

        def on_submit():
            # On valide d'abord, on ne remplit `result` qu'ensuite
            name = v_name.get().strip()
            user = v_user.get().strip()
            tech = v_tech.get()
            custom = v_custom.get().strip()
            if not name or not user:
                messagebox.showerror("Erreur", "Le nom et le pseudo sont obligatoires.", parent=dialog)
                return
            if tech == CUSTOM_TEMPLATE and not (custom.startswith("https://") or custom.startswith("git@")):
                messagebox.showerror("Erreur", "L'URL du dépôt doit commencer par https:// ou git@",
                                     parent=dialog)
                return
            result.update(name=name, user=user, tech=tech, custom=custom)
            dialog.destroy()

        btn_submit = ttk.Button(dialog, text="Initialiser le projet", command=on_submit)
        btn_submit.pack(pady=20)
        self.wait_window(dialog)

        if not result:  # fenêtre fermée avec la croix
            return

        tech = result["tech"]
        github_user = result["user"]
        proj_name = safe_identifier(result["name"])
        user_id = safe_identifier(github_user)
        template_url = TEMPLATES[tech]["url"] or result["custom"]
        top_module = f"tt_um_{proj_name}_{user_id}"
        project_dir = os.path.join(folder, proj_name)

        if proj_name != result["name"]:
            self.log_console(f"ℹ️ Nom de projet normalisé : '{result['name']}' -> '{proj_name}'")

        if os.path.exists(project_dir) and (not os.path.isdir(project_dir) or os.listdir(project_dir)):
            messagebox.showerror("Erreur", f"Le dossier existe déjà et n'est pas vide :\n{project_dir}")
            return
        try:
            os.makedirs(project_dir, exist_ok=True)
        except OSError as e:
            messagebox.showerror("Erreur", f"Impossible de créer le dossier :\n{e}")
            return

        cmd = f"""set -euo pipefail

# Copie propre du template (on récupère la version de tt-support-tools épinglée par le template)
git clone --depth 1 -- {shlex.quote(template_url)} .temp
if (cd .temp && git submodule update --init --depth 1 -- tt); then
    echo "tt-support-tools : version épinglée par le template."
    rm -rf .temp/.git .temp/tt/.git
    cp -a .temp/. .
    rm -rf .temp
else
    echo "Sous-module 'tt' indisponible : clone de la branche par défaut de tt-support-tools."
    rm -rf .temp/.git .temp/tt
    cp -a .temp/. .
    rm -rf .temp
    git clone --depth 1 https://github.com/TinyTapeout/tt-support-tools tt
fi

git init

# On ignore les dossiers/fichiers générés pour ne pas polluer GitHub
printf '\\n' >> .gitignore
for p in tt_env/ tt/ sim_build/ runs/ '*.vcd' results.xml __pycache__/ rtl_netlist.json rtl_view.svg .easy_tt_cad.json; do
    grep -qxF -- "$p" .gitignore || echo "$p" >> .gitignore
done

git config user.name {shlex.quote(github_user)}
git config user.email {shlex.quote(github_user + "@users.noreply.github.com")}
git add .
git commit -m "Initial commit"

# Environnement Python
python3 -m venv tt_env
source tt_env/bin/activate
pip install --upgrade pip
        
# Suppression des contraintes de version strictes pour éviter l'erreur contourpy
sed -i 's/==.*//' tt/requirements.txt
        
pip install -r tt/requirements.txt
# Installation des dépendances de test (on garde cocotb<2.0 pour vos snippets)
pip install "cocotb<2.0" "pytest<8.0.0" lark librelane
"""

        def on_created():
            self.project_dir = project_dir
            self.top_module = top_module
            self.project_name = proj_name
            self.project_template = tech
            self.write_project_config(github_user)

            self.global_config["github_user"] = github_user
            self.global_config["last_project"] = project_dir
            self.save_global_config()
            self.ent_git_user.delete(0, tk.END)
            self.ent_git_user.insert(0, github_user)

            self.apply_project_pdk()
            self.show_workspace()
            self.load_editors()  # on charge le template dans les éditeurs, seulement maintenant

        self.log_console(f"--- Création du projet {top_module} depuis {template_url} ---")
        self.run_async_command(
            cmd, shell=True, cwd=project_dir, require_project=False,
            blocking_msg=f"Téléchargement du template ({tech})...\nInstallation Git, Python venv, Pip\n\nVeuillez patienter.",
            success_msg="Le projet a été créé et l'environnement est prêt !",
            error_msg=f"❌ La création du projet a échoué.\nConsultez la console.\n\n"
                      f"Supprimez le dossier {project_dir} avant de réessayer.",
            success_callback=on_created
        )

    def load_project(self, folder_path=None, silent=False):
        if not self.confirm_unsaved():
            return
        if not folder_path:
            folder_path = filedialog.askdirectory(title="Sélectionner le dossier du projet existant")
        if not folder_path:
            return

        if not (os.path.exists(os.path.join(folder_path, "info.yaml")) or
                os.path.isdir(os.path.join(folder_path, "src"))):
            if not messagebox.askyesno("Dossier inhabituel",
                                       "Ce dossier ne contient ni info.yaml ni src/.\nLe charger quand même ?"):
                return

        top_module = UNKNOWN_TOP
        name = os.path.basename(os.path.normpath(folder_path))
        template = ""

        # 1. Lecture via notre config locale
        local_config_path = os.path.join(folder_path, ".easy_tt_cad.json")
        if os.path.exists(local_config_path):
            try:
                with open(local_config_path, "r", encoding="utf-8") as f:
                    conf = json.load(f)
                top_module = conf.get("top_module", UNKNOWN_TOP) or UNKNOWN_TOP
                name = conf.get("name", name) or name
                template = conf.get("template", "")
            except (OSError, json.JSONDecodeError):
                pass

        # 2. Plan B : info.yaml (on ignore les lignes commentées)
        if top_module == UNKNOWN_TOP:
            yaml_path = os.path.join(folder_path, "info.yaml")
            if os.path.exists(yaml_path):
                try:
                    with open(yaml_path, "r", encoding="utf-8") as f:
                        match = re.search(r'^\s*top_module:\s*["\']?([A-Za-z_]\w*)', f.read(), re.MULTILINE)
                    if match:
                        top_module = match.group(1)
                except (OSError, UnicodeDecodeError):
                    pass

        # 3. Plan C : on demande à l'utilisateur
        if top_module == UNKNOWN_TOP:
            answer = simpledialog.askstring(
                "Module top introuvable",
                "Le nom du module top n'a pas été trouvé (ni .easy_tt_cad.json, ni info.yaml).\n"
                "Entrez-le (ex: tt_um_alu_pseudo) :", parent=self)
            if answer and re.fullmatch(r"[A-Za-z_]\w*", answer.strip()):
                top_module = answer.strip()
            else:
                messagebox.showwarning(
                    "Module top inconnu",
                    "Sans module top, la génération de code, la vérification et le schéma seront désactivés.")

        self.project_dir = folder_path
        self.top_module = top_module
        self.project_name = name
        self.project_template = template

        self.global_config["last_project"] = self.project_dir
        self.save_global_config()

        self.apply_project_pdk()
        self.show_workspace()
        self.load_editors()

        self.log_console(f"✅ Projet '{self.top_module}' chargé depuis {self.project_dir}.")
        if not silent:
            messagebox.showinfo("Projet chargé", f"Le projet {self.top_module} a été chargé avec succès.")

    def save_all(self):
        """Sauvegarde tous les éditeurs. Retourne True si tout s'est bien passé."""
        if not self.project_dir:
            return False
        results = [editor.save() for editor in self.editors]
        ok = all(results)
        if ok:
            self.log_console("✅ Sauvegarde globale effectuée.")
        return ok

    # ----------------------------------------------------------- fenêtre d'attente
    def show_loading(self, message):
        if self.loading_win:  # évite une fenêtre orpheline avec grab_set
            self.hide_loading()
        self.loading_win = tk.Toplevel(self)
        self.loading_win.title("Veuillez patienter")
        self.loading_win.geometry("450x200")
        self.loading_win.transient(self)
        self.loading_win.grab_set()
        self.loading_win.protocol("WM_DELETE_WINDOW", lambda: None)

        lbl = ttk.Label(self.loading_win, text=message, justify=tk.CENTER, font=("Helvetica", 11))
        lbl.pack(expand=True, fill=tk.BOTH, padx=20, pady=(20, 10))

        pb = ttk.Progressbar(self.loading_win, mode='indeterminate')
        pb.pack(fill=tk.X, padx=20, pady=10)
        pb.start(10)

        # Bouton de secours pour récupérer la main sur l'UI si ça bloque
        ttk.Button(self.loading_win, text="Masquer (En cas de blocage)", command=self.hide_loading).pack(pady=5)
        self.update()

    def hide_loading(self):
        if self.loading_win:
            self.loading_win.grab_release()
            self.loading_win.destroy()
            self.loading_win = None

    # ------------------------------------------------------------- outils externes
    def open_gtkwave(self):
        if not self.project_dir:
            return
        vcd_path = os.path.join(self.project_dir, "test", "tb.vcd")
        if not os.path.exists(vcd_path):
            messagebox.showwarning("Fichier introuvable", "Lancez d'abord une simulation pour générer le tb.vcd.")
            return
        self.launch_detached(["gtkwave", vcd_path], cwd=self.project_dir)

    def open_openroad(self):
        if not self.project_dir:
            messagebox.showerror("Erreur", "Veuillez d'abord charger ou créer un projet.")
            return
        cfg = PDK_SETTINGS.get(self.cbox_pdk.get(), PDK_SETTINGS["SkyWater 130nm"])
        cmd = f"source tt_env/bin/activate && export PDK={shlex.quote(cfg['env'])} && ./tt/tt_tool.py --open-in-openroad"
        self.log_console(f"\n> {cmd}")
        self.launch_detached(cmd, cwd=self.project_dir, shell=True)

    def open_digital_editor(self):
        if not shutil.which("java"):
            messagebox.showerror("Erreur", "Java n'est pas installé sur ce système.\nRequis pour lancer Digital.")
            return

        install_dir = os.path.expanduser("~/.easy_tt_cad")
        jar_path = os.path.join(install_dir, "Digital", "Digital.jar")

        if not os.path.exists(jar_path):
            q_dir = shlex.quote(install_dir)
            cmd = f"""set -euo pipefail
mkdir -p {q_dir}
cd {q_dir}
curl -f -sL -o Digital.zip https://github.com/hneemann/Digital/releases/latest/download/Digital.zip
unzip -q -o Digital.zip
rm Digital.zip
"""
            self.run_async_command(
                cmd, shell=True, require_project=False,
                blocking_msg="Téléchargement de Digital...",
                success_msg="Téléchargement terminé !",
                success_callback=lambda: self.launch_detached(["java", "-jar", jar_path]),
                error_msg="Erreur lors du téléchargement ou de l'extraction de Digital (Vérifiez qu'unzip est installé)."
            )
        else:
            self.launch_detached(["java", "-jar", jar_path])

    # ----------------------------------------------------------------- RTL
    def insert_snippet(self):
        if not self.ensure_top_module():
            return

        choice = self.cbox_snippets.get()
        if not choice:
            return

        # Squelette commun de déclaration des ports Tiny Tapeout
        header = f"""module {self.top_module} (
    input  wire [7:0] ui_in,    // Entrées dédiées
    output wire [7:0] uo_out,   // Sorties dédiées
    input  wire [7:0] uio_in,   // Entrées/Sorties (mode entrée)
    output wire [7:0] uio_out,  // Entrées/Sorties (mode sortie)
    output wire [7:0] uio_oe,   // Direction des E/S (1=Sortie, 0=Entrée)
    input  wire       ena,      // Actif à 1
    input  wire       clk,      // Horloge
    input  wire       rst_n     // Reset (Actif à 0)
);
    // Configurer toutes les broches bidirectionnelles en entrées par défaut
    assign uio_oe  = 8'b00000000;
    assign uio_out = 8'b00000000;
"""

        snippet = ""
        if "1. Squelette" in choice:
            snippet = header + "\n    // --- VOTRE LOGIQUE ICI ---\n\n    assign uo_out = 8'b00000000;\n\nendmodule\n"

        elif "2. Hello World" in choice:
            snippet = header + """
    // --- HELLO WORLD ---
    // ui_in[0] ET ui_in[1] contrôle la sortie uo_out[0]
    assign uo_out[0] = ui_in[0] & ui_in[1];

    // ui_in[2] OU ui_in[3] contrôle la sortie uo_out[1]
    assign uo_out[1] = ui_in[2] | ui_in[3];

    // Les autres sorties sont forcées à 0
    assign uo_out[7:2] = 6'b000000;

endmodule
"""

        elif "3. Compteur" in choice:
            snippet = header + """
    // --- COMPTEUR 8 BITS ---
    reg [7:0] counter;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            counter <= 8'b00000000; // Remise à zéro
        end else if (ena) begin
            counter <= counter + 1; // Incrémentation
        end
    end

    // Assigner le registre à la sortie physique
    assign uo_out = counter;

endmodule
"""

        elif "4. Clignotant" in choice:
            snippet = header + """
    // --- BLINK LED (Diviseur d'horloge) ---
    // Un compteur de 24 bits pour ralentir l'horloge (ex: de 10MHz à qqs Hz)
    reg [23:0] diviseur;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            diviseur <= 24'b0;
        end else if (ena) begin
            diviseur <= diviseur + 1;
        end
    end

    // Le bit le plus fort (MSB) clignote très lentement
    assign uo_out[0] = diviseur[23];

    // Le reste à zéro
    assign uo_out[7:1] = 7'b0000000;

endmodule
"""

        if not snippet:
            return
        if self.confirm_replace(self.tab_rtl, "Générer ce module"):
            self.tab_rtl.set_content(snippet)
            self.log_console(f"Module '{choice}' inséré avec succès.")

    def verify_rtl(self):
        if not self.ensure_top_module():
            return
        rtl_code = self.txt_rtl.get("1.0", tk.END)

        # Recherche exacte du nom du module avec une regex
        pattern = rf"\bmodule\s+{re.escape(self.top_module)}\b"
        if not re.search(pattern, rtl_code):
            messagebox.showwarning("Erreur de Top Module",
                                   f"Attention ! Déclaration introuvable :\nmodule {self.top_module} (")
            return

        if not self.tab_rtl.save():
            return
        files = " ".join(shlex.quote(f"src/{f}") for f in self.src_files())
        cmd = f"verilator --lint-only --top-module {shlex.quote(self.top_module)} {files}"
        self.run_async_command(
            cmd, shell=True,
            success_msg="✅ Le code RTL a été vérifié et ne contient aucune erreur de syntaxe !",
            error_msg="❌ Des erreurs de syntaxe ont été détectées par Verilator.\nVeuillez consulter la console.")

    def view_rtl_schematic(self):
        if not self.ensure_top_module():
            return
        if not self.tab_rtl.save():
            return
        reads = "; ".join(f"read_verilog src/{f}" for f in self.src_files())
        script = f"{reads}; prep -top {self.top_module}; write_json rtl_netlist.json"
        # '|' comme délimiteur sed : aucun échappement fragile
        sed_cmd = r"""sed -i 's|<svg[^>]*>|&<rect width="100%" height="100%" fill="white"/>|' rtl_view.svg"""
        cmd = (f"yosys -p {shlex.quote(script)} "
               f"&& netlistsvg rtl_netlist.json -o rtl_view.svg "
               f"&& {sed_cmd} && xdg-open rtl_view.svg")
        self.run_async_command(
            cmd, shell=True,
            success_msg="✅ Schéma RTL Haute Définition généré !\nIl s'ouvre avec un fond blanc pour une meilleure lisibilité.",
            error_msg="❌ Échec de la génération.\nVérifiez la syntaxe Verilog ou l'installation de netlistsvg.")

    # ------------------------------------------------------------ testbench / tests
    def generate_tbv_auto(self):
        if not self.ensure_top_module():
            return
        if not self.confirm_replace(self.tab_tbv, "Générer le testbench"):
            return

        tbv_content = f"""`default_nettype none
`timescale 1ns / 1ps

/* Ce fichier généré automatiquement connecte votre module au simulateur Python.
   Vous n'avez pas besoin de le modifier. */

module tb ();
    // Configuration pour générer le graphique des ondes (GTKWave)
    initial begin
        $dumpfile("tb.vcd");
        $dumpvars(0, tb);
        #1;
    end

    // Déclaration des signaux
    reg clk;
    reg rst_n;
    reg ena;
    reg [7:0] ui_in;
    reg [7:0] uio_in;
    wire [7:0] uo_out;
    wire [7:0] uio_out;
    wire [7:0] uio_oe;

    // Instanciation de votre circuit
    {self.top_module} user_project (
    `ifdef GL_TEST
            .VPWR(1'b1),
            .VGND(1'b0),
    `endif
            .ui_in  (ui_in),
            .uo_out (uo_out),
            .uio_in (uio_in),
            .uio_out(uio_out),
            .uio_oe (uio_oe),
            .ena    (ena),
            .clk    (clk),
            .rst_n  (rst_n)
        );
endmodule
"""
        self.tab_tbv.set_content(tbv_content)
        if self.tab_tbv.save():
            self.log_console("Fichier testbench (tb.v) généré et sauvegardé avec succès.")

    def insert_test_snippet(self):
        choice = self.cbox_test.get()
        if not choice:
            return

        snippet = ""
        if "1. Test Logique" in choice:
            snippet = """import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def test_combinatoire(dut):
    dut._log.info("Début du test logique")

    # 1. Initialisation de TOUTES les entrées (sinon elles restent à X dans Icarus)
    dut.ena.value = 1
    dut.clk.value = 0
    dut.rst_n.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0

    # 2. On applique une valeur (ex: 3)
    dut.ui_in.value = 3

    # 3. On attend un peu que le courant passe (1 nanoseconde)
    await Timer(1, units="ns")

    # 4. On vérifie le résultat (ex: on s'attend à lire 3 en sortie)
    # assert dut.uo_out.value == 3, f"Erreur: attendu 3, obtenu {dut.uo_out.value}"
    dut._log.info(f"Valeur de sortie : {dut.uo_out.value}")
"""
        elif "2. Test Séquentiel" in choice:
            snippet = """import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

@cocotb.test()
async def test_sequentiel(dut):
    dut._log.info("Début du test avec horloge")

    # 1. Lancement de l'horloge (10 us de période)
    clock = Clock(dut.clk, 10, units="us")
    cocotb.start_soon(clock.start())

    # 2. Reset du circuit (toutes les entrées sont initialisées)
    dut._log.info("Reset")
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)  # On attend 5 cycles d'horloge

    # 3. Fin du reset, le circuit démarre
    dut.rst_n.value = 1

    # 4. On laisse tourner le circuit pendant 10 cycles
    await ClockCycles(dut.clk, 10)

    dut._log.info(f"Valeur finale : {dut.uo_out.value}")
"""
        if not snippet:
            return
        if self.confirm_replace(self.tab_testpy, "Générer ce modèle de test"):
            self.tab_testpy.set_content(snippet)
            self.tab_testpy.save()

    def run_simulation(self):
        if not self.project_dir:
            messagebox.showerror("Erreur", "Veuillez d'abord créer ou charger un projet.")
            return
        if not self.save_all():
            return
        if not self.patch_makefile():
            return
        cmd_test = "source tt_env/bin/activate && export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 && cd test && make -B"
        self.run_async_command(
            cmd_test, shell=True,
            success_msg="✅ Simulation terminée !\nVérifiez si 'PASS' s'affiche dans la console.",
            error_msg="❌ Échec de la simulation (Erreurs Icarus ou Cocotb).")

    def patch_makefile(self):
        """Génère test/Makefile (tous les .v de src/). Un Makefile non généré par nous est sauvegardé en .orig."""
        makefile_content = f"""# Makefile
{MAKEFILE_MARKER}
SIM ?= icarus
TOPLEVEL_LANG ?= verilog
SRC_DIR = $(PWD)/../src
PROJECT_SOURCES = {" ".join(self.src_files())}

ifneq ($(GATES),yes)
SIM_BUILD = sim_build/rtl
VERILOG_SOURCES += $(addprefix $(SRC_DIR)/,$(PROJECT_SOURCES))
COMPILE_ARGS += -I$(SRC_DIR)
else
# Simulation gate-level : définissez PDK_ROOT avant 'make GATES=yes'
SIM_BUILD = sim_build/gl
COMPILE_ARGS += -DGL_TEST -DFUNCTIONAL -DUSE_POWER_PINS -DSIM -DUNIT_DELAY=\\#1
VERILOG_SOURCES += $(PDK_ROOT)/sky130A/libs.ref/sky130_fd_sc_hd/verilog/primitives.v
VERILOG_SOURCES += $(PDK_ROOT)/sky130A/libs.ref/sky130_fd_sc_hd/verilog/sky130_fd_sc_hd.v
VERILOG_SOURCES += $(PWD)/gate_level_netlist.v
endif

VERILOG_SOURCES += $(PWD)/tb.v
TOPLEVEL = tb
MODULE = test
include $(shell cocotb-config --makefiles)/Makefile.sim
"""
        test_dir = os.path.join(self.project_dir, "test")
        makefile_path = os.path.join(test_dir, "Makefile")
        try:
            os.makedirs(test_dir, exist_ok=True)
            if os.path.exists(makefile_path):
                with open(makefile_path, "r", encoding="utf-8", errors="replace") as f:
                    existing = f.read()
                backup = makefile_path + ".orig"
                if MAKEFILE_MARKER not in existing and not os.path.exists(backup):
                    shutil.copy2(makefile_path, backup)
                    self.log_console("ℹ️ Makefile d'origine sauvegardé dans test/Makefile.orig")
            with open(makefile_path, "w", encoding="utf-8") as f:
                f.write(makefile_content)
            return True
        except OSError as e:
            messagebox.showerror("Erreur", f"Impossible d'écrire test/Makefile :\n{e}")
            return False

    # ---------------------------------------------------------------- info.yaml
    def open_pinout_assistant(self):
        if not self.ensure_top_module():
            return

        dialog = tk.Toplevel(self)
        dialog.title("Assistant info.yaml (Mapping des Pins)")
        dialog.geometry("800x600")
        dialog.transient(self)
        dialog.grab_set()

        # --- INFOS GÉNÉRALES ---
        frame_info = ttk.LabelFrame(dialog, text="Informations du Projet")
        frame_info.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(frame_info, text="Titre :").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        ent_title = ttk.Entry(frame_info, width=50)
        ent_title.insert(0, self.project_name or "mon_projet")
        ent_title.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(frame_info, text="Description :").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        ent_desc = ttk.Entry(frame_info, width=50)
        ent_desc.insert(0, "Description de mon circuit")
        ent_desc.grid(row=1, column=1, padx=5, pady=5)

        # --- MATRICE DU PINOUT ---
        frame_pins = ttk.LabelFrame(dialog, text="Assignation Physique (Laissez 'unused' si non utilisé)")
        frame_pins.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        ui_entries, uo_entries, uio_entries = [], [], []

        ttk.Label(frame_pins, text="Entrées (ui_in)", font=("Helvetica", 10, "bold")).grid(row=0, column=0, padx=20, pady=5)
        ttk.Label(frame_pins, text="Sorties (uo_out)", font=("Helvetica", 10, "bold")).grid(row=0, column=1, padx=20, pady=5)
        ttk.Label(frame_pins, text="Bidir (uio)", font=("Helvetica", 10, "bold")).grid(row=0, column=2, padx=20, pady=5)

        # Génération de la grille 3x8
        for i in range(8):
            for col, prefix, default, store in ((0, "ui", f"data_in[{i}]", ui_entries),
                                                (1, "uo", f"data_out[{i}]", uo_entries),
                                                (2, "uio", "unused", uio_entries)):
                cell = ttk.Frame(frame_pins)
                cell.grid(row=i + 1, column=col, pady=3, padx=10)
                ttk.Label(cell, text=f"{prefix}[{i}] :").pack(side=tk.LEFT)
                entry = ttk.Entry(cell, width=15)
                entry.insert(0, default)
                entry.pack(side=tk.LEFT)
                store.append(entry)

        def on_generate():
            if not self.tab_yaml.is_empty() and not messagebox.askyesno(
                    "Remplacer info.yaml",
                    "Cela va écraser le contenu actuel de info.yaml. Continuer ?", parent=dialog):
                return
            self.generate_yaml_from_assistant(ent_title.get(), ent_desc.get(), ui_entries, uo_entries, uio_entries)
            dialog.destroy()

        ttk.Button(dialog, text="Générer et Sauvegarder info.yaml", command=on_generate).pack(pady=10)

    def generate_yaml_from_assistant(self, title, desc, ui_entries, uo_entries, uio_entries):
        author = self.global_config.get("github_user", "") or "Auteur"

        def q(value):
            # json.dumps produit une chaîne entre guillemets valide en YAML (échappe " et \)
            return json.dumps(value, ensure_ascii=False)

        sources = "\n".join(f"    - {q(f)}" for f in self.src_files())

        yaml_content = f"""# Tiny Tapeout project information
project:
  title:        {q(title.strip())}
  author:       {q(author)}
  discord:      ""
  description:  {q(desc.strip())}
  language:     "Verilog"
  clock_hz:     0

  tiles: "1x1"
  top_module:  {q(self.top_module)}

  source_files:
{sources}

pinout:
"""
        for prefix, entries in (("ui", ui_entries), ("uo", uo_entries), ("uio", uio_entries)):
            for i in range(8):
                val = entries[i].get().strip() or "unused"
                yaml_content += f"  {prefix}[{i}]: {q(val)}\n"
            yaml_content += "\n"

        yaml_content = yaml_content.rstrip("\n") + "\n\nyaml_version: 6\n"

        self.tab_yaml.set_content(yaml_content)
        if self.tab_yaml.save():
            self.log_console("✅ info.yaml généré via l'assistant avec succès.")

    # ----------------------------------------------------------------- Place & Route
    def build_pnr_tab(self):
        ttk.Label(self.tab_pnr, text="Flow RTL-to-GDS", font=("Helvetica", 14, "bold")).pack(pady=20)
        frame_pdk = ttk.Frame(self.tab_pnr)
        frame_pdk.pack(pady=5)
        ttk.Label(frame_pdk, text="Technologie (PDK) :").pack(side=tk.LEFT, padx=5)
        self.cbox_pdk = ttk.Combobox(frame_pdk, values=list(PDK_SETTINGS.keys()), state="readonly", width=25)
        self.cbox_pdk.current(0)
        self.cbox_pdk.pack(side=tk.LEFT, padx=5)
        ttk.Button(self.tab_pnr, text="Placer et Router (Hardening)", command=self.run_pnr).pack(pady=10)
        ttk.Button(self.tab_pnr, text="Ouvrir dans OpenROAD", command=self.open_openroad).pack(pady=10)

    def run_pnr(self):
        if not self.project_dir:
            messagebox.showerror("Erreur", "Veuillez d'abord charger ou créer un projet.")
            return
        if not self.save_all():
            return
        cfg = PDK_SETTINGS.get(self.cbox_pdk.get())
        if not cfg:
            return
        harden = cfg["harden"]
        cmd_pnr = f"""set -e
source tt_env/bin/activate
export PDK={shlex.quote(cfg['env'])}
help_out=$(./tt/tt_tool.py --help 2>&1 || true)
if ! grep -q -- {shlex.quote(harden)} <<< "$help_out"; then
    echo "❌ Option {harden} introuvable dans ./tt/tt_tool.py (ou tt_tool.py ne démarre pas)."
    echo "   Vérifiez la branche de tt-support-tools : ./tt/tt_tool.py --help"
    exit 1
fi
./tt/tt_tool.py {cfg['create']}
./tt/tt_tool.py {harden}
"""
        self.run_async_command(
            cmd_pnr, shell=True,
            blocking_msg="Routage GDS et génération physique en cours...\n(Ceci prend généralement entre 3 et 5 minutes)\n\nVeuillez patienter.",
            success_msg="✅ Hardening terminé avec succès !\nVérifiez les mentions LVS et DRC dans la console.",
            error_msg="❌ Échec du Place & Route (Hardening).\nVérifiez les journaux OpenLane dans la console.")

    # ------------------------------------------------------------------ onglets
    def build_rtl_tab(self):
        ttk.Label(self.tab_rtl.toolbar, text="|").pack(side=tk.LEFT, padx=5)
        ttk.Button(self.tab_rtl.toolbar, text="Vérifier le Verilog (Lint)", command=self.verify_rtl).pack(side=tk.LEFT, padx=5)
        ttk.Button(self.tab_rtl.toolbar, text="Visualiser RTL (Schéma)", command=self.view_rtl_schematic).pack(side=tk.LEFT, padx=5)

        acc_frame = self.tab_rtl.custom_frame
        ttk.Label(acc_frame, text="Assistant de code :").pack(side=tk.LEFT, padx=5)
        self.cbox_snippets = ttk.Combobox(acc_frame, values=[
            "1. Squelette de base", "2. Hello World (Portes ET/OU)",
            "3. Compteur 8 bits", "4. Clignotant (Blink LED)"
        ], state="readonly", width=25)
        self.cbox_snippets.current(0)
        self.cbox_snippets.pack(side=tk.LEFT, padx=5)
        ttk.Button(acc_frame, text="Générer le code", command=self.insert_snippet).pack(side=tk.LEFT, padx=5)

        ttk.Label(acc_frame, text="|").pack(side=tk.LEFT, padx=10)
        ttk.Button(acc_frame, text="Ouvrir l'éditeur visuel (Digital)", command=self.open_digital_editor).pack(side=tk.LEFT, padx=5)

        help_text = "Astuce : Dessinez votre circuit dans 'Digital' -> Exportez en Verilog -> Utilisez 'Importer...' ci-dessus."
        ttk.Label(self.tab_rtl.custom_frame, text=help_text, font=("Helvetica", 9, "italic"), foreground="gray").pack(fill=tk.X, pady=(5, 0))

    def build_tbv_tab(self):
        ttk.Label(self.tab_tbv.toolbar, text="|").pack(side=tk.LEFT, padx=5)
        ttk.Button(self.tab_tbv.toolbar, text="✨ Générer tb.v automatiquement", command=self.generate_tbv_auto).pack(side=tk.LEFT, padx=5)

    def build_testpy_tab(self):
        ttk.Label(self.tab_testpy.toolbar, text="| Assistant :").pack(side=tk.LEFT, padx=5)
        self.cbox_test = ttk.Combobox(self.tab_testpy.toolbar, values=["1. Test Logique", "2. Test Séquentiel"], state="readonly", width=20)
        self.cbox_test.current(0)
        self.cbox_test.pack(side=tk.LEFT, padx=5)
        ttk.Button(self.tab_testpy.toolbar, text="Générer", command=self.insert_test_snippet).pack(side=tk.LEFT, padx=5)

        sim_frame = self.tab_testpy.custom_frame
        ttk.Button(sim_frame, text="▶ Lancer la Simulation (Test)", command=self.run_simulation).pack(side=tk.LEFT, padx=5)
        ttk.Button(sim_frame, text="🔍 Ouvrir GTKWave", command=self.open_gtkwave).pack(side=tk.LEFT, padx=5)

    def build_yaml_tab(self):
        ttk.Label(self.tab_yaml.toolbar, text="|").pack(side=tk.LEFT, padx=5)
        ttk.Button(self.tab_yaml.toolbar, text="🎛️ Assistant Configuration & Pinout", command=self.open_pinout_assistant).pack(side=tk.LEFT, padx=5)

    def build_doc_tab(self):
        ttk.Label(self.tab_doc.toolbar, text="|").pack(side=tk.LEFT, padx=5)
        ttk.Button(self.tab_doc.toolbar, text="Générer Template info.md", command=self.generate_doc_template).pack(side=tk.LEFT, padx=5)

    def generate_doc_template(self):
        template = """<!---
This file is used to generate your project datasheet. Please fill in the information below and delete any unused sections.
You can also include images in this folder and reference them in the markdown. Each image must be less than 512 kb in size.
-->
## How it works
Explain how your project works
## How to test
Explain how to use your project
## External hardware
List external hardware used in your project (e.g. PMOD, LED display, etc), if any
"""
        if self.confirm_replace(self.tab_doc, "Générer le template"):
            self.tab_doc.set_content(template)

    def build_git_tab(self):
        # 1. Le conteneur principal avec la scrollbar
        canvas = tk.Canvas(self.tab_git, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.tab_git, orient=tk.VERTICAL, command=canvas.yview)
        
        # 2. Le frame intérieur principal
        frame = ttk.Frame(canvas)
        
        # 3. Lier la scrollbar et le canvas
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # 4. Créer la fenêtre dans le canvas (PAS de pack ou grid sur 'frame' après ça)
        canvas_window = canvas.create_window((0, 0), window=frame, anchor="nw")
        
        # 5. Ajuster la zone de défilement à la taille du contenu
        frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        
        # 6. Ajuster la largeur du contenu à celle du canvas
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_window, width=e.width))

        # --- Conteneur pour les marges internes (remplace le pack_configure) ---
        content = ttk.Frame(frame, padding="50 20 50 20")
        content.pack(fill=tk.BOTH, expand=True)

        ttk.Label(content, text="Soumission GitHub (Tapeout)", font=("Helvetica", 14, "bold")).grid(row=0, column=0, columnspan=2, pady=10)
        
        instructions = ("⚠️ IMPORTANT AVANT DE PUSHER :\n"
                        "1. Settings > Pages : choisissez « GitHub Actions » dans Build and deployment > Source.\n"
                        "2. Settings > Actions > General : cochez « Read and write permissions » (Workflow permissions).\n"
                        "3. Le token classique doit avoir les scopes « repo » ET « workflow » (le push modifie .github/workflows/).\n"
                        "4. Le dépôt distant doit être vide (pas de README/licence), sinon cochez « Forcer le push ».")
        ttk.Label(content, text=instructions, foreground="red", justify=tk.LEFT, wraplength=700).grid(row=1, column=0, columnspan=2, pady=10, sticky="w")

        ttk.Label(content, text="Pseudo :").grid(row=2, column=0, sticky="w", pady=5)
        self.ent_git_user = ttk.Entry(content, width=40)
        self.ent_git_user.insert(0, self.global_config.get("github_user", ""))
        self.ent_git_user.grid(row=2, column=1)

        ttk.Label(content, text="Token (Clé classique) :").grid(row=3, column=0, sticky="w", pady=5)
        self.ent_git_pass = ttk.Entry(content, width=40, show="*")
        self.ent_git_pass.grid(row=3, column=1)

        ttk.Label(content, text="URL du Repo :").grid(row=4, column=0, sticky="w", pady=5)
        self.ent_git_url = ttk.Entry(content, width=40)
        self.ent_git_url.grid(row=4, column=1)

        ttk.Label(content, text="Message du commit :").grid(row=5, column=0, sticky="w", pady=5)
        self.ent_git_commit = ttk.Entry(content, width=40)
        self.ent_git_commit.insert(0, "Mon design prêt pour le tapeout")
        self.ent_git_commit.grid(row=5, column=1)

        self.var_force = tk.BooleanVar(value=False)
        ttk.Checkbutton(content, text="Forcer le push (--force) : écrase le contenu du dépôt distant",
                        variable=self.var_force).grid(row=6, column=0, columnspan=2, sticky="w", pady=5)

        ttk.Button(content, text="Push to GitHub", command=self.push_to_github).grid(row=7, column=0, columnspan=2, pady=20)

        ttk.Separator(content, orient='horizontal').grid(row=8, column=0, columnspan=2, sticky="ew", pady=15)
        ttk.Label(content, text="Étape Finale : Acheter / Valider le Tapeout", font=("Helvetica", 12, "bold")).grid(row=9, column=0, columnspan=2, pady=10)
        ttk.Label(content, text="Une fois le push terminé et les Actions GitHub validées au vert,\ncliquez ci-dessous pour soumettre officiellement votre puce à la fabrication.", justify=tk.CENTER).grid(row=10, column=0, columnspan=2, pady=5)
        ttk.Button(content, text="Ouvrir app.tinytapeout.com", command=lambda: webbrowser.open("https://app.tinytapeout.com")).grid(row=11, column=0, columnspan=2, pady=10)
    
    def patch_docs_yaml(self):
        """Workflow docs figé sur tt08 : uniquement pertinent pour le template SkyWater."""
        if self.project_template != SKYWATER_TEMPLATE:
            return
        yaml_content = """name: docs
on:
  push:
  workflow_dispatch:
jobs:
  docs:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repo
        uses: actions/checkout@v4
        with:
          submodules: recursive
      - name: Install Typst
        run: |
          curl -fsSL https://github.com/typst/typst/releases/download/@@TYPST@@/typst-x86_64-unknown-linux-musl.tar.xz | tar -xJ
          sudo mv typst-*/typst /usr/local/bin/
      - name: Build docs
        uses: TinyTapeout/tt-gds-action/docs@tt08
""".replace("@@TYPST@@", TYPST_VERSION)
        docs_path = os.path.join(self.project_dir, ".github", "workflows", "docs.yaml")
        try:
            os.makedirs(os.path.dirname(docs_path), exist_ok=True)
            with open(docs_path, "w", encoding="utf-8") as f:
                f.write(yaml_content)
        except OSError as e:
            self.log_console(f"⚠️ Impossible d'écrire docs.yaml : {e}")

    def push_to_github(self):
        if not self.project_dir:
            messagebox.showerror("Erreur", "Veuillez d'abord créer ou charger un projet avant de soumettre sur GitHub.")
            return

        user = self.ent_git_user.get().strip()
        token = self.ent_git_pass.get().strip()
        repo_url = self.ent_git_url.get().strip()
        commit_text = self.ent_git_commit.get().strip() or "Mise à jour du design"

        if not user or not token or not repo_url:
            messagebox.showerror("Erreur", "Le pseudo, le token et l'URL du dépôt sont obligatoires.")
            return
        if not repo_url.startswith("https://"):
            messagebox.showerror("Erreur", "L'URL du dépôt doit commencer par https:// (authentification par token).")
            return

        force = self.var_force.get()
        if force and not messagebox.askyesno(
                "Push forcé",
                "Le push forcé va ÉCRASER l'historique du dépôt distant.\nÊtes-vous sûr de vouloir continuer ?"):
            return

        if not self.save_all():
            return
        self.patch_docs_yaml()

        actions_url = (repo_url[:-4] if repo_url.endswith(".git") else repo_url).rstrip("/") + "/actions"

        # Authentification par variables d'environnement : le token n'apparaît jamais dans la commande
        auth = base64.b64encode(f"{user}:{token}".encode()).decode()
        custom_env = {**os.environ,
                      "GIT_TERMINAL_PROMPT": "0",
                      "GIT_CONFIG_COUNT": "1",
                      "GIT_CONFIG_KEY_0": "http.extraheader",
                      "GIT_CONFIG_VALUE_0": f"Authorization: Basic {auth}"}

        force_flag = " --force" if force else ""
        cmd = f"""set -e
git rev-parse --git-dir >/dev/null 2>&1 || git init
git remote remove origin 2>/dev/null || true
git rm -r --cached --ignore-unmatch -q tt 2>/dev/null || true
git config user.email {shlex.quote(user + "@users.noreply.github.com")}
git config user.name {shlex.quote(user)}
git add .
git commit -m {shlex.quote(commit_text)} || echo "(Rien de nouveau à commiter, on continue)"
git branch -M main
git remote add origin {shlex.quote(repo_url)}
git push -u origin main{force_flag}
"""
        msg_succes = ("✅ Soumission terminée !\n\nVotre navigateur va s'ouvrir sur la page 'Actions' de votre dépôt.\n\n"
                      "⚠️ VEUILLEZ VÉRIFIER : Assurez-vous que les workflows (docs et gds) se terminent tous par une icône verte sans erreur.")

        self.run_async_command(
            cmd, shell=True, env=custom_env, secrets=[token, auth],
            blocking_msg="Envoi du projet vers GitHub en cours...\nVeuillez patienter.",
            success_msg=msg_succes,
            error_msg="❌ Le push a échoué.\nConsultez la console (token sans scope 'workflow' ? dépôt distant non vide ?).",
            success_callback=lambda: webbrowser.open(actions_url))

    # ------------------------------------------------------ exécution asynchrone
    @staticmethod
    def _mask(text, secrets):
        for secret in secrets:
            text = text.replace(secret, "********")
        return text

    def run_async_command(self, cmd, shell=False, secrets=None, env=None, cwd=None, require_project=True,
                          blocking_msg=None, success_msg=None, error_msg=None, success_callback=None):
        if require_project and not self.project_dir:
            messagebox.showerror("Erreur", "Veuillez d'abord créer ou charger un projet.")
            return
        secrets = [s for s in (secrets or []) if s and s.strip()]
        if blocking_msg:
            self.show_loading(blocking_msg)
        self.log_console(f"\n> {self._mask(cmd, secrets)}")

        cwd = cwd or self.project_dir or None
        thread = threading.Thread(
            target=self._exec_cmd,
            args=(cmd, shell, secrets, env, cwd, blocking_msg, success_msg, error_msg, success_callback),
            daemon=True)
        thread.start()

    def _exec_cmd(self, cmd, shell, secrets, env, cwd, blocking_msg, success_msg, error_msg, success_callback):
        """Tourne dans un thread : ne touche JAMAIS à Tkinter, tout passe par cmd_queue."""
        try:
            process = subprocess.Popen(
                cmd, shell=shell, cwd=cwd, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                executable="/bin/bash" if shell else None)
            for line in process.stdout:
                self.cmd_queue.put(self._mask(line, secrets))
            process.wait()
            returncode = process.returncode
            self.cmd_queue.put(f"\n[Terminé avec le code de retour {returncode}]\n")

            def cleanup():
                if blocking_msg:
                    self.hide_loading()
                if returncode == 0:
                    if success_msg:
                        messagebox.showinfo("Succès", success_msg)
                    if success_callback:
                        success_callback()
                elif error_msg:
                    messagebox.showerror("Erreur", error_msg)

            self.cmd_queue.put(cleanup)
        except Exception as e:  # noqa: BLE001 - on veut tout remonter à l'UI
            err_msg = self._mask(str(e), secrets)
            self.cmd_queue.put(f"\n[Erreur d'exécution: {err_msg}]\n")

            def cleanup_error():
                if blocking_msg:
                    self.hide_loading()
                messagebox.showerror("Erreur Système", err_msg)

            self.cmd_queue.put(cleanup_error)

    # ------------------------------------------------------------------ console
    def check_console_queue(self):
        try:
            chunk = []
            for _ in range(MAX_QUEUE_ITEMS_PER_TICK):
                try:
                    item = self.cmd_queue.get_nowait()
                except queue.Empty:
                    break
                if callable(item):
                    # On vide d'abord les lignes en attente pour garder l'ordre,
                    # puis on exécute le callback hors de ce tick (les popups bloquent).
                    if chunk:
                        self.log_console("".join(chunk), newline=False)
                        chunk = []
                    self.after(0, item)
                else:
                    chunk.append(item)
            if chunk:
                self.log_console("".join(chunk), newline=False)
        finally:
            self.after(100, self.check_console_queue)

    def log_console(self, text, newline=True):
        # Nettoyage des codes de couleur ANSI générés par bash/OpenLane
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        clean_text = ansi_escape.sub('', text)

        # On déverrouille temporairement, on écrit, on reverrouille
        self.console.config(state=tk.NORMAL)
        self.console.insert(tk.END, clean_text + ("\n" if newline else ""))
        # Limite l'historique pour ne pas ralentir l'UI avec les longs logs
        total_lines = int(self.console.index("end-1c").split(".")[0])
        if total_lines > MAX_CONSOLE_LINES:
            self.console.delete("1.0", f"{total_lines - MAX_CONSOLE_LINES}.0")
        self.console.see(tk.END)
        self.console.config(state=tk.DISABLED)


if __name__ == "__main__":
    app = EasyTTCad()
    app.mainloop()
