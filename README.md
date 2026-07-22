# Project2PDF

Project2PDF turns downloaded 3D-print files, project folders, and model-page links into durable PDFs that retain the information needed months or years later: the original listing, creator, photographs, description, print guidance, model files, dimensions, slicer settings, and license.

The desktop app uses a dark PySide6 interface and accepts drag-and-drop input from Explorer and web browsers.

## Supported sources

- Printables
- MakerWorld
- Thingiverse
- Creality Cloud
- Thangs
- Yeggi links, resolved to their original listing
- 3Drop links, resolved to their original listing
- Other pages through Open Graph and JSON-LD metadata when possible

Project2PDF never uploads model geometry. Filename-based discovery sends only the filename or title to a search page. Website layouts and access controls change over time, so every detected source includes confidence and evidence and remains editable before PDF creation.

## Install for development

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\project2pdf-gui.exe
```

You can also launch it with:

```powershell
.\.venv\Scripts\python.exe run_project2pdf.py
```

## Using the application

1. Drop a file, folder, or model-page link onto the drop area.
2. Review the detected source and confidence evidence. If no source is found, paste the original model-page URL into **Original URL** and select **Fetch from URL** to use it as the metadata seed.
3. Check the image preview and correct or expand the title, creator, description, print instructions, tags, or license if needed. Images found in the dropped folder are kept and prioritized ahead of website images in the PDF.
4. Choose the light (sun) or dark (moon) PDF theme from the top-right switch.
5. Select **Generate this PDF** or **Generate all PDFs**.

Related files in a dropped folder are treated as one project. Existing PDFs are inspected for clickable source and license links. 3MF packages are inspected for Bambu/3MF metadata, embedded photographs, plate previews, model names, and slicer settings. STL files provide geometry and dimensions; on Windows, Project2PDF also checks the `Zone.Identifier` download stream for the original referrer and download URL.

## Command line

Inspect normalized metadata without network access:

```powershell
.\.venv\Scripts\project2pdf.exe analyze --offline "Resources\Wandermark"
```

Generate a PDF:

```powershell
.\.venv\Scripts\project2pdf.exe generate "Resources\Wandermark" -o output
```

Add `--theme dark` to generate a dark PDF from the command line.

## Build the Windows executable

```powershell
.\build_windows.ps1
```

The packaged application is written to `dist\Project2PDF.exe`.

## Tests

```powershell
.\.venv\Scripts\pytest.exe
```

The local `Resources` fixtures cover three provenance paths:

- Wandermark: origin from a companion Printables PDF.
- CSGO: origin and content embedded in MakerWorld 3MF metadata.
- Level 5 Pyramid: a raw STL identified through Windows download metadata and filename matching.
