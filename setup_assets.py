import os
import shutil

# --- НАСТРОЙКИ: Укажи здесь, где сейчас лежат твои файлы ---
# Если они в той же папке, где запускаешь скрипт, оставь '.'
current_files_path = '.' 

# Список файлов, которые нужно переместить (укажи точные имена!)
files_to_move = [
    {"name": "char_king.gif", "type": "gif"},
    # {"name": "luffy.png", "type": "image"},  # Раскомментируй и добавь другие файлы
]

# --- ЛОГИКА СКРИПТА ---
base_dir = os.path.dirname(os.path.abspath(__file__))
assets_dir = os.path.join(base_dir, "assets")
images_dir = os.path.join(assets_dir, "images")
gifs_dir = os.path.join(assets_dir, "gifs")

# 1. Создаем папки, если их нет
os.makedirs(images_dir, exist_ok=True)
os.makedirs(gifs_dir, exist_ok=True)
print(f"✅ Папки созданы: {assets_dir}")

# 2. Перемещаем файлы
for file_info in files_to_move:
    filename = file_info["name"]
    file_type = file_info["type"]
    
    src_path = os.path.join(current_files_path, filename)
    
    if os.path.exists(src_path):
        # Выбираем целевую папку
        if file_type == "gif":
            dest_dir = gifs_dir
        else:
            dest_dir = images_dir
            
        dest_path = os.path.join(dest_dir, filename)
        
        # Перемещаем
        shutil.move(src_path, dest_path)
        print(f"📂 Файл {filename} перемещен в {dest_dir}")
    else:
        print(f"⚠️ Файл {filename} не найден в {current_files_path}. Пропускаем.")

# 3. Генерируем команды для Git
print("\n--- ГОТОВЫЕ КОМАНДЫ ДЛЯ GIT ---")
print("Скопируй и вставь эти команды в терминал:")
print(f"git add assets/")
print(f'git commit -m "add assets and files: {', '.join([f["name"] for f in files_to_move])}"')
print("git push")
