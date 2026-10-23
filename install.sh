#!/bin/bash

# Vérifier que le script est lancé en sudo
if [ "$EUID" -ne 0 ]; then
  echo "Veuillez lancer l'installation avec sudo (ex: sudo ./install.sh)"
  exit 1
fi

echo "Détection de la distribution Linux..."

# 1. Installation des dépendances selon la distribution
if command -v apt >/dev/null 2>&1; then
    echo "Distribution basée sur Debian/Ubuntu détectée."
    apt update
    apt update && apt install -y build-essential python3 python3-venv python3-pip make git iverilog gtkwave verilator yosys klayout magic ngspice docker-ce docker-ce-cli containerd.io nodejs npm default-jre unzip
    npm install -g netlistsvg

elif command -v dnf >/dev/null 2>&1; then
    echo "Distribution basée sur Fedora/RedHat détectée."
    # Note : Les noms de paquets peuvent légèrement varier sur Fedora
    dnf install -y make gcc gcc-c++ python3 python3-pip git iverilog gtkwave verilator yosys klayout magic docker

elif command -v pacman >/dev/null 2>&1; then
    echo "Distribution basée sur Arch Linux détectée."
    pacman -Syu --noconfirm base-devel python python-pip git iverilog gtkwave verilator yosys klayout magic docker

else
    echo "Erreur : Gestionnaire de paquets non reconnu (ni apt, ni dnf, ni pacman)."
    echo "Veuillez installer les dépendances EDA manuellement."
    exit 1
fi

echo "2. Configuration de Docker..."
systemctl start docker
systemctl enable docker
if [ -n "$SUDO_USER" ]; then
    usermod -aG docker $SUDO_USER
fi

echo "3. Déploiement de Easy TT CAD..."
# Création du dossier d'installation
mkdir -p /opt/easy_tt_cad
# On suppose que main.py est dans le même dossier que ce script d'installation
cp main.py /opt/easy_tt_cad/
chmod +x /opt/easy_tt_cad/main.py

echo "4. Création du raccourci système..."
cat << 'EOF' > /usr/local/bin/easy_tt_cad
#!/bin/bash
python3 /opt/easy_tt_cad/main.py
EOF
chmod +x /usr/local/bin/easy_tt_cad

echo "Installation terminée avec succès !"
echo "Vous pouvez maintenant lancer l'IDE en tapant 'easy_tt_cad' dans votre terminal."
echo "IMPORTANT : Tapez 'newgrp docker' ou redémarrez votre PC pour appliquer les droits Docker."
