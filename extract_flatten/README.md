# Archive Flattener Tool

Extracts and flattens archives or directories into a single-level directory structure with intelligent deduplication.

## Features

- **Multiple archive format support**: ZIP, TAR (all variants), GZIP, 7ZIP*, RAR*
- **Recursive directory processing**: Flattens nested directory structures
- **Smart deduplication**: Uses path-based hashes to handle duplicate filenames
- **File type transformation**: Automatically adds `.txt` extension to config files
- **Smart file filtering**: Skips empty files and OS metadata files automatically
- **Log consolidation**: Optional consolidation of `.log` and `.previous.log` files by subdirectory
- **Safety checks**: Aborts if output directory is not empty
- **Mapping documentation**: Creates `.path_mappings.txt` showing hash-to-path relationships

*\*Requires optional dependencies*

## Installation

**Quick setup:**
```bash
./setup.sh
```

**Manual installation (basic - ZIP, TAR, GZIP support):**
```bash
# No additional dependencies needed - uses Python standard library
python3 extract_flatten.py --help
```

**Full installation (includes 7ZIP and RAR support):**
```bash
pip install -r requirements.txt
```

## Usage

```bash
# Extract a ZIP archive
python3 extract_flatten.py -s archive.zip -o extracted_files

# Flatten a directory structure
python3 extract_flatten.py -s /path/to/directory -o flattened_output

# Process TAR.GZ with verbose output
python3 extract_flatten.py -s backup.tar.gz -o output -v

# Enable log consolidation for support bundle analysis
python3 extract_flatten.py -s support-bundle.tar.gz -o extracted -c

# Short form
python3 extract_flatten.py -s file.zip -o out
```

## Command Line Options

- `-s, --source SRC`: Source directory or archive file (required)
- `-o, --output OUT`: Output directory for flattened files (required)
- `-c, --consolidate`: Consolidate all `.log` and `.previous.log` files in each subdirectory
- `-v, --verbose`: Verbose output
- `-h, --help`: Show help message

## Log Consolidation

The `-c, --consolidate` flag enables consolidation of log files within each subdirectory:

- **What gets consolidated**: All `.log` and `.previous.log` files in the same subdirectory
- **Output files**: `CONSOLIDATED_LOGS.log.txt` (root) or `{hash}_CONSOLIDATED_LOGS.log.txt` (subdirs)
- **File ordering**: Alphabetical, with `.previous.log` appearing before `.log` for same base filename
- **Separators**: Clean `--- original/path/filename ---` format

## File Processing Rules

1. **Extension transformation**: Files with these extensions get `.txt` appended:
   - `yaml`, `yml`, `list`, `log`, `descr`, `status`, `labels`

2. **Deduplication**: Files from different subdirectories with the same name get prefixed with an 8-character hash:
   - `config.yaml` from `dir1/` becomes `a1b2c3d4_config.yaml.txt`
   - `config.yaml` from `dir2/` becomes `e5f6g7h8_config.yaml.txt`

3. **File filtering**: Automatically skipped and reported:
   - **Empty files**: Zero-byte files
   - **macOS metadata**: `__MACOSX/` directories, `._*` files, `.DS_Store`, `.Trashes`, etc.
   - **Windows metadata**: `Thumbs.db`, `desktop.ini`, `$RECYCLE.BIN`
   - **Linux metadata**: `.directory` (KDE folder settings)

## Output

The tool creates:
- **Flattened files**: All files in a single directory with unique names
- **Mapping file**: `.path_mappings.txt` showing hash-to-path relationships
- **Console output**: Progress and summary information

## Supported Archive Formats

| Format | Extension | Requirements |
|--------|-----------|--------------|
| ZIP | `.zip` | Built-in |
| TAR | `.tar`, `.tar.gz`, `.tar.bz2`, `.tar.xz`, `.tgz`, `.tbz2`, `.txz` | Built-in |
| GZIP | `.gz` | Built-in |
| 7ZIP | `.7z` | `pip install py7zr` |
| RAR | `.rar` | `pip install rarfile` |

## Examples

**Customer support use cases:**
```bash
# Extract GPU operator logs (filters out macOS metadata automatically)
python3 extract_flatten.py -s nvidia-gpu-operator_20250613_1433.tar.gz -o gpu-logs-extracted

# Flatten support bundle (skips OS metadata and empty files)
python3 extract_flatten.py -s support-bundle.zip -o support-bundle-flat

# Consolidate logs in support bundle for easier analysis
python3 extract_flatten.py -s support-bundle.tar.gz -o support-analysis -c

# Process debugging info from container
python3 extract_flatten.py -s debug-info.tar.xz -o debug-flat
```