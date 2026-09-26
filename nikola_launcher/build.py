"""
Build script for PyInstaller compilation to .exe
"""

import subprocess
import sys
from pathlib import Path
from PIL import Image, ImageDraw
import os


def create_ico_icon():
    """Create Nikola.ico with multiple sizes."""
    print("Generating icon...")
    
    icon_path = Path("nikola_icon.ico")
    
    # Create base image with all sizes
    sizes = [16, 32, 48, 64, 128, 256]
    images = []
    
    for size in sizes:
        img = Image.new('RGBA', (size, size), color=(15, 10, 20, 255))  # Navy background
        draw = ImageDraw.Draw(img)
        
        # Purple circle
        margin = max(1, size // 8)
        draw.ellipse(
            [margin, margin, size - margin, size - margin],
            fill='#7c6af7',
            outline='#6a5ae0'
        )
        
        # White N letter (simplified)
        text_size = max(4, size // 2)
        try:
            draw.text(
                (size // 4, size // 4),
                'N',
                fill='white'
            )
        except:
            pass
        
        images.append(img)
    
    # Save as ICO with all sizes
    images[0].save(
        icon_path,
        format='ICO',
        sizes=[(s, s) for s in sizes]
    )
    
    print(f"Icon created: {icon_path}")
    return str(icon_path)


def build_exe(icon_path):
    """Build executable with PyInstaller."""
    print("Building executable...")
    
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
            "--noconfirm",
            "--clean",
        # A directory build keeps python313.dll beside the bootloader instead
        # of extracting it to a temporary _MEI folder at every launch.
        "--onedir",
            "--contents-directory=.",
        "--windowed",
        f"--icon={icon_path}",
        "--name=Nikola",
        "--hidden-import=pystray._win32",
        "--hidden-import=PIL._tkinter_finder",
        "--hidden-import=win32gui",
        "--collect-all=pystray",
        "--collect-all=PIL",
        "--add-data=../backend:backend",
        "--add-data=../telegram_bot:telegram_bot",
        "--add-data=../electron_app:electron_app",
        "--add-data=../browser_extension:browser_extension",
        "launcher.py"
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print("Build failed:")
        print(result.stderr)
        return False
    
    print("Build completed successfully")
    
    # Copy the directory build contents to the project root. This keeps
    # C:\nikola\Nikola.exe as the familiar double-click entry point while
    # placing its _internal runtime beside it.
    package_src = Path("dist") / "Nikola"
    root_dir = Path("..").resolve()
    
    if package_src.exists():
        import shutil
        for item in package_src.iterdir():
            destination = root_dir / item.name
            if item.is_dir():
                if destination.exists():
                    shutil.rmtree(destination)
                shutil.copytree(item, destination)
            else:
                shutil.copy2(item, destination)
        print(f"Executable package copied to: {root_dir}")
    
    return True


def main():
    """Build Nikola executable."""
    try:
        # Check PyInstaller is installed
        subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--version"],
            capture_output=True,
            check=True
        )
    except:
        print("PyInstaller not found. Installing...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "pyinstaller"],
            check=True
        )
    
    os.chdir(Path(__file__).parent)
    
    icon = create_ico_icon()
    build_exe(icon)


if __name__ == "__main__":
    main()
