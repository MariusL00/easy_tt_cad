import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import subprocess
import os
import threading
import queue
import webbrowser

class EasyTTCad(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Easy TT CAD - Flow RTL-to-GDS")
        self.geometry("1100x850")
        
        self.project_dir = ""
        self.top_module = ""
        self.cmd_queue = queue.Queue()
        self.loading_win = None
        
        self.setup_menu()
        self.setup_ui()
        self.check_console_queue()

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
        file_menu.add_command(label="Quitter", command=self.quit)
        
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Aide & Liens", menu=help_menu)
        help_menu.add_command(label="Documentation Tiny Tapeout", command=lambda: webbrowser.open("https://tinytapeout.com"))
        help_menu.add_command(label="Soumettre son projet (App)", command=lambda: webbrowser.open("https://app.tinytapeout.com"))

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
        
        self.tab_rtl = ttk.Frame(self.notebook)
        self.tab_tbv = ttk.Frame(self.notebook)
        self.tab_testpy = ttk.Frame(self.notebook)
        self.tab_yaml = ttk.Frame(self.notebook)
        self.tab_pnr = ttk.Frame(self.notebook)
        self.tab_doc = ttk.Frame(self.notebook)
        self.tab_git = ttk.Frame(self.notebook)
        
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
        self.console = tk.Text(console_frame, bg="black", fg="lightgreen", font=("Courier", 10))
        self.console.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    def create_new_project(self):
        folder = filedialog.askdirectory(title="Sélectionner le dossier de destination")
        if not folder: return
        
        dialog = tk.Toplevel(self)
        dialog.title("Configuration du projet")
        dialog.geometry("450x380")
        dialog.transient(self)
        dialog.grab_set()
        
        v_name = tk.StringVar(value="alu")
        v_user = tk.StringVar(value="MariusL00")
        v_tech = tk.StringVar(value="SkyWater 130nm (ex: tt08)")
        v_custom = tk.StringVar(value="")
        
        ttk.Label(dialog, text="Nom du projet (ex: alu) :").pack(pady=(15, 2))
        ttk.Entry(dialog, textvariable=v_name, width=30).pack(pady=2)
        
        ttk.Label(dialog, text="Pseudo GitHub :").pack(pady=(10, 2))
        ttk.Entry(dialog, textvariable=v_user, width=30).pack(pady=2)
        
        ttk.Label(dialog, text="Choix de la technologie (Template) :").pack(pady=(10, 2))
        cb_tech = ttk.Combobox(dialog, textvariable=v_tech, values=[
            "SkyWater 130nm (ex: tt08)",
            "GlobalFoundries 180nm (ex: GF26)",
            "Lien personnalisé"
        ], state="readonly", width=35)
        cb_tech.pack(pady=2)
        
        lbl_custom = ttk.Label(dialog, text="URL du dépôt GitHub personnalisé :")
        ent_custom = ttk.Entry(dialog, textvariable=v_custom, width=40)
        
        def on_tech_change(event):
            if v_tech.get() == "Lien personnalisé":
                lbl_custom.pack(pady=(10, 2))
                ent_custom.pack(pady=2)
            else:
                lbl_custom.pack_forget()
                ent_custom.pack_forget()
                
        cb_tech.bind("<<ComboboxSelected>>", on_tech_change)
        
        result = {}
        def on_submit():
            result['name'] = v_name.get().strip()
            result['user'] = v_user.get().strip()
            result['tech'] = v_tech.get()
            result['custom'] = v_custom.get().strip()
            if not result['name'] or not result['user']:
                messagebox.showerror("Erreur", "Le nom et le pseudo sont obligatoires.")
                return
            dialog.destroy()
            
        ttk.Button(dialog, text="Initialiser le projet", command=on_submit).pack(pady=20)
        self.wait_window(dialog)
        
        if not result or not result.get('name'): return
            
        proj_name = result['name']
        github_user = result['user']
        
        if result['tech'] == "SkyWater 130nm (ex: tt08)":
            template_url = "https://github.com/TinyTapeout/tt08-verilog-template"
        elif result['tech'] == "GlobalFoundries 180nm (ex: GF26)":
            template_url = "https://github.com/TinyTapeout/tt-gf180-template"
        else:
            template_url = result['custom']
            
        if not template_url: return
            
        self.top_module = f"tt_um_{proj_name}_{github_user}"
        self.project_dir = os.path.join(folder, proj_name)
        os.makedirs(self.project_dir, exist_ok=True)
        
        self.welcome_frame.pack_forget()
        self.paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        cmd = f"""
        git clone {template_url} .temp
        mv .temp/* .temp/.* . 2>/dev/null
        rm -rf .temp
        rm -rf .git
        git init
        git submodule add https://github.com/TinyTapeout/tt-support-tools tt
        echo "tt_env/" >> .gitignore
        
        git config user.name "{github_user}"
        git config user.email "{github_user}@users.noreply.github.com"
        git add .
        git commit -m "Initial commit"
        
        python3 -m venv tt_env
        source tt_env/bin/activate
        pip install --upgrade pip
        sed -i 's/==.*//' tt/requirements.txt
        pip install -r tt/requirements.txt
        pip install cocotb pytest lark "pytest<8.0.0" librelane
        """
        self.log_console(f"--- Création du projet {self.top_module} depuis {template_url} ---")
        self.run_async_command(
            cmd, shell=True, 
            blocking_msg=f"Téléchargement du template ({result['tech']})...\nInstallation Git, Python venv, Pip\n\nVeuillez patienter.",
            success_msg="Le projet a été créé et l'environnement est prêt !"
        )

    def load_project(self):
        folder = filedialog.askdirectory(title="Sélectionner le dossier du projet existant")
        if not folder: return
        
        self.project_dir = folder
        self.top_module = "tt_um_inconnu"
        
        yaml_path = os.path.join(self.project_dir, "info.yaml")
        if os.path.exists(yaml_path):
            with open(yaml_path, 'r') as f:
                for line in f:
                    if "top_module:" in line:
                        self.top_module = line.split(":")[1].strip().strip('"').strip("'")
                        break
                        
        self.welcome_frame.pack_forget()
        self.paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.load_file_into_widget("src/project.v", self.txt_rtl)
        self.load_file_into_widget("test/tb.v", self.txt_tbv)
        self.load_file_into_widget("test/test.py", self.txt_testpy)
        self.load_file_into_widget("info.yaml", self.txt_yaml)
        self.load_file_into_widget("docs/info.md", self.txt_doc)
        
        self.log_console(f"✅ Projet '{self.top_module}' chargé depuis {self.project_dir}.")
        messagebox.showinfo("Projet chargé", f"Le projet {self.top_module} a été chargé avec succès.")

    def save_all(self):
        if not self.project_dir: return
        self.save_file("src/project.v", self.txt_rtl)
        self.save_file("test/tb.v", self.txt_tbv)
        self.save_file("test/test.py", self.txt_testpy)
        self.save_file("info.yaml", self.txt_yaml)
        self.save_file("docs/info.md", self.txt_doc)
        messagebox.showinfo("Sauvegarde globale", "Tous les fichiers du projet ont été sauvegardés.")

    def load_file_into_widget(self, filepath, text_widget):
        full_path = os.path.join(self.project_dir, filepath)
        if os.path.exists(full_path):
            with open(full_path, "r") as f:
                content = f.read()
            text_widget.delete("1.0", tk.END)
            text_widget.insert("1.0", content)

    def import_file(self, text_widget):
        filepath = filedialog.askopenfilename(title="Importer un fichier")
        if filepath:
            try:
                with open(filepath, "r") as f:
                    content = f.read()
                text_widget.delete("1.0", tk.END)
                text_widget.insert("1.0", content)
                self.log_console(f"✅ Fichier importé : {filepath}")
            except Exception as e:
                messagebox.showerror("Erreur", f"Impossible de lire le fichier : {e}")

    def show_loading(self, message):
        self.loading_win = tk.Toplevel(self)
        self.loading_win.title("Veuillez patienter")
        self.loading_win.geometry("450x150")
        self.loading_win.transient(self)
        self.loading_win.grab_set() 
        self.loading_win.protocol("WM_DELETE_WINDOW", lambda: None) 
        lbl = ttk.Label(self.loading_win, text=message, justify=tk.CENTER, font=("Helvetica", 11))
        lbl.pack(expand=True, fill=tk.BOTH, padx=20, pady=20)
        self.update()

    def hide_loading(self):
        if self.loading_win:
            self.loading_win.grab_release()
            self.loading_win.destroy()
            self.loading_win = None

    def build_rtl_tab(self):
        btn_frame = ttk.Frame(self.tab_rtl)
        btn_frame.pack(fill=tk.X, pady=5)
        ttk.Button(btn_frame, text="Importer un fichier...", command=lambda: self.import_file(self.txt_rtl)).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Sauvegarder src/project.v", command=lambda: self.save_file("src/project.v", self.txt_rtl)).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Vérifier le Verilog (Lint)", command=self.verify_rtl).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Visualiser RTL (Schéma)", command=self.view_rtl_schematic).pack(side=tk.LEFT, padx=5)
        
        # --- BLOC : ACCESSIBILITÉ & ASSISTANT ---
        ttk.Separator(self.tab_rtl, orient='horizontal').pack(fill=tk.X, pady=5)
        acc_frame = ttk.Frame(self.tab_rtl)
        acc_frame.pack(fill=tk.X, pady=2)
        
        ttk.Label(acc_frame, text="Assistant de code :").pack(side=tk.LEFT, padx=5)
        self.cbox_snippets = ttk.Combobox(acc_frame, values=[
            "1. Squelette de base (Vide)",
            "2. Hello World (Portes ET/OU)",
            "3. Compteur 8 bits",
            "4. Clignotant (Blink LED)"
        ], state="readonly", width=25)
        self.cbox_snippets.current(0)
        self.cbox_snippets.pack(side=tk.LEFT, padx=5)
        ttk.Button(acc_frame, text="Générer le code", command=self.insert_snippet).pack(side=tk.LEFT, padx=5)
        
        ttk.Label(acc_frame, text="|").pack(side=tk.LEFT, padx=10)
        
        # --- NOUVEAU BOUTON : DIGITAL (H. NEEMANN) ---
        ttk.Button(acc_frame, text="Ouvrir l'éditeur visuel (Digital)", command=self.open_digital_editor).pack(side=tk.LEFT, padx=5)
        
        # Petit texte d'aide sous la barre d'outils
        help_text = "Astuce : Dessinez votre circuit dans 'Digital' -> Exportez en Verilog -> Utilisez le bouton 'Importer un fichier...' ci-dessus."
        ttk.Label(self.tab_rtl, text=help_text, font=("Helvetica", 9, "italic"), foreground="gray").pack(fill=tk.X, pady=(0, 5))

        self.txt_rtl = tk.Text(self.tab_rtl, font=("Monospace", 11))
        self.txt_rtl.pack(fill=tk.BOTH, expand=True, pady=5)

    def open_digital_editor(self):
        # On cache l'installation dans un dossier .easy_tt_cad dans le répertoire de l'utilisateur
        install_dir = os.path.expanduser("~/.easy_tt_cad")
        jar_path = os.path.join(install_dir, "Digital", "Digital.jar")
        
        # Si le fichier n'existe pas encore, on le télécharge, on l'extrait et on le lance
        if not os.path.exists(jar_path):
            cmd = f"""
            mkdir -p {install_dir}
            cd {install_dir}
            curl -sL -o Digital.zip https://github.com/hneemann/Digital/releases/latest/download/Digital.zip
            unzip -q Digital.zip
            rm Digital.zip
            java -jar "{jar_path}" &
            """
            self.run_async_command(
                cmd, 
                shell=True,
                blocking_msg="Premier lancement : Téléchargement de l'outil Digital en cours...\n(Ceci ne se fera qu'une seule fois)\n\nVeuillez patienter.",
                error_msg="❌ Impossible de lancer Digital.\nVérifiez que Java et unzip sont installés : sudo apt install default-jre unzip"
            )
        else:
            # Si déjà installé, on lance directement l'interface Java
            self.run_async_command(
                f'java -jar "{jar_path}" &', 
                shell=True,
                error_msg="❌ Impossible de lancer Digital.\nVérifiez que Java est bien installé sur le système."
            )

    def insert_snippet(self):
        if not self.top_module:
            messagebox.showerror("Erreur", "Créez ou chargez d'abord un projet.")
            return
            
        choice = self.cbox_snippets.get()
        if not choice: return
        
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

        if messagebox.askyesno("Remplacer le code", "Générer ce module va écraser le contenu actuel de l'éditeur RTL. Continuer ?"):
            self.txt_rtl.delete("1.0", tk.END)
            self.txt_rtl.insert("1.0", snippet)
            self.log_console(f"Module '{choice}' inséré avec succès.")

    def verify_rtl(self):
        if not self.project_dir:
            messagebox.showerror("Erreur", "Veuillez d'abord créer ou charger un projet.")
            return
        rtl_code = self.txt_rtl.get("1.0", tk.END)
        expected_declaration = f"module {self.top_module}"
        if expected_declaration not in rtl_code:
            messagebox.showwarning("Erreur de Top Module", f"Attention ! Ligne attendue :\n{expected_declaration} (")
            return
        self.save_file("src/project.v", self.txt_rtl)
        cmd = "verilator --lint-only src/project.v"
        self.run_async_command(cmd, shell=True, success_msg="✅ Le code RTL a été vérifié et ne contient aucune erreur de syntaxe !", error_msg="❌ Des erreurs de syntaxe ont été détectées par Verilator.\nVeuillez consulter la console.")

    def view_rtl_schematic(self):
        if not self.project_dir:
            messagebox.showerror("Erreur", "Veuillez d'abord créer ou charger un projet.")
            return
        self.save_file("src/project.v", self.txt_rtl)
        cmd = f"yosys -p 'read_verilog src/project.v; prep -top {self.top_module}; write_json rtl_netlist.json' && netlistsvg rtl_netlist.json -o rtl_view.svg && sed -i 's/<svg[^>]*>/&<rect width=\"100%\" height=\"100%\" fill=\"white\"\/>/' rtl_view.svg && xdg-open rtl_view.svg"
        self.run_async_command(cmd, shell=True, success_msg="✅ Schéma RTL Haute Définition généré !\nIl s'ouvre avec un fond blanc pour une meilleure lisibilité.", error_msg="❌ Échec de la génération.\nVérifiez la syntaxe Verilog ou l'installation de netlistsvg.")

    def build_tbv_tab(self):
        btn_frame = ttk.Frame(self.tab_tbv)
        btn_frame.pack(fill=tk.X, pady=5)
        
        # Nouveau bouton de génération automatique
        ttk.Button(btn_frame, text="✨ Générer tb.v automatiquement", command=self.generate_tbv_auto).pack(side=tk.LEFT, padx=5)
        ttk.Label(btn_frame, text="|").pack(side=tk.LEFT, padx=5)
        
        ttk.Button(btn_frame, text="Importer un fichier...", command=lambda: self.import_file(self.txt_tbv)).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Sauvegarder test/tb.v", command=lambda: self.save_file("test/tb.v", self.txt_tbv)).pack(side=tk.LEFT, padx=5)
        
        self.txt_tbv = tk.Text(self.tab_tbv, font=("Monospace", 11))
        self.txt_tbv.pack(fill=tk.BOTH, expand=True, pady=5)

    def generate_tbv_auto(self):
        if not self.top_module:
            messagebox.showerror("Erreur", "Veuillez d'abord créer ou charger un projet.")
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
        self.txt_tbv.delete("1.0", tk.END)
        self.txt_tbv.insert("1.0", tbv_content)
        self.save_file("test/tb.v", self.txt_tbv)
        self.log_console("Fichier testbench (tb.v) généré et sauvegardé avec succès.")

    def build_testpy_tab(self):
        btn_frame = ttk.Frame(self.tab_testpy)
        btn_frame.pack(fill=tk.X, pady=5)
        
        # Menu déroulant pour les tests Python
        ttk.Label(btn_frame, text="Assistant :").pack(side=tk.LEFT, padx=5)
        self.cbox_test = ttk.Combobox(btn_frame, values=[
            "1. Test Logique (ex: Portes, ALU)",
            "2. Test Séquentiel (ex: Compteur, Horloge)"
        ], state="readonly", width=35)
        self.cbox_test.current(0)
        self.cbox_test.pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Générer", command=self.insert_test_snippet).pack(side=tk.LEFT, padx=5)
        
        ttk.Label(btn_frame, text="|").pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Importer...", command=lambda: self.import_file(self.txt_testpy)).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Sauvegarder", command=lambda: self.save_file("test/test.py", self.txt_testpy)).pack(side=tk.LEFT, padx=5)
        
        ttk.Separator(self.tab_testpy, orient='horizontal').pack(fill=tk.X, pady=2)
        sim_frame = ttk.Frame(self.tab_testpy)
        sim_frame.pack(fill=tk.X, pady=2)
        ttk.Button(sim_frame, text="▶ Lancer la Simulation (Test)", command=self.run_simulation).pack(side=tk.LEFT, padx=5)
        ttk.Button(sim_frame, text="🔍 Ouvrir GTKWave", command=lambda: self.run_async_command("gtkwave test/tb.vcd &", shell=True)).pack(side=tk.LEFT, padx=5)

        self.txt_testpy = tk.Text(self.tab_testpy, font=("Monospace", 11))
        self.txt_testpy.pack(fill=tk.BOTH, expand=True, pady=5)

    def insert_test_snippet(self):
        choice = self.cbox_test.get()
        if not choice: return
        
        snippet = ""
        if "1. Test Logique" in choice:
            snippet = """import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def test_combinatoire(dut):
    dut._log.info("Début du test logique")
    
    # 1. Initialisation des entrées
    dut.ena.value = 1
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

    # 2. Reset du circuit
    dut._log.info("Reset")
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5) # On attend 5 cycles d'horloge
    
    # 3. Fin du reset, le circuit démarre
    dut.rst_n.value = 1
    
    # 4. On laisse tourner le circuit pendant 10 cycles
    await ClockCycles(dut.clk, 10)
    
    dut._log.info(f"Valeur finale : {dut.uo_out.value}")
"""
        if messagebox.askyesno("Remplacer le code", "Générer ce modèle de test va remplacer le contenu actuel. Continuer ?"):
            self.txt_testpy.delete("1.0", tk.END)
            self.txt_testpy.insert("1.0", snippet)
            self.save_file("test/test.py", self.txt_testpy)

    def generate_testpy_template(self):
        template = """# SPDX-FileCopyrightText: © 2024 Tiny Tapeout
# SPDX-License-Identifier: Apache-2.0

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

@cocotb.test()
async def test_project(dut):
    dut._log.info("Start")
    clock = Clock(dut.clk, 10, units="us")
    cocotb.start_soon(clock.start())
    dut._log.info("Reset")
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)
    dut._log.info("Test behavior")
"""
        self.txt_testpy.delete("1.0", tk.END)
        self.txt_testpy.insert("1.0", template)

    def run_simulation(self):
        if not self.project_dir: return
        self.patch_makefile()
        cmd_test = "source tt_env/bin/activate && export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 && cd test && make -B"
        self.run_async_command(cmd_test, shell=True, success_msg="✅ Simulation terminée !\nVérifiez si 'PASS' s'affiche dans la console.", error_msg="❌ Échec de la simulation (Erreurs Icarus ou Cocotb).")

    def patch_makefile(self):
        makefile_content = """# Makefile
SIM ?= icarus
TOPLEVEL_LANG ?= verilog
SRC_DIR = $(PWD)/../src
PROJECT_SOURCES = project.v

ifneq ($(GATES),yes)
SIM_BUILD = sim_build/rtl
VERILOG_SOURCES += $(addprefix $(SRC_DIR)/,$(PROJECT_SOURCES))
COMPILE_ARGS += -I$(SRC_DIR)
else
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
        makefile_path = os.path.join(self.project_dir, "test", "Makefile")
        os.makedirs(os.path.dirname(makefile_path), exist_ok=True)
        with open(makefile_path, "w") as f:
            f.write(makefile_content)

    def build_yaml_tab(self):
        btn_frame = ttk.Frame(self.tab_yaml)
        btn_frame.pack(fill=tk.X, pady=5)
        
        # Nouveau bouton vers l'interface visuelle
        ttk.Button(btn_frame, text="🎛️ Assistant Configuration & Pinout", command=self.open_pinout_assistant).pack(side=tk.LEFT, padx=5)
        ttk.Label(btn_frame, text="|").pack(side=tk.LEFT, padx=5)
        
        ttk.Button(btn_frame, text="Importer un fichier...", command=lambda: self.import_file(self.txt_yaml)).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Sauvegarder info.yaml", command=lambda: self.save_file("info.yaml", self.txt_yaml)).pack(side=tk.LEFT, padx=5)

        self.txt_yaml = tk.Text(self.tab_yaml, font=("Monospace", 11))
        self.txt_yaml.pack(fill=tk.BOTH, expand=True, pady=5)

    def open_pinout_assistant(self):
        if not self.top_module:
            messagebox.showerror("Erreur", "Veuillez d'abord créer ou charger un projet.")
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
        # Extrait le nom du projet depuis "tt_um_alu_MariusL00"
        ent_title.insert(0, self.top_module.split('_')[2] if len(self.top_module.split('_')) > 2 else "mon_projet")
        ent_title.grid(row=0, column=1, padx=5, pady=5)
        
        ttk.Label(frame_info, text="Description :").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        ent_desc = ttk.Entry(frame_info, width=50)
        ent_desc.insert(0, "Description de mon circuit")
        ent_desc.grid(row=1, column=1, padx=5, pady=5)
        
        # --- MATRICE DU PINOUT ---
        frame_pins = ttk.LabelFrame(dialog, text="Assignation Physique (Laissez 'unused' si non utilisé)")
        frame_pins.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        ui_entries = []
        uo_entries = []
        uio_entries = []
        
        ttk.Label(frame_pins, text="Entrées (ui_in)", font=("Helvetica", 10, "bold")).grid(row=0, column=0, padx=20, pady=5)
        ttk.Label(frame_pins, text="Sorties (uo_out)", font=("Helvetica", 10, "bold")).grid(row=0, column=1, padx=20, pady=5)
        ttk.Label(frame_pins, text="Bidir (uio)", font=("Helvetica", 10, "bold")).grid(row=0, column=2, padx=20, pady=5)
        
        # Génération de la grille 3x8
        for i in range(8):
            # Colonne UI (Entrées)
            f_ui = ttk.Frame(frame_pins)
            f_ui.grid(row=i+1, column=0, pady=3, padx=10)
            ttk.Label(f_ui, text=f"ui[{i}] :").pack(side=tk.LEFT)
            e_ui = ttk.Entry(f_ui, width=15)
            e_ui.insert(0, f"data_in[{i}]")
            e_ui.pack(side=tk.LEFT)
            ui_entries.append(e_ui)
            
            # Colonne UO (Sorties)
            f_uo = ttk.Frame(frame_pins)
            f_uo.grid(row=i+1, column=1, pady=3, padx=10)
            ttk.Label(f_uo, text=f"uo[{i}] :").pack(side=tk.LEFT)
            e_uo = ttk.Entry(f_uo, width=15)
            e_uo.insert(0, f"data_out[{i}]")
            e_uo.pack(side=tk.LEFT)
            uo_entries.append(e_uo)
            
            # Colonne UIO (Bidirectionnels)
            f_uio = ttk.Frame(frame_pins)
            f_uio.grid(row=i+1, column=2, pady=3, padx=10)
            ttk.Label(f_uio, text=f"uio[{i}] :").pack(side=tk.LEFT)
            e_uio = ttk.Entry(f_uio, width=15)
            e_uio.insert(0, "unused")
            e_uio.pack(side=tk.LEFT)
            uio_entries.append(e_uio)

        def on_generate():
            title = ent_title.get()
            desc = ent_desc.get()
            self.generate_yaml_from_assistant(title, desc, ui_entries, uo_entries, uio_entries)
            dialog.destroy()

        ttk.Button(dialog, text="Générer et Sauvegarder info.yaml", command=on_generate).pack(pady=10)

    def generate_yaml_from_assistant(self, title, desc, ui_entries, uo_entries, uio_entries):
        # Récupère l'auteur dynamiquement à partir du top_module
        author = self.top_module.split('_')[-1] if len(self.top_module.split('_')) > 2 else "Auteur"
        
        yaml_content = f"""# Tiny Tapeout project information
project:
  title:        "{title}"
  author:       "{author}"
  discord:      ""
  description:  "{desc}"
  language:     "Verilog"
  clock_hz:     0

  tiles: "1x1"
  top_module:  "{self.top_module}"

  source_files:
    - "project.v"

pinout:
"""
        # Injection propre des entrées
        for i in range(8):
            val = ui_entries[i].get().strip() or "unused"
            yaml_content += f'  ui[{i}]: "{val}"\n'
        yaml_content += "\n"
        
        # Injection propre des sorties
        for i in range(8):
            val = uo_entries[i].get().strip() or "unused"
            yaml_content += f'  uo[{i}]: "{val}"\n'
        yaml_content += "\n"
        
        # Injection propre des bidirectionnelles
        for i in range(8):
            val = uio_entries[i].get().strip() or "unused"
            yaml_content += f'  uio[{i}]: "{val}"\n'
            
        yaml_content += "\nyaml_version: 6\n"
        
        self.txt_yaml.delete("1.0", tk.END)
        self.txt_yaml.insert("1.0", yaml_content)
        self.save_file("info.yaml", self.txt_yaml)
        self.log_console("✅ info.yaml généré via l'assistant avec succès.")

    def build_pnr_tab(self):
        ttk.Label(self.tab_pnr, text="Flow RTL-to-GDS", font=("Helvetica", 14, "bold")).pack(pady=20)
        frame_pdk = ttk.Frame(self.tab_pnr)
        frame_pdk.pack(pady=5)
        ttk.Label(frame_pdk, text="Technologie (PDK) :").pack(side=tk.LEFT, padx=5)
        self.cbox_pdk = ttk.Combobox(frame_pdk, values=["SkyWater 130nm", "GlobalFoundries 180nm", "IHP 130nm"], state="readonly", width=25)
        self.cbox_pdk.current(0)
        self.cbox_pdk.pack(side=tk.LEFT, padx=5)
        ttk.Button(self.tab_pnr, text="Placer et Router (Hardening)", command=self.run_pnr).pack(pady=10)
        ttk.Button(self.tab_pnr, text="Ouvrir dans OpenROAD", command=lambda: self.run_async_command("source tt_env/bin/activate && ./tt/tt_tool.py --open-in-openroad &", shell=True)).pack(pady=10)

    def run_pnr(self):
        if not self.project_dir:
            messagebox.showerror("Erreur", "Veuillez d'abord charger ou créer un projet.")
            return
        pdk_choice = self.cbox_pdk.get()
        if pdk_choice == "SkyWater 130nm":
            cmd_pnr = "source tt_env/bin/activate && export PDK=sky130A && ./tt/tt_tool.py --create-user-config && ./tt/tt_tool.py --harden"
        elif pdk_choice == "GlobalFoundries 180nm":
            cmd_pnr = "source tt_env/bin/activate && export PDK=gf180mcuD && ./tt/tt_tool.py --gf-create-user-config && ./tt/tt_tool.py --gf-harden"
        elif pdk_choice == "IHP 130nm":
            cmd_pnr = "source tt_env/bin/activate && export PDK=ihp-sg13g2 && ./tt/tt_tool.py --ihp-create-user-config && ./tt/tt_tool.py --ihp-harden"
        self.run_async_command(cmd_pnr, shell=True, blocking_msg="Routage GDS et génération physique en cours...\n(Ceci prend généralement entre 3 et 5 minutes)\n\nVeuillez patienter.", success_msg="✅ Hardening terminé avec succès !\nVérifiez les mentions LVS et DRC dans la console.", error_msg="❌ Échec du Place & Route (Hardening).\nVérifiez les journaux OpenLane dans la console.")

    def build_doc_tab(self):
        btn_frame = ttk.Frame(self.tab_doc)
        btn_frame.pack(fill=tk.X, pady=5)
        ttk.Button(btn_frame, text="Générer Template info.md", command=self.generate_doc_template).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Importer un fichier...", command=lambda: self.import_file(self.txt_doc)).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Sauvegarder docs/info.md", command=lambda: self.save_file("docs/info.md", self.txt_doc)).pack(side=tk.LEFT, padx=5)
        self.txt_doc = tk.Text(self.tab_doc, font=("Monospace", 11))
        self.txt_doc.pack(fill=tk.BOTH, expand=True, pady=5)

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
        self.txt_doc.delete("1.0", tk.END)
        self.txt_doc.insert("1.0", template)

    def build_git_tab(self):
        frame = ttk.Frame(self.tab_git)
        frame.pack(pady=20, padx=50, fill=tk.X)
        ttk.Label(frame, text="Soumission GitHub (Tapeout)", font=("Helvetica", 14, "bold")).grid(row=0, column=0, columnspan=2, pady=10)
        instructions = ("⚠️ IMPORTANT AVANT DE PUSHER :\n1. Allez dans Settings > Pages et mettez GitHub Actions dans Build and deployment > Source.\n2. Allez dans Settings > Actions > General et cochez 'Read and write permissions' dans Workflow permissions.")
        ttk.Label(frame, text=instructions, foreground="red", justify=tk.LEFT).grid(row=1, column=0, columnspan=2, pady=10, sticky="w")
        
        ttk.Label(frame, text="Pseudo :").grid(row=2, column=0, sticky="w", pady=5)
        self.ent_git_user = ttk.Entry(frame, width=40)
        self.ent_git_user.insert(0, "MariusL00")
        self.ent_git_user.grid(row=2, column=1)

        ttk.Label(frame, text="Token (Clé classique) :").grid(row=3, column=0, sticky="w", pady=5)
        self.ent_git_pass = ttk.Entry(frame, width=40, show="*")
        self.ent_git_pass.grid(row=3, column=1)

        ttk.Label(frame, text="URL du Repo :").grid(row=4, column=0, sticky="w", pady=5)
        self.ent_git_url = ttk.Entry(frame, width=40)
        self.ent_git_url.grid(row=4, column=1)

        ttk.Label(frame, text="Message du commit :").grid(row=5, column=0, sticky="w", pady=5)
        self.ent_git_commit = ttk.Entry(frame, width=40)
        self.ent_git_commit.insert(0, "Mon design prêt pour le tapeout")
        self.ent_git_commit.grid(row=5, column=1)

        ttk.Button(frame, text="Push to GitHub", command=self.push_to_github).grid(row=6, column=0, columnspan=2, pady=20)
        
        ttk.Separator(frame, orient='horizontal').grid(row=7, column=0, columnspan=2, sticky="ew", pady=15)
        ttk.Label(frame, text="Étape Finale : Acheter / Valider le Tapeout", font=("Helvetica", 12, "bold")).grid(row=8, column=0, columnspan=2, pady=10)
        ttk.Label(frame, text="Une fois le push terminé et les Actions GitHub validées au vert,\ncliquez ci-dessous pour soumettre officiellement votre puce à la fabrication.", justify=tk.CENTER).grid(row=9, column=0, columnspan=2, pady=5)
        ttk.Button(frame, text="Ouvrir app.tinytapeout.com", command=lambda: webbrowser.open("https://app.tinytapeout.com")).grid(row=10, column=0, columnspan=2, pady=10)

    def save_file(self, filepath, text_widget):
        if not self.project_dir: return
        full_path = os.path.join(self.project_dir, filepath)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as f:
            f.write(text_widget.get("1.0", tk.END))

    def patch_docs_yaml(self):
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
          curl -sL https://github.com/typst/typst/releases/latest/download/typst-x86_64-unknown-linux-musl.tar.xz | tar -xJ 
          sudo mv typst-*/typst /usr/local/bin/
      - name: Build docs
        uses: TinyTapeout/tt-gds-action/docs@tt08
"""
        docs_path = os.path.join(self.project_dir, ".github", "workflows", "docs.yaml")
        os.makedirs(os.path.dirname(docs_path), exist_ok=True)
        with open(docs_path, "w") as f:
            f.write(yaml_content)

    def push_to_github(self):
        if not self.project_dir:
            messagebox.showerror("Erreur", "Veuillez d'abord créer ou charger un projet avant de soumettre sur GitHub.")
            return
            
        self.patch_docs_yaml()
        user = self.ent_git_user.get().strip()
        token = self.ent_git_pass.get().strip()
        repo_url = self.ent_git_url.get().strip()
        commit_msg = self.ent_git_commit.get().replace('"', '\\"')
        
        actions_url = repo_url[:-4] if repo_url.endswith(".git") else repo_url
        actions_url += "/actions"
        
        auth_url = repo_url.replace("https://", f"https://{user}:{token}@")
        cmd = f"""
        git remote remove origin 2>/dev/null || true
        git rm --cached tt 2>/dev/null || true
        git config user.email "easy_tt_cad@example.com"
        git config user.name "{user}"
        git add .
        git commit -m "{commit_msg}"
        git branch -M main
        git remote add origin {auth_url}
        git push -u origin main --force
        """
        msg_succes = "✅ Soumission terminée !\n\nVotre navigateur va s'ouvrir sur la page 'Actions' de votre dépôt.\n\n⚠️ VEUILLEZ VÉRIFIER : Assurez-vous que les workflows (docs et gds) se terminent tous par une icône verte sans erreur."
        self.run_async_command(cmd, shell=True, hidden_token=token, blocking_msg="Envoi du projet vers GitHub en cours...\nVeuillez patienter.", success_msg=msg_succes, success_callback=lambda: webbrowser.open(actions_url))

    def run_async_command(self, cmd, shell=False, hidden_token=None, blocking_msg=None, success_msg=None, error_msg=None, success_callback=None):
        if not self.project_dir and not "mkdir" in cmd and not "git clone" in cmd:
            messagebox.showerror("Erreur", "Veuillez d'abord créer ou charger un projet.")
            return
        if blocking_msg:
            self.show_loading(blocking_msg)
        log_text = cmd
        if hidden_token and hidden_token.strip() != "":
            log_text = log_text.replace(hidden_token, "********")
        self.log_console(f"\n> {log_text}")
        thread = threading.Thread(target=self._exec_cmd, args=(cmd, shell, hidden_token, blocking_msg, success_msg, error_msg, success_callback))
        thread.daemon = True
        thread.start()

    def _exec_cmd(self, cmd, shell, hidden_token, blocking_msg, success_msg, error_msg, success_callback):
        try:
            cwd = self.project_dir if self.project_dir else None
            process = subprocess.Popen(cmd, shell=shell, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, executable='/bin/bash')
            for line in process.stdout:
                if hidden_token and hidden_token.strip() != "":
                    line = line.replace(hidden_token, "********")
                self.cmd_queue.put(line)
            process.wait()
            self.cmd_queue.put(f"\n[Terminé avec le code de retour {process.returncode}]\n")
            def cleanup():
                if blocking_msg: self.hide_loading()
                if process.returncode == 0:
                    if success_msg: messagebox.showinfo("Succès", success_msg)
                    if success_callback: success_callback()
                elif process.returncode != 0 and error_msg:
                    messagebox.showerror("Erreur", error_msg)
            self.after(0, cleanup)
        except Exception as e:
            err_msg = str(e)
            if hidden_token and hidden_token.strip() != "":
                err_msg = err_msg.replace(hidden_token, "********")
            self.cmd_queue.put(f"\n[Erreur d'exécution: {err_msg}]\n")
            def cleanup_error():
                if blocking_msg: self.hide_loading()
                messagebox.showerror("Erreur Système", err_msg)
            self.after(0, cleanup_error)

    def check_console_queue(self):
        while not self.cmd_queue.empty():
            line = self.cmd_queue.get_nowait()
            self.log_console(line, newline=False)
        self.after(100, self.check_console_queue)

    def log_console(self, text, newline=True):
        self.console.insert(tk.END, text + ("\n" if newline else ""))
        self.console.see(tk.END)

if __name__ == "__main__":
    app = EasyTTCad()
    app.mainloop()