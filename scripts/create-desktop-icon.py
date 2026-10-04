import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ui_components import app_icon


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: create-desktop-icon.py OUTPUT.png OUTPUT.ico")
    png_target = Path(sys.argv[1])
    ico_target = Path(sys.argv[2])
    png_target.parent.mkdir(parents=True, exist_ok=True)

    image = app_icon(1024)
    image.save(png_target, format="PNG", optimize=True)
    image.save(ico_target, format="ICO", sizes=[(16,16), (24,24), (32,32), (48,48), (64,64), (128,128), (256,256)])


if __name__ == "__main__":
    main()
