"""
Build script for PyInstaller compilation to .exe
"""

import subprocess
import sys
from pathlib import Path
import os


def build_electron(project_root):
    """Build and verify the packaged Electron renderer before PyInstaller."""
    electron_dir = project_root / "electron_app"
    npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
    print("Building Electron package...")
    result = subprocess.run(
        [npm_cmd, "run", "build"],
        cwd=electron_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        return False

    asar_path = electron_dir / "dist" / "win-unpacked" / "resources" / "app.asar"
    if not asar_path.is_file():
        print(f"Build failed: Electron app.asar was not produced at {asar_path}.")
        return False

    # Electron Builder archives the source files. Verify the deployed archive
    # through the installed asar CLI when available.
    asar_cmd = electron_dir / "node_modules" / ".bin" / "asar.cmd"
    if not asar_cmd.is_file():
        print(f"Build failed: expected asar tool is missing at {asar_cmd}.")
        return False
    inspect_dir = electron_dir / "dist" / "asar-inspect"
    if inspect_dir.exists():
        import shutil
        shutil.rmtree(inspect_dir)
    extract = subprocess.run(
        [str(asar_cmd), "extract", str(asar_path), str(inspect_dir)],
        capture_output=True,
        text=True,
    )
    if extract.returncode != 0:
        print(extract.stderr)
        return False
    api_client = (inspect_dir / "renderer" / "services" / "api-client.js").read_text(encoding="utf-8")
    app_renderer = (inspect_dir / "renderer" / "app-v2.js").read_text(encoding="utf-8")
    if "SCREEN_VISION_TIMEOUT_MS = 180_000" not in api_client or "Capturing screen" not in app_renderer:
        print("Build failed: Electron archive does not contain the current screen-vision renderer.")
        return False
    import shutil
    shutil.rmtree(inspect_dir)
    print(f"Electron package verified: {asar_path}")
    return True


def build_exe(icon_path):
    """Build executable with PyInstaller."""
    print("Building executable...")
    project_root = Path(__file__).resolve().parent.parent
    launcher_dir = Path(__file__).resolve().parent
    import shutil

    if not build_electron(project_root):
        return False

    for generated_dir in (launcher_dir / "build", launcher_dir / "dist"):
        if generated_dir.exists():
            shutil.rmtree(generated_dir)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
            f"--specpath={launcher_dir / 'build'}",
            f"--distpath={launcher_dir / 'dist'}",
            f"--workpath={launcher_dir / 'build' / 'work'}",
            "--noconfirm",
            "--clean",
        # A directory build keeps python313.dll beside the bootloader instead
        # of extracting it to a temporary _MEI folder at every launch.
        "--onedir",
            "--contents-directory=_internal",
        "--windowed",
        f"--icon={icon_path}",
        "--name=Nikola",
        "--hidden-import=pystray._win32",
        "--hidden-import=PIL._tkinter_finder",
        "--hidden-import=PIL._imaging",
        "--hidden-import=PIL.Image",
        "--hidden-import=PIL.ImageGrab",
        "--hidden-import=win32gui",
        "--collect-all=pystray",
        "--collect-all=PIL",
        "--collect-binaries=PIL",
        f"--add-data={Path(icon_path).resolve()}{os.pathsep}.",
        f"--add-data={project_root / 'backend'}{os.pathsep}backend",
        f"--add-data={project_root / 'telegram_bot'}{os.pathsep}telegram_bot",
        f"--add-data={project_root / 'electron_app'}{os.pathsep}electron_app",
        f"--add-data={project_root / 'browser_extension'}{os.pathsep}browser_extension",
        "launcher.py"
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print("Build failed:")
        print(result.stderr)
        return False
    
    print("Build completed successfully")
    
    # Keep the bundled runtime isolated from the source backend, model files,
    # virtual environments, and user data in the project root.
    package_src = launcher_dir / "dist" / "Nikola"
    root_dir = project_root
    
    runtime_src = package_src / "_internal"
    executable_src = package_src / "Nikola.exe"
    if runtime_src.is_dir() and executable_src.is_file():
        imaging_binaries = list((runtime_src / "PIL").glob("_imaging*.pyd"))
        if not imaging_binaries:
            print(f"Build failed: no Pillow native extension found under {runtime_src / 'PIL'}.")
            return False

        executable_dest = root_dir / executable_src.name
        if executable_dest.exists():
            try:
                with executable_dest.open("r+b"):
                    pass
            except OSError:
                print(
                    f"Package built at {package_src}; close the running launcher "
                    "before deploying it to the project root."
                )
                return False

        runtime_dest = root_dir / "_internal"
        if runtime_dest.exists():
            shutil.rmtree(runtime_dest)
        shutil.copytree(runtime_src, runtime_dest)
        shutil.copy2(executable_src, executable_dest)
        for stale_path in (
            root_dir / "PIL",
            root_dir / "PIL_legacy",
            root_dir / "pillow-11.3.0.dist-info",
            root_dir / "pillow-12.2.0.dist-info",
        ):
            if stale_path.is_dir():
                shutil.rmtree(stale_path)
        print(f"Executable package copied to: {root_dir}")
        print(
            f"Packaged Pillow native extension: "
            f"{(runtime_dest / 'PIL' / imaging_binaries[0].name)}"
        )
    else:
        print("Build failed: expected onedir executable and _internal runtime were not produced.")
        return False
    
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
    
    icon_path = Path(__file__).with_name("nikola_icon.ico")
    if not icon_path.is_file():
        raise FileNotFoundError(f"Icon asset not found: {icon_path}")
    if not build_exe(str(icon_path)):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
