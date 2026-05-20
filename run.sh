#!/bin/bash
# Lokalno pokretanje real-estate-tracker-a na Mac-u.
#
# Korisenje:
#   ./run.sh
#
# Ovo:
#  1. pull-uje najnovije izmene iz GitHub-a (ako si dodao oglase iz drugog uredjaja)
#  2. pokreće tracker
#  3. commit-uje data/ promene nazad u repo

set -e

# Boja za output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

cd "$(dirname "$0")"

echo -e "${BLUE}=== Real Estate Tracker - Lokalno pokretanje ===${NC}"
echo ""

# 1. Pull
echo -e "${BLUE}[1/3] Pull-ujem najnovije iz GitHub-a...${NC}"
git pull --rebase --autostash || {
    echo -e "${RED}Pull pukao. Proveri internet ili git stanje.${NC}"
    exit 1
}
echo ""

# 2. Run tracker
echo -e "${BLUE}[2/3] Pokrecem tracker...${NC}"
python3 -m app.tracker
echo ""

# 3. Commit and push
echo -e "${BLUE}[3/3] Commit-ujem data/ promene...${NC}"
git add data/
if git diff --staged --quiet; then
    echo "Nema promena u data/."
else
    git commit -m "chore: local tracker run [skip ci]"
    git push
    echo -e "${GREEN}Promene push-ovane na GitHub.${NC}"
fi

echo ""
echo -e "${GREEN}=== Gotovo! ===${NC}"
