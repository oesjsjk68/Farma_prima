# -*- coding: utf-8 -*-
"""
setup_assets.py — раскладывает картинки из папки images в имена, которые ждёт бот.
Запуск: python setup_assets.py   (положи файл рядом с папкой images)
Оригиналы не трогает — только копирует.
"""

import os
import re
import shutil

# ============ НАСТРОЙКИ (можно менять) ============

# Порядок шахт: имя_с_github -> номер локации в боте
MINE_ORDER = {
    "common":    "1",
    "deep":      "2",
    "fire":      "3",
    "ice":       "4",
    "mithril":   "5",
    "enchanted": "6",
}

# Кирки: имя_с_github -> ключ в боте (правь, если у тебя другие ключи)
PICK_MAP = {
    "wood":      "wood",
    "stone":     "stone",
    "iron":      "iron",
    "ruby":      "steel",
    "gold":      "mithril",
    "diamond":   "adamant",
    "mithril":   "dragon",
    "legendary": "legendary",
}

# Персонажи: имя_с_github -> ключ в боте (CHARACTERS["key"])
CHAR_MAP = {
    "girls":      "podrugi",
    "kazuya":     "kazuya",
    "mineta":     "minu",
    "usopp":      "usopp",
    "shinji":     "shinji",
    "mumen":      "mumen",
    "tenten":     "tenten",
    "buggy":      "buggy",
    "yukiteru":   "yukiteru",
    "kazuma":     "kazuma",
    "luffy":      "luffy",
    "sung_jinwoo":"jinwoo",
    "king":       "king",
    "lelouch":    "lelouch",
    "neito":      "monoma",
    "reigen":     "reigen",
    "ichigo":     "ichigo",
    "kurapika":   "kurapika",
    "killua":     "killua",
    "gojo":       "gojo",
    "adam":       "adam",
    "simon":      "simon",
    "alucard":    "alucard",
    "mob":        "mob",
}

# Баннеры и события: имя_с_github -> имя в боте
EVENT_MAP = {
    "shop_banner":   "banner",
    "profile_banner":"profile",
    "quests_banner": "quests",
    "icon_top":      "top",
    "case":          "case_open",
    "jackpot":       "jackpot",
    "welcome":       "welcome",
    "bonus":         "bonus",
    "transfer":      "transfer",
    "promo":         "promo",
    "auto_mine":     "auto_mine",
    "roulette_win":  "roulette_win",
}

# Всё, что должно быть в images, чтобы закрыть список
WANTED = (
    [f"char_{k}" for k in CHAR_MAP.values()]
    + [f"mine_{n}" for n in MINE_ORDER.values()]
    + [f"pick_{k}" for k in PICK_MAP.values()]
    + list(EVENT_MAP.values())
)

ALLOWED_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif")

# ============ ЛОГИКА ============

def clean_name(stem: str) -> str:
    """Убирает хвосты ezgif и двойные расширения: char_mythic_gojo-ezgif.com-resize-to-kb-50kb -> char_mythic_gojo"""
    stem = re.sub(r"-ezgif\.com-.*$", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"\.(png|jpg|jpeg|webp|gif)$", "", stem, flags=re.IGNORECASE)
    return stem.strip()

def find_images_dir():
    # рядом со скриптом или в текущей папке
    for base in (os.path.dirname(os.path.abspath(__file__)), os.getcwd()):
        d = os.path.join(base, "images")
        if os.path.isdir(d):
            return d
    return None

def main():
    img_dir = find_images_dir()
    if not img_dir:
        print("!! Папка 'images' не найдена. Положи скрипт рядом с ней и запусти снова.")
        return

    print(f"Папка с картинками: {img_dir}\n")
    done, kept, errors = [], [], []

    for fname in sorted(os.listdir(img_dir)):
        path = os.path.join(img_dir, fname)
        if not os.path.isfile(path):
            continue
        stem, ext = os.path.splitext(fname)
        ext = ext.lower()
        if ext not in ALLOWED_EXT:
            errors.append(f"{fname}: расширение {ext or '(нет)'} не поддерживается (нужно jpg/png/webp/gif)")
            continue

        stem = clean_name(stem)
        target = None

        # --- персонажи: char_common_girls, char_rare_buggy, char_mythic_gojo-... ---
        m = re.match(r"char_(?:common|rare|epic|legendary|mythic|unique)_(.+)$", stem)
        if m and m.group(1) in CHAR_MAP:
            target = f"char_{CHAR_MAP[m.group(1)]}"
        elif stem.startswith("char_"):
            key = stem[len("char_"):]
            if key in CHAR_MAP.values():
                target = stem  # уже правильное имя
            else:
                errors.append(f"{fname}: не понял, какой это персонаж ('{key}')")

        # --- шахты ---
        elif stem.startswith("mine_"):
            sub = stem[len("mine_"):]
            if sub in MINE_ORDER:
                target = f"mine_{MINE_ORDER[sub]}"
            elif re.fullmatch(r"[1-6]", sub):
                target = stem  # уже нумерованная
            else:
                errors.append(f"{fname}: не понял шахту '{sub}'")

        # --- кирки ---
        elif stem.startswith("pickaxe_"):
            sub = stem[len("pickaxe_"):]
            if sub in PICK_MAP:
                target = f"pick_{PICK_MAP[sub]}"
            else:
                errors.append(f"{fname}: не понял кирку '{sub}'")
        elif stem.startswith("pick_"):
            target = stem  # уже правильное имя

        # --- баннеры и события ---
        elif stem in EVENT_MAP:
            target = EVENT_MAP[stem]
        elif stem in EVENT_MAP.values():
            target = stem  # уже правильное имя

        # --- руды и кнопки панели: оставляем как есть ---
        elif stem.startswith(("ore_", "btn_")):
            kept.append(fname)
            continue

        else:
            errors.append(f"{fname}: неизвестное имя, оставил как есть")
            kept.append(fname)
            continue

        new_name = target + ext
        if new_name != fname:
            dest = os.path.join(img_dir, new_name)
            if os.path.exists(dest):
                errors.append(f"{fname}: целевой файл {new_name} уже есть — пропустил")
                continue
            shutil.copy2(path, dest)
            os.remove(path)
            done.append(f"{fname}  ->  {new_name}")
        else:
            kept.append(fname)

    print("ПЕРЕИМЕНОВАНО:")
    for line in done or ["  (ничего — все имена уже правильные)"]:
        print("  " + line)
    print("\nОСТАВЛЕНО КАК ЕСТЬ:")
    for line in kept or ["  —"]:
        print("  " + line)
    if errors:
        print("\nПРОБЛЕМЫ:")
        for line in errors:
            print("  " + line)

    # --- чего не хватает ---
    have = {clean_name(os.path.splitext(f)[0]) for f in os.listdir(img_dir)
            if os.path.isfile(os.path.join(img_dir, f))}
    missing = [w for w in WANTED if w not in have]
    if missing:
        print("\nЖДУ КАРТИНКИ (бот покажет текст вместо фото):")
        for w in missing:
            print("  " + w + ".jpg (или .png/.gif)")
    else:
        print("\nВсе нужные картинки на месте! ✅")

if __name__ == "__main__":
    main()
