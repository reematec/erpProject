# Create Project Root
mkdir ~/erpProject && cd ~/erpProject
mkdir custom_addons

# Clone Odoo 18 Source
git clone https://www.github.com/odoo/odoo --depth 1 --branch 18.0 --single-branch

# Python Virtual Environment
python3 -m venv odoo-venv
source odoo-venv/bin/activate

# Core Python Dependencies
pip install -r odoo/requirements.txt
pip install lxml_html_clean inotify psycopg2-binary Pillow

# System dependencies for Odoo 18 & wkhtmltopdf
sudo apt update
sudo apt install -y python3-dev libxml2-dev libxslt1-dev zlib1g-dev libsasl2-dev \
    libldap2-dev libpq-dev libjpeg-dev libfontenc1 xfonts-75dpi xfonts-base

# PostgreSQL Setup
sudo apt install postgresql postgresql-contrib -y
sudo -u postgres psql -c "CREATE USER wsl_amir WITH CREATEDB SUPERUSER PASSWORD 'your_password';"

# PDF Engine (Sialkot Invoices/Work Tickets)
wget https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.jammy_amd64.deb
sudo apt install ./wkhtmltox_0.12.6.1-3.jammy_amd64.deb

# Key Paths in your Config:
# db_name = odoo18_sgo_football_dev
# addons_path = /home/wsl_amir/erpProject/custom_addons, /home/wsl_amir/erpProject/odoo/addons, /home/wsl_amir/erpProject/odoo/odoo/addons

# First-time initialization (Builds the DB tables)
python3 odoo/odoo-bin -c odoo.conf -d odoo18_sgo_football_dev -i base

# Daily Development Command (With auto-reload)
python3 odoo/odoo-bin -c odoo.conf --dev=all



sudo -u postgres psql -d odoo18_sgo_football_dev
dropdb -U wsl_amir odoo18_sgo_football_dev
createdb -U wsl_amir odoo18_sgo_football_dev
python3 odoo/odoo-bin -c odoo.conf -d odoo18_sgo_football_dev -i mrp --without-demo=all



---
 1. How to start Odoo (The "Daily Command")
  Run this command from your terminal to spin up the server with auto-reload (perfect for development):

   1 ./odoo-venv/bin/python3 odoo/odoo-bin -c odoo.conf --dev=all

  2. How to access it
  Once the command is running, open your web browser and go to:
  http://localhost:8069

  3. Logins
  You can log in using any of the accounts I created. Refer to your credential.md file for the full
  list, but here is a quick start:
   * Database: odoo18_sgo_football_dev
   * Admin Login: admin / admin
   * Production Manager (Waleed): waleed / waleed123

  Summary of Commands
  I recommend saving these to a small note or using the commands.md file for quick reference:

  ┌──────────────┬──────────────────────────────────────────────────────────────┐
  │ Action       │ Command                                                      │
  ├──────────────┼──────────────────────────────────────────────────────────────┤
  │ Start Odoo   │ ./odoo-venv/bin/python3 odoo/odoo-bin -c odoo.conf --dev=all │
  │ Stop Odoo    │ Press Ctrl + C in the terminal                               │
  │ Restart Odoo │ Just stop and run the Start command again                    │
  └──────────────┴──────────────────────────────────────────────────────────────┘
