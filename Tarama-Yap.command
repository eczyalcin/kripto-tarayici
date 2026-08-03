#!/bin/bash
# Finder'dan çift tıklanarak çalıştırılır — tek tarama yapıp sonucu gösterir.
cd "$(dirname "$0")"
./kripto tara
echo ""
read -n 1 -s -r -p "Kapatmak için bir tuşa basın..."
