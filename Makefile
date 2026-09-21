.PHONY: update fetch classify enrich review readme check stats

update: fetch classify enrich classify review readme ## полный проход: найти новое и пересобрать

fetch:    ; python3 scripts/fetch.py
classify: ; python3 scripts/classify.py
enrich:   ; python3 scripts/enrich.py
review:   ; python3 scripts/review.py
readme:   ; python3 scripts/build_readme.py
check:    ; python3 scripts/build_readme.py --check
stats:    ; python3 scripts/stats.py
