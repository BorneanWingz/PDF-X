Optional pdf2docx plugin
========================

This folder contains the existing PDF-to-DOCX plugin as source for a future
integration. It uses pdf2docx and PyMuPDF, which have AGPL-3.0 licensing
requirements. Review those requirements before distributing or using them.

The clean PDF-X executable already converts PDF to DOCX using LibreOffice.
Copying this file alone into its plugins folder will not enable pdf2docx:
the clean executable excludes the plugin's dependencies.

For a source installation, install the project's agpl extra and place
pdf2docx_plugin.py in the application's plugins folder. An internal build
made with scripts\build.ps1 -Mode internal bundles those dependencies and
the plugin. When available, the plugin takes precedence over LibreOffice
for PDF-to-DOCX conversions.
